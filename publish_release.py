#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 The JusicRoomPlayer Authors
"""
publish_release.py —— 把 dist 下的发行产物发布到 GitHub / Gitee 的 Releases
================================================================================
用途
    读取根目录 VERSION，找到 dist 下的两个产物：
        dist\\JusicRoomPlayer <版本>.exe
        dist\\JusicRoomPlayerPortable_<版本>.zip
    在 GitHub 与 Gitee 上创建（已存在则复用）同名 tag 的 Release，
    并把这两个文件作为 Release 附件上传；最后打印下载链接与 SHA256。

凭证
    GitHub : 环境变量 GH_TOKEN  （或 --github-token，需 repo 权限的 PAT）
    Gitee  : 环境变量 GITEE_TOKEN（或 --gitee-token，需 projects 权限的私人令牌）
    token 只放在请求头 / query，不会写进磁盘。

用法
    python publish_release.py                     # 发布到 github + gitee
    python publish_release.py --platform github   # 只发 GitHub
    python publish_release.py --platform gitee    # 只发 Gitee
    python publish_release.py --dry-run           # 只显示将要做什么
    python publish_release.py --prerelease        # 标记为预发行
    python publish_release.py --notes-file NOTES.md
    python publish_release.py --push-tag          # 先把本地 tag 推到两个远端

仅依赖 Python 标准库（urllib），无需 pip 安装任何东西。
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
GH_API = "https://api.github.com"
GITEE_API = "https://gitee.com/api/v5"
UA = "JusicRoomPlayer-release-publisher"
TIMEOUT = 600  # 上传 60MB 级别附件留足时间

DEFAULT_REPOS = {
    "github": "seaworld92/JusicRoomPlayer",
    "gitee": "seaworld/JusicRoomPlayer",
}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def log(msg=""):
    print(msg, flush=True)


def fail(msg):
    log(f"[ERROR] {msg}")
    sys.exit(1)


def setup_console():
    """让中文在 Windows 控制台尽量正常输出。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def read_version():
    path = os.path.join(ROOT, "VERSION")
    if not os.path.isfile(path):
        fail(f"找不到 VERSION 文件: {path}")
    text = open(path, encoding="utf-8").read().strip()
    if not re.fullmatch(r"\d+\.\d+(\.\d+)?", text):
        fail(f"VERSION 内容不像版本号: {text!r}")
    return text


def artifacts(ver):
    """返回 [(绝对路径, 上传后的附件文件名, 说明)]。"""
    exe = f"JusicRoomPlayer {ver}.exe"
    zip_ = f"JusicRoomPlayerPortable_{ver}.zip"
    items = [
        (os.path.join(ROOT, "dist", exe), exe, "单文件版（内置 mpv，首次启动稍慢）"),
        (os.path.join(ROOT, "dist", zip_), zip_, "便携版（解压即用，启动更快）"),
    ]
    missing = [p for p, _, _ in items if not os.path.isfile(p)]
    if missing:
        for p in missing:
            log(f"        缺少: {p}")
        fail("发行产物不完整，请先运行 build_exe.bat 与 build_exe_dir.bat")
    return items


def human(n):
    return f"{n / 1048576:.1f} MB"


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args):
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8", errors="replace")
        return out.returncode, (out.stdout or "").strip(), (out.stderr or "").strip()
    except FileNotFoundError:
        return 1, "", "git not found"


def remote_repo(name):
    """从 git remote 解析 owner/repo，失败则回退内置默认值。"""
    rc, out, _ = git("remote", "get-url", name)
    if rc == 0 and out:
        m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", out)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    return DEFAULT_REPOS.get(name)


def prev_tag(current):
    rc, out, _ = git("tag", "--sort=-v:refname")
    if rc != 0 or not out:
        return None
    for t in out.splitlines():
        t = t.strip()
        if t and t != current:
            return t
    return None


def changelog(current_tag):
    tag = prev_tag(current_tag)
    rng = f"{tag}..HEAD" if tag else "-15"
    rc, out, _ = git("log", "--no-merges", "--pretty=format:%s", rng)
    if rc != 0 or not out:
        return []
    return [f"- {line.strip()}" for line in out.splitlines() if line.strip()][:15]


def build_notes(args, ver, items, sums):
    if args.notes_file:
        return open(args.notes_file, encoding="utf-8").read()
    if args.notes is not None:
        return args.notes

    rows = ["| 附件 | 说明 | 大小 |", "| --- | --- | --- |"]
    for path, name, desc in items:
        rows.append(f"| `{name}` | {desc} | {human(os.path.getsize(path))} |")
    table = "\n".join(rows)

    checks = "\n".join(f"{sums[name]}  {name}" for _, name, _ in items)
    lines = [
        f"### Jusic 轻量房间播放器 {ver}",
        "",
        "本次发布包含以下 Windows 发行产物（**已内置 mpv 播放引擎**，目标机器无需安装 Python 或 mpv）：",
        "",
        table,
        "",
        "**SHA256 校验**",
        "",
        "```text",
        checks,
        "```",
    ]
    commits = changelog(args.tag)
    if commits:
        lines += ["", "**变更**", ""] + commits
    lines += [
        "",
        "**运行要求**：Windows 10/11 x64；单文件版首次启动需解包（稍慢），便携版解压即用（更快）。",
        "",
        "**许可证**：GPL-3.0（见仓库 `LICENSE` / `THIRD_PARTY_NOTICES`）。",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def request(url, method="GET", headers=None, data=None):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", UA)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # 网络层错误
        return 0, str(e).encode()


def as_json(body):
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return None


def brief(body, limit=300):
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------
def gh_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def gh_release(repo, token, tag):
    url = f"{GH_API}/repos/{repo}/releases/tags/{urllib.parse.quote(tag)}"
    status, body = request(url, headers=gh_headers(token))
    if status == 200:
        return as_json(body)
    if status == 404:
        return None
    fail(f"GitHub 查询 release 失败: HTTP {status} {brief(body)}")


def gh_create(repo, token, tag, title, notes, prerelease):
    payload = {
        "tag_name": tag,
        "target_commitish": "master",
        "name": title,
        "body": notes,
        "draft": False,
        "prerelease": prerelease,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = gh_headers(token)
    headers["Content-Type"] = "application/json"
    status, body = request(f"{GH_API}/repos/{repo}/releases", "POST", headers, data)
    if status not in (200, 201):
        fail(f"GitHub 创建 release 失败: HTTP {status} {brief(body)}")
    return as_json(body)


def gh_upload(repo, token, release_id, path, name):
    data = open(path, "rb").read()
    headers = gh_headers(token)
    headers["Content-Type"] = "application/octet-stream"
    headers["Content-Length"] = str(len(data))
    q = urllib.parse.quote(name)
    url = f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?name={q}"
    status, body = request(url, "POST", headers, data)
    if status not in (200, 201):
        fail(f"GitHub 上传附件失败({name}): HTTP {status} {brief(body)}")
    return as_json(body)


# ---------------------------------------------------------------------------
# Gitee
# ---------------------------------------------------------------------------
def gitee_release(repo, token, tag):
    url = (f"{GITEE_API}/repos/{repo}/releases/tags/{urllib.parse.quote(tag)}"
           f"?access_token={urllib.parse.quote(token)}")
    status, body = request(url)
    if status == 200:
        return as_json(body)
    if status in (404, 400):
        return None
    fail(f"Gitee 查询 release 失败: HTTP {status} {brief(body)}")


def gitee_create(repo, token, tag, title, notes, prerelease):
    fields = {
        "access_token": token,
        "tag_name": tag,
        "target_commitish": "master",
        "name": title,
        "body": notes,
        "prerelease": "true" if prerelease else "false",
    }
    data = urllib.parse.urlencode(fields).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    status, body = request(f"{GITEE_API}/repos/{repo}/releases", "POST", headers, data)
    if status not in (200, 201):
        fail(f"Gitee 创建 release 失败: HTTP {status} {brief(body)}")
    return as_json(body)


def gitee_upload(repo, token, release_id, path, name):
    boundary = "----JusicRelease" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    payload = open(path, "rb").read()
    body = head + payload + tail
    url = (f"{GITEE_API}/repos/{repo}/releases/{release_id}/attach_files"
           f"?access_token={urllib.parse.quote(token)}")
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    status, resp = request(url, "POST", headers, body)
    if status not in (200, 201):
        fail(f"Gitee 上传附件失败({name}): HTTP {status} {brief(resp)}")
    return as_json(resp)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def publish_github(repo, token, args, ver, items):
    tag, title = args.tag, args.name
    log(f"[GitHub] 仓库 {repo}   tag {tag}")
    if args.dry_run:
        log("         [dry-run] 将查询 / 创建 release")
        rel = {"id": 0, "assets": []}
    else:
        rel = gh_release(repo, token, tag)
        if rel:
            log(f"         release 已存在（id={rel.get('id')}），复用")
        else:
            rel = gh_create(repo, token, tag, title, args.notes_text, args.prerelease)
            log(f"         release 创建成功（id={rel.get('id')}）")

    existing = {a.get("name") for a in (rel.get("assets") or [])}
    for path, name, _ in items:
        if name in existing:
            log(f"         已存在同名附件，跳过: {name}")
            continue
        if args.dry_run:
            log(f"         [dry-run] 将上传 {name} ({human(os.path.getsize(path))})")
            continue
        log(f"         上传 {name} ({human(os.path.getsize(path))}) ...")
        asset = gh_upload(repo, token, rel["id"], path, name)
        log(f"         完成: {asset.get('browser_download_url')}")
    url = rel.get("html_url") or f"https://github.com/{repo}/releases/tag/{tag}"
    log(f"         Release 页面: {url}")
    return url


def publish_gitee(repo, token, args, ver, items):
    tag, title = args.tag, args.name
    log(f"[Gitee ] 仓库 {repo}   tag {tag}")
    if args.dry_run:
        log("         [dry-run] 将查询 / 创建 release")
        rel = {"id": 0, "assets": []}
    else:
        rel = gitee_release(repo, token, tag)
        if rel:
            log(f"         release 已存在（id={rel.get('id')}），复用")
        else:
            rel = gitee_create(repo, token, tag, title, args.notes_text, args.prerelease)
            log(f"         release 创建成功（id={rel.get('id')}）")

    existing = {a.get("name") for a in (rel.get("assets") or [])}
    for path, name, _ in items:
        if name in existing:
            log(f"         已存在同名附件，跳过: {name}")
            continue
        if args.dry_run:
            log(f"         [dry-run] 将上传 {name} ({human(os.path.getsize(path))})")
            continue
        log(f"         上传 {name} ({human(os.path.getsize(path))}) ...")
        asset = gitee_upload(repo, token, rel["id"], path, name)
        log(f"         完成: {asset.get('browser_download_url')}")
    url = rel.get("html_url") or f"https://gitee.com/{repo}/releases/tag/{tag}"
    log(f"         Release 页面: {url}")
    return url


def main():
    setup_console()
    p = argparse.ArgumentParser(
        description="发布 dist 下的 JusicRoomPlayer 产物到 GitHub / Gitee Releases",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--platform", choices=["all", "github", "gitee"], default="all",
                   help="发布到哪个平台（默认 all）")
    p.add_argument("--version", help="覆盖 VERSION 文件里的版本号")
    p.add_argument("--tag", help="tag 名（默认 v<版本>）")
    p.add_argument("--name", help="Release 标题（默认 'JusicRoomPlayer <版本>'）")
    p.add_argument("--notes", help="直接给出 Release 说明文本")
    p.add_argument("--notes-file", help="从文件读取 Release 说明")
    p.add_argument("--prerelease", action="store_true", help="标记为预发行（Pre-release）")
    p.add_argument("--push-tag", action="store_true", help="发布前把本地 tag 推送到远端")
    p.add_argument("--dry-run", action="store_true", help="只打印将执行的操作")
    p.add_argument("--github-repo", help="owner/repo，默认取自 git remote github")
    p.add_argument("--gitee-repo", help="owner/repo，默认取自 git remote origin")
    p.add_argument("--github-token", help="GitHub PAT（默认读环境变量 GH_TOKEN）")
    p.add_argument("--gitee-token", help="Gitee 私人令牌（默认读环境变量 GITEE_TOKEN）")
    p.add_argument("--skip-checksum", action="store_true", help="跳过 SHA256 计算")
    args = p.parse_args()

    ver = args.version or read_version()
    args.tag = args.tag or f"v{ver}"
    args.name = args.name or f"JusicRoomPlayer {ver}"

    log("=" * 68)
    log(f" 发布 JusicRoomPlayer {ver}   →  GitHub / Gitee Releases")
    log("=" * 68)

    items = artifacts(ver)
    log("发行产物:")
    sums = {}
    for path, name, _ in items:
        if args.skip_checksum:
            sums[name] = "(skipped)"
        else:
            sums[name] = sha256_of(path)
        log(f"  - {name}  {human(os.path.getsize(path))}")
        if not args.skip_checksum:
            log(f"    sha256 {sums[name]}")

    args.notes_text = build_notes(args, ver, items, sums)

    want = ["github", "gitee"] if args.platform == "all" else [args.platform]
    gh_repo = args.github_repo or remote_repo("github")
    gt_repo = args.gitee_repo or remote_repo("origin")

    if args.push_tag and not args.dry_run:
        for remote in ("origin", "github"):
            rc, _, err = git("push", remote, f"refs/tags/{args.tag}")
            log(f"[tag  ] push {remote} {args.tag}: "
                f"{'OK' if rc == 0 else '跳过/失败 - ' + err}")

    results = {}
    if "github" in want:
        token = args.github_token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token and not args.dry_run:
            fail("缺少 GitHub 凭证：请设置环境变量 GH_TOKEN（PAT，需 repo 权限）")
        results["github"] = publish_github(gh_repo, token or "-", args, ver, items)

    if "gitee" in want:
        token = args.gitee_token or os.environ.get("GITEE_TOKEN")
        if not token and not args.dry_run:
            fail("缺少 Gitee 凭证：请设置环境变量 GITEE_TOKEN（私人令牌，需 projects 权限）")
        results["gitee"] = publish_gitee(gt_repo, token or "-", args, ver, items)

    log("")
    log("-" * 68)
    for k, v in results.items():
        log(f"{k:6s} → {v}")
    log("完成。" if not args.dry_run else "dry-run 结束，未做任何改动。")


if __name__ == "__main__":
    main()

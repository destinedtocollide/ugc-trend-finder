"""
Auto-updater for UGC Trend Finder.

New versions are published as GitHub Releases. The installed app (.exe) downloads the
release's Setup.exe and runs it silently; a copy running from source downloads the
release's source zip and replaces its own files. Either way the app restarts itself.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from urllib.request import Request, urlopen

UA = "UGC-Trend-Finder-Updater"
INSTALLER_SUFFIX = "Setup.exe"
SOURCE_FILES = (".py", ".pyw", ".ico", ".png", ".html", ".css", ".js", ".txt", ".md")
SKIP_DIRS = {".github", "dist", "build", "Output", "__pycache__", ".git"}


def load_build_info(app_dir, fallback_version):
    """build_info.json is written by the GitHub build; update_config.json is for source copies."""
    info = {"version": fallback_version, "repo": ""}
    for name in ("update_config.json", "build_info.json"):
        try:
            with open(os.path.join(app_dir, name), encoding="utf-8-sig") as f:
                data = json.load(f)
            for k in ("version", "repo"):
                if data.get(k):
                    info[k] = str(data[k]).strip()
        except Exception:
            pass
    info["repo"] = normalize_repo(info["repo"])
    return info


def normalize_repo(repo):
    """Accepts 'user/repo' or a full GitHub URL."""
    repo = (repo or "").strip()
    m = re.search(r"github\.com[/:]([^/\s]+)/([^/\s#?]+)", repo)
    if m:
        repo = f"{m.group(1)}/{m.group(2)}"
    repo = repo.strip("/").removesuffix(".git")
    return repo if re.fullmatch(r"[\w.-]+/[\w.-]+", repo or "") else ""


def vtuple(v):
    nums = [int(x) for x in re.findall(r"\d+", v or "")[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def _get(url, timeout=20):
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def check(repo, current):
    """Returns info about the latest release. Raises on network errors."""
    if not repo:
        return {"available": False, "configured": False}
    rel = _get(f"https://api.github.com/repos/{repo}/releases/latest")
    tag = rel.get("tag_name") or ""
    installer = next((a.get("browser_download_url") for a in rel.get("assets") or []
                      if (a.get("name") or "").endswith(INSTALLER_SUFFIX)), None)
    notes = (rel.get("body") or "").strip()
    first = next((ln.strip(" -*#") for ln in notes.splitlines() if ln.strip(" -*#")), "")
    return {
        "available": vtuple(tag) > vtuple(current),
        "configured": True,
        "version": tag.lstrip("vV") or tag,
        "notes": notes,
        "notes_short": first[:140],
        "installer_url": installer,
        "zip_url": rel.get("zipball_url"),
        "page": rel.get("html_url"),
    }


def download(url, dest, on_progress=None):
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if on_progress:
                on_progress(got, total)
    return dest


def apply_installer(info, on_progress=None):
    """Installed app: download Setup.exe and run it silently. It closes this app,
    installs over it and starts the new version."""
    if not info.get("installer_url"):
        raise RuntimeError("This release doesn't have an installer yet. It's probably still being built; try again in a few minutes.")
    tmp = os.path.join(tempfile.gettempdir(), f"UGC-Trend-Finder-Setup-{info['version']}.exe")
    download(info["installer_url"], tmp, on_progress)
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([tmp, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                      "/CLOSEAPPLICATIONS", "/FORCECLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True)


def apply_source(info, app_dir, repo, on_progress=None):
    """Source copy: download the release zip and replace the app files."""
    if not info.get("zip_url"):
        raise RuntimeError("This release has no download.")
    work = tempfile.mkdtemp(prefix="ugc_update_")
    try:
        zpath = download(info["zip_url"], os.path.join(work, "src.zip"), on_progress)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(work)
        root = None
        for dirpath, dirnames, files in os.walk(work):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            if "app.py" in files and "ugc_trend_finder.py" in files:
                root = dirpath
                break
        if not root:
            raise RuntimeError("The update download didn't contain the app files.")
        for dirpath, dirnames, files in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            rel = os.path.relpath(dirpath, root)
            for fn in files:
                if not fn.endswith(SOURCE_FILES) or fn in ("update_config.json",):
                    continue
                dest_dir = os.path.join(app_dir, rel) if rel != "." else app_dir
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy2(os.path.join(dirpath, fn), os.path.join(dest_dir, fn))
        # remember which release is installed, so it isn't offered again
        with open(os.path.join(app_dir, "build_info.json"), "w", encoding="utf-8") as f:
            json.dump({"version": info["version"], "repo": repo}, f)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def restart_source(app_dir):
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    launcher = os.path.join(app_dir, "UGC Trend Finder.pyw")
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0
    subprocess.Popen([pyw if os.path.exists(pyw) else exe, launcher], creationflags=flags, close_fds=True,
                     cwd=app_dir)

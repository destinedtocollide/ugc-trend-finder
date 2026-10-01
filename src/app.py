"""
UGC Trend Finder: desktop app
=============================
A native window (Edge WebView2 via pywebview) showing the interface in ui/index.html,
a system-tray icon, automatic scans and automatic updates.
"""

import gc
import glob
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
import base64
import io
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

APP_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
EXE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else APP_DIR
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

try:                                            # instant startup image shown by the .exe
    import pyi_splash  # noqa: F401
except Exception:
    pyi_splash = None


def close_native_splash():
    global pyi_splash
    if pyi_splash is not None:
        try:
            pyi_splash.close()
        except Exception:
            pass
        pyi_splash = None


import ugc_trend_finder as core  # noqa: E402
import updater  # noqa: E402

FROZEN = getattr(sys, "frozen", False)
BUILD = updater.load_build_info(APP_DIR, core.VERSION)   # version + GitHub repo for updates
VERSION = BUILD["version"]
REPO = BUILD["repo"]
APP_NAME = "UGC Trend Finder"
SINGLE_PORT = 47831
BG = "#0f1115"
SIDE = "#13161b"
# theme -> (window background, title bar color, dark title bar?)
THEMES = {
    "midnight": ("#0f1115", "#13161b", True),
    "sakura": ("#151015", "#1a1219", True),
    "violet": ("#100f16", "#15131d", True),
    "emerald": ("#0d1311", "#111815", True),
    "sunset": ("#14100d", "#1a1511", True),
    "graphite": ("#111111", "#161616", True),
    "daylight": ("#f4f5f8", "#ffffff", False),
    "blossom": ("#fdf4f8", "#fff8fb", False),
}
# Themes people make themselves are stored in the settings as "custom_themes" and picked as
# "custom:<id>". The page works out every shade from four base colors and sends them along;
# only plain color values are kept, so nothing else can end up in the page or loading window.
CUSTOM_PREFIX = "custom:"
MAX_CUSTOM_THEMES = 24
_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_VAR_NAME = re.compile(r"--[a-z0-9-]{1,24}")
_VAR_VALUE = re.compile(r"#[0-9a-fA-F]{6}|\d{1,3},\d{1,3},\d{1,3}"
                        r"|rgba\(\d{1,3},\d{1,3},\d{1,3},(?:0|1|0?\.\d{1,3})\)")

DATA_HOME = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "UGC Trend Finder")
SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".ugc_trend_finder_settings.json")
LOG_PATH = os.path.join(DATA_HOME, "app.log")
SPLASH_TITLE = "UGC Trend Finder - loading"
THUMB_DIR = os.path.join(DATA_HOME, "thumbs")
SAVED_PATH = os.path.join(DATA_HOME, "saved_ideas.json")
DEFAULTS = {
    "out_dir": core.default_out_dir(),
    "scope": "all",
    "blender_only": False,
    "include_roblox": False,
    "depth": 3,
    "gap": 3.0,
    "open_report": False,
    "close_to_tray": True,
    "auto_scan_hours": 0,
    "auto_install": False,
    "theme": "midnight",
    "last_version_seen": "",
    "tray_hint_shown": False,
    "update_attempt": {},
    "custom_themes": [],
}


# ---------------------------------------------------------------- basics
_LOG_MAX = 512 * 1024


def trim_log():
    """Keeps app.log small: when it gets big, only the newest half is kept."""
    try:
        if os.path.getsize(LOG_PATH) <= _LOG_MAX:
            return
        with open(LOG_PATH, "rb") as f:
            f.seek(-_LOG_MAX // 2, os.SEEK_END)
            tail = f.read()
        tail = tail[tail.find(b"\n") + 1:]
        with open(LOG_PATH, "wb") as f:
            f.write(tail)
    except OSError:
        pass


def write_log(text):
    try:
        os.makedirs(DATA_HOME, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
    except Exception:
        pass


def _excepthook(t, v, tb):
    write_log("".join(traceback.format_exception(t, v, tb)))


sys.excepthook = _excepthook
threading.excepthook = lambda a: write_log("".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        saved.pop("delay", None)
        s.update(saved)
    except Exception:
        pass
    s["gap"] = max(2.0, float(s.get("gap", 3.0)))
    s["custom_themes"] = [t for t in (clean_custom_theme(x) for x in (s.get("custom_themes") or [])
                                      if isinstance(s.get("custom_themes"), list)) if t][:MAX_CUSTOM_THEMES]
    return s


def save_settings(s):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=1)
    except Exception:
        pass


def open_path(path):
    if sys.platform == "win32":
        os.startfile(path)  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def stamp_time(filename):
    m = re.search(r"(\d{4}-\d{2}-\d{2}_\d{4,6})", filename)
    if not m:
        return None
    for fmt in ("%Y-%m-%d_%H%M%S", "%Y-%m-%d_%H%M"):
        try:
            return datetime.strptime(m.group(1), fmt)
        except ValueError:
            pass
    return None


def clean_custom_theme(t):
    """A custom theme as sent by the page, keeping only valid names and colors (None if unusable)."""
    if not isinstance(t, dict):
        return None
    tid = str(t.get("id") or "")
    if not re.fullmatch(r"[a-z0-9]{1,24}", tid):
        return None
    base = t.get("base") if isinstance(t.get("base"), dict) else {}
    base = {k: str(base.get(k)) for k in ("bg", "card", "accent", "text") if _HEX.fullmatch(str(base.get(k) or ""))}
    raw = t.get("vars") if isinstance(t.get("vars"), dict) else {}
    vars_ = {}
    for k, v in list(raw.items())[:80]:
        v = re.sub(r"\s+", "", str(v))
        if _VAR_NAME.fullmatch(str(k)) and _VAR_VALUE.fullmatch(v):
            vars_[k] = v
    if len(base) < 4 or not {"--bg", "--side", "--accent"} <= set(vars_):
        return None
    name = re.sub(r"\s+", " ", str(t.get("name") or "")).strip()[:40] or "My theme"
    return {"id": tid, "name": name, "dark": bool(t.get("dark")), "base": base, "vars": vars_}


def find_custom_theme(settings, key):
    if not str(key or "").startswith(CUSTOM_PREFIX):
        return None
    tid = key[len(CUSTOM_PREFIX):]
    return next((t for t in settings.get("custom_themes") or [] if t["id"] == tid), None)


def theme_colors(settings, key):
    """(window background, title bar color, dark title bar?) for a built-in or custom theme."""
    if key in THEMES:
        return THEMES[key]
    t = find_custom_theme(settings, key)
    if t:
        return t["vars"]["--bg"], t["vars"]["--side"], t["dark"]
    return THEMES["midnight"]


def theme_exists(settings, key):
    return key in THEMES or find_custom_theme(settings, key) is not None


def custom_style(t, splash=False):
    """The theme's colors as an inline style for the page (or the loading window)."""
    v = t["vars"]
    if splash:
        pick = {"--bg": "--bg", "--edge": "--line", "--ink": "--ink", "--muted": "--muted", "--track": "--soft",
                "--a1": "--accent", "--a2": "--accent2", "--g1": "--accent2", "--g2": "--accent-deep",
                "--glow": "--accent-rgb", "--on": "--on-accent"}
        v = {k: t["vars"][src] for k, src in pick.items() if src in t["vars"]}
    scheme = "dark" if t["dark"] else "light"
    return ";".join(f"{k}:{val}" for k, val in v.items()) + f";color-scheme:{scheme}"


def dark_titlebar(hwnd, colors):
    """Colors the Windows title bar to match the theme (Windows 10/11)."""
    if sys.platform != "win32" or not hwnd:
        return
    _bg, caption, dark = colors
    try:
        import ctypes
        on = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4) == 0:
                break
        r, g, b = int(caption[1:3], 16), int(caption[3:5], 16), int(caption[5:7], 16)
        color = ctypes.c_int(r | (g << 8) | (b << 16))
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), 4)
    except Exception:
        pass


class WinFx:
    """Window positioning and whole-window fades for the startup hand-off.
    Windows only; every call quietly does nothing elsewhere and never raises."""
    GWL_EXSTYLE, WS_EX_LAYERED, LWA_ALPHA = -20, 0x80000, 0x2
    _api = None

    @classmethod
    def api(cls):
        if cls._api is not None or sys.platform != "win32":
            return cls._api
        try:
            import ctypes
            from ctypes import wintypes as w
            u, d = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("dwmapi")
            H = w.HWND
            ptr_long = ctypes.c_ssize_t
            get_long = getattr(u, "GetWindowLongPtrW", None) or u.GetWindowLongW
            set_long = getattr(u, "SetWindowLongPtrW", None) or u.SetWindowLongW
            get_long.argtypes, get_long.restype = [H, ctypes.c_int], ptr_long
            set_long.argtypes, set_long.restype = [H, ctypes.c_int, ptr_long], ptr_long
            u.SetLayeredWindowAttributes.argtypes = [H, w.DWORD, ctypes.c_ubyte, w.DWORD]
            u.SetWindowPos.argtypes = [H, H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            u.GetWindowRect.argtypes = [H, ctypes.POINTER(w.RECT)]
            u.RedrawWindow.argtypes = [H, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
            u.GetWindowTextW.argtypes = [H, w.LPWSTR, ctypes.c_int]
            u.GetWindowThreadProcessId.argtypes = [H, ctypes.POINTER(w.DWORD)]
            u.IsWindowVisible.argtypes = [H]
            u.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
            u.MonitorFromPoint.argtypes, u.MonitorFromPoint.restype = [w.POINT, w.DWORD], w.HMONITOR
            d.DwmSetWindowAttribute.argtypes = [H, w.DWORD, ctypes.c_void_p, w.DWORD]
            d.DwmGetWindowAttribute.argtypes = [H, w.DWORD, ctypes.c_void_p, w.DWORD]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT), ("rcWork", w.RECT), ("dwFlags", w.DWORD)]
            u.GetMonitorInfoW.argtypes = [w.HMONITOR, ctypes.POINTER(MONITORINFO)]
            cls._api = {"ct": ctypes, "w": w, "u": u, "d": d, "get": get_long, "set": set_long, "MI": MONITORINFO}
        except Exception:
            write_log("WinFx setup failed: " + traceback.format_exc())
            cls._api = None
        return cls._api

    @classmethod
    def find(cls, title):
        """Top-level windows of this process with exactly this title (visible or not)."""
        a = cls.api()
        if not a:
            return []
        ct, w, u = a["ct"], a["w"], a["u"]
        me, found = os.getpid(), []
        proto = ct.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

        def cb(h, _):
            pid = w.DWORD()
            u.GetWindowThreadProcessId(h, ct.byref(pid))
            if pid.value == me:
                buf = ct.create_unicode_buffer(256)
                u.GetWindowTextW(h, buf, 256)
                if buf.value == title:
                    found.append(h)
            return True
        u.EnumWindows(proto(cb), 0)
        return found

    @classmethod
    def layered(cls, hwnd, on):
        a = cls.api()
        if not a or not hwnd:
            return False
        try:
            ex = a["get"](hwnd, cls.GWL_EXSTYLE)
            a["set"](hwnd, cls.GWL_EXSTYLE, (ex | cls.WS_EX_LAYERED) if on else (ex & ~cls.WS_EX_LAYERED))
            if not on:                              # Windows asks for a repaint after un-layering
                a["u"].RedrawWindow(hwnd, None, None, 0x1 | 0x4 | 0x80 | 0x400)
            return True
        except Exception:
            write_log("WinFx.layered failed: " + traceback.format_exc())
            return False

    @classmethod
    def alpha(cls, hwnd, v):
        a = cls.api()
        if a and hwnd:
            try:
                a["u"].SetLayeredWindowAttributes(hwnd, 0, max(0, min(255, int(v))), cls.LWA_ALPHA)
            except Exception:
                pass

    @classmethod
    def rect(cls, hwnd, visible_frame=False):
        """(x, y, w, h) of a window. visible_frame=True leaves out the invisible resize border
        Windows 10/11 puts around normal windows, so it matches what you actually see."""
        a = cls.api()
        if not a or not hwnd:
            return None
        try:
            ct, r = a["ct"], a["w"].RECT()
            ok = visible_frame and a["d"].DwmGetWindowAttribute(hwnd, 9, ct.byref(r), ct.sizeof(r)) == 0
            if not ok and not a["u"].GetWindowRect(hwnd, ct.byref(r)):
                return None
            w, h = r.right - r.left, r.bottom - r.top
            return (r.left, r.top, w, h) if w > 0 and h > 0 else None
        except Exception:
            return None

    @classmethod
    def place(cls, hwnd, x, y, w, h, show=False):
        a = cls.api()
        if a and hwnd:
            try:          # NOZORDER | NOACTIVATE | NOOWNERZORDER (| SHOWWINDOW)
                a["u"].SetWindowPos(hwnd, None, int(round(x)), int(round(y)), int(round(w)), int(round(h)),
                                    0x0004 | 0x0010 | 0x0200 | (0x0040 if show else 0))
            except Exception:
                pass

    @classmethod
    def work_area(cls):
        """The usable part (minus taskbar) of the screen the mouse is on."""
        a = cls.api()
        if not a:
            return None
        try:
            ct, w, u = a["ct"], a["w"], a["u"]
            pt = w.POINT()
            u.GetCursorPos(ct.byref(pt))
            mon = u.MonitorFromPoint(pt, 2)           # nearest monitor
            mi = a["MI"]()
            mi.cbSize = ct.sizeof(mi)
            if not u.GetMonitorInfoW(mon, ct.byref(mi)):
                return None
            r = mi.rcWork
            return (r.left, r.top, r.right - r.left, r.bottom - r.top)
        except Exception:
            return None

    @classmethod
    def center(cls, hwnd):
        """Moves a window to the middle of the screen the mouse is on (keeps its size)."""
        r, wa = cls.rect(hwnd), cls.work_area()
        if not (r and wa):
            return False
        w, h = min(r[2], wa[2]), min(r[3], wa[3])
        cls.place(hwnd, wa[0] + (wa[2] - w) / 2, wa[1] + (wa[3] - h) / 2, w, h)
        return True

    @classmethod
    def transitions(cls, hwnd, enabled):
        """Turns Windows' own pop-in animation off while we run ours (so they don't fight)."""
        a = cls.api()
        if a and hwnd:
            try:
                v = a["ct"].c_int(0 if enabled else 1)
                a["d"].DwmSetWindowAttribute(hwnd, 3, a["ct"].byref(v), 4)
            except Exception:
                pass


def _hwnd_of(win, title=None):
    """Window handle of a pywebview window: asked from Windows by title first (reliable),
    then from pywebview itself."""
    if title:
        hs = WinFx.find(title)
        if hs:
            return hs[0]
    try:
        h = win.native.Handle
        return h.ToInt64() if hasattr(h, "ToInt64") else int(h)
    except Exception:
        return None


def create_desktop_shortcut():
    if sys.platform != "win32":
        raise RuntimeError("Desktop shortcuts can only be made on Windows.")
    if FROZEN:
        target, args, icon, workdir = sys.executable, "", sys.executable, EXE_DIR
    else:
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        target = pyw if os.path.exists(pyw) else sys.executable
        args = '"' + os.path.join(APP_DIR, "UGC Trend Finder.pyw") + '"'
        icon, workdir = os.path.join(APP_DIR, "icon.ico"), APP_DIR

    def q(s):
        return s.replace("'", "''")
    ps = ("$d=[Environment]::GetFolderPath('Desktop');"
          "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'UGC Trend Finder.lnk'));"
          f"$s.TargetPath='{q(target)}';$s.Arguments='{q(args)}';"
          f"$s.WorkingDirectory='{q(workdir)}';$s.IconLocation='{q(icon)}';$s.Save()")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "PowerShell couldn't create the shortcut.")


# ---------------------------------------------------------------- single instance
def signal_running_instance():
    """If the app is already running (e.g. in the tray), ask it to show its window."""
    try:
        with socket.create_connection(("127.0.0.1", SINGLE_PORT), timeout=1.5) as s:
            s.sendall(b"show")
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- item pictures
# Pictures are fetched here (not by the page) and kept on disk, so they also show for
# older scans that never stored them, and keep working after Roblox's links expire.
_THUMB_MEM = OrderedDict()       # small recent-pictures cache; the page keeps its own copy
_THUMB_MEM_MAX = 120
_THUMB_DISK_MAX = 800             # pictures kept on disk; older ones are removed at startup


def _thumb_remember(aid, uri):
    with _THUMB_LOCK:
        _THUMB_MEM[aid] = uri
        _THUMB_MEM.move_to_end(aid)
        while len(_THUMB_MEM) > _THUMB_MEM_MAX:
            _THUMB_MEM.popitem(last=False)
    return uri


def _thumb_recall(aid):
    with _THUMB_LOCK:
        uri = _THUMB_MEM.get(aid)
        if uri is not None:
            _THUMB_MEM.move_to_end(aid)
        return uri


def prune_thumb_dir():
    """Keeps the picture folder from growing forever: only the newest pictures stay."""
    try:
        files = [os.path.join(THUMB_DIR, f) for f in os.listdir(THUMB_DIR) if f.endswith(".img")]
        if len(files) <= _THUMB_DISK_MAX:
            return
        files.sort(key=os.path.getmtime, reverse=True)
        for p in files[_THUMB_DISK_MAX:]:
            try:
                os.remove(p)
            except OSError:
                pass
    except OSError:
        pass


_THUMB_LOCK = threading.Lock()
_THUMB_SMALL = 60_000             # cached files above this size are old full-size pictures


def _http(url, timeout=20):
    req = Request(url, headers={"User-Agent": core.UA})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def _shrink(raw):
    """Small WebP copy of a picture (what's kept on disk and sent to the page)."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as im:
            im.thumbnail((320, 320))
            buf = io.BytesIO()
            im.save(buf, "WEBP", quality=86, method=4)
            return buf.getvalue()
    except Exception:
        return raw


def _to_data_uri(raw):
    kind = "png" if raw[:4] == b"\x89PNG" else ("webp" if raw[8:12] == b"WEBP" else "jpeg")
    return f"data:image/{kind};base64," + base64.b64encode(raw).decode()


def _read_cached_thumb(path):
    """Reads a cached picture. Pictures saved by older versions were full size; those are
    shrunk once and saved again, so later reads skip the image work entirely."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[8:12] == b"WEBP" and len(raw) <= _THUMB_SMALL:
        return raw
    small = _shrink(raw)
    if small is not raw:
        try:
            with open(path, "wb") as f:
                f.write(small)
        except OSError:
            pass
    return small


def load_thumbs(ids):
    """{asset_id: data_uri} for up to 100 ids, from memory, disk, or Roblox."""
    clean = []
    for i in ids or []:
        s = str(i)
        if s.isdigit() and s not in clean:
            clean.append(s)
    clean = clean[:100]
    out, need = {}, []
    os.makedirs(THUMB_DIR, exist_ok=True)
    for i in clean:
        hit = _thumb_recall(i)
        if hit is not None:
            out[i] = hit
            continue
        path = os.path.join(THUMB_DIR, i + ".img")
        try:
            if os.path.getsize(path) > 0:
                out[i] = _thumb_remember(i, _to_data_uri(_read_cached_thumb(path)))
                continue
        except OSError:
            pass
        need.append(i)
    if not need:
        return out
    try:
        q = {"assetIds": ",".join(need), "size": "420x420", "format": "Png", "isCircular": "false"}
        rows = json.loads(_http(core.THUMB_API + "?" + urlencode(q))).get("data") or []
    except Exception as e:
        write_log(f"thumbnail lookup failed: {e}")
        return out
    urls = {str(r.get("targetId")): r.get("imageUrl") for r in rows
            if r.get("state") == "Completed" and r.get("imageUrl")}

    def grab(item):
        aid, url = item
        try:
            small = _shrink(_http(url))
            with open(os.path.join(THUMB_DIR, aid + ".img"), "wb") as f:
                f.write(small)
            return aid, _to_data_uri(small)
        except Exception:
            return aid, None
    if not urls:
        return out
    with ThreadPoolExecutor(max_workers=min(6, len(urls))) as pool:
        for aid, uri in pool.map(grab, urls.items()):
            if uri:
                out[aid] = _thumb_remember(aid, uri)
    return out


# ---------------------------------------------------------------- the api the page calls
class Api:
    """Every public method here can be called from the page as pywebview.api.<name>()."""

    def __init__(self, app):
        self._app = app

    def ui_ready(self):
        self._app.ui_ready = True
        return True

    def thumbs(self, ids):
        return load_thumbs(ids)

    # ---- "My list": ideas the designer saved, with a status and notes
    _saved_lock = threading.Lock()

    @staticmethod
    def _read_saved():
        try:
            with open(SAVED_PATH, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    @staticmethod
    def _write_saved(items):
        os.makedirs(DATA_HOME, exist_ok=True)
        tmp = SAVED_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=1)
        os.replace(tmp, SAVED_PATH)

    def get_saved(self):
        return self._read_saved()

    def save_idea(self, idea):
        if not isinstance(idea, dict) or not idea.get("theme"):
            return self._read_saved()
        keep = ("theme", "type", "image", "image_id", "price", "score", "colors", "reasons", "kind", "examples")
        entry = {k: idea.get(k) for k in keep}
        entry["key"] = f"{idea.get('theme')}|{idea.get('type')}".lower()
        entry["status"], entry["notes"] = "todo", ""
        entry["added"] = datetime.now().isoformat(timespec="seconds")
        with self._saved_lock:
            items = [x for x in self._read_saved() if x.get("key") != entry["key"]]
            items.insert(0, entry)
            self._write_saved(items)
            return items

    def update_saved(self, key, patch):
        with self._saved_lock:
            items = self._read_saved()
            for x in items:
                if x.get("key") == key:
                    for k in ("status", "notes"):
                        if k in (patch or {}):
                            x[k] = str(patch[k])[:4000]
            self._write_saved(items)
            return items

    def remove_saved(self, key):
        with self._saved_lock:
            items = [x for x in self._read_saved() if x.get("key") != key]
            self._write_saved(items)
            return items

    def momentum(self):
        s = self._app.settings
        try:
            return core.momentum_history(os.path.join(s["out_dir"], "data"),
                                         include_roblox=bool(s.get("include_roblox")))
        except Exception:
            write_log(traceback.format_exc())
            return {"points": [], "themes": [], "items": [], "error": True}
        finally:
            gc.collect()                            # the scan files read for the chart can be large

    def boot_progress(self, pct, text=""):
        self._app.splash_progress(pct, text)
        return True

    def boot_done(self):
        threading.Thread(target=self._app.reveal, daemon=True).start()
        return True

    def get_state(self):
        return self._app.state()

    def get_scan(self, scan_id):
        try:
            with open(scan_id, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def start_scan(self, force=False):
        return self._app.start_scan(force=bool(force))

    def cancel_scan(self):
        self._app.cancel_scan()
        return True

    def save_settings(self, patch):
        allowed = set(DEFAULTS) - {"update_attempt", "tray_hint_shown", "out_dir", "last_version_seen",
                                   "custom_themes", "theme"}
        for k, v in (patch or {}).items():
            if k in allowed:
                self._app.settings[k] = v
        self._app.settings["gap"] = max(2.0, float(self._app.settings["gap"]))
        save_settings(self._app.settings)
        return self._app.public_settings()

    def open_url(self, url):
        if isinstance(url, str) and url.startswith(("https://www.roblox.com/", "https://github.com/")):
            webbrowser.open(url)
        return True

    def open_report(self, scan_id):
        try:
            with open(scan_id, encoding="utf-8") as f:
                rep = json.load(f).get("report")
            path = os.path.join(os.path.dirname(scan_id), rep)
            if os.path.exists(path):
                webbrowser.open("file:///" + os.path.abspath(path).replace("\\", "/"))
                return True
        except Exception:
            pass
        self._app.emit({"type": "toast", "msg": "That report file isn't there anymore.", "kind": "err"})
        return False

    def open_folder(self):
        d = os.path.join(self._app.settings["out_dir"], "reports")
        os.makedirs(d, exist_ok=True)
        open_path(d)
        return True

    def change_folder(self):
        import webview
        kind = getattr(webview, "FOLDER_DIALOG", None)
        if kind is None:
            kind = webview.FileDialog.FOLDER
        res = self._app.window.create_file_dialog(kind, directory=self._app.settings["out_dir"])
        if not res:
            return None
        d = res[0] if isinstance(res, (list, tuple)) else res
        self._app.settings["out_dir"] = d
        save_settings(self._app.settings)
        return d

    def delete_scan(self, scan_id):
        try:
            with open(scan_id, encoding="utf-8") as f:
                rep = json.load(f).get("report")
        except Exception:
            rep = None
        for p in (scan_id, os.path.join(os.path.dirname(scan_id), rep) if rep else None):
            if p and p.startswith(os.path.abspath(self._app.settings["out_dir"])):
                try:
                    os.remove(p)
                except OSError:
                    pass
        return True

    def create_shortcut(self):
        try:
            create_desktop_shortcut()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def check_update(self):
        return self._app.check_update(manual=True)

    def set_theme(self, name):
        s = self._app.settings
        if not theme_exists(s, name):
            return False
        s["theme"] = name
        save_settings(s)
        dark_titlebar(self._app.hwnd, theme_colors(s, name))
        return True

    def save_custom_theme(self, theme):
        """Adds a new custom theme or updates one with the same id."""
        s = self._app.settings
        t = clean_custom_theme(theme)
        if not t:
            return {"error": "That theme couldn't be saved."}
        themes = [x for x in s.get("custom_themes") or [] if x["id"] != t["id"]]
        if len(themes) >= MAX_CUSTOM_THEMES:
            return {"error": f"You can keep up to {MAX_CUSTOM_THEMES} of your own themes. Delete one to make room."}
        old = next((i for i, x in enumerate(s.get("custom_themes") or []) if x["id"] == t["id"]), None)
        themes.insert(len(themes) if old is None else old, t)
        s["custom_themes"] = themes
        if s.get("theme") == CUSTOM_PREFIX + t["id"]:
            dark_titlebar(self._app.hwnd, theme_colors(s, s["theme"]))
        save_settings(s)
        return {"ok": True, "settings": self._app.public_settings()}

    def delete_custom_theme(self, tid):
        s = self._app.settings
        s["custom_themes"] = [x for x in s.get("custom_themes") or [] if x["id"] != tid]
        if s.get("theme") == CUSTOM_PREFIX + str(tid):
            s["theme"] = "midnight"
            dark_titlebar(self._app.hwnd, theme_colors(s, "midnight"))
        save_settings(s)
        return self._app.public_settings()

    def release_notes(self, version):
        if not REPO:
            return ""
        try:
            rel = updater._get(f"https://api.github.com/repos/{REPO}/releases/tags/v{version}")
            return (rel.get("body") or "").strip()
        except Exception:
            return ""

    def install_update(self):
        threading.Thread(target=self._app.install_update, daemon=True).start()
        return True

    def quit_app(self):
        threading.Thread(target=self._app.quit, daemon=True).start()
        return True


# ---------------------------------------------------------------- the app
class TrendApp:
    def __init__(self):
        self.settings = load_settings()
        self.settings["out_dir"] = self.settings.get("out_dir") or DEFAULTS["out_dir"]
        self.window = None
        self.tray = None
        self.ui_ready = False
        self.hidden = False
        self.quitting = False
        self.worker = None
        self.cancel_ev = None
        self.run = None
        self.launched = time.time()
        self.update_info = None
        self.update_status = ""
        self.updating = False
        self.lock = threading.Lock()
        self.hwnd = None
        self.splash = None
        self.splash_hwnd = None
        self.revealed = False
        self.centered = False
        if not theme_exists(self.settings, self.settings.get("theme")):
            self.settings["theme"] = "midnight"
        # remember whether this start is the first one after an update
        seen = self.settings.get("last_version_seen") or ""
        if not seen and self._had_older_install():
            seen = "1.3"                                  # v1.3 and older didn't record this
        self.just_updated = VERSION if seen and updater.vtuple(seen) < updater.vtuple(VERSION) else None
        if seen != VERSION:
            self.settings["last_version_seen"] = VERSION
            save_settings(self.settings)

    # ---- helpers
    @staticmethod
    def _had_older_install():
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                return "last_version_seen" not in json.load(f)
        except Exception:
            return False

    def emit(self, ev):
        if self.run is not None:
            self._track(ev)
        if not (self.window and self.ui_ready):
            return
        try:
            self.window.evaluate_js("window.__ev(%s)" % json.dumps(ev))
        except Exception:
            pass

    def _track(self, ev):
        """Keep a copy of scan progress so a reloaded page can pick up where it was."""
        r = self.run
        now = time.time() * 1000
        t = ev.get("type")
        if t == "progress":
            r.update(done=ev["done"], total=ev["total"], lastActivity=now,
                     label=f"{ev['label']} · page {ev['page']} of {ev['pages']}" if ev.get("page") else ev["label"])
        elif t == "step":
            r.update(label=ev["label"], lastActivity=now)
        elif t == "wait":
            r.update(waitUntil=now + ev["seconds"] * 1000, waitStart=now, waitReason=ev["reason"])
        elif t == "log":
            r["logs"] = (r["logs"] + [ev["msg"]])[-300:]

    def public_settings(self):
        return {k: v for k, v in self.settings.items() if k not in ("update_attempt",)}

    def reports_dir(self):
        return os.path.join(self.settings["out_dir"], "reports")

    _hist_cache = {}                                # report path -> (modified time, history row)

    def _report_files(self):
        return glob.glob(os.path.join(self.reports_dir(), "ugc_trends_*.json"))

    def history(self):
        """One row per saved scan. Each report is only read once (until it changes), so
        refreshing the list doesn't re-read every scan from disk."""
        items, cache, seen = [], TrendApp._hist_cache, set()
        for jp in self._report_files():
            try:
                mt = os.path.getmtime(jp)
            except OSError:
                continue
            seen.add(jp)
            hit = cache.get(jp)
            if hit and hit[0] == mt:
                items.append(dict(hit[1]))
                continue
            try:
                with open(jp, encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:
                continue
            dt = stamp_time(os.path.basename(jp))
            ideas = d.get("ideas") or []
            row = {
                "id": jp, "iso": dt.isoformat() if dt else None,
                "label": dt.strftime("%a %d %b, %H:%M") if dt else d.get("when", "?"),
                "label_long": dt.strftime("%a %d %b %Y, %H:%M") if dt else d.get("when", "?"),
                "scope": d.get("scope", ""), "n_items": d.get("n_items", 0),
                "top": f"{ideas[0]['theme'].title()} · {ideas[0]['type']}" if ideas else "—",
            }
            del d
            cache[jp] = (mt, row)
            items.append(dict(row))
        for gone in set(cache) - seen:
            cache.pop(gone, None)
        items.sort(key=lambda h: os.path.basename(h["id"]), reverse=True)
        return items

    def last_scan(self):
        """Time of the newest scan, from the file names alone (no files are opened)."""
        names = sorted(os.path.basename(p) for p in self._report_files())
        for name in reversed(names):
            dt = stamp_time(name)
            if dt:
                return dt
        return None

    def state(self):
        hist = self.history()
        running = None
        if self.worker and self.worker.is_alive() and self.run:
            running = dict(self.run)
        return {
            "version": VERSION, "frozen": FROZEN, "repo": REPO, "settings": self.public_settings(),
            "history": hist, "last_scan": hist[0]["iso"] if hist else None, "running": running,
            "update": self.update_info if (self.update_info or {}).get("available") else None,
            "update_status": self.update_status, "tray": bool(self.tray),
            "just_updated": self.just_updated,
        }

    def notify(self, title, text):
        if self.tray:
            try:
                self.tray.notify(text, title)
            except Exception:
                pass

    # ---- scanning
    def start_scan(self, force=False, auto=False):
        with self.lock:
            if self.worker and self.worker.is_alive():
                return {"error": "A scan is already running."}
            last = self.last_scan()
            if not force and not auto and last and (datetime.now() - last).total_seconds() < 15 * 60:
                mins = max(1, int((datetime.now() - last).total_seconds() // 60))
                return {"confirm": f"Your last scan was {mins} min ago. The marketplace won't have changed much, "
                                   "and scanning often makes Roblox more likely to slow you down."}
            s = self.settings
            cats = 1 if s["scope"] in ("accessories", "clothing") else 2
            pages = int(s["depth"])
            total = cats * len(core.LISTS) * pages + 1
            estimate = core.estimate_seconds(pages, cats, float(s["gap"]))
            now = time.time() * 1000
            self.run = {"auto": auto, "startTs": now, "total": total, "done": 0, "estimate": estimate,
                        "label": "Starting…", "waitUntil": 0, "waitedTotal": 0, "lastActivity": now, "logs": []}
            self.cancel_ev = threading.Event()
            core.HOOKS["log"] = lambda m: self.emit({"type": "log", "msg": m})
            core.HOOKS["event"] = self._core_event
            core.HOOKS["cancel"] = self.cancel_ev
            kw = dict(pages=pages, only=None if s["scope"] == "all" else s["scope"],
                      include_roblox=bool(s["include_roblox"]), blender_only=bool(s["blender_only"]),
                      delay=float(s["gap"]), out=s["out_dir"])
            self.worker = threading.Thread(target=self._scan_thread, args=(kw, auto), daemon=True)
            self.worker.start()
        self.emit({"type": "scan_start", "auto": auto, "total": total, "estimate": estimate})
        return {"ok": True}

    def _core_event(self, ev):
        if ev.get("type") in ("progress", "step", "wait"):
            self.emit(ev)

    def _scan_thread(self, kw, auto):
        try:
            path, summary = core.run_scan(**kw)
            jp = os.path.splitext(path)[0] + ".json"
            n = len(summary.get("ideas") or [])
            self.emit({"type": "scan_done", "id": jp, "n_ideas": n, "go": not auto})
            if self.hidden:
                top = (summary.get("ideas") or [None])[0]
                self.notify("New ideas are ready",
                            f"#1 idea: {top['theme'].title()} · {top['type']}" if top else "Scan finished.")
            elif self.settings.get("open_report"):
                webbrowser.open("file:///" + os.path.abspath(path).replace("\\", "/"))
        except core.ScanCancelled:
            self.emit({"type": "scan_cancelled"})
        except RuntimeError as e:
            self.emit({"type": "scan_error", "msg": str(e)})
            if self.hidden:
                self.notify("Scan didn't finish", str(e)[:200])
        except Exception as e:
            write_log(traceback.format_exc())
            self.emit({"type": "log", "msg": traceback.format_exc()})
            self.emit({"type": "scan_error", "msg": f"Something went wrong: {e}. Details were saved to {LOG_PATH}"})
        finally:
            self.run = None
            gc.collect()                            # give back the memory the scan used

    def cancel_scan(self):
        if self.cancel_ev:
            self.cancel_ev.set()

    def background_loop(self):
        """Automatic scans and update checks."""
        next_update_check = time.time() + 4
        tick = 0
        while not self.quitting:
            time.sleep(1)
            tick += 1
            if time.time() >= next_update_check:
                next_update_check = time.time() + 6 * 3600
                try:
                    self.check_update(manual=False)
                except Exception:
                    write_log(traceback.format_exc())
            if tick % 15:
                continue
            try:
                hrs = int(self.settings.get("auto_scan_hours") or 0)
                busy = self.worker and self.worker.is_alive()
                if hrs and not busy and not self.updating and time.time() - self.launched > 60:
                    last = self.last_scan()
                    if last is None or (datetime.now() - last).total_seconds() >= hrs * 3600:
                        self.start_scan(auto=True)
                        self.emit({"type": "toast", "msg": "Automatic scan started."})
            except Exception:
                write_log(traceback.format_exc())

    # ---- updates
    def check_update(self, manual=False):
        if not REPO:
            self.update_status = "Updates aren't set up for this copy."
            return {"message": self.update_status}
        try:
            info = updater.check(REPO, VERSION)
        except Exception as e:
            self.update_status = "Couldn't reach the update server."
            if manual:
                write_log(f"update check failed: {e}")
            return {"message": self.update_status}
        self.update_info = info
        if not info.get("available"):
            self.update_status = "You're up to date."
            return {"message": self.update_status}
        self.update_status = f"Version {info['version']} is available."
        attempt = self.settings.get("update_attempt") or {}
        recently_failed = attempt.get("version") == info["version"] and time.time() - attempt.get("at", 0) < 24 * 3600
        busy = self.worker and self.worker.is_alive()
        if not manual and self.settings.get("auto_install", False) and not recently_failed and not busy:
            if FROZEN and not info.get("installer_url"):
                return {"message": self.update_status}      # installer still building; try later
            threading.Thread(target=self.install_update, daemon=True).start()
        else:
            self.emit({"type": "update", "info": info})
            if self.hidden and not manual:
                self.notify("Update available", f"Version {info['version']} is ready. Open the app to update.")
        return {"message": self.update_status, "info": info}

    def install_update(self):
        info = self.update_info
        if not info or not info.get("available") or self.updating:
            return
        if self.worker and self.worker.is_alive():
            self.emit({"type": "toast", "msg": "The update will install after the current scan.", "kind": ""})
            return
        self.updating = True
        self.settings["update_attempt"] = {"version": info["version"], "at": time.time()}
        save_settings(self.settings)

        def prog(got, total):
            pct = int(100 * got / total) if total else 50
            self.emit({"type": "update_progress", "pct": min(95, pct),
                       "msg": f"Downloading version {info['version']}… {got / 1e6:.1f} MB"})
        try:
            self.emit({"type": "update_progress", "pct": 2, "msg": f"Downloading version {info['version']}…"})
            if FROZEN:
                updater.apply_installer(info, prog)
                self.emit({"type": "update_progress", "pct": 100, "msg": "Installing… the app will reopen by itself."})
                time.sleep(1.5)
                self.quit(force=True)
            else:
                updater.apply_source(info, APP_DIR, REPO, prog)
                self.emit({"type": "update_progress", "pct": 100, "msg": "Restarting…"})
                time.sleep(0.8)
                updater.restart_source(APP_DIR)
                self.quit(force=True)
        except Exception as e:
            write_log(traceback.format_exc())
            self.updating = False
            self.emit({"type": "update_progress", "stage": "failed", "msg": f"{e}"})

    # ---- window & tray
    def on_closing(self):
        if self.quitting:
            return True
        if self.settings.get("close_to_tray", True) and self.tray:
            threading.Thread(target=self.hide_window, daemon=True).start()
            if not self.settings.get("tray_hint_shown"):
                self.notify("Still running in the tray", "Right-click the icon to open the app or quit.")
                self.settings["tray_hint_shown"] = True
                save_settings(self.settings)
            return False
        self.quitting = True
        self._stop_tray()
        return True

    def hide_window(self):
        self.hidden = True
        try:
            self.window.hide()
        except Exception:
            pass
        self.webview_memory(low=True)
        gc.collect()

    def webview_memory(self, low):
        """While the app sits in the tray, ask the browser engine to use as little memory as
        it can; back to normal as soon as the window is shown again."""
        try:
            from System import Func, Type
            from Microsoft.Web.WebView2.Core import CoreWebView2MemoryUsageTargetLevel as Level
            form = self.window.native

            def apply():
                core_wv = form.webview.CoreWebView2
                if core_wv is not None:
                    core_wv.MemoryUsageTargetLevel = Level.Low if low else Level.Normal
            form.Invoke(Func[Type](apply))
        except Exception as e:
            write_log(f"memory level change skipped: {e}")

    def show_window(self):
        self.hidden = False
        self.webview_memory(low=False)
        if not self.centered and self.hwnd:         # started in the tray: first time it's opened
            self.centered = WinFx.center(self.hwnd)
        try:
            self.window.show()
            self.window.restore()
        except Exception:
            pass
        try:
            self.window.on_top = True
            time.sleep(0.2)
            self.window.on_top = False
        except Exception:
            pass

    def quit(self, force=False):
        if self.worker and self.worker.is_alive() and not force:
            self.cancel_scan()
        self.quitting = True
        self._stop_tray()
        try:
            self.window.destroy()
        except Exception:
            pass
        if force:
            time.sleep(1.0)
            os._exit(0)

    def _stop_tray(self):
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass

    def start_tray(self):
        try:
            import pystray
            from PIL import Image
        except Exception:
            write_log("tray unavailable: " + traceback.format_exc())
            return
        img = Image.open(os.path.join(APP_DIR, "icon.png"))

        def scan_from_tray(icon, item):
            r = self.start_scan(force=True)
            if r.get("ok"):
                self.notify("Scan started", "You'll get a notification when your ideas are ready.")
        menu = pystray.Menu(
            pystray.MenuItem("Open UGC Trend Finder", lambda i, it: self.show_window(), default=True),
            pystray.MenuItem("Scan now", scan_from_tray),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda i, it: threading.Thread(target=self.quit, daemon=True).start()),
        )
        self.tray = pystray.Icon("UGCTrendFinder", img, APP_NAME, menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def single_instance_server(self):
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind(("127.0.0.1", SINGLE_PORT))
            srv.listen(2)
        except OSError:
            return
        while not self.quitting:
            try:
                conn, _ = srv.accept()
                with conn:
                    if conn.recv(16) == b"show":
                        self.show_window()
            except OSError:
                break

    # ---- startup window
    def splash_progress(self, pct, text=""):
        sp = self.splash
        if sp is None:
            return
        try:
            sp.evaluate_js("window.setP && setP(%d, %s)" % (int(pct), json.dumps(text or "")))
        except Exception:
            pass

    def _splash_loaded(self):
        """The loading window was created hidden; now that its page has drawn, put it in the
        middle of the screen and show it (so it never appears as an empty box in a corner)."""
        close_native_splash()                       # only matters for older builds that still had one
        self.splash_hwnd = h = _hwnd_of(self.splash, SPLASH_TITLE)
        a = WinFx.api()
        if a and h:
            try:
                pref = a["ct"].c_int(2)             # rounded corners on Windows 11
                a["d"].DwmSetWindowAttribute(h, 33, a["ct"].byref(pref), 4)
            except Exception:
                pass
        centered = WinFx.center(h)
        write_log(f"startup: loading window hwnd={h} centered={centered} rect={WinFx.rect(h)}")
        if not self.revealed:
            try:
                self.splash.show()
            except Exception:
                pass
        self.splash_progress(18, "Starting…")

    def reveal(self):
        """Loading finished: fill the bar, then cross-fade from the loading window into the app.

        The app window starts fully transparent; over ~0.4 s it fades in (its content zooms
        up into place) while the loading window swells and fades out, so it reads as the
        small window opening up into the big one instead of one window popping in."""
        with self.lock:
            if self.revealed:
                return
            self.revealed = True
        sp, sp_hwnd = self.splash, getattr(self, "splash_hwnd", None)
        if sp is not None:
            self.splash_progress(100, "Ready")
            time.sleep(0.5)                         # let the bar finish filling
        main = getattr(self, "hwnd", None)
        if self.hidden:                             # started in the tray: nothing to animate
            self.emit_raw({"type": "reveal"})
            self.webview_memory(low=True)
        elif sp is not None and self._grow_into_app(sp, sp_hwnd, main):
            pass
        else:
            fade_main = WinFx.layered(main, True)
            if fade_main:
                WinFx.alpha(main, 0)
                WinFx.transitions(main, False)
            fade_sp = sp is not None and WinFx.layered(sp_hwnd, True)
            if fade_sp:
                WinFx.alpha(sp_hwnd, 255)
            try:
                self.window.show()
            except Exception:
                pass
            if sp is not None:
                try:
                    sp.evaluate_js("document.body.classList.add('leaving')")
                except Exception:
                    pass
            self.emit_raw({"type": "reveal"})
            dur, t0 = 0.42, time.perf_counter()
            while fade_main or fade_sp:
                t = min(1.0, (time.perf_counter() - t0) / dur)
                e = 1 - (1 - t) ** 3                # ease-out
                if fade_main:
                    WinFx.alpha(main, 255 * e)
                if fade_sp:
                    WinFx.alpha(sp_hwnd, 255 * (1 - min(1.0, t * 1.35)))
                if t >= 1:
                    break
                time.sleep(1 / 120)
            if fade_main:
                WinFx.alpha(main, 255)
                WinFx.layered(main, False)          # back to a normal window (no extra redraw cost)
                WinFx.transitions(main, True)       # keep Windows' usual minimize/restore animations
        if sp is not None:
            try:
                sp.destroy()
            except Exception:
                pass
            self.splash = None

    def _grow_into_app(self, sp, sp_hwnd, main):
        """The loading window stretches out until it covers exactly where the app window is,
        then fades away on top of the app. Returns False if this can't be done (then the
        simpler cross-fade runs instead)."""
        start = WinFx.rect(sp_hwnd)
        end = WinFx.rect(main, visible_frame=True)
        layered = bool(start and end) and WinFx.layered(main, True)
        write_log(f"reveal: splash={sp_hwnd} main={main} start={start} end={end} layered={layered}")
        if not layered:
            return False
        WinFx.alpha(main, 0)                        # the app stays invisible while the box grows
        WinFx.transitions(main, False)
        try:
            self.window.show()
        except Exception:
            pass
        try:
            sp.evaluate_js("document.body.classList.add('leaving')")   # logo + bar fade out
        except Exception:
            pass
        time.sleep(0.16)

        def ease(t):                                # smooth start and smooth landing
            return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2

        dur, t0 = 0.46, time.perf_counter()
        while True:
            t = min(1.0, (time.perf_counter() - t0) / dur)
            e = ease(t)
            WinFx.place(sp_hwnd, *(a + (b - a) * e for a, b in zip(start, end)))
            if t >= 1:
                break
            time.sleep(1 / 144)
        WinFx.alpha(main, 255)                      # app is now fully under the loading window
        self.emit_raw({"type": "reveal"})           # its content starts zooming in
        fade_sp = WinFx.layered(sp_hwnd, True)
        dur, t0 = 0.3, time.perf_counter()
        while fade_sp:
            t = min(1.0, (time.perf_counter() - t0) / dur)
            WinFx.alpha(sp_hwnd, 255 * (1 - t) ** 1.6)
            if t >= 1:
                break
            time.sleep(1 / 144)
        try:
            sp.hide()
        except Exception:
            pass
        WinFx.layered(main, False)
        WinFx.transitions(main, True)
        return True

    def _reveal_watchdog(self):
        time.sleep(25)                              # never leave the user staring at a loading window
        if not self.revealed:
            write_log("startup took too long; showing the window anyway")
            self.reveal()

    def emit_raw(self, ev):
        try:
            self.window.evaluate_js("window.__ev && window.__ev(%s)" % json.dumps(ev))
        except Exception:
            pass

    def on_started(self):
        """Runs once the window exists."""
        threading.Thread(target=prune_thumb_dir, daemon=True).start()
        hwnd = None
        for _ in range(40):                         # the window may take a moment to exist
            hwnd = _hwnd_of(self.window, APP_NAME)
            if hwnd:
                break
            time.sleep(0.05)
        self.hwnd = hwnd
        dark_titlebar(hwnd, theme_colors(self.settings, self.settings.get("theme", "midnight")))
        if not self.hidden:
            self.centered = WinFx.center(hwnd)      # open in the middle of the screen you're using
        write_log(f"startup: app window hwnd={hwnd} rect={WinFx.rect(hwnd)}")
        if self.splash is None:
            close_native_splash()
        threading.Thread(target=self._reveal_watchdog, daemon=True).start()
        self.start_tray()
        threading.Thread(target=self.single_instance_server, daemon=True).start()
        threading.Thread(target=self.background_loop, daemon=True).start()

    def run_app(self):
        import webview
        start_hidden = "--tray" in sys.argv          # started with Windows: stay in the tray
        self.hidden = start_hidden
        # The page is handed to the window directly (not loaded from a local address), so
        # another app running on this PC can never end up showing its page in this window.
        with open(os.path.join(APP_DIR, "ui", "index.html"), encoding="utf-8") as f:
            page = f.read()
        theme = self.settings.get("theme", "midnight")
        custom = find_custom_theme(self.settings, theme)
        win_bg = theme_colors(self.settings, theme)[0]

        def themed(html_text, extra="", splash=False):
            attrs = f'data-theme="custom" style="{custom_style(custom, splash)}"' if custom else f'data-theme="{theme}"'
            return html_text.replace('<html lang="en">', f'<html lang="en" {attrs}{extra}>', 1)
        page = themed(page, ' data-launch="managed"')
        # The app window loads hidden while a small loading window shows progress; when the
        # page is ready the loading window closes and the app fades in (see reveal()).
        self.window = webview.create_window(
            APP_NAME, html=page, js_api=Api(self),
            width=1280, height=840, min_size=(960, 640), background_color=win_bg, text_select=False,
            hidden=True)
        self.window.events.closing += self.on_closing
        if not start_hidden:
            with open(os.path.join(APP_DIR, "ui", "splash.html"), encoding="utf-8") as f:
                sp = themed(f.read(), splash=True)
            self.splash = webview.create_window(
                SPLASH_TITLE, html=sp, width=520, height=320, resizable=False, frameless=True,
                on_top=True, background_color=win_bg, text_select=False, hidden=True)
            self.splash.events.loaded += self._splash_loaded
        webview.start(self.on_started, debug=False, private_mode=False,
                      storage_path=os.path.join(DATA_HOME, "webview"))
        self.quitting = True
        self._stop_tray()


def main():
    if signal_running_instance():
        close_native_splash()
        return
    os.makedirs(DATA_HOME, exist_ok=True)
    trim_log()
    TrendApp().run_app()
    os._exit(0)


if __name__ == "__main__":
    main()

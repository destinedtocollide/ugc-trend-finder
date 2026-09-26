"""
UGC Trend Finder: desktop app
=============================
A native window (Edge WebView2 via pywebview) showing the interface in ui/index.html,
a system-tray icon, automatic scans and automatic updates.
"""

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
}

DATA_HOME = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "UGC Trend Finder")
SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".ugc_trend_finder_settings.json")
LOG_PATH = os.path.join(DATA_HOME, "app.log")
THUMB_DIR = os.path.join(DATA_HOME, "thumbs")
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
}


# ---------------------------------------------------------------- basics
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


def dark_titlebar(hwnd, theme="midnight"):
    """Colors the Windows title bar to match the theme (Windows 10/11)."""
    if sys.platform != "win32" or not hwnd:
        return
    _bg, caption, dark = THEMES.get(theme, THEMES["midnight"])
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
_THUMB_MEM = {}
_THUMB_LOCK = threading.Lock()


def _http(url, timeout=20):
    req = Request(url, headers={"User-Agent": core.UA})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def _to_data_uri(raw):
    """Shrinks the picture (smaller transfer to the page) and returns it as a data URI."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.thumbnail((320, 320))
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=86, method=4)
        return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        kind = "png" if raw[:4] == b"\x89PNG" else ("webp" if raw[8:12] == b"WEBP" else "jpeg")
        return f"data:image/{kind};base64," + base64.b64encode(raw).decode()


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
        if i in _THUMB_MEM:
            out[i] = _THUMB_MEM[i]
            continue
        path = os.path.join(THUMB_DIR, i + ".img")
        try:
            if os.path.getsize(path) > 0:
                with open(path, "rb") as f:
                    out[i] = _THUMB_MEM[i] = _to_data_uri(f.read())
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
            raw = _http(url)
            with open(os.path.join(THUMB_DIR, aid + ".img"), "wb") as f:
                f.write(raw)
            return aid, _to_data_uri(raw)
        except Exception:
            return aid, None
    with ThreadPoolExecutor(max_workers=6) as pool:
        for aid, uri in pool.map(grab, urls.items()):
            if uri:
                with _THUMB_LOCK:
                    _THUMB_MEM[aid] = uri
                out[aid] = uri
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
        allowed = set(DEFAULTS) - {"update_attempt", "tray_hint_shown", "out_dir", "last_version_seen"}
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
        if name not in THEMES:
            return False
        self._app.settings["theme"] = name
        save_settings(self._app.settings)
        dark_titlebar(self._app.hwnd, name)
        return True

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
        self.revealed = False
        if self.settings.get("theme") not in THEMES:
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

    def history(self):
        items = []
        for jp in glob.glob(os.path.join(self.reports_dir(), "ugc_trends_*.json")):
            try:
                with open(jp, encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:
                continue
            dt = stamp_time(os.path.basename(jp))
            ideas = d.get("ideas") or []
            items.append({
                "id": jp, "iso": dt.isoformat() if dt else None,
                "label": dt.strftime("%a %d %b, %H:%M") if dt else d.get("when", "?"),
                "label_long": dt.strftime("%a %d %b %Y, %H:%M") if dt else d.get("when", "?"),
                "scope": d.get("scope", ""), "n_items": d.get("n_items", 0),
                "top": f"{ideas[0]['theme'].title()} · {ideas[0]['type']}" if ideas else "—",
                "_sort": os.path.basename(jp),
            })
        items.sort(key=lambda h: h["_sort"], reverse=True)
        for h in items:
            h.pop("_sort")
        return items

    def last_scan(self):
        h = self.history()
        return datetime.fromisoformat(h[0]["iso"]) if h and h[0]["iso"] else None

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

    def show_window(self):
        self.hidden = False
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
        close_native_splash()                       # the animated window takes over from the static image
        try:
            hwnd = self.splash.native.Handle.ToInt64()
            import ctypes
            pref = ctypes.c_int(2)                  # rounded corners on Windows 11
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), 4)
        except Exception:
            pass
        self.splash_progress(18, "Starting…")

    def reveal(self):
        """Loading finished: fill the bar, then swap the loading window for the app."""
        with self.lock:
            if self.revealed:
                return
            self.revealed = True
        if self.splash is not None:
            self.splash_progress(100, "Ready")
            time.sleep(0.55)
        if not self.hidden:
            try:
                self.window.show()
            except Exception:
                pass
        self.emit_raw({"type": "reveal"})
        if self.splash is not None:
            time.sleep(0.12)
            try:
                self.splash.destroy()
            except Exception:
                pass
            self.splash = None

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
        try:
            native = self.window.native
            hwnd = native.Handle.ToInt64() if hasattr(native.Handle, "ToInt64") else int(native.Handle)
            self.hwnd = hwnd
            dark_titlebar(hwnd, self.settings.get("theme", "midnight"))
        except Exception:
            pass
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
        page = page.replace('<html lang="en">', f'<html lang="en" data-theme="{theme}" data-launch="managed">', 1)
        # The app window loads hidden while a small loading window shows progress; when the
        # page is ready the loading window closes and the app fades in (see reveal()).
        self.window = webview.create_window(
            APP_NAME, html=page, js_api=Api(self),
            width=1280, height=840, min_size=(960, 640), background_color=THEMES[theme][0], text_select=False,
            hidden=True)
        self.window.events.closing += self.on_closing
        if not start_hidden:
            with open(os.path.join(APP_DIR, "ui", "splash.html"), encoding="utf-8") as f:
                sp = f.read().replace('<html lang="en">', f'<html lang="en" data-theme="{theme}">', 1)
            self.splash = webview.create_window(
                APP_NAME, html=sp, width=520, height=320, resizable=False, frameless=True,
                on_top=True, background_color=THEMES[theme][0], text_select=False)
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
    TrendApp().run_app()
    os._exit(0)


if __name__ == "__main__":
    main()

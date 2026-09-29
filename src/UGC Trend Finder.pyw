"""Runs UGC Trend Finder from source. Installs its three helper packages the first time."""
import importlib
import os
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
NEEDED = {"webview": "pywebview", "pystray": "pystray", "PIL": "pillow"}


def missing():
    out = []
    for mod, pkg in NEEDED.items():
        try:
            importlib.import_module(mod)
        except Exception:
            out.append(pkg)
    return out


def install(pkgs):
    exe = sys.executable
    py = os.path.join(os.path.dirname(exe), "python.exe")
    py = py if os.path.exists(py) else exe
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for extra in ([], ["--user"]):
        r = subprocess.run([py, "-m", "pip", "install", "--disable-pip-version-check", "-q", *pkgs, *extra],
                           capture_output=True, creationflags=flags)
        if r.returncode == 0:
            break
    try:
        import site
        up = site.getusersitepackages()
        if up and os.path.isdir(up) and up not in sys.path:
            sys.path.append(up)
    except Exception:
        pass
    importlib.invalidate_caches()


todo = missing()
if todo:
    import tkinter as tk
    root = tk.Tk()
    root.title("UGC Trend Finder")
    root.configure(bg="#13161b")
    root.geometry("380x120")
    root.resizable(False, False)
    tk.Label(root, text="Setting up UGC Trend Finder…", fg="#e8eaee", bg="#13161b",
             font=("Segoe UI", 12, "bold")).pack(pady=(26, 4))
    tk.Label(root, text="One-time setup, this takes about a minute.", fg="#7f8795", bg="#13161b",
             font=("Segoe UI", 10)).pack()
    t = threading.Thread(target=install, args=(todo,), daemon=True)
    t.start()

    def wait():
        if t.is_alive():
            root.after(300, wait)
        else:
            root.destroy()
    root.after(300, wait)
    root.mainloop()
    if missing():
        from tkinter import messagebox
        r2 = tk.Tk()
        r2.withdraw()
        messagebox.showerror("UGC Trend Finder",
                             "The one-time setup didn't finish. Check your internet connection and try again, "
                             "or use the installer (UGC-Trend-Finder-Setup.exe) instead.")
        sys.exit(1)

if not os.path.exists(os.path.join(HERE, "icon.png")):
    import make_icons  # noqa: E402
    make_icons.main(HERE)

import app  # noqa: E402

app.main()

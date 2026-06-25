"""
herald_tray.py — Herald system tray daemon.

Sits in the system tray. Shows a Windows notification when a peer sends a message.
No terminal window — launch with pythonw.exe.

Auto-start setup (run once in PowerShell):
    python herald_tray.py --install
"""
import json
import sys
import threading
import time
from pathlib import Path

import httpx
import pystray
from PIL import Image, ImageDraw

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def make_icon() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], fill=(30, 120, 220, 255))  # blue ring
    d.ellipse([18, 18, 46, 46], fill=(255, 255, 255, 255))  # white center
    return img


def sse_loop(icon: pystray.Icon, server_url: str, peer_name: str) -> None:
    url = f"{server_url.rstrip('/')}/subscribe"
    while icon._running:
        try:
            with httpx.Client(timeout=None) as client:
                with client.stream("GET", url, params={"peer": peer_name}) as r:
                    for line in r.iter_lines():
                        if not icon._running:
                            return
                        if line.startswith("data:"):
                            payload = json.loads(line[5:].strip())
                            from_peer = payload.get("from_peer", "?")
                            msg_id = payload.get("message_id", "?")[:8]
                            icon.notify(
                                f"From: {from_peer}  |  ID: {msg_id}…\nOpen Claude Code to get_pending and reply.",
                                title="Herald — New Message",
                            )
        except Exception:
            pass
        if icon._running:
            time.sleep(5)


def install_startup() -> None:
    """Add a Startup folder shortcut so herald_tray runs at logon."""
    import os, winreg  # noqa: F401 — windows only
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    script = Path(__file__).resolve()
    startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/herald_tray.lnk"

    import win32com.client  # pywin32
    wsh = win32com.client.Dispatch("WScript.Shell")
    lnk = wsh.CreateShortcut(str(startup))
    lnk.TargetPath = str(pythonw)
    lnk.Arguments = f'"{script}"'
    lnk.WorkingDirectory = str(script.parent)
    lnk.Save()
    print(f"Shortcut created: {startup}")


def main() -> None:
    if "--install" in sys.argv:
        install_startup()
        return

    cfg = load_config()

    icon = pystray.Icon(
        name="herald",
        icon=make_icon(),
        title=f"Herald ({cfg['name']})",
        menu=pystray.Menu(
            pystray.MenuItem("Exit", lambda: icon.stop())
        ),
    )
    icon._running = True

    threading.Thread(
        target=sse_loop,
        args=(icon, cfg["server_url"], cfg["name"]),
        daemon=True,
    ).start()

    icon.run()
    icon._running = False


if __name__ == "__main__":
    main()

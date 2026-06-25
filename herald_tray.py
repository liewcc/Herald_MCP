"""
herald_tray.py — Herald system tray daemon.

Sits in the system tray. Shows a Windows notification when a peer sends a message.
No terminal window — launch with pythonw.exe.

Auto-start setup (run once in PowerShell):
    python herald_tray.py --install
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

import httpx
import pystray
from PIL import Image, ImageDraw

CONFIG_PATH = Path(__file__).parent / "config.json"
STARTUP_LNK = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/herald_tray.lnk"


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


def is_startup_enabled() -> bool:
    return STARTUP_LNK.exists()


def install_startup() -> None:
    import win32com.client
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    script = Path(__file__).resolve()
    wsh = win32com.client.Dispatch("WScript.Shell")
    lnk = wsh.CreateShortcut(str(STARTUP_LNK))
    lnk.TargetPath = str(pythonw)
    lnk.Arguments = f'"{script}"'
    lnk.WorkingDirectory = str(script.parent)
    lnk.Save()


def uninstall_startup() -> None:
    STARTUP_LNK.unlink(missing_ok=True)


def toggle_startup(icon, item) -> None:
    if is_startup_enabled():
        uninstall_startup()
    else:
        install_startup()


def main() -> None:
    if "--install" in sys.argv:
        install_startup()
        print(f"Shortcut created: {STARTUP_LNK}")
        return

    cfg = load_config()

    icon = pystray.Icon(
        name="herald",
        icon=make_icon(),
        title=f"Herald ({cfg['name']})",
        menu=pystray.Menu(
            pystray.MenuItem(
                "Start on Login",
                toggle_startup,
                checked=lambda item: is_startup_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda: icon.stop()),
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

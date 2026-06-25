"""
herald_tray.py — Herald system tray daemon with full UI window.

Left-click tray icon  → open/focus the Herald window
Close window (X)      → minimize back to tray (keeps running)
Right-click tray icon → Exit

Auto Reply: when enabled, invokes claude.exe once per incoming message (event-driven,
            NOT a timer — zero token cost while idle).

Auto-start: python herald_tray.py --install
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, simpledialog
from pathlib import Path

import httpx
import pystray
from PIL import Image, ImageDraw

CONFIG_PATH = Path(__file__).parent / "config.json"
STARTUP_LNK = (
    Path(os.environ["APPDATA"])
    / "Microsoft/Windows/Start Menu/Programs/Startup/herald_tray.lnk"
)

REPLY_PROMPT = (
    "Use the herald MCP tools. Call get_pending to retrieve incoming messages. "
    "For each message, process it and call reply with an appropriate response. "
    "When done, exit."
)
ALLOWED_TOOLS = "mcp__herald__get_pending,mcp__herald__reply"


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ── Tray icon image ───────────────────────────────────────────────────────────

def make_icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], fill=(30, 120, 220, 255))
    d.ellipse([18, 18, 46, 46], fill=(255, 255, 255, 255))
    return img


# ── Startup shortcut ──────────────────────────────────────────────────────────

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


# ── Claude auto-reply ─────────────────────────────────────────────────────────

def find_claude_exe() -> str | None:
    base = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude-code"
    if base.exists():
        for d in sorted(base.iterdir(), key=lambda p: p.name, reverse=True):
            exe = d / "claude.exe"
            if exe.exists():
                return str(exe)
    return shutil.which("claude")


def invoke_claude_reply(project_dir: str) -> None:
    claude_exe = find_claude_exe()
    if not claude_exe:
        return
    subprocess.Popen(
        [claude_exe, "-p", REPLY_PROMPT, "--allowedTools", ALLOWED_TOOLS],
        cwd=project_dir,
    )


# ── Herald UI window ──────────────────────────────────────────────────────────

class HeraldWindow:
    def __init__(self, cfg: dict, msg_queue: queue.Queue):
        self.cfg = cfg
        self.peer_name = cfg["name"]
        self.msg_queue = msg_queue
        self.project_dir = str(Path(__file__).parent)

        self.root = tk.Tk()
        self.root.title(f"Herald — {self.peer_name}")
        self.root.geometry("420x360")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

        self._reconnect = threading.Event()
        self._build_ui()
        self.root.withdraw()
        self.root.after(300, self._poll_messages)

    def _build_ui(self):
        # ── Status bar ───────────────────────────────────────────────────────
        top = tk.Frame(self.root, padx=10, pady=8)
        top.pack(fill="x")

        tk.Label(top, text="Herald", font=("Segoe UI", 13, "bold")).pack(side="left")

        self.name_label = tk.Label(
            top, text=self.peer_name,
            font=("Segoe UI", 9), fg="#555", cursor="hand2",
        )
        self.name_label.pack(side="left", padx=(6, 0))
        self.name_label.bind("<Button-1>", lambda e: self._rename())

        self.status_dot = tk.Label(top, text="●", fg="#aaa", font=("Segoe UI", 14))
        self.status_dot.pack(side="right")
        self.status_label = tk.Label(top, text="Connecting…", fg="#888", font=("Segoe UI", 9))
        self.status_label.pack(side="right", padx=(0, 4))

        ttk.Separator(self.root, orient="horizontal").pack(fill="x")

        # ── Message log ──────────────────────────────────────────────────────
        tk.Label(self.root, text="Incoming Messages", font=("Segoe UI", 9, "bold"),
                 anchor="w", padx=10).pack(fill="x", pady=(6, 2))

        frame = tk.Frame(self.root, padx=10)
        frame.pack(fill="both", expand=True)

        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")

        self.log = tk.Text(
            frame, height=10, font=("Consolas", 9),
            state="disabled", wrap="word",
            yscrollcommand=scrollbar.set,
            bg="#f8f8f8", relief="flat", bd=0,
        )
        self.log.pack(fill="both", expand=True)
        scrollbar.config(command=self.log.yview)

        ttk.Separator(self.root, orient="horizontal").pack(fill="x", pady=(6, 0))

        # ── Bottom bar ───────────────────────────────────────────────────────
        bottom = tk.Frame(self.root, padx=10, pady=8)
        bottom.pack(fill="x")

        self.startup_var = tk.BooleanVar(value=is_startup_enabled())
        tk.Checkbutton(
            bottom, text="Start on Login",
            variable=self.startup_var,
            command=self._toggle_startup,
            font=("Segoe UI", 9),
        ).pack(side="left")

        self.autoreply_var = tk.BooleanVar(value=self.cfg.get("auto_reply", False))
        tk.Checkbutton(
            bottom, text="Auto Reply",
            variable=self.autoreply_var,
            command=self._toggle_autoreply,
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(12, 0))

        tk.Button(
            bottom, text="Exit", command=self._exit,
            font=("Segoe UI", 9), relief="flat", bd=1,
            padx=10,
        ).pack(side="right")

    def _toggle_startup(self):
        if self.startup_var.get():
            install_startup()
        else:
            uninstall_startup()

    def _toggle_autoreply(self):
        self.cfg["auto_reply"] = self.autoreply_var.get()
        save_config(self.cfg)

    def _rename(self):
        new_name = simpledialog.askstring(
            "Rename Machine",
            "Enter new machine name:",
            initialvalue=self.peer_name,
            parent=self.root,
        )
        if not new_name or new_name.strip() == self.peer_name:
            return
        new_name = new_name.strip()
        self.cfg["name"] = new_name
        self.peer_name = new_name
        save_config(self.cfg)
        self.name_label.config(text=new_name)
        self.root.title(f"Herald — {new_name}")
        # Signal SSE thread to reconnect with new name by setting reconnect flag
        self._reconnect.set()

    def _exit(self):
        self.root.destroy()
        os._exit(0)

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self):
        self.root.withdraw()

    def set_status(self, connected: bool):
        if connected:
            self.status_dot.config(fg="#22bb44")
            self.status_label.config(text="Connected")
        else:
            self.status_dot.config(fg="#cc3333")
            self.status_label.config(text="Disconnected")

    def append_message(self, from_peer: str, msg_id: str, auto_replied: bool = False):
        ts = time.strftime("%H:%M:%S")
        suffix = "  → auto-replied" if auto_replied else ""
        line = f"[{ts}] from {from_peer}  |  ID: {msg_id[:8]}…{suffix}\n"
        self.log.config(state="normal")
        self.log.insert("end", line)
        self.log.see("end")
        self.log.config(state="disabled")

    def _poll_messages(self):
        try:
            while True:
                event = self.msg_queue.get_nowait()
                if event["type"] == "status":
                    self.set_status(event["connected"])
                elif event["type"] == "message":
                    auto_replied = event.get("auto_replied", False)
                    self.append_message(event["from_peer"], event["message_id"], auto_replied)
        except queue.Empty:
            pass
        self.root.after(300, self._poll_messages)

    def run(self):
        self.root.mainloop()


# ── SSE background thread ─────────────────────────────────────────────────────

def sse_thread(cfg: dict, msg_queue: queue.Queue, running: threading.Event,
               reconnect: threading.Event, project_dir: str) -> None:
    server_url = cfg["server_url"]
    url = f"{server_url.rstrip('/')}/subscribe"

    while running.is_set():
        reconnect.clear()
        peer_name = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("name", cfg["name"])
        try:
            with httpx.Client(timeout=None) as client:
                with client.stream("GET", url, params={"peer": peer_name}) as r:
                    msg_queue.put({"type": "status", "connected": True})
                    for line in r.iter_lines():
                        if not running.is_set() or reconnect.is_set():
                            break
                        if not line.startswith("data:"):
                            continue
                        payload = json.loads(line[5:].strip())
                        from_peer = payload.get("from_peer", "?")
                        msg_id = payload.get("message_id", "?")

                        auto_reply = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("auto_reply", False)
                        if auto_reply:
                            invoke_claude_reply(project_dir)

                        msg_queue.put({
                            "type": "message",
                            "from_peer": from_peer,
                            "message_id": msg_id,
                            "auto_replied": auto_reply,
                        })
        except Exception:
            pass
        msg_queue.put({"type": "status", "connected": False})
        if running.is_set() and not reconnect.is_set():
            time.sleep(5)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    if "--install" in sys.argv:
        install_startup()
        print(f"Shortcut created: {STARTUP_LNK}")
        return

    cfg = load_config()
    project_dir = str(Path(__file__).parent)

    msg_queue: queue.Queue = queue.Queue()
    running = threading.Event()
    running.set()

    win = HeraldWindow(cfg, msg_queue)

    threading.Thread(
        target=sse_thread,
        args=(cfg, msg_queue, running, win._reconnect, project_dir),
        daemon=True,
    ).start()

    def on_click(icon, item):
        win.show()

    icon = pystray.Icon(
        name="herald",
        icon=make_icon_image(),
        title=f"Herald ({cfg['name']})",
        menu=pystray.Menu(
            pystray.MenuItem("Open", on_click, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda: win._exit()),
        ),
    )

    threading.Thread(target=icon.run, daemon=True).start()

    win.run()


if __name__ == "__main__":
    import traceback
    try:
        main()
    except Exception:
        log = Path(__file__).parent / "herald_tray.log"
        log.write_text(traceback.format_exc(), encoding="utf-8")
        raise

"""
herald_tray.py — Herald system tray daemon with full UI window.

Left-click tray icon  → open/focus the Herald window
Close window (X)      → minimize back to tray (keeps running)
Right-click tray icon → Exit

Tabs:
  Messages    — incoming message/deposit log (SSE events)
  Comm Log    — full two-way log from herald_comm.log (exec_shell + ask_peer)
  Remote Tasks — fire exec_shell to a peer and see their running processes

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
import uuid
import tkinter as tk
from tkinter import ttk, simpledialog
from pathlib import Path

import httpx
import pystray
from PIL import Image, ImageDraw

CONFIG_PATH    = Path(__file__).parent / "config.json"
COMM_LOG       = Path(__file__).parent / "herald_comm.log"
STARTUP_LNK    = (
    Path(os.environ["APPDATA"])
    / "Microsoft/Windows/Start Menu/Programs/Startup/herald_tray.lnk"
)

REPLY_PROMPT = (
    "Use herald MCP tools. Call get_pending to see incoming messages. "
    "For each message where the message body is NOT a JSON object with type='shell': "
    "read the from_peer field, then call ask_peer(peer_name=<from_peer>, message=<your response>). "
    "Do NOT call reply() — the original connection is gone. "
    "Ignore shell-type messages. When done, exit."
)
ALLOWED_TOOLS = "mcp__herald__get_pending,mcp__herald__ask_peer"

# Preset commands for Remote Tasks tab
TASK_PRESETS = [
    "tasklist | findstr /i claude",
    "tasklist | findstr /i python",
    "Get-Process | Sort-Object CPU -Descending | Select-Object -First 15 | Format-Table Name,Id,CPU -AutoSize",
    "tasklist",
]


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
    native = Path.home() / ".local" / "bin" / "claude.exe"
    if native.exists():
        return str(native)
    base = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude-code"
    if base.exists():
        for d in sorted(base.iterdir(), key=lambda p: p.name, reverse=True):
            exe = d / "claude.exe"
            if exe.exists():
                return str(exe)
    return shutil.which("claude")


_claude_proc: subprocess.Popen | None = None


def invoke_claude_reply(project_dir: str) -> None:
    global _claude_proc
    # ponytail: single-instance guard — skip if previous claude is still running
    if _claude_proc is not None and _claude_proc.poll() is None:
        return
    claude_exe = find_claude_exe()
    if not claude_exe:
        return
    _claude_proc = subprocess.Popen(
        [claude_exe, "-p", REPLY_PROMPT, "--allowedTools", ALLOWED_TOOLS],
        cwd=project_dir,
        creationflags=subprocess.CREATE_NO_WINDOW,
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
        self.root.geometry("720x520")
        self.root.minsize(600, 400)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

        self._reconnect = threading.Event()
        self._log_pos = 0  # byte offset in herald_comm.log
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

        # ── Notebook ─────────────────────────────────────────────────────────
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)

        self._build_messages_tab()
        self._build_commlog_tab()
        self._build_tasks_tab()

        ttk.Separator(self.root, orient="horizontal").pack(fill="x")

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
            font=("Segoe UI", 9), relief="flat", bd=1, padx=10,
        ).pack(side="right")

    # ── Tab 1: Messages ───────────────────────────────────────────────────────

    def _build_messages_tab(self):
        frame = tk.Frame(self.nb)
        self.nb.add(frame, text="  Messages  ")

        inner = tk.Frame(frame, padx=8, pady=4)
        inner.pack(fill="both", expand=True)

        sb = tk.Scrollbar(inner)
        sb.pack(side="right", fill="y")

        self.msg_log = tk.Text(
            inner, font=("Consolas", 9), state="disabled", wrap="word",
            yscrollcommand=sb.set, bg="#f8f8f8", relief="flat", bd=0,
        )
        self.msg_log.pack(fill="both", expand=True)
        sb.config(command=self.msg_log.yview)

        self.msg_log.tag_config("msg",  foreground="#336600")
        self.msg_log.tag_config("dep",  foreground="#885500")
        self.msg_log.tag_config("auto", foreground="#888888")

    # ── Tab 2: Comm Log ───────────────────────────────────────────────────────

    def _build_commlog_tab(self):
        frame = tk.Frame(self.nb)
        self.nb.add(frame, text="  Comm Log  ")

        toolbar = tk.Frame(frame, padx=8, pady=4)
        toolbar.pack(fill="x")
        tk.Label(toolbar, text="Channel:", font=("Segoe UI", 8), fg="#666").pack(side="left")
        tk.Label(toolbar, text="■ exec_shell", font=("Segoe UI", 8), fg="#0055cc").pack(side="left", padx=(4, 8))
        tk.Label(toolbar, text="■ ask_peer", font=("Segoe UI", 8), fg="#770099").pack(side="left", padx=(0, 8))
        tk.Label(toolbar, text="■ SSE msg", font=("Segoe UI", 8), fg="#996600").pack(side="left", padx=(0, 8))
        tk.Label(toolbar, text="■ error", font=("Segoe UI", 8), fg="#cc0000").pack(side="left")
        tk.Button(toolbar, text="Clear", font=("Segoe UI", 8), relief="flat", bd=1,
                  command=self._clear_commlog).pack(side="right")

        inner = tk.Frame(frame, padx=8, pady=4)
        inner.pack(fill="both", expand=True)

        sb = tk.Scrollbar(inner)
        sb.pack(side="right", fill="y")

        self.comm_log = tk.Text(
            inner, font=("Consolas", 9), state="disabled", wrap="none",
            yscrollcommand=sb.set, bg="#0f0f0f", fg="#cccccc", relief="flat", bd=0,
        )
        self.comm_log.pack(fill="both", expand=True)
        sb.config(command=self.comm_log.yview)

        self.comm_log.tag_config("shell_out", foreground="#44aaff")
        self.comm_log.tag_config("shell_in",  foreground="#66ccff")
        self.comm_log.tag_config("claude_out", foreground="#cc88ff")
        self.comm_log.tag_config("claude_in",  foreground="#dd99ff")
        self.comm_log.tag_config("msg_in",     foreground="#ffcc44")
        self.comm_log.tag_config("err",        foreground="#ff4444")
        self.comm_log.tag_config("ts",         foreground="#666666")

    def _clear_commlog(self):
        self.comm_log.config(state="normal")
        self.comm_log.delete("1.0", "end")
        self.comm_log.config(state="disabled")
        # reset file position to end so we don't re-read old entries
        if COMM_LOG.exists():
            self._log_pos = COMM_LOG.stat().st_size

    # ── Tab 3: Remote Tasks ───────────────────────────────────────────────────

    def _build_tasks_tab(self):
        frame = tk.Frame(self.nb)
        self.nb.add(frame, text="  Remote Tasks  ")

        toolbar = tk.Frame(frame, padx=8, pady=6)
        toolbar.pack(fill="x")

        tk.Label(toolbar, text="Peer:", font=("Segoe UI", 9)).pack(side="left")
        peers = self.cfg.get("peers", ["April"])
        self._tasks_peer = tk.StringVar(value=peers[0] if peers else "")
        peer_cb = ttk.Combobox(toolbar, textvariable=self._tasks_peer,
                                values=peers, width=12, font=("Segoe UI", 9))
        peer_cb.pack(side="left", padx=(4, 10))

        tk.Label(toolbar, text="Cmd:", font=("Segoe UI", 9)).pack(side="left")
        self._tasks_cmd = tk.StringVar(value=TASK_PRESETS[0])
        cmd_cb = ttk.Combobox(toolbar, textvariable=self._tasks_cmd,
                               values=TASK_PRESETS, width=48, font=("Consolas", 9))
        cmd_cb.pack(side="left", padx=(4, 8))

        self._tasks_btn = tk.Button(
            toolbar, text="Refresh", font=("Segoe UI", 9), relief="flat", bd=1,
            padx=10, command=self._refresh_tasks,
        )
        self._tasks_btn.pack(side="left")

        self._tasks_status = tk.Label(toolbar, text="", font=("Segoe UI", 8), fg="#888")
        self._tasks_status.pack(side="left", padx=(8, 0))

        inner = tk.Frame(frame, padx=8, pady=4)
        inner.pack(fill="both", expand=True)

        sb = tk.Scrollbar(inner)
        sb.pack(side="right", fill="y")

        self.tasks_text = tk.Text(
            inner, font=("Consolas", 9), state="disabled", wrap="none",
            yscrollcommand=sb.set, bg="#0f0f0f", fg="#cccccc", relief="flat", bd=0,
        )
        self.tasks_text.pack(fill="both", expand=True)
        sb.config(command=self.tasks_text.yview)

        self.tasks_text.tag_config("claude", foreground="#cc88ff")
        self.tasks_text.tag_config("python", foreground="#44aaff")
        self.tasks_text.tag_config("err",    foreground="#ff4444")

    def _refresh_tasks(self):
        peer = self._tasks_peer.get().strip()
        cmd  = self._tasks_cmd.get().strip()
        if not peer or not cmd:
            return
        self._tasks_btn.config(state="disabled")
        self._tasks_status.config(text="Querying…")
        threading.Thread(target=self._do_refresh_tasks, args=(peer, cmd), daemon=True).start()

    def _do_refresh_tasks(self, peer: str, cmd: str) -> None:
        try:
            cfg   = load_config()
            relay = cfg.get("server_url", f"http://localhost:{cfg.get('port', 7700)}")
            payload = {
                "message_id": str(uuid.uuid4()),
                "from_peer":  cfg.get("name", "unknown"),
                "to_peer":    peer,
                "message":    json.dumps({"type": "shell", "cmd": cmd}),
                "attachments": [],
            }
            with httpx.Client(timeout=20.0) as client:
                r = client.post(f"{relay.rstrip('/')}/ask", json=payload)
                data   = r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"}
                answer = data.get("answer", str(data))
                try:
                    result = json.loads(answer)
                    text = result.get("stdout") or result.get("error") or answer
                except Exception:
                    text = answer
        except Exception as e:
            text = f"Error: {e}"
        self.msg_queue.put({"type": "tasks_result", "text": text})

    # ── Polling ───────────────────────────────────────────────────────────────

    def _poll_messages(self):
        try:
            while True:
                event = self.msg_queue.get_nowait()
                etype = event["type"]
                if etype == "status":
                    self.set_status(event["connected"])
                elif etype in ("message", "deposit"):
                    self._append_msg_log(event)
                elif etype == "commlog":
                    self._append_comm_entry(event["entry"])
                elif etype == "tasks_result":
                    self._update_tasks(event["text"])
        except queue.Empty:
            pass
        self._tail_comm_log()
        self.root.after(300, self._poll_messages)

    def _tail_comm_log(self):
        if not COMM_LOG.exists():
            return
        try:
            with COMM_LOG.open("r", encoding="utf-8") as f:
                f.seek(self._log_pos)
                new_data = f.read()
                self._log_pos = f.tell()
            for line in new_data.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    self._append_comm_entry(entry)
                except Exception:
                    pass
        except Exception:
            pass

    # ── Rendering helpers ─────────────────────────────────────────────────────

    def _append_msg_log(self, event: dict):
        ts = time.strftime("%H:%M:%S")
        from_peer = event.get("from_peer", "?")
        mid       = event.get("message_id", "?")
        if event["type"] == "deposit":
            line = f"[{ts}] deposit from {from_peer}  ID:{mid[:8]}…\n"
            tag  = "dep"
        else:
            auto   = event.get("auto_replied", False)
            suffix = "  → auto-replied" if auto else ""
            line   = f"[{ts}] from {from_peer}  ID:{mid[:8]}…{suffix}\n"
            tag    = "msg"
        self.msg_log.config(state="normal")
        self.msg_log.insert("end", line, tag)
        self.msg_log.see("end")
        self.msg_log.config(state="disabled")

    def _append_comm_entry(self, entry: dict):
        tool = entry.get("tool", "")
        direction = entry.get("dir", "")
        ts   = entry.get("ts", "?")
        peer = entry.get("peer") or entry.get("from") or entry.get("to") or "?"

        # determine display text and color tag
        if tool == "exec_shell":
            if direction == "out":
                cmd  = entry.get("cmd", "")
                text = f"[{ts}] → exec_shell → {peer}: {cmd}\n"
                tag  = "shell_out"
            else:
                rc      = entry.get("rc", "?")
                preview = (entry.get("preview") or entry.get("error") or "")[:120]
                error   = entry.get("error")
                text    = f"[{ts}] ← {peer} rc={rc}: {preview}\n"
                tag     = "err" if error else "shell_in"
        elif tool == "ask_peer":
            if direction == "out":
                msg  = entry.get("msg", "")[:100]
                text = f"[{ts}] → ask_peer → {peer}: {msg}\n"
                tag  = "claude_out"
            else:
                preview = (entry.get("preview") or entry.get("error") or "")[:120]
                error   = entry.get("error")
                text    = f"[{ts}] ← {peer}: {preview}\n"
                tag     = "err" if error else "claude_in"
        elif tool == "message":
            mid  = entry.get("mid", "?")
            text = f"[{ts}] ← [SSE msg] {peer}  ID:{mid[:8]}…\n"
            tag  = "msg_in"
        else:
            # other entries (exec, reply, blocked from shell_agent.log)
            text = f"[{ts}] {json.dumps(entry)}\n"
            tag  = "ts"

        self.comm_log.config(state="normal")
        self.comm_log.insert("end", text, tag)
        self.comm_log.see("end")
        self.comm_log.config(state="disabled")

    def _update_tasks(self, text: str):
        self._tasks_btn.config(state="normal")
        self._tasks_status.config(text=f"Updated {time.strftime('%H:%M:%S')}")
        self.tasks_text.config(state="normal")
        self.tasks_text.delete("1.0", "end")
        for line in text.splitlines():
            if any(k in line.lower() for k in ("claude", "claude.exe")):
                self.tasks_text.insert("end", line + "\n", "claude")
            elif "python" in line.lower():
                self.tasks_text.insert("end", line + "\n", "python")
            else:
                self.tasks_text.insert("end", line + "\n")
        self.tasks_text.config(state="disabled")

    # ── Controls ──────────────────────────────────────────────────────────────

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

    def run(self):
        self.root.mainloop()


# ── SSE background thread ─────────────────────────────────────────────────────

def _comm_log_write(entry: dict) -> None:
    import datetime
    entry.setdefault("ts", datetime.datetime.now().strftime("%H:%M:%S"))
    with COMM_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _load_allowlist() -> list:
    """Load shell command allowlist from allowlist.json."""
    p = Path(__file__).parent / "allowlist.json"
    import re
    rules = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    result = []
    for r in rules:
        if r.get("type") == "regex":
            result.append(re.compile(r["value"], re.IGNORECASE))
        else:
            result.append(r["value"])
    return result


def _shell_allowed(cmd: str, allowlist: list) -> bool:
    import re
    s = cmd.strip()
    for rule in allowlist:
        if isinstance(rule, re.Pattern):
            if rule.match(s):
                return True
        elif s.startswith(rule):
            return True
    return False


def _handle_shell(mid: str, cmd: str, timeout_s: int, from_peer: str,
                  relay: str, allowlist: list) -> None:
    """Execute a shell command and post the reply — runs in a daemon thread."""
    if not _shell_allowed(cmd, allowlist):
        answer = json.dumps({"error": f"command not in allowlist: {cmd!r}", "returncode": -1})
        _comm_log_write({"dir": "blocked", "from": from_peer, "cmd": cmd})
    else:
        _comm_log_write({"dir": "exec", "from": from_peer, "cmd": cmd})
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True, text=True, timeout=timeout_s,
            )
            result = {"stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode}
        except subprocess.TimeoutExpired:
            result = {"error": "command timed out", "returncode": -1}
        except Exception as e:
            result = {"error": str(e), "returncode": -1}
        answer = json.dumps(result)
        _comm_log_write({"dir": "reply", "to": from_peer,
                         "rc": result.get("returncode"), "preview": answer[:200]})

    try:
        with httpx.Client(timeout=10.0) as c:
            c.post(f"{relay.rstrip('/')}/reply/{mid}", json={"answer": answer})
    except Exception:
        pass


def sse_thread(cfg: dict, msg_queue: queue.Queue, running: threading.Event,
               reconnect: threading.Event, project_dir: str) -> None:
    """Single SSE subscriber — handles both shell commands and chat auto-reply.

    Merging shell_agent logic here ensures only one subscriber per peer,
    avoiding relay work-queue delivery misses when two processes both subscribe.
    """
    server_url = cfg["server_url"]
    relay      = server_url.rstrip("/")
    url        = f"{relay}/subscribe"
    allowlist  = _load_allowlist()

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
                        event_type = payload.get("type", "message")
                        from_peer  = payload.get("from_peer", "?")

                        if event_type == "deposit":
                            mid = payload.get("deposit_id", "?")
                            msg_queue.put({
                                "type": "deposit",
                                "from_peer": from_peer,
                                "message_id": mid,
                            })
                            continue

                        mid = payload.get("message_id", "?")

                        # fetch full message body via a separate client
                        # (never reuse the SSE streaming client for other requests)
                        msg_body = None
                        try:
                            with httpx.Client(timeout=5.0) as peek:
                                rp = peek.get(f"{relay}/pending", params={"peer": peer_name})
                                for m in (rp.json() if rp.status_code == 200 else []):
                                    if m.get("message_id") == mid:
                                        msg_body = m
                                        break
                        except Exception:
                            pass

                        # parse body to determine routing
                        shell_body = None
                        if msg_body:
                            try:
                                parsed = json.loads(msg_body.get("message", ""))
                                if parsed.get("type") == "shell":
                                    shell_body = parsed
                            except Exception:
                                pass

                        if shell_body:
                            # shell command — execute and reply directly, no claude
                            _comm_log_write({"dir": "in", "tool": "exec_shell",
                                             "from": from_peer, "cmd": shell_body.get("cmd", "")})
                            threading.Thread(
                                target=_handle_shell,
                                args=(mid, shell_body.get("cmd", ""),
                                      int(shell_body.get("timeout", 60)),
                                      from_peer, relay, allowlist),
                                daemon=True,
                            ).start()
                            msg_queue.put({
                                "type": "message",
                                "from_peer": from_peer,
                                "message_id": mid,
                                "auto_replied": False,
                            })
                        else:
                            # chat message — optionally trigger claude auto-reply
                            _comm_log_write({"dir": "in", "tool": "message",
                                             "from": from_peer, "mid": mid})
                            auto_reply = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("auto_reply", False)
                            triggered = False
                            if auto_reply:
                                invoke_claude_reply(project_dir)
                                triggered = True
                            msg_queue.put({
                                "type": "message",
                                "from_peer": from_peer,
                                "message_id": mid,
                                "auto_replied": triggered,
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

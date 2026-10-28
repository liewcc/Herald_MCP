"""
herald_tray.py — Herald system tray daemon with full UI window.

Left-click tray icon  → open/focus the Herald window
Close window (X)      → minimize back to tray (keeps running)
Right-click tray icon → Exit

Tabs:
  Messages    — incoming message/deposit log (SSE events)
  Comm Log    — full two-way log from herald_comm.log (exec_shell + ask_peer)
  Remote Tasks — fire exec_shell to a peer and see their running processes
  Network     — star diagram per relay: which peers' trays are connected right now

Auto Reply: when enabled, invokes claude.exe once per incoming message (event-driven,
            NOT a timer — zero token cost while idle).

Auto-start: python herald_tray.py --install
"""
import base64
import json
import math
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

REPLY_PROMPT = (
    "Use herald MCP tools. Call get_pending to retrieve incoming messages. "
    "For each message, call reply(message_id=<id>, answer=<your response>). "
    "When done, exit."
)
ALLOWED_TOOLS = "mcp__herald__get_pending,mcp__herald__reply"

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


def _auth() -> dict:
    return {"X-Herald-Token": load_config().get("token", "")}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def networks(cfg: dict) -> list:
    """Every relay in config: top level is the default network, "networks" adds more (same merge as mcp_server)."""
    return [cfg] + [{**cfg, **net} for net in cfg.get("networks", {}).values()]


def net_for(cfg: dict, peer: str) -> dict:
    """The network config (relay + token) that lists this peer; unknown peers fall back to the default."""
    for net in cfg.get("networks", {}).values():
        if peer in net.get("peers", []):
            return {**cfg, **net}
    return cfg


def probe_relay(net: dict) -> dict:
    """GET /health on one relay. online is None when the relay is down or predates the online list."""
    t0 = time.monotonic()
    try:
        r = httpx.get(net["server_url"].rstrip("/") + "/health", timeout=3.0,
                      headers={"X-Herald-Token": net.get("token", "")})
        r.raise_for_status()
        body = r.json()
        return {"up": True, "ms": int((time.monotonic() - t0) * 1000),
                "online": body.get("online"), "host": body.get("name")}
    except Exception:
        return {"up": False, "ms": None, "online": None, "host": None}


_my_ip = None


def my_ip() -> str:
    """This PC's Tailscale IPv4, asked once ("" without Tailscale). Call it off the UI thread."""
    global _my_ip
    if _my_ip is None:
        try:
            _my_ip = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5,
                                    creationflags=subprocess.CREATE_NO_WINDOW).stdout.split("\n")[0].strip()
        except Exception:
            _my_ip = ""
    return _my_ip


def relay_host(net: dict, probe: dict, ips: dict) -> str | None:
    """Which PC runs this relay: its own /health name, else the peer whose IP matches the relay URL."""
    if probe.get("host"):
        return probe["host"]
    ip = net["server_url"].split("//")[-1].split(":")[0]
    return next((peer for peer, addr in ips.items() if addr == ip), None)


# Network tab palette: (fill, outline, text) per node state
NODE = {"online": ("#E1F5EE", "#1D9E75", "#085041"),
        "offline": ("#F1EFE8", "#B4B2A9", "#5F5E5A"),
        "unknown": ("#FFFFFF", "#B4B2A9", "#5F5E5A")}
PILL_UP, PILL_DOWN = NODE["online"], ("#FCEBEB", "#A32D2D", "#791F1F")
INK, MUTED, RELAY, DOWN ="#222222", "#888780", "#185FA5", "#A32D2D"


def split_members(net: dict, host_pc: str | None) -> tuple:
    """(center, around): the relay host sits in the middle and is not drawn again in the ring."""
    members = [net["name"]] + [p for p in net.get("peers", []) if p != net["name"]]
    if not host_pc:
        return None, members
    return host_pc, [p for p in members if p != host_pc]


def round_rect(c, x0, y0, x1, y1, r, **kw):
    """Rounded rectangle on a tk Canvas (smoothed polygon; tk has no native one)."""
    # whole pixels: tk does not antialias, and a fractional spline wobbles along its straight edges
    x0, y0, x1, y1 = round(x0), round(y0), round(x1), round(y1)
    pts =[x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, **kw)


def node_state(peer: str, probe: dict, me: str = "", me_up: bool = False) -> str:
    """online / offline from the relay's subscriber list; unknown when the relay can't tell us.
    This PC is online whenever any relay answers: it may only send on a network, never subscribe to it."""
    if peer == me:
        return "online" if me_up else "offline"
    if probe["online"] is None:
        return "unknown"
    return "online" if peer in probe["online"] else "offline"


# ── Tray icon image ───────────────────────────────────────────────────────────

def make_icon_image() -> Image.Image:
    ico = Path(__file__).parent / "img" / "logo.ico"
    if ico.exists():
        return Image.open(ico).convert("RGBA").resize((64, 64))
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], fill=(30, 120, 220, 255))
    d.ellipse([18, 18, 46, 46], fill=(255, 255, 255, 255))
    return img


# ── Startup entry ─────────────────────────────────────────────────────────────
# Same entries setup_wizard writes, so the "Start on Login" checkbox shows and changes the real state.

def is_startup_enabled() -> bool:
    import setup_wizard
    return any((setup_wizard.STARTUP / n).exists() for n in ("herald_autostart.vbs", "herald_tray.lnk"))


def install_startup() -> Path:
    import setup_wizard
    # A relay PC must start server.py at logon too, not just the tray.
    return setup_wizard.install_autostart("relay" if load_config().get("host") else "join")


def uninstall_startup() -> None:
    import setup_wizard
    setup_wizard.remove_autostart()


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


def reply_args(claude_exe: str, locked: bool) -> list:
    """claude -p command line for auto-reply.

    locked (config "auto_reply_locked"): no built-in tools, only the herald MCP server, and only
    get_pending / reply usable — the remote peer can get text answers but nothing that touches
    this machine (no shell, files, screen or other MCP servers).
    """
    args = [claude_exe, "-p", REPLY_PROMPT, "--allowedTools", ALLOWED_TOOLS]
    if locked:
        herald = {"mcpServers": {"herald": {
            "command": str(Path(sys.executable).with_name("pythonw.exe")),
            "args": [str(Path(__file__).with_name("mcp_server.py"))]}}}
        others = ",".join(f"mcp__herald__{t}" for t in (
            "ask_peer", "exec_shell", "send_file", "deposit_file", "get_deposits",
            "save_attachment", "list_peers", "ping_peer"))
        args += ["--tools", "", "--strict-mcp-config", "--mcp-config", json.dumps(herald),
                 "--disallowedTools", others, "--permission-mode", "dontAsk"]
    return args


def invoke_claude_reply(project_dir: str) -> None:
    global _claude_proc
    # ponytail: single-instance guard — skip if previous claude is still running
    if _claude_proc is not None and _claude_proc.poll() is None:
        return
    claude_exe = find_claude_exe()
    if not claude_exe:
        return
    _claude_proc = subprocess.Popen(
        reply_args(claude_exe, load_config().get("auto_reply_locked", False)),
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

        # Own taskbar identity: without it Windows groups the window under pythonw.exe and shows Python's icon.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Herald.Tray")
        except (AttributeError, OSError):
            pass
        self.root = tk.Tk()
        self.root.title(f"Herald — {self.peer_name}")
        _ico = Path(__file__).parent / "img" / "logo.ico"
        if _ico.exists():
            self.root.iconbitmap(default=str(_ico))   # default= also covers the taskbar's large icon
        self.root.geometry("720x520")
        self.root.minsize(600, 400)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

        self._reconnect = threading.Event()
        self.icon = None            # pystray icon, set by main() for notifications
        self._last_notified = {}    # peer -> time.monotonic() of last toast
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

        # one pill per relay: green reachable, red not, grey not checked yet
        self._subscribed = None   # the tray's own link to the top-level relay; None while connecting
        self.pills = tk.Canvas(top, height=24, width=1, bg=top.cget("bg"), highlightthickness=0)
        self.pills.pack(side="right")
        self.pill_tip = tk.Label(top, text="", fg="#888", font=("Segoe UI", 8))
        self.pill_tip.pack(side="right", padx=(0, 6))

        ttk.Separator(self.root, orient="horizontal").pack(fill="x")

        # ── Notebook ─────────────────────────────────────────────────────────
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)

        self._build_messages_tab()
        self._build_commlog_tab()
        self._build_tasks_tab()
        self._build_network_tab()

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

        self.notify_var = tk.BooleanVar(value=self.cfg.get("notify", True))
        tk.Checkbutton(
            bottom, text="Notify",
            variable=self.notify_var,
            command=self._toggle_notify,
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
        self._tasks_frame = frame

        toolbar = tk.Frame(frame, padx=8, pady=6)
        toolbar.pack(fill="x")

        tk.Label(toolbar, text="Peer:", font=("Segoe UI", 9)).pack(side="left")
        peers = [p for n in networks(self.cfg) for p in n.get("peers", [])] or ["April"]
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
            net   = net_for(cfg, peer)
            relay = net.get("server_url", f"http://localhost:{cfg.get('port', 7700)}")
            payload = {
                "message_id": str(uuid.uuid4()),
                "from_peer":  cfg.get("name", "unknown"),
                "to_peer":    peer,
                "message":    json.dumps({"type": "shell", "cmd": cmd}),
                "attachments": [],
            }
            with httpx.Client(timeout=20.0, headers={"X-Herald-Token": net.get("token", "")}) as client:
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

    # ── Tab 4: Network ────────────────────────────────────────────────────────

    def _build_network_tab(self):
        frame = tk.Frame(self.nb)
        self.nb.add(frame, text="  Network  ")
        self._net_frame = frame
        self._net_probes = []   # [(network cfg, probe_relay result)]
        self._net_busy = False

        toolbar = tk.Frame(frame, padx=8, pady=6)
        toolbar.pack(fill="x")
        tk.Button(toolbar, text="Refresh", font=("Segoe UI", 9), relief="flat", bd=1,
                  padx=10, command=self._refresh_network).pack(side="left")
        self._net_status = tk.Label(toolbar, text="", font=("Segoe UI", 8), fg="#888")
        self._net_status.pack(side="left", padx=(8, 0))
        tk.Label(toolbar, text="Click a PC to open it in Remote Tasks",
                 font=("Segoe UI", 8), fg="#888").pack(side="right")

        self.net_canvas = tk.Canvas(frame, bg="#ffffff", highlightthickness=0)
        self.net_canvas.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.net_canvas.bind("<Configure>", lambda e: self._draw_network())
        self.nb.bind("<<NotebookTabChanged>>",
                     lambda e: self._refresh_network() if self.nb.select() == str(frame) else None)
        self.root.after(15000, self._net_tick)
        self._draw_pills()

    def _net_tick(self):
        # ponytail: probes only while the window is on screen (header pills + Network tab), so a hidden tray costs nothing
        if self.root.state() == "normal":
            self._refresh_network()
        self.root.after(15000, self._net_tick)

    def _refresh_network(self):
        if self._net_busy:
            return
        self._net_busy = True
        self._net_status.config(text="Checking…")
        def probe():
            my_ip()   # warm the cache here, off the UI thread
            self.msg_queue.put({"type": "net_result", "nets": [(n, probe_relay(n)) for n in networks(load_config())]})
        threading.Thread(target=probe, daemon=True).start()

    def _draw_network(self):
        c = self.net_canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if not self._net_probes or w < 50:
            return
        col = w / len(self._net_probes)
        # an oval ring: wider than tall, so side nodes clear the relay host in the center
        rx, ry = max(100, min(col * 0.38, 220)), max(60, (h - 170) / 2)
        # my_ip() is already cached: the probe thread asked it before any result could reach here
        ips = {**self.cfg.get("ips", {}), self.cfg.get("name", ""): my_ip()}
        self._me_up = any(p["up"] for _, p in self._net_probes)

        for i, (net, probe) in enumerate(self._net_probes):
            cx, cy = col * i + col / 2, 70 + ry
            c.create_text(cx, 18, text=net["server_url"].split("//")[-1], fill=INK, font=("Segoe UI", 10, "bold"))
            host_pc = relay_host(net, probe, ips)
            center, around = split_members(net, host_pc)
            relay_col = RELAY if probe["up"] else DOWN

            for j, peer in enumerate(around):
                a = 2 * math.pi * j / len(around) - math.pi / 2
                x, y = cx + rx * math.cos(a), cy + ry * math.sin(a)
                # a dead relay carries nothing, so every link to it is grey even when the PC itself is up
                online = probe["up"] and node_state(peer, probe, net["name"], self._me_up) == "online"
                c.create_line(cx, cy, x, y, fill=NODE["online"][1] if online else NODE["offline"][1],
                              dash=() if online else (4, 4), width=2 if online else 1.5)
            for j, peer in enumerate(around):
                a = 2 * math.pi * j / len(around) - math.pi / 2
                self._draw_node(c, cx + rx * math.cos(a), cy + ry * math.sin(a), peer, net, probe,
                                ips.get(peer, ""), f"peer-{i}-{j}")

            if center:
                # the relay is a program on this PC: the PC sits in the middle, the relay is a band on its card
                band = f"relay · {probe['ms']} ms" if probe["up"] else "relay unreachable"
                self._draw_node(c, cx, cy, center, net, probe, ips.get(center, ""), f"host-{i}",
                                band=(band, relay_col))
            else:   # host unknown: say only that a relay is there
                c.create_rectangle(cx - 40, cy - 16, cx + 40, cy + 16, fill="#ffffff", outline=relay_col,
                                   width=2, dash=() if probe["up"] else (4, 3))
                c.create_text(cx, cy, text="relay", fill=relay_col, font=("Segoe UI", 9, "bold"))

            everyone = ([center] if center else []) + around
            if not probe["up"]:
                status = "relay unreachable"
            elif probe["online"] is None:
                status = f"{probe['ms']} ms · old relay, no peer list"
            else:
                up = sum(node_state(p, probe, net["name"], self._me_up) == "online" for p in everyone)
                status = f"{probe['ms']} ms · {up}/{len(everyone)} online"
            c.create_text(cx, h - 16, text=status, fill=relay_col, font=("Segoe UI", 9))


    def _draw_node(self, c, x, y, peer, net, probe, sub, tag, band=None):
        state = node_state(peer, probe, net["name"], self._me_up)
        fill, edge, ink = NODE[state]
        me = peer == net["name"]
        x, y = round(x), round(y)   # see round_rect
        hw, hh = (58, 33) if band else (46, 22)
        c.create_text(x - hw + 2, y + hh + 2, text=state, anchor="nw", fill=MUTED, font=("Segoe UI", 8))
        round_rect(c, x - hw, y - hh, x + hw, y + hh, 9, tags=tag, fill=fill,
                   outline=edge, dash=(4, 3) if state == "unknown" else ())
        if band:
            # rounded top, square bottom: tk's smooth polygon keeps a corner sharp where a point is tripled
            x0, y0, x1, yb, r = x - hw, y - hh, x + hw, y - hh + 18, 9
            c.create_polygon([x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r] + [x1, yb] * 3 + [x0, yb] * 3
                             + [x0, y0 + r, x0, y0], smooth=True, fill=band[1], outline="", tags=tag)
            c.create_text(x, y0 + 9, text=band[0], fill="#ffffff", font=("Segoe UI", 8), tags=tag)
            y += 9   # name and sub sit below the band
        name = peer + (" · this PC" if me else "")
        c.create_text(x, y - (7 if sub else 0), text=name, fill=ink, font=("Segoe UI", 10, "bold"), tags=tag)
        if sub:
            c.create_text(x, y + 9, text=sub, fill=ink, font=("Segoe UI", 8), tags=tag)
        if not me:
            c.tag_bind(tag, "<Button-1>", lambda e, p=peer: self._open_in_tasks(p))
            c.tag_bind(tag, "<Enter>", lambda e: c.config(cursor="hand2"))
            c.tag_bind(tag, "<Leave>", lambda e: c.config(cursor=""))

    def _open_in_tasks(self, peer: str):
        self._tasks_peer.set(peer)
        self.nb.select(self._tasks_frame)

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
                    self._notify(event)
                elif etype == "commlog":
                    self._append_comm_entry(event["entry"])
                elif etype == "tasks_result":
                    self._update_tasks(event["text"])
                elif etype == "net_result":
                    self._net_busy = False
                    self._net_probes = event["nets"]
                    self._net_status.config(text=f"Updated {time.strftime('%H:%M:%S')}")
                    self._draw_network()
                    self._draw_pills()
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
        elif tool == "notice":
            arrow = "→" if direction == "out" else "←"
            text = f"[{ts}] {arrow} notice {peer}: {entry.get('text') or entry.get('error', '')}\n"
            tag  = "err" if entry.get("error") else "msg_in"
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

    def _toggle_notify(self):
        self.cfg["notify"] = self.notify_var.get()
        save_config(self.cfg)

    def _notify(self, event: dict):
        """Windows toast telling the user a peer is using this machine."""
        # ponytail: one toast per peer per 60s so a burst of exec_shell calls doesn't spam;
        # later commands inside the window only show in the Messages / Comm Log tabs.
        if not self.notify_var.get() or self.icon is None:
            return
        peer = event.get("from_peer", "?")
        if event.get("notice"):    # a notice is the point of the message: always show it
            try:
                self.icon.notify(event["notice"][:250], f"Herald — {peer}")
            except Exception:
                pass
            return
        now = time.monotonic()
        if now - self._last_notified.get(peer, -60.0) < 60:
            return
        self._last_notified[peer] = now
        if event["type"] == "deposit":
            body = f"{peer} sent a file to this PC"
        elif event.get("cmd"):
            body = f"{peer} is running a command on this PC: {event['cmd'][:100]}"
        else:
            body = f"{peer} is talking to this PC's AI"
        try:
            self.icon.notify(body, "Herald")
        except Exception:
            pass

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
        self._refresh_network()

    def hide(self):
        self.root.withdraw()

    def set_status(self, connected: bool):
        self._subscribed = connected
        self._draw_pills()

    def _draw_pills(self):
        c = self.pills
        c.delete("all")
        ips = self.cfg.get("ips", {})
        probes = self._net_probes or [(n, {"up": None, "ms": None, "host": None}) for n in networks(self.cfg)]
        x = 2
        for i, (net, probe) in enumerate(probes):
            # the top-level pill follows the tray's own subscription: green there means commands can reach this PC
            up = self._subscribed if i == 0 else probe["up"]
            fill, edge, ink = (PILL_UP if up else PILL_DOWN) if up is not None else NODE["unknown"]
            host = net["server_url"].split("//")[-1]
            label = relay_host(net, probe, ips) or host.split(":")[0]
            t = c.create_text(x + 22, 12, text=label, anchor="w", fill=ink, font=("Segoe UI", 9, "bold"))
            x1 = c.bbox(t)[2] + 10
            pill = round_rect(c, x, 1, x1, 23, 11, fill=fill, outline=edge)
            dot = c.create_oval(x + 9, 8, x + 17, 16, fill=edge, outline="")
            c.tag_raise(t)
            tip = host + (f" · {probe['ms']} ms" if probe.get("ms") else " · unreachable" if up is False else "")
            for item in (pill, dot, t):
                c.tag_bind(item, "<Enter>", lambda e, s=tip: self.pill_tip.config(text=s))
                c.tag_bind(item, "<Leave>", lambda e: self.pill_tip.config(text=""))
            x = x1 + 6
        c.config(width=x)

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


# Parses the command with PowerShell's own parser (so quoting can't fool us) and
# prints "start end" offsets of each pipeline element. Exits 1 on anything that
# could run code outside those elements: ; or newlines (multiple statements),
# $(...), (...), {...}, variables, & / . invocation, redirection, member calls.
_PS_GUARD = r"""
$c = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:HERALD_CMD_B64))
$t = $null; $e = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($c, [ref]$t, [ref]$e)
if ($e.Count -or $ast.ParamBlock -or $ast.BeginBlock -or $ast.ProcessBlock -or $ast.DynamicParamBlock) { exit 1 }
$s = $ast.EndBlock.Statements
if ($s.Count -ne 1 -or $s[0] -isnot [System.Management.Automation.Language.PipelineAst]) { exit 1 }
$banned = 'SubExpressionAst','ParenExpressionAst','ScriptBlockExpressionAst','VariableExpressionAst',
  'ArrayExpressionAst','InvokeMemberExpressionAst','MemberExpressionAst','FileRedirectionAst',
  'MergingRedirectionAst','ExpandableStringExpressionAst','HashtableAst','ConvertExpressionAst','IndexExpressionAst'
if ($ast.Find({ param($n) $banned -contains $n.GetType().Name }, $true)) { exit 1 }
foreach ($el in $s[0].PipelineElements) {
  if ($el -isnot [System.Management.Automation.Language.CommandAst] -or $el.InvocationOperator -ne 'Unknown') { exit 1 }
  "$($el.Extent.StartOffset) $($el.Extent.EndOffset)"
}
"""
_PS_GUARD_B64 = base64.b64encode(_PS_GUARD.encode("utf-16-le")).decode("ascii")


def _rule_match(s: str, allowlist: list) -> bool:
    import re
    return any(rule.match(s) if isinstance(rule, re.Pattern) else s.startswith(rule)
               for rule in allowlist)


def _shell_allowed(cmd: str, allowlist: list) -> bool:
    """Allow only a single pipeline whose every element matches an allowlist rule."""
    if any(ord(ch) > 0xFFFF for ch in cmd):  # parser offsets are UTF-16 units
        return False
    env = {**os.environ, "HERALD_CMD_B64": base64.b64encode(cmd.encode("utf-8")).decode("ascii")}
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", _PS_GUARD_B64],
            capture_output=True, text=True, timeout=15, env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return False
    if p.returncode != 0:
        return False
    parts = [cmd[int(a):int(b)] for a, b in (ln.split() for ln in p.stdout.splitlines() if ln.strip())]
    return bool(parts) and all(_rule_match(x, allowlist) for x in parts)


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
                creationflags=subprocess.CREATE_NO_WINDOW,  # tray is pythonw: no console to inherit
            )
            result = {"stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode}
        except subprocess.TimeoutExpired:
            result = {"error": "command timed out", "returncode": -1}
        except Exception as e:
            result = {"error": str(e), "returncode": -1}
        answer = json.dumps(result)
        _comm_log_write({"dir": "reply", "to": from_peer,
                         "rc": result.get("returncode"), "preview": answer[:200]})
    _post_reply(relay, mid, answer)


def _post_reply(relay: str, mid: str, answer: str) -> None:
    try:
        with httpx.Client(timeout=10.0, headers=_auth()) as c:
            c.post(f"{relay.rstrip('/')}/reply/{mid}", json={"answer": answer})
    except Exception:
        pass


def send_notice(peer: str, text: str) -> None:
    """Tell a peer's tray something (toast + Comm Log there). No shell, no claude."""
    cfg = load_config()
    payload = {"message_id": str(uuid.uuid4()), "from_peer": cfg.get("name", "unknown"), "to_peer": peer,
               "message": json.dumps({"type": "notice", "text": text}), "attachments": []}
    try:
        with httpx.Client(timeout=30.0, headers=_auth()) as c:
            c.post(f"{cfg['server_url'].rstrip('/')}/ask", json=payload)
        _comm_log_write({"dir": "out", "tool": "notice", "peer": peer, "text": text[:200]})
    except Exception as e:
        _comm_log_write({"dir": "out", "tool": "notice", "peer": peer, "error": str(e)})


def watch_thread(rule: dict, running: threading.Event) -> None:
    """Tail rule["file"]; each new line containing rule["match"] goes to rule["peer"] as a notice.

    config.json: "watch": [{"file": "C:/AI/Open_Vending/log/scan.log",
                            "match": "Refund: Done in", "peer": "cc"}]
    """
    # ponytail: 2s polling, no file-change events; ceiling is ~2s latency, fine for status lines.
    path, match, peer = Path(rule["file"]), rule["match"], rule["peer"]
    pos = path.stat().st_size if path.exists() else 0     # only lines written from now on
    while running.is_set():
        time.sleep(2)
        try:
            size = path.stat().st_size
            if size < pos:                                 # truncated or replaced: start over
                pos = 0
            if size == pos:
                continue
            with path.open("rb") as f:
                f.seek(pos)
                chunk = f.read()
            chunk = chunk[:chunk.rfind(b"\n") + 1]            # leave a half-written line for next time
            pos += len(chunk)
            for line in chunk.decode("utf-8", errors="replace").splitlines():
                if match in line:
                    threading.Thread(target=send_notice, args=(peer, line.strip()), daemon=True).start()
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
            # The relay sends ": keepalive" every 25s, so 60s of silence means a half-open
            # connection (sleep/resume, Tailscale reconnect): ReadTimeout drops us into reconnect.
            sse_timeout = httpx.Timeout(10.0, read=60.0)
            with httpx.Client(timeout=sse_timeout, headers=_auth()) as client:
                with client.stream("GET", url, params={"peer": peer_name}) as r:
                    msg_queue.put({"type": "status", "connected": True})
                    for line in r.iter_lines():
                        if not running.is_set() or reconnect.is_set():
                            break
                        if not line.startswith("data:"):
                            continue
                        try:
                            payload = json.loads(line[5:].strip())
                        except Exception:
                            continue
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

                        try:
                            # fetch full message body via a separate client
                            # (never reuse the SSE streaming client for other requests)
                            msg_body = None
                            try:
                                with httpx.Client(timeout=5.0, headers=_auth()) as peek:
                                    rp = peek.get(f"{relay}/pending", params={"peer": peer_name})
                                    for m in (rp.json() if rp.status_code == 200 else []):
                                        if m.get("message_id") == mid:
                                            msg_body = m
                                            break
                            except Exception:
                                pass

                            # parse body to determine routing
                            shell_body = notice_body = None
                            if msg_body:
                                try:
                                    parsed = json.loads(msg_body.get("message", ""))
                                    if parsed.get("type") == "shell":
                                        shell_body = parsed
                                    elif parsed.get("type") == "notice":
                                        notice_body = parsed
                                except Exception:
                                    pass

                            if notice_body:
                                # notice — show and log it, ack at once; no shell, no claude
                                text = str(notice_body.get("text", ""))[:500]
                                _comm_log_write({"dir": "in", "tool": "notice", "from": from_peer, "text": text})
                                threading.Thread(target=_post_reply, args=(relay, mid, '{"ok": true}'),
                                                 daemon=True).start()
                                msg_queue.put({"type": "message", "from_peer": from_peer,
                                               "message_id": mid, "notice": text})
                            elif shell_body:
                                # shell command — execute and reply directly, no claude
                                try:
                                    _comm_log_write({"dir": "in", "tool": "exec_shell",
                                                     "from": from_peer, "cmd": shell_body.get("cmd", "")})
                                except Exception:
                                    pass
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
                                    "cmd": shell_body.get("cmd", ""),
                                })
                            else:
                                # chat message — optionally trigger claude auto-reply
                                try:
                                    _comm_log_write({"dir": "in", "tool": "message",
                                                     "from": from_peer, "mid": mid})
                                except Exception:
                                    pass
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
                            pass  # never let a single message crash the SSE loop
        except Exception:
            pass
        msg_queue.put({"type": "status", "connected": False})
        if running.is_set() and not reconnect.is_set():
            time.sleep(5)


# ── Entry point ───────────────────────────────────────────────────────────────

def already_running(name: str) -> bool:
    """One tray per peer: a second subscriber makes the relay's work queue drop exec_shell commands."""
    import ctypes
    global _instance_mutex  # held until the process exits
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    _instance_mutex = k32.CreateMutexW(None, False, f"Local\\HeraldTray-{name}")
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def main() -> None:
    if "--install" in sys.argv:
        print(f"Startup entry created: {install_startup()}")
        return

    cfg = load_config()
    if already_running(cfg["name"]):
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, "Herald is already running - use its icon in the system tray.", "Herald", 0x40)
        return
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
    for rule in cfg.get("watch", []):
        threading.Thread(target=watch_thread, args=(rule, running), daemon=True).start()

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

    win.icon = icon
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

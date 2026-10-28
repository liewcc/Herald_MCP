"""Herald setup wizard: answer every question first, then config.json is written once.

Interactive (setup.bat runs this):
    python setup_wizard.py
Non-interactive (AI installers - pass every answer, nothing will prompt):
    python setup_wizard.py --role relay --name abby --yes
    python setup_wizard.py --role join  --name leno --server-url http://100.x.x.x:7700 --token <hex> --yes
    python setup_wizard.py --role join  --name cc   --server-url http://100.x.x.x:7700 --token <hex> --peers abby --add-network abby --yes
Check the wizard itself:
    python setup_wizard.py --self-test

Stdlib only (except --shortcut, which needs pywin32), so it runs before `pip install -r requirements.txt`.
"""
import argparse
import http.client
import json
import os
import secrets
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.json"
STARTUP = (Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")  # never a relative path
           / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup")
PORT = 7700
CREATE_NO_WINDOW = 0x08000000

SHARE_HELP = """  Make the PCs see each other on Tailscale - either:
    a) log every PC into the SAME Tailscale account, or
    b) the relay PC's owner opens https://login.tailscale.com/admin/machines , clicks "..." on the
       relay machine > Share, and sends the link to the other PC's Tailscale account to accept.
  Check on the joining PC: `tailscale status` must list the relay PC's 100.x.x.x address."""
TAILSCALE_HELP = """Herald PCs reach each other over Tailscale (a private network). On EVERY PC:
  1. Install Tailscale from https://tailscale.com/download
  2. Log in (Tailscale tray icon > Log in), or run `tailscale up`.
""" + SHARE_HELP
UNREACHABLE_HELP = """  Cannot reach the relay. Check, in order:
    1. Tailscale is installed, running and logged in on THIS PC (`tailscale status`).
    2. The relay PC is listed in `tailscale status` here. If not:
""" + textwrap.indent(SHARE_HELP, "    ") + """
    3. The relay (server.py) is running on that PC and the URL/port are right."""
BAD_TOKEN_HELP = "  The relay rejected the token. Copy it again from the relay PC's config.json (no spaces)."
NOT_HERALD_HELP = ("  Something answers at that URL, but it is not a Herald relay. Check the IP and the port\n"
                   "  (default 7700) - the relay PC's wizard printed the exact URL.")


def ask(prompt, default=None, choices=None):
    """Prompt on a console; on a non-interactive run fail fast instead of hanging."""
    missing = f"ERROR: no answer for '{prompt}'. Non-interactive run: pass it as a flag (see --help)."
    if not sys.stdin.isatty():
        sys.exit(missing)
    hint = f" [{default}]" if default else ""
    while True:
        try:
            v = input(f"{prompt}{hint}: ").strip() or (default or "")
            v = v.lower() if choices else v
        except EOFError:  # Windows reports NUL as a tty, so EOF is the real "nobody is typing" signal
            sys.exit("\n" + missing)
        if v and (not choices or v in choices):
            return v
        print(f"  Enter one of: {', '.join(choices)}" if choices else "  A value is required.")


def normalize_url(url):
    """Accept what people paste: '100.x.x.x', '100.x.x.x:7700', quotes, trailing slash."""
    url = url.strip().strip("'\"").rstrip("/")
    if "://" not in url:
        url = "http://" + url
    if url.count(":") == 1:  # scheme only, no port
        url += f":{PORT}"
    return url


def clean_token(token):
    """Tokens copied out of config.json often keep their quotes or a trailing space."""
    return token.strip().strip("'\"").strip()


def check_relay(url, token, timeout=8):
    """'ok', 'bad-token', 'not-herald', 'unreachable (...)' or 'HTTP <code>'."""
    try:
        req = urllib.request.Request(url.rstrip("/") + "/health", headers={"X-Herald-Token": token})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return f"HTTP {r.status}"
            try:
                body = json.loads(r.read() or b"{}")
            except ValueError:
                body = None
            # Any web server answers 200; only a Herald relay says {"status": "ok"}.
            return "ok" if isinstance(body, dict) and body.get("status") == "ok" else "not-herald"
    except urllib.error.HTTPError as e:
        return "bad-token" if e.code == 401 else f"HTTP {e.code}"
    except http.client.HTTPException:  # something answered, but not in HTTP (e.g. SSH on that port)
        return "not-herald"
    except OSError as e:
        return f"unreachable ({getattr(e, 'reason', e)})"
    except ValueError as e:  # not a URL at all
        return f"unreachable (bad URL: {e})"


def tailscale_ip():
    exe = shutil.which("tailscale") or r"C:\Program Files\Tailscale\tailscale.exe"
    try:
        out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=10,
                             encoding="utf-8", errors="replace").stdout.split()
        # Logged out, it may print words instead of an address.
        return next((w for w in out if w.count(".") == 3 and w.replace(".", "").isdigit()), None)
    except (OSError, subprocess.SubprocessError):  # missing exe, or a hung daemon (TimeoutExpired)
        return None


def claude_ready():
    """True when the Claude Code CLI is installed and logged in; Auto Reply runs it for every ask_peer."""
    exe = shutil.which("claude")
    if not exe:
        return False
    try:
        out = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=20,
                             encoding="utf-8", errors="replace").stdout
        return bool(json.loads(out).get("loggedIn"))
    except (OSError, subprocess.SubprocessError, ValueError):  # ValueError: not JSON (old CLI, error text)
        return False


def tailscale_machines():
    """`tailscale status` lines (one per visible machine), so the user can spot the relay PC."""
    exe = shutil.which("tailscale") or r"C:\Program Files\Tailscale\tailscale.exe"
    try:
        out = subprocess.run([exe, "status"], capture_output=True, text=True, timeout=10,
                             encoding="utf-8", errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in out.splitlines() if line.strip().startswith("100.")][:20]


def load_existing():
    """config.json parsed; {} if unreadable (e.g. a half-pasted here-string); None if absent."""
    if not CONFIG.exists():
        return None
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    except ValueError:
        data = None
    if not isinstance(data, dict):
        print("WARNING: config.json is not a valid JSON object - it will be backed up and replaced.")
        return {}
    return data


# Keys the wizard decides. Everything else (auto_reply, watch, notify, networks...) is kept on a rerun.
WIZARD_KEYS = {"name", "server_url", "token", "peers", "host", "port"}


def keep_other_settings(cfg, existing):
    """A rerun must not silently drop settings the wizard never asks about (e.g. April's auto_reply)."""
    return {**cfg, **{k: v for k, v in (existing or {}).items() if k not in WIZARD_KEYS}}


def reusable_relay_token(existing):
    """A relay rerun must keep its token, or every connected peer starts getting 401."""
    return existing.get("token") if existing and existing.get("host") else None


def build_config(role, name, token, server_url, peers):
    if role == "relay":
        # This PC's own tray talks to its relay over loopback; host 0.0.0.0 lets the tailnet in.
        return {"name": name, "server_url": f"http://127.0.0.1:{PORT}", "host": "0.0.0.0",
                "port": PORT, "token": token, "peers": peers}
    return {"name": name, "server_url": server_url, "token": token, "peers": peers}


def add_network(existing, label, server_url, token, peers):
    """Keep the default network; route `peers` to an extra relay (mcp_server picks by peer name)."""
    merged = dict(existing)
    merged["networks"] = {**existing.get("networks", {}),
                          label: {"server_url": server_url, "token": token, "peers": peers}}
    return merged


def masked(cfg):
    """Copy safe to print: every token, including nested network tokens, cut to 6 chars."""
    out = {k: (v[:6] + "..." if k == "token" else v) for k, v in cfg.items()}
    if "networks" in cfg:
        out["networks"] = {n: masked(net) for n, net in cfg["networks"].items()}
    return out


def stop_running():
    """Stop this checkout's relay/tray so a restart never leaves two subscribers (mcp_server is spared)."""
    here = str(HERE).replace("'", "''")
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe'\" | "
          f"Where-Object {{ $_.CommandLine -like '*{here}\\herald_tray.py*' -or $_.CommandLine -like '*{here}\\server.py*' "
          "-or $_.CommandLine -match '(^|[ \"])herald_tray\\.py' } | "  # also `python herald_tray.py` started from the folder
          "ForEach-Object { $_.ProcessId }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    pids = [pid for pid in out.split() if pid.isdigit() and int(pid) != os.getpid()]
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
    if pids:
        # taskkill returns before the process is gone; until then the tray's single-instance lock is
        # still held and the new tray would exit with "already running".
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Wait-Process -Id {','.join(pids)} -Timeout 10 -ErrorAction SilentlyContinue"],
                       capture_output=True)


def launchers(role):
    exe_dir = Path(sys.executable).parent
    # The relay needs python.exe with a hidden console: under pythonw uvicorn has no stdout and dies silently.
    items = [(exe_dir / "python.exe", HERE / "server.py")] if role == "relay" else []
    return items + [(exe_dir / "pythonw.exe", HERE / "herald_tray.py")]


def remove_autostart():
    for stale in ("herald_autostart.vbs", "herald_tray.lnk", "run_shell_agent.vbs", "herald_autostart.bat"):
        (STARTUP / stale).unlink(missing_ok=True)


def install_autostart(role):
    remove_autostart()  # stale entries would start a duplicate tray
    lines = ['Set o = CreateObject("WScript.Shell")']
    lines += [f'o.Run """{exe}"" ""{script}""", 0, False' for exe, script in launchers(role)]
    vbs = STARTUP / "herald_autostart.vbs"
    # UTF-16 with BOM: WSH reads it as Unicode, so a user name outside the ANSI code page still works.
    vbs.write_text("\r\n".join(lines) + "\r\n", encoding="utf-16")
    return vbs


def launch_now(role):
    for exe, script in launchers(role):
        subprocess.Popen([str(exe), str(script)], cwd=HERE, creationflags=CREATE_NO_WINDOW)


def antigravity_files():
    home = Path.home()  # reads USERPROFILE on Windows
    return [home / ".gemini" / "config" / "mcp_config.json", home / ".gemini" / "antigravity" / "mcp_config.json"]


def antigravity(action):
    """check: exit 0 if both Antigravity configs list herald. register: add it, keeping every other
    server, and never overwrite a file that cannot be parsed (that would wipe the user's servers)."""
    configs = {}
    for p in antigravity_files():
        try:
            configs[p] = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
        except ValueError:
            configs[p] = None
        if not isinstance(configs[p], dict):
            sys.exit(f"ERROR: {p} is not a valid JSON object - left unchanged. Add herald there by hand.")
    if action == "check":
        sys.exit(0 if all("herald" in c.get("mcpServers", {}) for c in configs.values()) else 1)
    for p, c in configs.items():
        c.setdefault("mcpServers", {})["herald"] = {"command": sys.executable, "args": [str(HERE / "mcp_server.py")]}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(c, indent=2), encoding="utf-8")
    print("  [OK] herald registered with Antigravity.")


def desktop_shortcut():
    """Desktop shortcut to the tray. SpecialFolders finds the real Desktop, also when OneDrive moved it."""
    import win32com.client
    wsh = win32com.client.Dispatch("WScript.Shell")
    # SpecialFolders returns "" when it cannot resolve the Desktop: never fall into a relative path.
    desktop = Path(wsh.SpecialFolders("Desktop") or Path.home() / "Desktop")
    if not desktop.is_absolute() or not desktop.is_dir():
        sys.exit(f"  Desktop folder not found ({desktop}) - skipped the shortcut.")
    lnk = wsh.CreateShortcut(str(desktop / "Herald MCP.lnk"))
    lnk.TargetPath = str(Path(sys.executable).parent / "pythonw.exe")  # no console window to close by accident
    lnk.Arguments = f'"{HERE / "herald_tray.py"}"'
    lnk.WorkingDirectory = str(HERE)
    lnk.IconLocation = str(HERE / "img" / "logo.ico")
    lnk.Description = "Herald MCP Tray"
    lnk.Save()
    print(f"  [OK] Shortcut: {lnk.FullName}")


def run(a):
    print("=" * 52 + "\n Herald setup wizard\n" + "=" * 52)
    if ip := tailscale_ip():
        print(f"Tailscale OK - this PC is {ip}\n")
    else:
        print("Tailscale is not installed or not logged in on this PC.\n" + TAILSCALE_HELP + "\n")
        if not a.yes and sys.stdin.isatty() and ask("Continue without Tailscale? (y/n)", "n", ["y", "n"]) != "y":
            sys.exit("Set up Tailscale as above, then rerun setup.bat.")

    role = a.role or {"1": "relay", "2": "join"}[ask(
        "Is this PC\n  1) hosting the relay for a NEW network\n  2) joining an EXISTING network\nChoose", "2", ["1", "2"])]
    name = a.name or ask("Peer name for this PC", os.environ.get("COMPUTERNAME", "").lower() or None)
    peers_raw = a.peers if a.peers is not None else (
        ask("Peers this PC will talk to (comma-separated, blank for none)", "-") if sys.stdin.isatty() else "")
    peers = [p.strip() for p in peers_raw.split(",") if p.strip() and p.strip() != "-"]

    existing = load_existing()
    if role == "relay":
        keep = reusable_relay_token(existing)
        if a.token:
            token = clean_token(a.token)
        elif keep and (a.yes or ask("Keep the existing relay token (peers stay connected)? (y/n)", "y", ["y", "n"]) == "y"):
            token = keep
        elif a.yes or ask("Generate a new token? (y/n)", "y", ["y", "n"]) == "y":
            token = secrets.token_hex(32)
        else:
            token = ask("Paste the token to use")
        server_url = None
    else:
        if not a.server_url:
            machines = tailscale_machines()
            print("Machines this PC can see on Tailscale - the relay PC must be in this list:")
            print("\n".join("  " + m for m in machines) if machines else "  (none)\n" + SHARE_HELP)
        server_url = normalize_url(a.server_url or ask("Relay URL (e.g. http://100.x.x.x:7700)"))
        token = clean_token(a.token or ask("Relay token (copy from the relay PC's config.json)"))
        while (status := check_relay(server_url, token)) != "ok":
            print(f"Relay check failed: {status}")
            print({"bad-token": BAD_TOKEN_HELP, "not-herald": NOT_HERALD_HELP}.get(status, UNREACHABLE_HELP))
            if a.yes or not sys.stdin.isatty():
                sys.exit(1)
            choice = ask("Retry (r), edit URL/token (e) or quit (q)?", "r", ["r", "e", "q"])
            if choice == "q":
                sys.exit(1)
            if choice == "e":
                server_url = normalize_url(ask("Relay URL", server_url))
                token = clean_token(ask("Relay token"))
        print("Relay check: OK (reachable, token accepted)")

    if role == "join" and existing and (a.add_network or (not a.yes and sys.stdin.isatty() and ask(
            "config.json already exists. Replace it (r) or add this as an extra network (a)?", "r", ["r", "a"]) == "a")):
        if not peers:
            sys.exit("ERROR: an extra network needs --peers (that is how exec_shell picks the relay).")
        cfg = add_network(existing, a.add_network or ask("Label for the extra network", name), server_url, token, peers)
        extra = True
    else:
        cfg = keep_other_settings(build_config(role, name, token, server_url, peers), existing)
        extra = False

    print("\nAbout to write config.json:\n" + json.dumps(masked(cfg), indent=2))
    if not a.yes and ask("Write it? (y/n)", "y", ["y", "n"]) != "y":
        sys.exit("Aborted, nothing written.")
    if existing is not None:
        shutil.copy2(CONFIG, CONFIG.with_name("config.json.bak"))
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print("[OK] config.json written" + (" (previous copy: config.json.bak)" if existing is not None else ""))

    if extra:
        print("Extra network added: this PC can now reach those peers. It is only *controlled* via its default network.")
        return
    autostart = a.autostart if a.autostart is not None else (
        a.yes or ask("Start Herald automatically at logon (unattended PC)? (y/n)", "y", ["y", "n"]) == "y")
    stop_running()
    if autostart:
        print(f"[OK] Autostart: {install_autostart(role)}")
    else:
        remove_autostart()
        print("[OK] Autostart off (removed any old Startup entries)")
    launch_now(role)

    if role == "relay":
        for _ in range(30):  # a fresh install compiles .pyc and imports fastapi on first start
            if (status := check_relay(f"http://127.0.0.1:{PORT}", token)) == "ok":
                break
            time.sleep(1)
        else:
            sys.exit(f"ERROR: relay check on port {PORT} failed ({status}). bad-token means another relay already "
                     "holds the port; otherwise run `python server.py` in a console to see why.")
        ip = tailscale_ip() or "<this PC's Tailscale IP>"
        print("\n[OK] Relay running. On every other PC run the wizard with:")
        print(f"     role = join, URL = http://{ip}:{PORT}, token = {token}")
        print("     Each of those PCs must see this PC over Tailscale:")
        print(SHARE_HELP)
        print("     If they still cannot connect, allow inbound TCP 7700 in Windows Firewall on this PC.")
    if cfg.get("auto_reply") and not claude_ready():
        print("\nWARNING: Auto Reply is on, but the Claude Code CLI is not installed or not logged in, so ask_peer to\n"
              "         this PC gets no answer. Install it (winget install Anthropic.ClaudeCode), then run: claude auth login")
    print("\n[OK] Herald started. Done.")


def self_test():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Relay(BaseHTTPRequestHandler):
        def do_GET(self):
            token = self.headers.get("X-Herald-Token")
            body = {"good": b'{"status": "ok", "name": "r"}', "web": b"<html>hi</html>"}.get(token)
            self.send_response(200 if body else 401)
            self.end_headers()
            self.wfile.write(body or b"")

        def log_message(self, *args):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Relay)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}"
    assert check_relay(url, "good") == "ok"
    assert check_relay(url, "bad") == "bad-token"
    assert check_relay(url, "web") == "not-herald"     # some other web server on that port
    srv.shutdown()
    import socket
    raw = socket.socket()
    raw.bind(("127.0.0.1", 0))
    raw.listen(1)

    def ssh_like():
        c, _ = raw.accept()
        c.recv(1024)
        c.sendall(b"SSH-2.0-OpenSSH_9.6\r\n")
        c.close()
    threading.Thread(target=ssh_like, daemon=True).start()
    assert check_relay(f"http://127.0.0.1:{raw.getsockname()[1]}", "t", timeout=5) == "not-herald"  # wrong port
    raw.close()
    srv.server_close()
    assert check_relay(url, "good", timeout=2).startswith("unreachable")

    assert normalize_url("100.1.2.3") == "http://100.1.2.3:7700"
    assert normalize_url(" 100.1.2.3:7700/ ") == "http://100.1.2.3:7700"
    assert normalize_url('"http://100.1.2.3:7701"') == "http://100.1.2.3:7701"
    assert clean_token(' "abc123" ') == "abc123"
    assert check_relay("::nonsense::", "t").startswith("unreachable")

    relay = build_config("relay", "abby", "t", None, ["cc"])
    assert relay["server_url"] == "http://127.0.0.1:7700" and relay["host"] == "0.0.0.0"
    join = build_config("join", "cc", "t", "http://100.1.2.3:7700", ["abby"])
    assert join == {"name": "cc", "server_url": "http://100.1.2.3:7700", "token": "t", "peers": ["abby"]}
    merged = add_network(join, "april", "http://100.9.9.9:7700", "deadbeefcafe1234", ["April"])
    assert merged["server_url"] == join["server_url"] and merged["networks"]["april"]["peers"] == ["April"]
    assert "cafe1234" not in json.dumps(masked(merged)) and masked(merged)["networks"]["april"]["token"] == "deadbe..."
    assert reusable_relay_token(relay) == "t"          # relay rerun keeps its token
    assert reusable_relay_token(join) is None          # a peer's token is never reused as a new relay's
    assert reusable_relay_token({}) is None and reusable_relay_token(None) is None
    old = {"name": "April", "server_url": "http://127.0.0.1:7700", "host": "0.0.0.0", "port": 7700,
           "token": "old", "peers": [], "auto_reply": True, "watch": [{"path": "x"}]}
    rerun = keep_other_settings(join, old)             # relay -> join, rerun keeps unrelated settings
    assert rerun["auto_reply"] is True and rerun["watch"] == [{"path": "x"}]
    assert "host" not in rerun and "port" not in rerun and rerun["token"] == "t"
    assert keep_other_settings(join, None) == join and keep_other_settings(join, {}) == join

    # Antigravity: keeps other servers, reads a BOM file, never overwrites a file it cannot parse.
    import tempfile
    global antigravity_files
    real_files = antigravity_files
    tmp = Path(tempfile.mkdtemp())
    files = [tmp / "a.json", tmp / "b.json"]
    antigravity_files = lambda: files
    try:
        files[0].write_text('{"mcpServers": {"other": {"command": "x"}}}', encoding="utf-8-sig")  # with BOM
        for action, code in (("check", 1), ("register", None), ("check", 0)):
            try:
                antigravity(action)
                got = None
            except SystemExit as e:
                got = e.code
            assert got == code, (action, got)
        assert set(json.loads(files[0].read_text(encoding="utf-8"))["mcpServers"]) == {"other", "herald"}
        files[1].write_text("{ broken", encoding="utf-8")
        before = files[0].read_text(encoding="utf-8")
        try:
            antigravity("register")
            raise AssertionError("register must refuse a broken file")
        except SystemExit as e:
            assert "left unchanged" in str(e.code)
        assert files[1].read_text(encoding="utf-8") == "{ broken" and files[0].read_text(encoding="utf-8") == before
    finally:
        antigravity_files = real_files
    assert [s.name for _, s in launchers("relay")] == ["server.py", "herald_tray.py"]
    assert [e.name for e, _ in launchers("relay")] == ["python.exe", "pythonw.exe"]
    print("self-test OK")


if __name__ == "__main__":
    # A captured (non-console) stdout is cp1252: a Chinese machine name must not crash the wizard.
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--role", choices=["relay", "join"], help="relay = host a new network; join = existing network")
    p.add_argument("--name", help="peer name of this PC")
    p.add_argument("--server-url", help="join only: relay URL, e.g. http://100.x.x.x:7700")
    p.add_argument("--token", help="shared token (relay: omit to generate one)")
    p.add_argument("--peers", help="comma-separated peers this PC talks to")
    p.add_argument("--add-network", metavar="LABEL", help="join only: keep config.json, add this relay as an extra network")
    p.add_argument("--autostart", dest="autostart", action="store_true", default=None, help="start at logon")
    p.add_argument("--no-autostart", dest="autostart", action="store_false")
    p.add_argument("--yes", action="store_true", help="accept defaults, never prompt")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--antigravity", choices=["check", "register"], help="used by setup.bat")
    p.add_argument("--shortcut", action="store_true", help="used by setup.bat: desktop shortcut to the tray")
    args = p.parse_args()
    if args.self_test:
        self_test()
    elif args.antigravity:
        antigravity(args.antigravity)
    elif args.shortcut:
        desktop_shortcut()
    else:
        run(args)

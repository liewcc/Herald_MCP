"""Herald setup wizard: answer every question first, then config.json is written once.

Interactive (setup.bat runs this):
    python setup_wizard.py
Non-interactive (AI installers - pass every answer, nothing will prompt):
    python setup_wizard.py --role relay --name abby --yes
    python setup_wizard.py --role join  --name leno --server-url http://100.x.x.x:7700 --token <hex> --yes
    python setup_wizard.py --role join  --name cc   --server-url http://100.x.x.x:7700 --token <hex> --peers abby --add-network abby --yes
Check the wizard itself:
    python setup_wizard.py --self-test

Stdlib only, so it runs before `pip install -r requirements.txt` finishes.
"""
import argparse
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
STARTUP = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
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


def ask(prompt, default=None, choices=None):
    """Prompt on a console; on a non-interactive run fail fast instead of hanging."""
    missing = f"ERROR: no answer for '{prompt}'. Non-interactive run: pass it as a flag (see --help)."
    if not sys.stdin.isatty():
        sys.exit(missing)
    hint = f" [{default}]" if default else ""
    while True:
        try:
            v = input(f"{prompt}{hint}: ").strip() or (default or "")
        except EOFError:  # Windows reports NUL as a tty, so EOF is the real "nobody is typing" signal
            sys.exit("\n" + missing)
        if v and (not choices or v in choices):
            return v
        print(f"  Enter one of: {', '.join(choices)}" if choices else "  A value is required.")


def check_relay(url, token, timeout=8):
    """'ok', 'bad-token', 'unreachable (...)' or 'HTTP <code>'."""
    req = urllib.request.Request(url.rstrip("/") + "/health", headers={"X-Herald-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return "ok" if r.status == 200 else f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return "bad-token" if e.code == 401 else f"HTTP {e.code}"
    except OSError as e:
        return f"unreachable ({getattr(e, 'reason', e)})"


def tailscale_ip():
    exe = shutil.which("tailscale") or r"C:\Program Files\Tailscale\tailscale.exe"
    try:
        out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=10).stdout.split()
        return out[0] if out else None
    except (OSError, subprocess.SubprocessError):  # missing exe, or a hung daemon (TimeoutExpired)
        return None


def tailscale_machines():
    """`tailscale status` lines (one per visible machine), so the user can spot the relay PC."""
    exe = shutil.which("tailscale") or r"C:\Program Files\Tailscale\tailscale.exe"
    try:
        out = subprocess.run([exe, "status"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in out.splitlines() if line.strip().startswith("100.")][:20]


def load_existing():
    """config.json parsed; {} if unreadable (e.g. a half-pasted here-string); None if absent."""
    if not CONFIG.exists():
        return None
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    except ValueError:
        print("WARNING: config.json is not valid JSON - it will be backed up and replaced.")
        return {}


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
          f"Where-Object {{ $_.CommandLine -like '*{here}\\herald_tray.py*' -or $_.CommandLine -like '*{here}\\server.py*' }} | "
          "ForEach-Object { $_.ProcessId }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout
    for pid in out.split():
        if pid.isdigit() and int(pid) != os.getpid():
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)


def launchers(role):
    exe_dir = Path(sys.executable).parent
    # The relay needs python.exe with a hidden console: under pythonw uvicorn has no stdout and dies silently.
    items = [(exe_dir / "python.exe", HERE / "server.py")] if role == "relay" else []
    return items + [(exe_dir / "pythonw.exe", HERE / "herald_tray.py")]


def install_autostart(role):
    for stale in ("herald_tray.lnk", "run_shell_agent.vbs", "herald_autostart.bat"):
        (STARTUP / stale).unlink(missing_ok=True)  # each would start a duplicate tray
    lines = ['Set o = CreateObject("WScript.Shell")']
    lines += [f'o.Run """{exe}"" ""{script}""", 0, False' for exe, script in launchers(role)]
    vbs = STARTUP / "herald_autostart.vbs"
    vbs.write_text("\r\n".join(lines) + "\r\n", encoding="mbcs")  # wscript reads the ANSI code page
    return vbs


def launch_now(role):
    for exe, script in launchers(role):
        subprocess.Popen([str(exe), str(script)], cwd=HERE, creationflags=CREATE_NO_WINDOW)


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
            token = a.token
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
        server_url = a.server_url or ask("Relay URL (e.g. http://100.x.x.x:7700)")
        token = a.token or ask("Relay token (copy from the relay PC's config.json)")
        while (status := check_relay(server_url, token)) != "ok":
            print(f"Relay check failed: {status}")
            print(BAD_TOKEN_HELP if status == "bad-token" else UNREACHABLE_HELP)
            if a.yes or not sys.stdin.isatty():
                sys.exit(1)
            choice = ask("Retry (r), edit URL/token (e) or quit (q)?", "r", ["r", "e", "q"])
            if choice == "q":
                sys.exit(1)
            if choice == "e":
                server_url = ask("Relay URL", server_url)
                token = ask("Relay token")
        print("Relay check: OK (reachable, token accepted)")

    if role == "join" and existing and (a.add_network or (not a.yes and sys.stdin.isatty() and ask(
            "config.json already exists. Replace it (r) or add this as an extra network (a)?", "r", ["r", "a"]) == "a")):
        if not peers:
            sys.exit("ERROR: an extra network needs --peers (that is how exec_shell picks the relay).")
        cfg = add_network(existing, a.add_network or ask("Label for the extra network", name), server_url, token, peers)
        extra = True
    else:
        cfg = build_config(role, name, token, server_url, peers)
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
    launch_now(role)

    if role == "relay":
        for _ in range(15):
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
    print("\n[OK] Herald started. Done.")


def self_test():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Relay(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.headers.get("X-Herald-Token") == "good" else 401)
            self.end_headers()

        def log_message(self, *args):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Relay)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}"
    assert check_relay(url, "good") == "ok"
    assert check_relay(url, "bad") == "bad-token"
    srv.shutdown()
    srv.server_close()
    assert check_relay(url, "good", timeout=2).startswith("unreachable")

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
    assert [s.name for _, s in launchers("relay")] == ["server.py", "herald_tray.py"]
    assert [e.name for e, _ in launchers("relay")] == ["python.exe", "pythonw.exe"]
    print("self-test OK")


if __name__ == "__main__":
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
    args = p.parse_args()
    self_test() if args.self_test else run(args)

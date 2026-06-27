"""shell_agent.py — run on April's machine to handle exec_shell commands from cc.

Usage:
    python shell_agent.py

Listens on the Herald relay SSE stream. When a message arrives with
{"type": "shell", "cmd": "..."}, executes it in PowerShell and replies with
{"stdout": "...", "stderr": "...", "returncode": N}.

Non-shell messages are ignored (left in pending for Claude CLI to handle).
Allowlist is loaded from allowlist.json in the same directory.
"""
import asyncio
import json
import re
import subprocess
from pathlib import Path

import httpx

CONFIG_PATH    = Path(__file__).parent / "config.json"
ALLOWLIST_PATH = Path(__file__).parent / "allowlist.json"
SHELL_LOG_PATH = Path(__file__).parent / "shell_agent.log"


def load_allowlist() -> list[str | re.Pattern]:
    rules = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    result: list[str | re.Pattern] = []
    for r in rules:
        if r["type"] == "regex":
            result.append(re.compile(r["value"], re.IGNORECASE))
        else:
            result.append(r["value"])
    return result


def is_allowed(cmd: str, allowed: list[str | re.Pattern]) -> bool:
    stripped = cmd.strip()
    for rule in allowed:
        if isinstance(rule, re.Pattern):
            if rule.match(stripped):
                return True
        elif stripped.startswith(rule):
            return True
    return False


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _log(entry: dict) -> None:
    import datetime
    entry.setdefault("ts", datetime.datetime.now().strftime("%H:%M:%S"))
    with SHELL_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


async def run():
    # ponytail: delay lets network stack settle after boot before first connect attempt
    await asyncio.sleep(10)

    config  = load_config()
    allowed = load_allowlist()
    relay   = config.get("server_url", f"http://localhost:{config.get('port', 7700)}")
    peer    = config.get("name", "April")

    print(f"shell_agent: connecting as '{peer}' to {relay}", flush=True)

    while True:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", f"{relay}/subscribe", params={"peer": peer}) as resp:
                    print("shell_agent: SSE stream open", flush=True)
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            evt = json.loads(line[5:])
                        except Exception:
                            continue
                        if evt.get("type") != "message":
                            continue

                        mid = evt["message_id"]

                        # fetch full message body
                        r = await client.get(f"{relay}/pending", params={"peer": peer})
                        msgs = r.json() if r.status_code == 200 else []
                        msg = next((m for m in msgs if m["message_id"] == mid), None)
                        if not msg:
                            continue

                        # only handle shell commands — leave others for Claude CLI
                        try:
                            body = json.loads(msg["message"])
                        except Exception:
                            continue
                        if body.get("type") != "shell":
                            continue

                        cmd      = body.get("cmd", "")
                        timeout_s = int(body.get("timeout", 60))
                        from_peer = msg.get("from_peer", "?")

                        if not is_allowed(cmd, allowed):
                            answer = json.dumps({"error": f"command not in allowlist: {cmd!r}", "returncode": -1})
                            await client.post(f"{relay}/reply/{mid}", json={"answer": answer})
                            _log({"dir": "blocked", "from": from_peer, "cmd": cmd})
                            print(f"shell_agent: blocked: {cmd!r}", flush=True)
                            continue

                        print(f"shell_agent: executing: {cmd!r}", flush=True)
                        _log({"dir": "exec", "from": from_peer, "cmd": cmd})

                        try:
                            proc = subprocess.run(
                                ["powershell", "-NoProfile", "-Command", cmd],
                                capture_output=True, text=True, timeout=timeout_s,
                            )
                            result = {
                                "stdout": proc.stdout,
                                "stderr": proc.stderr,
                                "returncode": proc.returncode,
                            }
                            answer = json.dumps(result)
                        except subprocess.TimeoutExpired:
                            result = {"error": "command timed out", "returncode": -1}
                            answer = json.dumps(result)
                        except Exception as e:
                            result = {"error": str(e), "returncode": -1}
                            answer = json.dumps(result)

                        await client.post(f"{relay}/reply/{mid}", json={"answer": answer})
                        _log({"dir": "reply", "to": from_peer, "rc": result.get("returncode"), "preview": answer[:200]})
                        print(f"shell_agent: replied to {mid}", flush=True)

        except Exception as e:
            print(f"shell_agent: connection error: {e} — reconnecting in 5s", flush=True)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())

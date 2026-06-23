"""Herald debug CLI — manual testing without Claude/MCP.

Usage:
    python cli.py ping <peer>
    python cli.py ask <peer> <message>
    python cli.py pending
    python cli.py reply <message_id> <answer>
    python cli.py health
"""
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

CONFIG_PATH = Path(__file__).parent / "config.json"

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def local_url(path: str) -> str:
    port = load_config().get("port", 7700)
    return f"http://localhost:{port}{path}"

def peer_url(peer_name: str, path: str) -> str:
    config = load_config()
    peer = config["peers"].get(peer_name)
    if not peer:
        print(f"Error: peer '{peer_name}' not in config.json")
        sys.exit(1)
    return f"http://{peer['ip']}:{peer.get('port', 7700)}{path}"

def cmd_health():
    r = httpx.get(local_url("/health"), timeout=3)
    print(json.dumps(r.json(), indent=2))

def cmd_ping(peer_name: str):
    t0 = time.perf_counter()
    try:
        r = httpx.get(peer_url(peer_name, "/health"), timeout=5)
        ms = int((time.perf_counter() - t0) * 1000)
        data = r.json()
        print(f"online  latency={ms}ms  name={data.get('name')}  status={data.get('status')}")
    except Exception as e:
        print(f"offline  error={e}")

def cmd_pending():
    r = httpx.get(local_url("/pending"), timeout=5)
    msgs = r.json()
    if not msgs:
        print("(no pending messages)")
        return
    for m in msgs:
        print(f"[{m['message_id'][:8]}]  from={m['from_peer']}  at={m['received_at']}")
        print(f"  {m['message']}")
        if m.get("attachments"):
            print(f"  attachments: {len(m['attachments'])}")

def cmd_ask(peer_name: str, message: str):
    config = load_config()
    payload = {
        "message_id": str(uuid.uuid4()),
        "from_peer": config.get("name", "cli"),
        "message": message,
        "attachments": [],
    }
    print(f"Sending to {peer_name}... (waiting up to 300s)")
    r = httpx.post(peer_url(peer_name, "/ask"), json=payload, timeout=305)
    data = r.json()
    if "error" in data:
        print(f"Error: {data['error']}")
    else:
        print(f"Answer: {data.get('answer')}")

def cmd_reply(message_id: str, answer: str):
    r = httpx.post(local_url(f"/reply/{message_id}"), json={"answer": answer, "attachments": []}, timeout=5)
    print(r.json())

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    match args[0]:
        case "health":
            cmd_health()
        case "ping" if len(args) == 2:
            cmd_ping(args[1])
        case "pending":
            cmd_pending()
        case "ask" if len(args) >= 3:
            cmd_ask(args[1], " ".join(args[2:]))
        case "reply" if len(args) >= 3:
            cmd_reply(args[1], " ".join(args[2:]))
        case _:
            print(__doc__)
            sys.exit(1)

if __name__ == "__main__":
    main()

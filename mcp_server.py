import base64
import datetime
import json
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Optional
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Herald")

CONFIG_PATH  = Path(__file__).parent / "config.json"
COMM_LOG     = Path(__file__).parent / "herald_comm.log"


def load_config(peer: str = "") -> dict:
    """Config for the network `peer` is on.

    Top-level keys are the default network. Each entry in "networks" overrides them
    (server_url, token, peers, ...) for the peers it lists, so one MCP server can reach
    several relays that never share a token.
    """
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.json not found")
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for net in cfg.get("networks", {}).values():
        if peer in net.get("peers", []):
            return {**cfg, **net}
    return cfg


def all_configs() -> list:
    """One config per network, default first — for inbox tools that must check every relay."""
    cfg = load_config()
    return [cfg] + [{**cfg, **net} for net in cfg.get("networks", {}).values()]


def server_url(config: dict, path: str) -> str:
    base = config.get("server_url", f"http://localhost:{config.get('port', 7700)}")
    return base.rstrip("/") + path


def _auth(config: dict) -> dict:
    return {"X-Herald-Token": config.get("token", "")}


def _log(**kwargs) -> None:
    entry = {"ts": datetime.datetime.now().strftime("%H:%M:%S"), **kwargs}
    with COMM_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


@mcp.tool()
async def ask_peer(peer_name: str, message: str, attachments: Optional[list] = None) -> dict:
    """Send a message to a named peer's Claude and wait up to ~50s for its reply.

    The remote peer's herald_tray auto_reply runs claude, which answers via reply().
    On timeout the result carries the message_id; the peer may still be working.

    Args:
        peer_name: Target peer name.
        message: Message text to send.
        attachments: Optional list of attachments.
    """
    if attachments is None:
        attachments = []
    try:
        config = load_config(peer_name)
    except Exception as e:
        return {"error": str(e)}

    mid = str(uuid.uuid4())
    _log(dir="out", tool="ask_peer", peer=peer_name, msg=message[:120], message_id=mid)

    payload = {
        "message_id": mid,
        "from_peer": config.get("name", "unknown"),
        "to_peer": peer_name,
        "message": message,
        "attachments": attachments,
    }

    # Block and wait for April's claude to reply (typically 20-50s).
    # 50s keeps us under the MCP framework's tool-call timeout (~60-120s).
    async with httpx.AsyncClient(timeout=50.0, headers=_auth(config)) as client:
        try:
            r = await client.post(server_url(config, "/ask"), json=payload)
            result = r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"}
            _log(dir="in", tool="ask_peer", peer=peer_name, preview=str(result)[:300])
            return result
        except httpx.TimeoutException:
            # Relay held the message long enough — claude may still be processing.
            # Use get_pending() to retrieve the reply when it arrives.
            _log(dir="in", tool="ask_peer", peer=peer_name, error="timeout")
            return {
                "status": "timeout",
                "message_id": mid,
                "note": "Claude may still be processing. Use get_pending() to retrieve reply.",
            }
        except Exception as e:
            _log(dir="in", tool="ask_peer", peer=peer_name, error=str(e))
            return {"error": str(e)}


@mcp.tool()
async def get_pending() -> list:
    """Check inbox for incoming questions from remote peers, on every configured relay."""
    try:
        configs = all_configs()
    except Exception as e:
        return [{"error": str(e)}]

    out = []
    for config in configs:
        relay = config.get("server_url", "")
        async with httpx.AsyncClient(timeout=10.0, headers=_auth(config)) as client:
            try:
                r = await client.get(server_url(config, "/pending"), params={"peer": config.get("name", "")})
                if r.status_code == 200:
                    out += [{**m, "relay": relay} for m in r.json()]
                else:
                    out.append({"error": f"HTTP {r.status_code}", "relay": relay})
            except Exception as e:
                out.append({"error": str(e), "relay": relay})
    return out


@mcp.tool()
async def reply(message_id: str, answer: str, attachments: Optional[list] = None) -> dict:
    """Send a reply to a pending incoming question (routed to whichever relay holds it)."""
    if attachments is None:
        attachments = []
    try:
        configs = all_configs()
    except Exception as e:
        return {"error": str(e)}

    # ponytail: tries each relay until one knows the id (others answer 404); fine for a handful of networks
    errors = []
    for config in configs:
        async with httpx.AsyncClient(timeout=10.0, headers=_auth(config)) as client:
            try:
                r = await client.post(server_url(config, f"/reply/{message_id}"),
                                      json={"answer": answer, "attachments": attachments})
                if r.status_code == 200:
                    return r.json()
                errors.append(f"{config.get('server_url')}: HTTP {r.status_code}")
            except Exception as e:
                errors.append(f"{config.get('server_url')}: {e}")
    return {"error": "; ".join(errors)}


@mcp.tool()
async def list_peers() -> dict:
    """Show configured peers and server health, per relay."""
    try:
        configs = all_configs()
    except Exception as e:
        return {"error": str(e)}

    networks = []
    for config in configs:
        async with httpx.AsyncClient(timeout=3.0, headers=_auth(config)) as client:
            try:
                r = await client.get(server_url(config, "/health"))
                server_ok = r.status_code == 200
            except Exception:
                server_ok = False
        networks.append({
            "server_url": config.get("server_url", "localhost"),
            "server_online": server_ok,
            "peers": config.get("peers", []),
        })
    return {"networks": networks}


@mcp.tool()
async def ping_peer(peer_name: str) -> dict:
    """Check if the relay serving peer_name is reachable (does not prove the peer itself is up)."""
    try:
        config = load_config(peer_name)
    except Exception as e:
        return {"online": False, "error": str(e)}

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=5.0, headers=_auth(config)) as client:
        try:
            r = await client.get(server_url(config, "/health"))
            ms = int((time.perf_counter() - t0) * 1000)
            return {"online": r.status_code == 200, "latency_ms": ms}
        except Exception as e:
            return {"online": False, "error": str(e)}


@mcp.tool()
async def send_file(peer_name: str, file_path: str, message: str = "") -> dict:
    """Send a file or image to a named peer's Claude.

    Args:
        peer_name: Target peer name (from config.json peers list).
        file_path: Absolute path to the file to send (max 5MB).
        message: Optional text message to accompany the file.
    """
    try:
        config = load_config(peer_name)
    except Exception as e:
        return {"error": str(e)}

    path = Path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}

    size = path.stat().st_size
    if size > 5 * 1024 * 1024:
        return {"error": f"File too large ({size // 1024 // 1024} MB). Maximum is 5 MB."}

    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type:
        mime_type = "application/octet-stream"

    data_b64 = base64.b64encode(path.read_bytes()).decode("ascii")

    payload = {
        "message_id": str(uuid.uuid4()),
        "from_peer": config.get("name", "unknown"),
        "to_peer": peer_name,
        "message": message or f"File: {path.name}",
        "attachments": [{"filename": path.name, "mime_type": mime_type, "data_b64": data_b64}],
    }

    async with httpx.AsyncClient(timeout=305.0, headers=_auth(config)) as client:
        try:
            r = await client.post(server_url(config, "/ask"), json=payload)
            return r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}", "detail": r.text}
        except httpx.TimeoutException:
            return {"error": "timeout"}
        except Exception as e:
            return {"error": str(e)}


@mcp.tool()
async def deposit_file(peer_name: str, file_path: str, message: str = "", expires_minutes: int = 30) -> dict:
    """Send a file to a peer non-blocking (no reply needed — avoids deadlock).

    Args:
        peer_name: Target peer name.
        file_path: Absolute path to the file to send (max 5MB).
        message: Optional text message.
        expires_minutes: How long the deposit is kept on the server (default 30).
    """
    try:
        config = load_config(peer_name)
    except Exception as e:
        return {"error": str(e)}

    path = Path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}
    if path.stat().st_size > 5 * 1024 * 1024:
        return {"error": "File too large (max 5MB)"}

    mime_type, _ = mimetypes.guess_type(str(path))
    payload = {
        "from_peer": config.get("name", "unknown"),
        "to_peer": peer_name,
        "filename": path.name,
        "data_b64": base64.b64encode(path.read_bytes()).decode("ascii"),
        "content_type": mime_type or "application/octet-stream",
        "message": message or f"File: {path.name}",
        "expires_minutes": expires_minutes,
    }
    async with httpx.AsyncClient(timeout=10.0, headers=_auth(config)) as client:
        try:
            r = await client.post(server_url(config, "/deposit"), json=payload)
            return r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"error": str(e)}


@mcp.tool()
async def get_deposits(save_dir: str = "") -> list:
    """Retrieve files deposited for this machine (non-blocking). Optionally save to save_dir.

    Args:
        save_dir: If provided, save received files to this directory.
    """
    try:
        configs = all_configs()
    except Exception as e:
        return [{"error": str(e)}]

    items, errors = [], []
    for config in configs:
        async with httpx.AsyncClient(timeout=10.0, headers=_auth(config)) as client:
            try:
                r = await client.get(server_url(config, "/deposits"), params={"peer": config.get("name", "")})
                if r.status_code == 200:
                    items += r.json()
                else:
                    errors.append({"error": f"HTTP {r.status_code}", "relay": config.get("server_url")})
            except Exception as e:
                errors.append({"error": str(e), "relay": config.get("server_url")})

    if not save_dir or not items:
        return items + errors
        return items

    out_dir = Path(save_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for item in items:
        filename = item.get("filename", "deposit")
        data = base64.b64decode(item.get("data_b64", ""))
        (out_dir / filename).write_bytes(data)
        item["saved_to"] = str(out_dir / filename)
    return items + errors


@mcp.tool()
async def save_attachment(message_id: str, save_dir: str) -> dict:
    """Decode and save attachments from a pending message to a local directory.

    Args:
        message_id: The message ID from get_pending().
        save_dir: Directory path where files will be saved.
    """
    messages = await get_pending()
    msg = next((m for m in messages if m.get("message_id") == message_id), None)
    if not msg:
        return {"error": f"Message '{message_id}' not found in pending inbox"}

    attachments = msg.get("attachments", [])
    if not attachments:
        return {"saved": [], "count": 0, "note": "No attachments in this message"}

    out_dir = Path(save_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for att in attachments:
        filename = att.get("filename", "attachment")
        data = base64.b64decode(att.get("data_b64", ""))
        out_path = out_dir / filename
        out_path.write_bytes(data)
        saved.append(str(out_path))

    return {"saved": saved, "count": len(saved)}


@mcp.tool()
async def exec_shell(peer_name: str, cmd: str, timeout: int = 60) -> dict:
    """Execute a PowerShell command on a remote peer running herald_tray.py.

    The peer accepts one pipeline only; every element must match its allowlist.json.
    No ; $ ( ) { } & or redirection.

    Args:
        peer_name: Target peer name (must be running herald_tray.py).
        cmd: PowerShell command string to execute.
        timeout: Seconds to wait for the result (default 60).
    """
    try:
        config = load_config(peer_name)
    except Exception as e:
        return {"error": str(e)}

    _log(dir="out", tool="exec_shell", peer=peer_name, cmd=cmd)

    payload = {
        "message_id": str(uuid.uuid4()),
        "from_peer": config.get("name", "unknown"),
        "to_peer": peer_name,
        "message": json.dumps({"type": "shell", "cmd": cmd}),
        "attachments": [],
    }

    async with httpx.AsyncClient(timeout=timeout + 5.0, headers=_auth(config)) as client:
        try:
            r = await client.post(server_url(config, "/ask"), json=payload)
            if r.status_code != 200:
                _log(dir="in", tool="exec_shell", peer=peer_name, error=f"HTTP {r.status_code}")
                return {"error": f"HTTP {r.status_code}", "detail": r.text}
            data = r.json()
            answer = data.get("answer", "")
            try:
                result = json.loads(answer)
            except Exception:
                result = {"raw": answer}
            _log(dir="in", tool="exec_shell", peer=peer_name,
                 rc=result.get("returncode"), preview=(result.get("stdout") or result.get("error") or answer)[:300])
            return result
        except httpx.TimeoutException:
            _log(dir="in", tool="exec_shell", peer=peer_name, error="timeout")
            return {"error": "timeout"}
        except Exception as e:
            _log(dir="in", tool="exec_shell", peer=peer_name, error=str(e))
            return {"error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")

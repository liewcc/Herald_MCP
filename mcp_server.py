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


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.json not found")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def server_url(config: dict, path: str) -> str:
    base = config.get("server_url", f"http://localhost:{config.get('port', 7700)}")
    return base.rstrip("/") + path


def _log(**kwargs) -> None:
    entry = {"ts": datetime.datetime.now().strftime("%H:%M:%S"), **kwargs}
    with COMM_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


@mcp.tool()
async def ask_peer(peer_name: str, message: str, attachments: Optional[list] = None) -> dict:
    """Send a message to a named peer's Claude. Returns immediately — does not block.

    The relay queues the message even after this call returns. The remote peer's
    auto_reply will process it and push a reply to this machine's pending inbox.
    Use get_pending() after ~30-60s to retrieve the reply.

    Args:
        peer_name: Target peer name.
        message: Message text to send.
        attachments: Optional list of attachments.
    """
    if attachments is None:
        attachments = []
    try:
        config = load_config()
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
    async with httpx.AsyncClient(timeout=50.0) as client:
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
    """Check inbox for incoming questions from remote peers."""
    try:
        config = load_config()
    except Exception as e:
        return [{"error": str(e)}]

    name = config.get("name", "")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(server_url(config, "/pending"), params={"peer": name})
            return r.json() if r.status_code == 200 else [{"error": f"HTTP {r.status_code}"}]
        except Exception as e:
            return [{"error": str(e)}]


@mcp.tool()
async def reply(message_id: str, answer: str, attachments: Optional[list] = None) -> dict:
    """Send a reply to a pending incoming question."""
    if attachments is None:
        attachments = []
    try:
        config = load_config()
    except Exception as e:
        return {"error": str(e)}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(server_url(config, f"/reply/{message_id}"),
                                  json={"answer": answer, "attachments": attachments})
            return r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"error": str(e)}


@mcp.tool()
async def list_peers() -> dict:
    """Show configured peers and server health."""
    try:
        config = load_config()
    except Exception as e:
        return {"error": str(e)}

    peers = config.get("peers", [])
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            r = await client.get(server_url(config, "/health"))
            server_ok = r.status_code == 200
        except Exception:
            server_ok = False

    return {
        "server_url": config.get("server_url", "localhost"),
        "server_online": server_ok,
        "peers": peers,
    }


@mcp.tool()
async def ping_peer(peer_name: str) -> dict:
    """Check if the Herald server is reachable (peer_name ignored in hub mode)."""
    try:
        config = load_config()
    except Exception as e:
        return {"online": False, "error": str(e)}

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=5.0) as client:
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
        config = load_config()
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

    async with httpx.AsyncClient(timeout=305.0) as client:
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
        config = load_config()
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
    async with httpx.AsyncClient(timeout=10.0) as client:
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
        config = load_config()
    except Exception as e:
        return [{"error": str(e)}]

    name = config.get("name", "")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(server_url(config, "/deposits"), params={"peer": name})
            if r.status_code != 200:
                return [{"error": f"HTTP {r.status_code}"}]
            items = r.json()
        except Exception as e:
            return [{"error": str(e)}]

    if not save_dir or not items:
        return items

    out_dir = Path(save_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for item in items:
        filename = item.get("filename", "deposit")
        data = base64.b64decode(item.get("data_b64", ""))
        (out_dir / filename).write_bytes(data)
        item["saved_to"] = str(out_dir / filename)
    return items


@mcp.tool()
async def save_attachment(message_id: str, save_dir: str) -> dict:
    """Decode and save attachments from a pending message to a local directory.

    Args:
        message_id: The message ID from get_pending().
        save_dir: Directory path where files will be saved.
    """
    try:
        config = load_config()
    except Exception as e:
        return {"error": str(e)}

    name = config.get("name", "")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(server_url(config, "/pending"), params={"peer": name})
            if r.status_code != 200:
                return {"error": f"HTTP {r.status_code}"}
            messages = r.json()
        except Exception as e:
            return {"error": str(e)}

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
    """Execute a PowerShell command on a remote peer running shell_agent.py.

    Args:
        peer_name: Target peer name (must be running shell_agent.py).
        cmd: PowerShell command string to execute.
        timeout: Seconds to wait for the result (default 60).
    """
    try:
        config = load_config()
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

    async with httpx.AsyncClient(timeout=timeout + 5.0) as client:
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

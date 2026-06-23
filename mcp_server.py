import json
import time
import uuid
from pathlib import Path
from typing import Optional
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Herald")

CONFIG_PATH = Path(__file__).parent / "config.json"

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.json not found")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

def server_url(config: dict, path: str) -> str:
    base = config.get("server_url", f"http://localhost:{config.get('port', 7700)}")
    return base.rstrip("/") + path

@mcp.tool()
async def ask_peer(peer_name: str, message: str, attachments: Optional[list] = None) -> dict:
    """Send a question to a named peer's Claude and wait for its reply."""
    if attachments is None:
        attachments = []
    try:
        config = load_config()
    except Exception as e:
        return {"error": str(e)}

    payload = {
        "message_id": str(uuid.uuid4()),
        "from_peer": config.get("name", "unknown"),
        "to_peer": peer_name,
        "message": message,
        "attachments": attachments,
    }

    async with httpx.AsyncClient(timeout=305.0) as client:
        try:
            r = await client.post(server_url(config, "/ask"), json=payload)
            return r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}", "detail": r.text}
        except httpx.TimeoutException:
            return {"error": "timeout"}
        except Exception as e:
            return {"error": "connection_error", "detail": str(e)}

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

if __name__ == "__main__":
    mcp.run(transport="stdio")

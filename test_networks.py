"""Self-check for multi-network routing in mcp_server.py. Run: python test_networks.py"""
import asyncio
import json
import tempfile
from pathlib import Path

import mcp_server

cfg = {
    "name": "cc", "server_url": "http://april:7700", "token": "A", "peers": ["April", "leno"],
    "networks": {"abby": {"server_url": "http://cc:7700", "token": "B", "peers": ["abby"]}},
}
tmp = Path(tempfile.mkdtemp()) / "config.json"
tmp.write_text(json.dumps(cfg), encoding="utf-8")
mcp_server.CONFIG_PATH = tmp

# Outgoing: the peer name picks the relay and its token; the two never mix.
assert (mcp_server.load_config("abby")["server_url"], mcp_server.load_config("abby")["token"]) == ("http://cc:7700", "B")
assert (mcp_server.load_config("April")["server_url"], mcp_server.load_config("April")["token"]) == ("http://april:7700", "A")
assert mcp_server.load_config("abby")["name"] == "cc"           # inherited from top level
assert mcp_server.load_config("nobody")["token"] == "A"         # unknown peer -> default network

# Incoming: inbox tools see both relays.
assert [c["token"] for c in mcp_server.all_configs()] == ["A", "B"]

# get_pending queries each relay with that relay's own token and tags messages with their relay.
seen = []
def handler(request):
    seen.append((str(request.url.host), request.headers["x-herald-token"]))
    return mcp_server.httpx.Response(200, json=[{"message_id": request.url.host}])
real = mcp_server.httpx.AsyncClient
mcp_server.httpx.AsyncClient = lambda **kw: real(transport=mcp_server.httpx.MockTransport(handler), **kw)
msgs = asyncio.run(mcp_server.get_pending())
assert seen == [("april", "A"), ("cc", "B")], seen
assert [m["relay"] for m in msgs] == ["http://april:7700", "http://cc:7700"], msgs

# Tray: same merge, and the Network tab's per-peer state from /health.
import herald_tray
assert herald_tray.net_for(cfg, "abby")["token"] == "B" and herald_tray.net_for(cfg, "leno")["token"] == "A"
assert [n["server_url"] for n in herald_tray.networks(cfg)] == ["http://april:7700", "http://cc:7700"]
assert herald_tray.node_state("leno", {"up": True, "online": ["leno"]}) == "online"
assert herald_tray.node_state("April", {"up": True, "online": ["leno"]}) == "offline"
assert herald_tray.node_state("April", {"up": True, "online": None}) == "unknown"     # old relay
assert herald_tray.node_state("April", {"up": False, "online": None}) == "unknown"    # relay down
herald_tray.httpx.get = lambda url, **kw: mcp_server.httpx.Response(
    200, json={"online": ["leno"], "name": "April"}, request=mcp_server.httpx.Request("GET", url))
assert herald_tray.probe_relay(cfg)["online"] == ["leno"]
assert herald_tray.relay_host(cfg, herald_tray.probe_relay(cfg), {}) == "April"      # relay names itself
herald_tray.httpx.get = lambda url, **kw: (_ for _ in ()).throw(OSError("down"))
down = herald_tray.probe_relay(cfg)
assert down == {"up": False, "ms": None, "online": None, "host": None}
net = {"server_url": "http://100.104.102.15:7700"}
assert herald_tray.relay_host(net, down, {"abby": "100.104.102.15"}) == "abby"       # down: IP lookup
assert herald_tray.relay_host(net, down, {}) is None
# The relay host is drawn once, in the middle, never again in the ring.
april = {"name": "cc", "peers": ["April", "leno", "dv"]}
assert herald_tray.split_members(april, "April") == ("April", ["cc", "leno", "dv"])
assert herald_tray.split_members({"name": "April", "peers": ["cc"]}, "April") == ("April", ["cc"])
assert herald_tray.split_members(april, None) == (None, ["cc", "April", "leno", "dv"])

print("ok")

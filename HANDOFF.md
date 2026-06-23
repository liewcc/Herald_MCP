# Herald_MCP — Work Handoff

> Shared baton for AI sessions working on this project.
> Read this first when you start; update it before you stop.

---

## Project Purpose

Herald_MCP enables two Claude instances (or any MCP-capable AI agent) on separate
Windows machines in different cities to communicate peer-to-peer over Tailscale.
Either side can initiate a request-response conversation. A thin-client browser UI
is a free bonus once the core is built.

Full architecture is documented in `DESIGN.md` — read that before touching any code.

---

## Current Status — PHASE 1 IMPLEMENTATION COMPLETE

All core files written. Ready for loopback testing on Machine A.

---

## Network Setup Status

| Item | Status |
|------|--------|
| Tailscale installed on Machine A | ✓ Done — IP: `100.70.161.73` |
| Tailscale auth key generated | ✓ Done — generate new keys at https://login.tailscale.com/admin/settings/keys (use Reusable for testing) |
| Machine B setup script | ✓ Done — `client.bat` (right-click → Run as administrator, paste auth key) |
| Tailscale installed on Machine B | ✗ Pending — waiting for Machine B person to run `client.bat` |
| Machine B Tailscale IP | ✗ Unknown until B is set up |

Machine B setup (send these two things to Machine B person):
1. The file `client.bat`
2. A Tailscale auth key (generate at the link above)

They right-click → Run as administrator → paste the key → script installs Tailscale and prints their `100.x.x.x` IP.

Once Machine B IP is known:
- Update `config.json` on Machine A: replace `100.x.x.x` with Machine B's real IP
- Send the Herald files to Machine B (server.py, mcp_server.py, run.py, requirements.txt, cli.py)
- On Machine B: create `config.json` with name="machine-b" and peer pointing to Machine A IP `100.70.161.73`

---

## Next Steps (in order)

1. [x] Write `server.py` — FastAPI HTTP server with long-poll
2. [x] Write `mcp_server.py` — MCP stdio server (5 tools)
3. [x] Write `run.py` — launcher for both processes
4. [x] Write `requirements.txt`
5. [x] Write `cli.py` — debug CLI for manual testing
6. [ ] Install dependencies: `pip install -r requirements.txt`
7. [ ] Loopback test on Machine A (two terminals, different ports)
      - Terminal 1: `python server.py` (port 7700)
      - Terminal 2: `python cli.py pending` / `python cli.py ask ...`
8. [ ] Confirm Machine B Tailscale IP (blocked on B's setup)
9. [ ] Update `config.json` on both machines with real IPs
10. [ ] End-to-end test A ↔ B

---

## Key Design Decisions (do not revisit without reason)

- **Transport:** HTTP over Tailscale (not SSE, not WebSocket — plain request/response)
- **Pattern:** Long-poll on server side — sender blocks up to 300s waiting for reply
- **Auth:** None in v1 — Tailscale network-level encryption is sufficient
- **Port:** 7700 (does not conflict with Gemi_MCP's 18800)
- **Attachments:** Base64 in JSON for files < 5 MB
- **Config:** Hand-edited `config.json` with peer IPs — no dynamic discovery needed
- **Symmetry:** Both machines run identical codebase — no separate client/server code

---

## Confirmed Answers from Design Session

- Both machines: Windows 10/11
- Both machines: Claude Code or Antigravity installed (MCP-capable)
- Communication: peer-to-peer, both sides can initiate
- Pattern: request-response (not async fire-and-forget)
- File transfer: yes, base64 for small files
- Extra security: not needed for v1
- Thin client (no-Claude terminal): automatically supported by the HTTP server

---

## File Structure (target)

```
D:\AI\Herald_MCP\
  server.py          ← FastAPI HTTP server
  mcp_server.py      ← MCP stdio server
  config.json        ← peer IPs and port config (create manually)
  run.py             ← starts both processes
  requirements.txt
  DESIGN.md          ← full architecture document (read this first)
  HANDOFF.md         ← this file
```

---

## Related Projects

- `D:\AI\Gemi_MCP` — Gemini/DeepSeek browser automation MCP (separate project)
- Herald is standalone — no code dependency on Gemi_MCP

---

## Last Updated

2026-06-23 by Claude Code (Sonnet 4.6) — initial handoff, pre-implementation

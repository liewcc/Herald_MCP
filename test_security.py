"""Self-check for the relay token and the exec_shell guard. Run: python test_security.py"""
import os
import sys
import types

sys.modules.setdefault("pystray", types.ModuleType("pystray"))  # tray UI dep, not needed here
os.environ["HERALD_TOKEN"] = "test-token"

from fastapi.testclient import TestClient  # noqa: E402

import herald_tray  # noqa: E402
import server  # noqa: E402

# Relay: every route needs the token.
c = TestClient(server.app)
assert c.get("/health").status_code == 401
assert c.get("/health", headers={"X-Herald-Token": "wrong"}).status_code == 401
assert c.get("/pending", headers={"X-Herald-Token": "test-token"}).status_code == 200

# Guard: allowlisted single pipelines pass, anything that can smuggle code fails.
rules = herald_tray._load_allowlist()
ok = [
    "Get-Date",
    "tasklist | findstr /i claude",
    "Get-Process | Sort-Object CPU -Descending | Select-Object -First 15 | Format-Table Name,Id,CPU -AutoSize",
    'python -c "print(chr(34))"',
    "git log --oneline -5",
]
bad = [
    "Get-Date; Remove-Item x",
    "Get-Date\nRemove-Item x",
    "tasklist | Remove-Item x",
    "Get-Date (Remove-Item x)",
    "Get-Date $(Remove-Item x)",
    'echo "$(Remove-Item x)"',
    "Get-Date > C:\\x.txt",
    "Get-Date | ForEach-Object { Remove-Item x }",
    "& Remove-Item x",
    "Get-Date -Format $env:USERNAME",
    "Remove-Item x",
    "Get-Date |",
]
for cmd in ok:
    assert herald_tray._shell_allowed(cmd, rules), f"should allow: {cmd!r}"
for cmd in bad:
    assert not herald_tray._shell_allowed(cmd, rules), f"should block: {cmd!r}"
print(f"OK: relay auth + {len(ok)} allowed / {len(bad)} blocked")

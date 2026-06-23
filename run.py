import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Resolve base directory
BASE_DIR = Path(__file__).parent.resolve()

# Add to system path if needed
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Import mcp instance from mcp_server
try:
    from mcp_server import mcp
except ImportError as e:
    print(f"Error: Could not import 'mcp' from 'mcp_server.py': {e}", file=sys.stderr)
    sys.exit(1)

def get_config_port() -> int:
    config_path = BASE_DIR / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                return config.get("port", 7700)
        except Exception as e:
            print(f"Warning: Failed to read config.json for port: {e}. Using default 7700.", file=sys.stderr)
    return 7700

def check_server_health(port: int) -> bool:
    # Use urllib.request from standard library to avoid external dependency issues during health checks
    import urllib.request
    import urllib.error
    
    url = f"http://localhost:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=1.0) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                return data.get("status") == "ok"
    except Exception:
        pass
    return False

def main():
    port = get_config_port()
    log_file_path = BASE_DIR / "server.log"
    
    print(f"Starting Herald HTTP Server on port {port}...", file=sys.stderr)
    print(f"Redirecting server output to {log_file_path}", file=sys.stderr)
    
    # Start server.py as a subprocess using the same python interpreter
    # We run it using python -m uvicorn server:app to support module loading correctly
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "server:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(port)
    ]
    
    # Open log file for stdout and stderr redirection
    log_file = open(log_file_path, "w", encoding="utf-8")
    
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(BASE_DIR),
            text=True
        )
    except Exception as e:
        print(f"Error: Failed to spawn uvicorn subprocess: {e}", file=sys.stderr)
        log_file.close()
        sys.exit(1)
        
    # Poll health endpoint until server is ready
    server_started = False
    max_attempts = 20
    print("Waiting for HTTP server to become healthy...", file=sys.stderr)
    
    for attempt in range(1, max_attempts + 1):
        # Check if subprocess died early
        if proc.poll() is not None:
            print(f"Error: server.py subprocess exited unexpectedly with code {proc.returncode}.", file=sys.stderr)
            log_file.close()
            # Try to show logs
            try:
                with open(log_file_path, "r", encoding="utf-8") as lf:
                    print("Last server logs:", file=sys.stderr)
                    print(lf.read(), file=sys.stderr)
            except Exception:
                pass
            sys.exit(1)
            
        if check_server_health(port):
            server_started = True
            print("HTTP server is healthy and responding.", file=sys.stderr)
            break
            
        time.sleep(0.5)
        
    if not server_started:
        print("Error: HTTP server failed to respond within the timeout period.", file=sys.stderr)
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()
        sys.exit(1)
        
    # Start the MCP stdio server
    print("Starting MCP Stdio Server...", file=sys.stderr)
    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        print("Received keyboard interrupt. Shutting down...", file=sys.stderr)
    finally:
        print("Stopping HTTP server subprocess...", file=sys.stderr)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("HTTP server did not stop, killing process...", file=sys.stderr)
            proc.kill()
        log_file.close()
        print("Herald MCP has shut down.", file=sys.stderr)

if __name__ == "__main__":
    main()

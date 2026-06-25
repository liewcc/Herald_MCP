"""
Herald SSE subscriber — zero-token notification daemon.

Holds one persistent HTTP connection to /subscribe. Prints an alert when a
message arrives. No Claude, no polling, no token cost while idle.

Usage:
  python subscriber.py           # run forever
  python subscriber.py --once    # exit after first event
"""
import sys
import json
import time
import httpx
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Herald SSE Push Notification Subscriber Daemon")
    parser.add_argument("--once", action="store_true", help="Connect, wait for ONE event, print it, then exit")
    args = parser.parse_args()

    # Load config.json from same directory as this script
    config_path = Path(__file__).parent.resolve() / "config.json"
    if not config_path.exists():
        print(f"Error: config.json not found at {config_path}", file=sys.stderr)
        sys.exit(1)
        
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error reading config.json: {e}", file=sys.stderr)
        sys.exit(1)
        
    server_url = config.get("server_url")
    name = config.get("name")
    
    if not server_url:
        print("Error: 'server_url' not configured in config.json", file=sys.stderr)
        sys.exit(1)
    if not name:
        print("Error: 'name' not configured in config.json", file=sys.stderr)
        sys.exit(1)

    base_url = server_url.rstrip("/")
    subscribe_url = f"{base_url}/subscribe"
    params = {"peer": name}

    print(f"Subscribing to {subscribe_url} as peer '{name}'...")
    
    backoff = 5
    while True:
        try:
            # We set timeout=None to allow the stream to remain open indefinitely.
            with httpx.stream("GET", subscribe_url, params=params, timeout=None) as response:
                if response.status_code != 200:
                    print(f"Connection failed: HTTP {response.status_code}", file=sys.stderr)
                else:
                    print("Connected to Herald relay server. Waiting for notifications...")
                    for line in response.iter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            try:
                                payload = json.loads(data_str)
                                # Print message notification clearly to stdout
                                print(f"\n[NOTIFICATION] New message received!")
                                print(f"  Message ID: {payload.get('message_id')}")
                                print(f"  From Peer:  {payload.get('from_peer')}")
                                sys.stdout.flush()
                                
                                if args.once:
                                    return
                            except json.JSONDecodeError:
                                print(f"Warning: Failed to parse data as JSON: {data_str}", file=sys.stderr)
                        elif line.startswith(":"):
                            pass  # keepalive
        except httpx.RequestError as exc:
            print(f"Connection error: {exc}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\nSubscriber daemon stopped by user.")
            sys.exit(0)
        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            
        if args.once:
            print("Failed to receive event in --once mode.", file=sys.stderr)
            sys.exit(1)
            
        print(f"Reconnecting in {backoff} seconds...", file=sys.stderr)
        try:
            time.sleep(backoff)
        except KeyboardInterrupt:
            print("\nSubscriber daemon stopped by user.")
            sys.exit(0)

if __name__ == "__main__":
    main()

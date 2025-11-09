import http.client
import json
import threading
import time
import sys
import argparse
from urllib.parse import urlencode, urlparse

class ChatClient:
    def __init__(self, base_url, peer_id, channel,
                 ip="127.0.0.1", port=5001, cookie="auth=true",
                 poll_interval=1.0):
        self.base_url = base_url
        self.peer_id = peer_id
        self.channel = channel
        self.ip = ip
        self.port = port
        self.cookie = cookie
        self.poll_interval = poll_interval
        self.last_seq = 0
        self.stop_flag = False

        u = urlparse(base_url)
        self.scheme = u.scheme or "http"
        self.host = u.hostname or "127.0.0.1"
        self.http_port = u.port or (443 if self.scheme == "https" else 80)
        self.is_https = (self.scheme == "https")

    def _conn(self):
        if self.is_https:
            return http.client.HTTPSConnection(self.host, self.http_port, timeout=10)
        return http.client.HTTPConnection(self.host, self.http_port, timeout=10)

    def post(self, path, data_dict):
        body = urlencode(data_dict)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": self.cookie,
            "User-Agent": "WeApRous-CLI/1.0",
            "Connection": "close",
        }
        conn = self._conn()
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        text = raw.decode("utf-8", errors="ignore") if raw else ""
        return resp.status, dict(resp.getheaders()), text

    def _unwrap(self, txt):
        """Return a dict and normalize server wrappers {result: {...}}."""
        try:
            data = json.loads(txt) if txt else None
        except Exception:
            return None
        if isinstance(data, dict) and "result" in data and isinstance(data["result"], dict):
            return data["result"]
        return data

    def start(self):
        # Register → create → join (with tiny delays to avoid race/close)
        self.post("/peer/register", {"peer_id": self.peer_id, "ip": self.ip, "port": str(self.port)})
        time.sleep(0.2)
        self.post("/channel/create", {"name": self.channel})
        time.sleep(0.2)

        # retry join a bit in case server is still busy
        for attempt in range(3):
            try:
                self.post("/channel/join", {"name": self.channel, "peer_id": self.peer_id})
                break
            except ConnectionResetError:
                time.sleep(0.5)

        # start poller
        t = threading.Thread(target=self._poll_loop, daemon=True)
        t.start()

        print(f"[{self.peer_id}] đã vào #{self.channel}. Gõ để chat, /quit để thoát.")
        try:
            for line in sys.stdin:
                msg = line.rstrip("\n")
                if msg == "/quit":
                    break
                if not msg.strip():
                    continue
                try:
                    status, _, txt = self.post("/message", {
                        "name": self.channel,
                        "peer_id": self.peer_id,
                        "text": msg
                    })
                    if status >= 400:
                        print(f"[error] send failed status={status} body={txt[:120]}")
                except ConnectionResetError as e:
                    print(f"[error] reset by server on /message: {e}")
                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop_flag = True
            print("\nbye.")

    def _poll_loop(self):
        while not self.stop_flag:
            try:
                status, _, txt = self.post("/sync", {"name": self.channel, "after": str(self.last_seq)})
                if status == 200 and txt:
                    payload = self._unwrap(txt)
                    msgs = []
                    if isinstance(payload, dict):
                        if "messages" in payload and isinstance(payload["messages"], list):
                            msgs = payload["messages"]
                    for m in msgs:
                        try:
                            self.last_seq = max(self.last_seq, int(m.get("seq", 0)))
                            frm = m.get("from", "?")
                            text = m.get("text", "")
                            print(f"\r[{frm}] {text}")
                        except Exception:
                            continue
                time.sleep(self.poll_interval)
            except ConnectionResetError as e:
                time.sleep(0.6)
            except Exception:
                time.sleep(0.6)

def main():
    ap = argparse.ArgumentParser(description="WeApRous CLI chat client")
    ap.add_argument("--server",  default="http://127.0.0.1:9000", help="Base URL server/proxy")
    ap.add_argument("--peer",    required=True, help="Peer ID (A/B/...)")
    ap.add_argument("--channel", default="room", help="Channel")
    ap.add_argument("--ip",      default="127.0.0.1", help="IP quảng bá (demo)")
    ap.add_argument("--port",    type=int, default=5001, help="Port quảng bá (demo)")
    ap.add_argument("--cookie",  default="auth=true", help="Cookie cho auth (liên hệ /login)")
    args = ap.parse_args()

    ChatClient(args.server, args.peer, args.channel,
               ip=args.ip, port=args.port, cookie=args.cookie).start()

if __name__ == "__main__":
    main()

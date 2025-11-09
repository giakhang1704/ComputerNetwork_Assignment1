import socket
import threading
import argparse
import sys
import time
import json
import http.client
from urllib.parse import urlencode, urlparse

LINE_SEP = b"\n"

def now():
    return time.time()

class P2PPeer:
    def __init__(self, server_base, peer_id, channel, listen_ip, listen_port, cookie="auth=true"):
        # Server info (for discovery / join)
        self.server_base = server_base
        u = urlparse(server_base)
        self.host = u.hostname or "127.0.0.1"
        self.port = u.port or (443 if (u.scheme or "http") == "https" else 80)
        self.is_https = (u.scheme == "https")

        # Peer info
        self.peer_id = str(peer_id)
        self.channel = str(channel)
        self.listen_ip = listen_ip
        self.listen_port = int(listen_port)
        self.cookie = cookie

        # Active P2P connections: {peer_id -> socket}
        self.conns = {}
        self.conns_lock = threading.Lock()

        self.stop = False
        self.last_seq = 0  

    # ---------------- REST helper ----------------
    def _conn(self):
        if self.is_https:
            return http.client.HTTPSConnection(self.host, self.port, timeout=10)
        return http.client.HTTPConnection(self.host, self.port, timeout=10)

    def _post(self, path, form):
        body = urlencode(form)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": self.cookie,
            "User-Agent": "P2P-CLI/1.0",
            "Connection": "close",
        }
        c = self._conn()
        c.request("POST", path, body=body, headers=headers)
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            txt = data.decode("utf-8", errors="ignore")
        except Exception:
            txt = ""
        try:
            js = json.loads(txt) if txt else None
        except Exception:
            js = None
        return r.status, js

    # ---------------- Discovery & bootstrap ----------------
    def register_and_join(self):
        # 1) register
        st, _ = self._post("/peer/register", {
            "peer_id": self.peer_id,
            "ip": self.listen_ip,
            "port": str(self.listen_port),
        })
        if st != 200:
            print("[!] register failed", st)

        # 2) create channel (idempotent) + join
        self._post("/channel/create", {"name": self.channel})
        st, js = self._post("/channel/join", {"name": self.channel, "peer_id": self.peer_id})
        if js and "peers" in js:
            for pid, info in js["peers"].items():
                if pid == self.peer_id:
                    continue
                if self.peer_id < pid:
                    self._ensure_connected(pid, info["ip"], int(info["port"]))

        # 3) refresh peers periodically (discover newcomers)
        t = threading.Thread(target=self._refresh_loop, daemon=True)
        t.start()

    def _refresh_loop(self):
        while not self.stop:
            try:
                st, js = self._post("/channel/join", {"name": self.channel, "peer_id": self.peer_id})
                if js and "peers" in js:
                    for pid, info in js["peers"].items():
                        if pid == self.peer_id:
                            continue
                        # single-sided dialing rule
                        if self.peer_id < pid:
                            self._ensure_connected(pid, info["ip"], int(info["port"]))
            except Exception:
                pass
            time.sleep(2.0)

    # ---------------- P2P listener & connectors ----------------
    def start_listener(self):
        def serve():
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                srv.bind((self.listen_ip, self.listen_port))
                srv.listen(20)
                print(f"[{self.peer_id}] listening on {self.listen_ip}:{self.listen_port}")
                while not self.stop:
                    try:
                        s, addr = srv.accept()
                        try:
                            s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                            s.settimeout(None)  # blocking recv
                        except Exception:
                            pass
                        # wait for "hello" to learn peer_id, handled in _on_line
                        t = threading.Thread(target=self._handle_conn, args=(s, f"in:{addr}"), daemon=True)
                        t.start()
                    except Exception:
                        break
            finally:
                try:
                    srv.close()
                except Exception:
                    pass
        threading.Thread(target=serve, daemon=True).start()

    def _ensure_connected(self, peer_key, ip, port):
        with self.conns_lock:
            if peer_key in self.conns:
                return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except Exception:
                pass

            # timeout ONLY for connect
            s.settimeout(3.0)
            s.connect((ip, port))

            s.settimeout(None)


            with self.conns_lock:
                self.conns[peer_key] = s

            # Send hello so the receiver can map our socket -> our peer_id
            hello = (json.dumps({"type": "hello", "from": self.peer_id, "chan": self.channel}) + "\n").encode("utf-8")
            try:
                s.sendall(hello)
            except Exception:
                pass

            threading.Thread(target=self._handle_conn, args=(s, f"out:{peer_key}"), daemon=True).start()
            print(f"[{self.peer_id}] connected to {peer_key} at {ip}:{port}")
        except Exception:
            try:
                s.close()
            except Exception:
                pass


    def _handle_conn(self, s, tag):
        buf = b""
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while True:
                    if LINE_SEP in buf:
                        line, buf = buf.split(LINE_SEP, 1)
                        self._on_line(line, s)
                    else:
                        break
        except Exception:
            pass
        finally:
            # remove the socket from conns if present
            with self.conns_lock:
                for k, v in list(self.conns.items()):
                    if v is s:
                        del self.conns[k]
                        break
            try:
                s.close()
            except Exception:
                pass

    def _on_line(self, line_bytes, sock):
        try:
            txt = line_bytes.decode("utf-8", errors="ignore")
            js = json.loads(txt)
        except Exception:
            return

        typ = js.get("type")
        if typ == "hello":
            pid = js.get("from")
            if pid:
                with self.conns_lock:
                    self.conns[pid] = sock
            return

        if typ == "msg":
            frm = js.get("from", "?")
            text = js.get("text", "")
            print(f"\r[{frm}] {text}")
            return


    # ---------------- Sending ----------------
    def send_all(self, text):
        payload = {"type": "msg", "chan": self.channel, "from": self.peer_id, "text": text, "ts": now()}
        raw = (json.dumps(payload) + "\n").encode("utf-8")
        with self.conns_lock:
            targets = list(self.conns.values())
        for s in targets:
            try:
                s.sendall(raw)
            except Exception:
                pass

        print(f"[{self.peer_id}] {text}")

    # ---------------- Main loop ----------------
    def run(self):
        # listener + discovery
        self.start_listener()
        self.register_and_join()

        print(f"[{self.peer_id}] đã vào kênh #{self.channel}. Gõ để chat, /quit để thoát.")
        try:
            for line in sys.stdin:
                msg = line.rstrip("\n")
                if msg == "/quit":
                    break
                if not msg.strip():
                    continue
                self.send_all(msg)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop = True
            with self.conns_lock:
                for s in self.conns.values():
                    try:
                        s.close()
                    except Exception:
                        pass
            print("\nbye.")

def main():
    ap = argparse.ArgumentParser(description="P2P peer with server-side discovery")
    ap.add_argument("--server",  default="http://127.0.0.1:9000", help="Base URL server/proxy")
    ap.add_argument("--peer",    required=True, help="Peer ID (A/B/...)")
    ap.add_argument("--channel", default="room", help="Channel name")
    ap.add_argument("--ip",      default="127.0.0.1", help="IP for other peer to dial")
    ap.add_argument("--port",    type=int, default=5001, help="P2P listen port")
    ap.add_argument("--cookie",  default="auth=true", help="Cookie for auth (/login)")
    args = ap.parse_args()

    P2PPeer(args.server, args.peer, args.channel, args.ip, args.port, cookie=args.cookie).run()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import socket
import threading
import argparse
import http.client
import mimetypes
from urllib.parse import urlencode, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LINE_SEP = b"\n"

def now():
    return time.time()

def guess_mime(path: str) -> str:
    mt, _ = mimetypes.guess_type(path)
    return mt or "application/octet-stream"


class P2PPeer:
    """
    Hybrid chat peer:
      - Uses central server for discovery (register/join) at startup and then periodically.
      - Maintains direct TCP connections to other peers (send/receive JSON lines).
      - Exposes a local HTTP bridge for the browser UI (serves chat.html and REST endpoints).
    """

    def __init__(
        self,
        server_base: str,
        peer_id: str,
        channel: str,
        listen_ip: str,
        listen_port: int,
        cookie: str = "auth=true",
        bridge_host: str = None,
        bridge_port: int = None,
        ui_root: str = ".",
    ):
        # ---- Central server info (for discovery) ----
        self.server_base = server_base
        u = urlparse(server_base)
        self.host = u.hostname or "127.0.0.1"
        # Note: if scheme missing, treat as http
        scheme = u.scheme or "http"
        self.port = u.port or (443 if scheme == "https" else 80)
        self.is_https = (scheme == "https")

        # ---- Peer info ----
        self.peer_id = str(peer_id)
        self.channel = str(channel)
        self.listen_ip = listen_ip
        self.listen_port = int(listen_port)
        self.cookie = cookie

        # ---- P2P sockets: {peer_id -> socket} ----
        self.conns = {}
        self.conns_lock = threading.Lock()

        # ---- Simple in-memory channel store for bridge/UI ----
        # chats[channel] = {"seq": int, "messages": [ {seq, from, text, ts}, ... ]}
        self.chats = {}
        self.chats_lock = threading.Lock()

        # runtime flags
        self.stop = False

        # ---- HTTP bridge ----
        self.bridge_host = bridge_host
        self.bridge_port = bridge_port
        self.ui_root = os.path.abspath(ui_root)

    # =============== Central server helpers ===============
    def _conn(self):
        if self.is_https:
            return http.client.HTTPSConnection(self.host, self.port, timeout=10)
        return http.client.HTTPConnection(self.host, self.port, timeout=10)

    def _post(self, path, form):
        """POST to central server; returns (status_code, json_or_None)."""
        body = urlencode(form)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": self.cookie,
            "User-Agent": "P2P-CLI/1.0",
            "Connection": "close",
        }
        c = self._conn()
        try:
            c.request("POST", path, body=body, headers=headers)
            r = c.getresponse()
            data = r.read()
            status = r.status
        finally:
            try:
                c.close()
            except Exception:
                pass

        try:
            txt = data.decode("utf-8", errors="ignore")
            js = json.loads(txt) if txt else None
        except Exception:
            js = None
        return status, js

    # =============== Discovery & bootstrap ===============
    def register_and_join(self):
        # 1) register (ignore error; the server may not enforce auth)
        try:
            st, _ = self._post("/peer/register", {
                "peer_id": self.peer_id,
                "ip": self.listen_ip,
                "port": str(self.listen_port),
            })
            if st != 200:
                print(f"[!] register failed: {st}")
        except Exception as e:
            print(f"[!] register exception: {e}")

        # 2) create channel (idempotent) + join
        try:
            self._post("/channel/create", {"name": self.channel})
        except Exception:
            pass

        try:
            st, js = self._post("/channel/join", {"name": self.channel, "peer_id": self.peer_id})
            if js and "peers" in js:
                for pid, info in js["peers"].items():
                    if pid == self.peer_id:
                        continue
                    # single-sided dialing rule to avoid duplicate connections
                    self._ensure_connected(pid, info.get("ip", "127.0.0.1"), int(info.get("port", 0)))
        except Exception as e:
            print(f"[!] join exception: {e}")

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
                        if self.peer_id < pid:
                            self._ensure_connected(pid, info.get("ip", "127.0.0.1"), int(info.get("port", 0)))
            except Exception:
                # silent retry
                pass
            time.sleep(2.0)

    # =============== P2P listener & connectors ===============
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
                        threading.Thread(target=self._handle_conn, args=(s, f"in:{addr}"), daemon=True).start()
                    except Exception:
                        break
            finally:
                try:
                    srv.close()
                except Exception:
                    pass
        threading.Thread(target=serve, daemon=True).start()

    def _ensure_connected(self, peer_key, ip, port):
        if not port:
            return
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
            # short timeout only for connect
            s.settimeout(3.0)
            s.connect((ip, port))
            s.settimeout(None)

            # remember
            with self.conns_lock:
                self.conns[peer_key] = s

            # send hello so receiver can map socket -> our peer_id
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
            # remove if present
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
            chan = js.get("chan", self.channel)
            ts = js.get("ts", now())
            print(f"\r[{frm}] {text}")
            # mirror into local UI store so the browser on this peer also sees it
            self._store_message(chan, frm, text, ts)
            return

    # =============== Message store for UI ===============
    def _ensure_channel(self, name: str):
        with self.chats_lock:
            if name not in self.chats:
                self.chats[name] = {"seq": 0, "messages": []}

    def _store_message(self, name: str, frm: str, text: str, ts: float = None):
        ts = ts if ts is not None else now()
        self._ensure_channel(name)
        with self.chats_lock:
            seq = self.chats[name]["seq"] + 1
            self.chats[name]["seq"] = seq
            self.chats[name]["messages"].append({
                "seq": seq, "from": frm, "text": text, "ts": ts
            })
            return seq

    def _get_messages_after(self, name: str, after_seq: int):
        self._ensure_channel(name)
        with self.chats_lock:
            return [m for m in self.chats[name]["messages"] if m["seq"] > after_seq]

    # =============== Sending ===============
    def send_all(self, text: str):
        payload = {"type": "msg", "chan": self.channel, "from": self.peer_id, "text": text, "ts": now()}
        raw = (json.dumps(payload) + "\n").encode("utf-8")

        # Store locally for the UI
        self._store_message(self.channel, self.peer_id, text, payload["ts"])

        # Broadcast to peers
        with self.conns_lock:
            targets = list(self.conns.values())
        for s in targets:
            try:
                s.sendall(raw)
            except Exception:
                pass

        print(f"[{self.peer_id}] {text}")

    # =============== HTTP bridge (UI) ===============
    def start_http_bridge(self):
        if not (self.bridge_host and self.bridge_port):
            return

        peer = self  # capture for the handler closure

        class Handler(BaseHTTPRequestHandler):
            server_version = "P2PBridge/1.0"

            # --- helpers ---
            def _read_body(self) -> bytes:
                try:
                    ln = int(self.headers.get("Content-Length", "0"))
                except Exception:
                    ln = 0
                if ln <= 0:
                    return b""
                return self.rfile.read(ln)

            def _form(self) -> dict:
                raw = self._read_body().decode("utf-8", errors="ignore")
                # parse application/x-www-form-urlencoded
                args = {}
                for pair in raw.split("&"):
                    if not pair:
                        continue
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                    else:
                        k, v = pair, ""
                    # minimal unquote (+ -> space handled by form on UI anyway)
                    args[k] = v.replace("+", " ")
                return args

            def _send(self, code: int, headers: dict, body: bytes):
                self.send_response(code)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _send_json(self, code: int, obj: dict, extra_headers: dict = None):
                raw = json.dumps(obj).encode("utf-8")
                headers = {"Content-Type": "application/json", "Content-Length": str(len(raw))}
                if extra_headers:
                    headers.update(extra_headers)
                self._send(code, headers, raw)

            def _require_cookie(self) -> bool:
                ck = self.headers.get("Cookie", "")
                return ("auth=true" in ck)

            # --- routing ---
            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path == "/":
                    path = "/chat.html"  # default UI page

                # static file under ui_root
                file_path = os.path.join(peer.ui_root, path.lstrip("/"))
                if not os.path.isfile(file_path):
                    body = (f"<html><body><h3>P2P Bridge for {peer.peer_id}</h3>"
                            f"<p>Try <a href='/chat.html'>/chat.html</a>.</p></body></html>").encode("utf-8")
                    return self._send(200, {"Content-Type": "text/html; charset=utf-8",
                                             "Content-Length": str(len(body))}, body)
                try:
                    with open(file_path, "rb") as f:
                        data = f.read()
                    mime = guess_mime(file_path)
                    headers = {"Content-Type": mime, "Content-Length": str(len(data))}
                    # Auto set cookie for convenience (so POSTs include Cookie)
                    if "auth=true" not in (self.headers.get("Cookie", "")):
                        headers["Set-Cookie"] = "auth=true; Path=/"
                    return self._send(200, headers, data)
                except Exception:
                    return self._send(404, {"Content-Type": "text/plain"}, b"Not found")

            def do_POST(self):
                path = self.path.split("?", 1)[0]

                # Optional login endpoint: always succeed and set cookie
                if path == "/login":
                    _ = self._form()
                    return self._send_json(200, {"ok": True}, {"Set-Cookie": "auth=true; Path=/"})

                # Enforce cookie for the rest
                if not self._require_cookie():
                    return self._send_json(403, {"ok": False, "error": "unauthorized"})

                # Parse form
                form = self._form()

                if path == "/channel/create":
                    name = (form.get("name") or "").strip() or peer.channel
                    peer._ensure_channel(name)
                    return self._send_json(200, {"ok": True, "channel": name})

                if path == "/channel/join":
                    name = (form.get("name") or "").strip() or peer.channel
                    pid  = (form.get("peer_id") or "").strip() or peer.peer_id
                    peer._ensure_channel(name)
                    # Return local knowledge of connected peers
                    with peer.conns_lock:
                        peers = {k: {"connected": True} for k in peer.conns.keys()}
                    return self._send_json(200, {"ok": True, "channel": name, "peer_id": pid, "peers": peers})

                if path == "/message":
                    name = (form.get("name") or "").strip() or peer.channel
                    pid  = (form.get("peer_id") or "").strip() or peer.peer_id
                    text = (form.get("text") or "").strip()
                    if not text:
                        return self._send_json(400, {"ok": False, "error": "empty"})
                    # Store locally and broadcast over P2P
                    peer.channel = name  # align
                    peer.send_all(text)
                    return self._send_json(200, {"ok": True})

                if path == "/sync":
                    name = (form.get("name") or "").strip() or peer.channel
                    after = 0
                    try:
                        after = int(form.get("after") or "0")
                    except Exception:
                        after = 0
                    msgs = peer._get_messages_after(name, after)
                    return self._send_json(200, {"messages": msgs})

                # Not found
                return self._send_json(404, {"ok": False, "error": "not found"})

            # Reduce noisy logging
            def log_message(self, fmt, *args):
                return

        def serve():
            addr = (self.bridge_host, int(self.bridge_port))
            httpd = ThreadingHTTPServer(addr, Handler)
            print(f"[{self.peer_id}] HTTP bridge on http://{self.bridge_host}:{self.bridge_port} (ui_root={self.ui_root})")
            try:
                httpd.serve_forever()
            except Exception:
                pass
            finally:
                try:
                    httpd.server_close()
                except Exception:
                    pass

        threading.Thread(target=serve, daemon=True).start()

    # =============== Main loop ===============
    def run(self):
        # Start TCP listener + discovery + (optional) HTTP bridge
        self.start_listener()
        self.register_and_join()
        if self.bridge_host and self.bridge_port:
            self.start_http_bridge()

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
    ap = argparse.ArgumentParser(description="Hybrid P2P chat peer with local HTTP bridge for UI")
    ap.add_argument("--server",  default="http://127.0.0.1:9000", help="Central server base URL")
    ap.add_argument("--peer",    required=True, help="Peer ID (A/B/...)")
    ap.add_argument("--channel", default="room", help="Channel name")
    ap.add_argument("--ip",      default="127.0.0.1", help="IP for other peers to dial")
    ap.add_argument("--port",    type=int, default=5001, help="P2P listen port")
    ap.add_argument("--cookie",  default="auth=true", help="Cookie for auth with central server")
    ap.add_argument("--bridge-host", default="127.0.0.1", help="Local HTTP bridge host")
    ap.add_argument("--bridge-port", type=int, default=7000, help="Local HTTP bridge port")
    ap.add_argument("--ui-root", default=".", help="Directory that contains chat.html and assets")
    args = ap.parse_args()

    P2PPeer(
        args.server, args.peer, args.channel, args.ip, args.port,
        cookie=args.cookie, bridge_host=args.bridge_host,
        bridge_port=args.bridge_port, ui_root=args.ui_root
    ).run()


if __name__ == "__main__":
    main()

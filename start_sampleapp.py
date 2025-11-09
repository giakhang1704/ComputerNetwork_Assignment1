# #
# # Copyright (C) 2025 pdnguyen of HCMC University of Technology VNU-HCM.
# # All rights reserved.
# # This file is part of the CO3093/CO3094 course,
# # and is released under the "MIT License Agreement". Please see the LICENSE
# # file that should have been included as part of this package.
# #
# # WeApRous release
# #
# # The authors hereby grant to Licensee personal permission to use
# # and modify the Licensed Source Code for the sole purpose of studying
# # while attending the course
# #


# """
# start_sampleapp
# ~~~~~~~~~~~~~~~~~

# This module provides a sample RESTful web application using the WeApRous framework.

# It defines basic route handlers and launches a TCP-based backend server to serve
# HTTP requests. The application includes a login endpoint and a greeting endpoint,
# and can be configured via command-line arguments.
# """

# import json
# import socket
# import argparse

# from daemon.weaprous import WeApRous

# PORT = 8000  # Default port

# app = WeApRous()

# @app.route('/login', methods=['POST'])
# def login(headers="guest", body="anonymous"):
#     """
#     Handle user login via POST request.

#     This route simulates a login process and prints the provided headers and body
#     to the console.

#     :param headers (str): The request headers or user identifier.
#     :param body (str): The request body or login payload.
#     """
#     print("[SampleApp] Logging in {} to {}".format(headers, body))

# @app.route('/hello', methods=['PUT'])
# def hello(headers, body):
#     """
#     Handle greeting via PUT request.

#     This route prints a greeting message to the console using the provided headers
#     and body.

#     :param headers (str): The request headers or user identifier.
#     :param body (str): The request body or message payload.
#     """
#     print("[SampleApp] ['PUT'] Hello in {} to {}".format(headers, body))

# if __name__ == "__main__":
#     # Parse command-line arguments to configure server IP and port
#     parser = argparse.ArgumentParser(prog='Backend', description='', epilog='Beckend daemon')
#     parser.add_argument('--server-ip', default='0.0.0.0')
#     parser.add_argument('--server-port', type=int, default=PORT)
 
#     args = parser.parse_args()
#     ip = args.server_ip
#     port = args.server_port

#     # Prepare and launch the RESTful application
#     app.prepare_address(ip, port)
#     app.run()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import time
from urllib.parse import parse_qs 

# Nếu package của bạn tên 'daemon', giữ nguyên import dưới:
from daemon.weaprous import WeApRous

# -----------------------------
# Trạng thái trong bộ nhớ (demo)
# -----------------------------
state = {
    "peers": {},      # peer_id -> {"ip": "...", "port": 5001, "last_seen": ts}
    "channels": {},   # chan -> {"members": set(peer_id), "messages": [ {seq, from, text, ts} ]}
    "seq": 0
}

def _parse_form(body: str) -> dict:
    """Properly parse x-www-form-urlencoded into a flat dict."""
    if not body:
        return {}
    qs = parse_qs(body, keep_blank_values=True, encoding="utf-8", errors="strict")
    # parse_qs returns lists; flatten to last item
    return {k: (v[-1] if isinstance(v, list) else v) for k, v in qs.items()}

def _require_auth(headers: dict) -> bool:
    """Yêu cầu có Cookie: auth=true (liên hệ phần 2.1)."""
    ck = headers.get("cookie", "")
    return "auth=true" in ck

# -----------------------------
# Khởi tạo app & routes
# -----------------------------
app = WeApRous()

@app.route("/login", methods=["POST"])
def login(headers, body):
    """Demo login: chấp nhận mọi username/password, yêu cầu client tự set Cookie: auth=true."""
    f = _parse_form(body)
    print("[SampleApp] Logging in {} to {}".format(headers, body))
    # Ở phiên bản HttpAdapter hiện tại, handler trả dict -> Response tự set JSON.
    # (Nếu bạn muốn set Set-Cookie header, cần sửa HttpAdapter để hỗ trợ tuple (status, headers, body))
    return {"ok": True, "hint": "Client hãy gửi Cookie: auth=true cho các API chat"}

@app.route("/peer/register", methods=["POST"])
def peer_register(headers, body):
    if not _require_auth(headers):
        return {"ok": False, "error": "Unauthorized"}
    f = _parse_form(body)
    peer_id = f.get("peer_id")
    ip = f.get("ip")
    port = f.get("port")
    if not peer_id or not ip or not port:
        return {"ok": False, "error": "Missing peer_id/ip/port"}
    try:
        port = int(port)
    except Exception:
        return {"ok": False, "error": "port must be int"}
    state["peers"][peer_id] = {"ip": ip, "port": port, "last_seen": time.time()}
    print("[SampleApp] peer_register:", state["peers"][peer_id])
    return {"ok": True, "peers": state["peers"]}

@app.route("/channel/create", methods=["POST"])
def channel_create(headers, body):
    if not _require_auth(headers):
        return {"ok": False, "error": "Unauthorized"}
    name = _parse_form(body).get("name")
    if not name:
        return {"ok": False, "error": "Missing name"}
    state["channels"].setdefault(name, {"members": set(), "messages": []})
    print("[SampleApp] channel_create:", name)
    return {"ok": True}

@app.route("/channel/join", methods=["POST"])
def channel_join(headers, body):
    if not _require_auth(headers):
        return {"ok": False, "error": "Unauthorized"}
    f = _parse_form(body)
    name = f.get("name")
    peer_id = f.get("peer_id")
    if not name or not peer_id:
        return {"ok": False, "error": "Missing name/peer_id"}
    ch = state["channels"].setdefault(name, {"members": set(), "messages": []})
    ch["members"].add(peer_id)
    # Trả danh sách peers hiện có trong kênh để client có thể (tuỳ chọn) kết nối P2P
    members = [p for p in ch["members"] if p in state["peers"]]
    peers_info = {p: state["peers"][p] for p in members}
    print("[SampleApp] channel_join:", name, "->", members)
    # set() không JSON được, trả list
    return {"ok": True, "peers": peers_info, "members": list(ch["members"])}

@app.route("/message", methods=["POST"])
def send_message(headers, body):
    if not _require_auth(headers):
        return {"ok": False, "error": "Unauthorized"}
    f = _parse_form(body)
    name = f.get("name")
    sender = f.get("peer_id")
    text = f.get("text", "")
    ch = state["channels"].get(name)
    if not ch:
        return {"ok": False, "error": "Channel not found"}
    state["seq"] += 1
    msg = {"seq": state["seq"], "from": sender, "text": text, "ts": time.time()}
    ch["messages"].append(msg)
    # (Tuỳ chọn) tại đây có thể implement server-relay đến peers qua TCP.
    print("[SampleApp] message:", msg)
    return {"ok": True, "seq": state["seq"]}

@app.route("/sync", methods=["POST", "GET"])
def sync(headers, body):
    if not _require_auth(headers):
        return {"ok": False, "error": "Unauthorized"}
    # Ở đây demo dùng form; nếu GET + query, bạn có thể tự parse headers['path'] nếu muốn
    f = _parse_form(body)
    name = f.get("name")
    after = int(f.get("after", "0"))
    ch = state["channels"].get(name, {"messages": []})
    delta = [m for m in ch["messages"] if int(m.get("seq", 0)) > after]
    return {"ok": True, "messages": delta}

@app.route("/hello", methods=["PUT"])   # hoặc ["GET","PUT"] nếu muốn test cả GET
def hello(headers, body):
    # body có thể rỗng nếu client không gửi payload
    return {
        "ok": True,
        "route": "/hello",
        "method": headers.get("x-http-method-override", "PUT"),
        "received": body or ""
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-ip", default="127.0.0.1")
    parser.add_argument("--server-port", type=int, default=9000)
    args = parser.parse_args()

    app.prepare_address(args.server_ip, args.server_port)
    app.run()

if __name__ == "__main__":
    main()

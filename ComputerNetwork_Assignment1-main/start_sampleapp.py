import argparse
import time
from urllib.parse import parse_qs 


from daemon.weaprous import WeApRous

# -----------------------------
# Trạng thái trong bộ nhớ (demo)
# -----------------------------
state = {
    "peers": {},      
    "channels": {},   
    "seq": 0
}

def _parse_form(body: str) -> dict:
    """Properly parse x-www-form-urlencoded into a flat dict."""
    if not body:
        return {}
    qs = parse_qs(body, keep_blank_values=True, encoding="utf-8", errors="strict")

    return {k: (v[-1] if isinstance(v, list) else v) for k, v in qs.items()}

def _require_auth(headers: dict) -> bool:
    """Yêu cầu có Cookie: auth=true (liên hệ phần 2.1)."""
    ck = headers.get("cookie", "")
    return "auth=true" in ck

# -----------------------------
# Khởi tạo app & routes
# -----------------------------
app = WeApRous()

@app.route("/login", methods=["POST", "PUT"])
def login(headers, body):
    """Demo login: chấp nhận mọi username/password, yêu cầu client tự set Cookie: auth=true."""
    f = _parse_form(body)
    print("[SampleApp] Logging in {} to {}".format(headers, body))
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
    # Trả danh sách peers hiện có trong kênh để client có thể kết nối P2P
    members = [p for p in ch["members"] if p in state["peers"]]
    peers_info = {p: state["peers"][p] for p in members}
    print("[SampleApp] channel_join:", name, "->", members)

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
    print("[SampleApp] message:", msg)
    return {"ok": True, "seq": state["seq"]}

@app.route("/sync", methods=["POST", "GET"])
def sync(headers, body):
    if not _require_auth(headers):
        return {"ok": False, "error": "Unauthorized"}
    f = _parse_form(body)
    name = f.get("name")
    after = int(f.get("after", "0"))
    ch = state["channels"].get(name, {"messages": []})
    delta = [m for m in ch["messages"] if int(m.get("seq", 0)) > after]
    return {"ok": True, "messages": delta}

@app.route("/hello", methods=["PUT"])  
def hello(headers, body):
    return {
        "ok": True,
        "route": "/hello",
        "method": headers.get("x-http-method-override", "PUT"),
        "received": body or ""
    }
    

@app.route("/submit-info", methods=["POST"])
def submit_info(headers, body):
    return peer_register(headers, body)

@app.route("/add-list", methods=["POST"])
def add_list(headers, body):
    return channel_create(headers, body)

@app.route("/get-list", methods=["POST"])
def get_list(headers, body):
    return channel_join(headers, body)

@app.route("/connect-peer", methods=["POST"])
def connect_peer(headers, body):
    return channel_join(headers, body)

@app.route("/broadcast-peer", methods=["POST"])
def broadcast_peer(headers, body):
    return send_message(headers, body)

@app.route("/send-peer", methods=["POST"])
def send_peer(headers, body):
    return send_message(headers, body)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-ip", default="127.0.0.1")
    parser.add_argument("--server-port", type=int, default=9000)
    args = parser.parse_args()

    app.prepare_address(args.server_ip, args.server_port)
    app.run()



if __name__ == "__main__":
    main()

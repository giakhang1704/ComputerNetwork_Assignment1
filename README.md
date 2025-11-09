
---

## 1. Test Cookie 

### 1.1. Chạy app REST (Terminal S)
```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 9000
```


### 1.2. Thiết lập cookie
**Cách A – kèm header Cookie:**
```powershell
# Đăng ký peer A
curl.exe -i -X POST http://127.0.0.1:9000/peer/register `
  -H "Content-Type: application/x-www-form-urlencoded" `
  -H "Cookie: auth=true" `
  --data "peer_id=A&ip=127.0.0.1&port=5001"

# Tạo channel "room"
curl.exe -i -X POST http://127.0.0.1:9000/channel/create `
  -H "Content-Type: application/x-www-form-urlencoded" `
  -H "Cookie: auth=true" `
  --data "name=room"

# Join channel
curl.exe -i -X POST http://127.0.0.1:9000/channel/join `
  -H "Content-Type: application/x-www-form-urlencoded" `
  -H "Cookie: auth=true" `
  --data "name=room&peer_id=A"

# Gửi tin nhắn
curl.exe -i -X POST http://127.0.0.1:9000/message `
  -H "Content-Type: application/x-www-form-urlencoded" `
  -H "Cookie: auth=true" `
  --data "name=room&peer_id=A&text=hi"

# Đọc tin nhắn
curl.exe -i -X POST http://127.0.0.1:9000/sync `
  -H "Content-Type: application/x-www-form-urlencoded" `
  -H "Cookie: auth=true" `
  --data "name=room&after=0"
```


## 2. Client–Server chat (REST)

**Ý tưởng:** Mỗi client gửi tin qua `/message`, client khác **poll** `/sync` để nhận.

### 2.1. Chạy server (Terminal S)
```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 9000
```

### 2.2. Chạy 2 client REST (Terminal A & B)
```powershell
# Terminal A
python chat_client.py --server http://127.0.0.1:9000 --peer A --channel room --port 5001

# Terminal B
python chat_client.py --server http://127.0.0.1:9000 --peer B --channel room --port 5002
```
- Lúc khởi tạo, client sẽ gọi: `/peer/register`, `/channel/create`, `/channel/join`.
- Khi gõ ở A → A `POST /message`.
- B **poll** `/sync`  → nhận tin nhắn.

---

## 3. Peer‑to‑Peer (P2P)

**Ý tưởng:** Server chỉ để **discover** (đăng ký/tìm peer). Sau khi 2 peer lập TCP trực tiếp, chat **không cần server** nữa.

### 3.1. Chạy server (Terminal S)
```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 9000
```

### 3.2. Chạy 2 peer P2P (Terminal A & B)
```powershell
# Terminal A
python p2p.py --server http://127.0.0.1:9000 --peer A --channel room --port 5001

# Terminal B
python p2p.py --server http://127.0.0.1:9000 --peer B --channel room --port 5002
```

**Kiểm thử:**
- Chat ở A → hiện ở B; chat ở B → hiện ở A.
- **Tắt server** → A & B vẫn chat (đường P2P còn sống).
---

## 4. (Tuỳ chọn) Chạy qua Proxy

### 4.1. Proxy (Terminal P)
```powershell
python start_proxy.py --server-ip 127.0.0.1 --server-port 8080
```

### 4.2. Test
```powershell
curl.exe -i http://127.0.0.1:8080/
```
Dùng proxy với client:
```powershell
python chat_client.py --server http://127.0.0.1:8080 --peer A --channel room --port 5001
python chat_client.py --server http://127.0.0.1:8080 --peer B --channel room --port 5002
```
---

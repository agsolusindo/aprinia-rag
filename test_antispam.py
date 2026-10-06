#!/usr/bin/env python3
"""Test anti-spam: 50 request cepat dari 1 IP -> harus kena 429.
Jalankan API dulu: .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8931
"""
import json, urllib.request, urllib.error

URL = "http://127.0.0.1:8931/api/chat"
HEADERS = {"Content-Type": "application/json",
           "User-Agent": "Mozilla/5.0 (Test) AntiSpamBot/1.0",
           "Origin": "https://apriniageosat.net"}

def post(msg, sid="test-sid"):
    data = json.dumps({"message": msg, "session_id": sid}).encode()
    req = urllib.request.Request(URL, data=data, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, "OK"
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:80]

def main():
    codes = {}
    for i in range(50):
        # pesan bervariasi agar tidak kena deteksi pesan identik,
        # fokus test rate limit 10/menit
        st, _ = post(f"berapa harga gps nomor {i}?")
        codes[st] = codes.get(st, 0) + 1
    print("Distribusi status:", codes)
    ok = codes.get(429, 0) >= 35 and codes.get(200, 0) <= 15
    print("RATE LIMIT TEST:", "PASS" if ok else "FAIL",
          "(harap ~10x200 lalu 429)")

    # test pesan identik -> ban
    for i in range(8):
        st, body = post("pesan spam identik test", sid="spam-sid")
    print(f"Identical-msg test: status terakhir={st} "
          f"{'PASS (banned)' if st == 429 else '(belum ban / sudah kena rate limit)'}")

    # test validasi
    st, body = post("", sid="v-sid")
    print(f"Empty msg: {st} {'PASS' if st == 400 else 'FAIL'}")
    st, body = post("x" * 600, sid="v-sid")
    print(f"Oversize msg: {st} {'PASS' if st == 400 else 'FAIL'}")
    st, body = post("klik http://a.com dan http://b.com sekarang", sid="v-sid")
    print(f"Multi-URL spam: {st} {'PASS' if st == 400 else 'FAIL'}")

if __name__ == "__main__":
    main()

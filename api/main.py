#!/usr/bin/env python3
"""Aprinia RAG Chat API — FastAPI backend.

POST /api/chat {message, session_id} -> {reply, sources, handoff_wa, cached}
POST /api/chat/stream (SSE) -> token progresif, first-token cepat

RAG: TF-IDF retrieval (retrieval.py) -> AI gateway (SG VPS via keep-alive pool).
Anti-spam: guard.py. Response cache: 24 jam, in-memory + jsonl.

Run:  .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8931
"""
import asyncio
import http.client
import json, os, re, threading, time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from retrieval import KBIndex
from guard import Guard, FALLBACK_MSG

# ---------- config ----------
GATEWAY_URL = os.environ.get("APrinia_GATEWAY_URL",
                             "http://127.0.0.1:20128/v1/chat/completions")
GATEWAY_MODEL = os.environ.get("APrinia_GATEWAY_MODEL", "rob")
GATEWAY_API_KEY = os.environ.get("APrinia_GATEWAY_KEY", "")
WA_NUMBER = "6282311162069"
WA_LINK = f"https://wa.me/{WA_NUMBER}?text=Halo%20Aprinia%20Geosat,%20saya%20mau%20konsultasi."
TURNSTILE_ENABLED = os.environ.get("APrinia_TURNSTILE", "0") == "1"  # default OFF
USAGE_LOG = Path(__file__).parent / "usage.log"
MARKER = "[HANDOFF_WA]"
HOLD = 24  # trailing buffer agar marker tidak bocor ke stream
NOTE_WA = ("\n\nUntuk penawaran resmi dan info lebih lanjut, "
           "tim kami siap membantu via WhatsApp.")
SSE_HEADERS = {"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}

OFFTOPIC_KEYWORDS = [
    "politik", "pemilu", "pilpres", "partai", "jokowi", "prabowo",
    "agama", "judi", "slot gacor", "togel", "porn", "bokep",
    "pinjaman online", "pinjol",
]
Handoff_KEYWORDS = [
    "nego", "negosiasi", "kurangin harga", "diskon", "quotation",
    "penawaran resmi", "minta penawaran", "tender", "invoice",
    "beli banyak", "jumlah besar", "reseller",
]

SYSTEM_PROMPT = """Kamu adalah SALES ENGINEER berpengalaman di Aprinia Geosat Solusindo,
toko alat GPS, survey pemetaan, drone mapping, dan telepon satelit di Indonesia.
Gaya bicara: Bahasa Indonesia yang ramah, percaya diri, spesifik, dan membantu —
seperti konsultan lapangan yang benar-benar menguasai produk.

ATURAN KERAS:
1. Jawab HANYA berdasarkan KONTEKS di bawah. Jangan mengarang harga, spesifikasi,
   atau produk yang tidak ada di konteks.
2. Setiap kali menyebut produk, WAJIB sebutkan harganya persis dari konteks.
3. Bersikap proaktif: beri rekomendasi spesifik sesuai kebutuhan user
   ("Untuk kebutuhan tambang, saya sarankan... karena...").
4. Sebutkan angka spesifikasi (akurasi, baterai, IP rating) untuk menunjukkan keahlian.
5. Jika pertanyaan di luar produk (politik, agama, dll): tolak dengan sopan,
   katakan kamu hanya bisa membantu soal produk, lalu tawarkan bantuan lain.
6. Jika user meminta NEGO HARGA, DISKON, PENAWARAN RESMI/QUOTATION, atau pembelian
   jumlah besar: jawab "Untuk itu saya sambungkan ke tim kami ya" dan akhiri
   jawaban dengan tepat: [HANDOFF_WA]
7. Jika tidak tahu jawabannya dari konteks: akui dengan jujur dan arahkan ke
   WhatsApp tim kami.
8. Jawaban maksimal 6 kalimat, padat dan jelas. Jangan bertele-tele."""

app = FastAPI(title="Aprinia RAG Chat")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://apriniageosat.net", "http://localhost:8931"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

kb = KBIndex()
guard = Guard()

# ---------- response cache (24 jam, in-memory + jsonl) ----------
CACHE_FILE = Path(__file__).parent / "reply_cache.jsonl"
CACHE_TTL = 24 * 3600
CACHE_MAX = 500
_reply_cache = {}
_cache_lock = threading.Lock()

def norm_question(msg: str) -> str:
    t = msg.lower().strip()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def _cache_load():
    try:
        now = time.time()
        n = 0
        with open(CACHE_FILE) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if now - e.get("ts", 0) > CACHE_TTL:
                    continue
                _reply_cache[e["nq"]] = e
                n += 1
        print(f"[cache] loaded {n} entries", flush=True)
    except FileNotFoundError:
        pass
    except Exception as ex:
        print(f"[cache] load gagal: {ex}", flush=True)

def _cache_rewrite_locked():
    try:
        with open(CACHE_FILE, "w") as f:
            for e in _reply_cache.values():
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    except Exception:
        pass

def cache_get(nq):
    with _cache_lock:
        e = _reply_cache.get(nq)
        if e:
            if time.time() - e["ts"] > CACHE_TTL:
                del _reply_cache[nq]
            else:
                return e
        # read-through: cek jsonl (ditulis semua worker) bila miss di memori
        e = _cache_scan_file(nq)
        if e:
            _reply_cache[nq] = e
            return e
        return None

def _cache_scan_file(nq):
    """Scan jsonl dari belakang; entri terakhir per nq yang menang."""
    try:
        now = time.time()
        with open(CACHE_FILE) as f:
            lines = f.readlines()
        for line in reversed(lines):
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("nq") != nq:
                continue
            if now - e.get("ts", 0) > CACHE_TTL:
                return None
            return e
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return None

def cache_put(nq, reply, sources, handoff, wa_link):
    with _cache_lock:
        _reply_cache[nq] = {"nq": nq, "reply": reply, "sources": sources,
                            "handoff": handoff, "wa_link": wa_link,
                            "ts": time.time()}
        try:
            with open(CACHE_FILE, "a") as f:
                f.write(json.dumps(_reply_cache[nq], ensure_ascii=False) + "\n")
        except Exception:
            pass
        if len(_reply_cache) > CACHE_MAX:
            old = sorted(_reply_cache.values(), key=lambda e: e["ts"])[:100]
            for e in old:
                _reply_cache.pop(e["nq"], None)
            _cache_rewrite_locked()

def cache_stats():
    with _cache_lock:
        return {"entries": len(_reply_cache)}

_cache_load()

# ---------- gateway keep-alive pool ----------
_gw = urlparse(GATEWAY_URL)
_GW_HOST = _gw.hostname or "127.0.0.1"
_GW_PORT = _gw.port or (443 if _gw.scheme == "https" else 80)
_GW_PATH = _gw.path or "/v1/chat/completions"
_GW_HTTPS = _gw.scheme == "https"
_pool = []
_pool_lock = threading.Lock()

def _gw_conn():
    with _pool_lock:
        if _pool:
            return _pool.pop()
    cls = http.client.HTTPSConnection if _GW_HTTPS else http.client.HTTPConnection
    return cls(_GW_HOST, _GW_PORT, timeout=75)

def _gw_release(c):
    with _pool_lock:
        if len(_pool) < 8:
            _pool.append(c)
            return
    try:
        c.close()
    except Exception:
        pass

def _gw_headers():
    h = {"Content-Type": "application/json"}
    if GATEWAY_API_KEY:
        h["Authorization"] = f"Bearer {GATEWAY_API_KEY}"
    return h

def _gw_body(system: str, context: str, user_msg: str, stream: bool) -> bytes:
    # NOTE: gateway bug — JANGAN kirim max_tokens (respons jadi kosong).
    # Panjang jawaban dikendalikan lewat system prompt (maks 6 kalimat).
    body = {
        "model": GATEWAY_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",
             "content": f"KONTEKS PRODUK:\n{context}\n\nPERTANYAAN:\n{user_msg}"},
        ],
    }
    if stream:
        body["stream"] = True
    return json.dumps(body).encode()

def _gw_request_once(body: bytes):
    """Satu percobaan POST. Return parsed JSON. Tutup koneksi bila gagal."""
    c = _gw_conn()
    try:
        c.request("POST", _GW_PATH, body, _gw_headers())
        r = c.getresponse()
        data = r.read()
        if r.status != 200:
            raise RuntimeError(f"gateway HTTP {r.status}: {data[:120]!r}")
        resp = json.loads(data)
    except Exception:
        try:
            c.close()
        except Exception:
            pass
        raise
    _gw_release(c)
    return resp

def _is_stale_conn_err(e: Exception) -> bool:
    return isinstance(e, (http.client.RemoteDisconnected,
                          ConnectionResetError, BrokenPipeError))

def call_gateway(system: str, context: str, user_msg: str) -> str:
    """Non-streaming via pooled keep-alive connection (retry 1x bila basi)."""
    body = _gw_body(system, context, user_msg, False)
    try:
        resp = _gw_request_once(body)
    except Exception as e:
        if not _is_stale_conn_err(e):
            raise
        resp = _gw_request_once(body)  # coba lagi dengan koneksi baru
    return resp["choices"][0]["message"]["content"].strip()

def _stream_once(system: str, context: str, user_msg: str, stop):
    c = _gw_conn()
    try:
        c.request("POST", _GW_PATH, _gw_body(system, context, user_msg, True),
                  _gw_headers())
        r = c.getresponse()
        if r.status != 200:
            raise RuntimeError(f"gateway HTTP {r.status}")
        while not stop.is_set():
            line = r.readline()
            if not line:
                break
            line = line.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            delta = obj.get("choices", [{}])[0].get("delta", {}).get("content")
            if delta:
                yield delta
    finally:
        try:
            c.close()
        except Exception:
            pass

def stream_gateway(system: str, context: str, user_msg: str, stop):
    """Yield token SSE dari gateway. Blocking — jalankan di thread.

    Tidak retry di tengah stream (token sudah terkirim parsial);
    koneksi basi hanya mungkin di awal sebelum token pertama.
    """
    it = _stream_once(system, context, user_msg, stop)
    try:
        first = next(it)
    except StopIteration:
        return
    except Exception as e:
        if not _is_stale_conn_err(e):
            raise
        it = _stream_once(system, context, user_msg, stop)
        try:
            first = next(it)
        except StopIteration:
            return
        log_usage("gw_retry", "stream stale-conn retry ok")
    yield first
    yield from it

# ---------- helpers ----------
def log_usage(kind: str, detail: str = ""):
    try:
        with open(USAGE_LOG, "a") as f:
            f.write(f"{datetime.now().isoformat()} {kind} {detail}\n")
    except Exception:
        pass

def is_offtopic(msg: str) -> bool:
    low = msg.lower()
    return any(k in low for k in OFFTOPIC_KEYWORDS)

def wants_handoff(msg: str) -> bool:
    low = msg.lower()
    return any(k in low for k in Handoff_KEYWORDS)

def build_context(hits):
    if not hits:
        return "(tidak ada konteks relevan ditemukan)"
    return "\n\n".join(
        f"[{h['source'].upper()}] {h['title']}\n{h['text'][:500]}"
        + (f"\nHarga: {h['price']}" if h["price"] else "")
        + (f"\nURL: {h['url']}" if h["url"] else "")
        for h in hits)

def build_sources(hits):
    return [{"title": h["title"], "url": h["url"], "price": h["price"]}
            for h in hits[:3] if h["url"]]

def finalize_reply(raw: str, msg: str):
    """Bersihkan marker, deteksi handoff. Return (reply, handoff, note_added)."""
    handoff = MARKER in raw or wants_handoff(msg)
    reply = raw.replace(MARKER, "").strip()
    note_added = False
    if handoff and "whatsapp" not in reply.lower():
        reply += NOTE_WA
        note_added = True
    return reply, handoff, note_added

def get_client_ip(req: Request) -> tuple:
    xff = req.headers.get("x-forwarded-for", "")
    direct = req.client.host if req.client else "unknown"
    if xff:
        return xff.split(",")[0].strip(), False
    return direct, direct in ("127.0.0.1", "::1")

def sse(data: dict) -> str:
    return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"

@app.get("/api/health")
def health():
    return {"ok": True, "kb": kb.stats, "guard": guard.stats(),
            "cache": cache_stats(), "turnstile": TURNSTILE_ENABLED}

# ---------- non-streaming ----------
@app.post("/api/chat")
async def chat(req: Request):
    t_start = time.perf_counter()
    client_ip, internal = get_client_ip(req)
    headers = {k.lower(): v for k, v in req.headers.items()}

    try:
        payload = await req.json()
    except Exception:
        return JSONResponse({"error": "Body harus JSON."}, status_code=400)
    msg = str(payload.get("message", "")).strip()
    session_id = str(payload.get("session_id", ""))[:64]

    ok, status, reason = guard.check(client_ip, session_id, msg, headers,
                                    internal=internal)
    if not ok:
        log_usage("blocked", f"{client_ip} {status} {reason[:40]}")
        return JSONResponse({"error": reason}, status_code=status)

    # cache hit = gratis, layani walau budget habis
    nq = norm_question(msg)
    hit = cache_get(nq)
    if hit:
        total_ms = (time.perf_counter() - t_start) * 1000
        log_usage("timing",
                  f"{client_ip} ret=0ms gw=0ms total={total_ms:.0f}ms cached=1")
        return {"reply": hit["reply"], "sources": hit["sources"],
                "handoff_wa": hit["handoff"],
                "wa_link": hit["wa_link"], "cached": True}

    if guard.budget_exceeded():
        log_usage("budget_fallback", client_ip)
        return {"reply": FALLBACK_MSG, "sources": [],
                "handoff_wa": True, "wa_link": WA_LINK, "fallback": True}

    if is_offtopic(msg):
        reply = ("Mohon maaf, saya hanya bisa membantu seputar produk kami: "
                 "GPS, alat survey, drone mapping, dan telepon satelit. "
                 "Ada yang bisa saya bantu soal itu?")
        return {"reply": reply, "sources": [], "handoff_wa": False}

    t_r = time.perf_counter()
    hits = kb.search(msg, top_k=5)
    ret_ms = (time.perf_counter() - t_r) * 1000
    ctx = build_context(hits)
    sources = build_sources(hits)

    t_g = time.perf_counter()
    try:
        raw = await asyncio.to_thread(call_gateway, SYSTEM_PROMPT, ctx, msg)
        guard.note_ai_call()
        log_usage("ai", f"{client_ip} q={len(msg)}")
    except Exception as e:
        log_usage("ai_error", f"{client_ip} {str(e)[:80]}")
        return {"reply": FALLBACK_MSG, "sources": [],
                "handoff_wa": True, "wa_link": WA_LINK, "fallback": True}
    gw_ms = (time.perf_counter() - t_g) * 1000

    reply, handoff, _ = finalize_reply(raw, msg)
    cache_put(nq, reply, sources, handoff, WA_LINK if handoff else "")
    total_ms = (time.perf_counter() - t_start) * 1000
    log_usage("timing",
              f"{client_ip} ret={ret_ms:.0f}ms gw={gw_ms:.0f}ms "
              f"total={total_ms:.0f}ms cached=0")
    return {"reply": reply, "sources": sources,
            "handoff_wa": handoff, "wa_link": WA_LINK if handoff else "",
            "cached": False}

# ---------- streaming (SSE) ----------
@app.post("/api/chat/stream")
async def chat_stream(req: Request):
    client_ip, internal = get_client_ip(req)
    headers = {k.lower(): v for k, v in req.headers.items()}

    try:
        payload = await req.json()
    except Exception:
        return JSONResponse({"error": "Body harus JSON."}, status_code=400)
    msg = str(payload.get("message", "")).strip()
    session_id = str(payload.get("session_id", ""))[:64]

    ok, status, reason = guard.check(client_ip, session_id, msg, headers,
                                    internal=internal)
    if not ok:
        return JSONResponse({"error": reason}, status_code=status)

    nq = norm_question(msg)
    hit = cache_get(nq)
    if hit:
        async def _cached_gen():
            yield sse({"type": "meta", "sources": hit["sources"],
                       "cached": True})
            yield sse({"type": "token", "text": hit["reply"]})
            yield sse({"type": "done", "handoff": hit["handoff"],
                       "wa_link": hit["wa_link"], "sources": hit["sources"],
                       "cached": True})
        log_usage("timing", f"{client_ip} stream cached=1")
        return StreamingResponse(_cached_gen(), media_type="text/event-stream",
                                 headers=SSE_HEADERS)

    if guard.budget_exceeded():
        async def _fb_gen():
            yield sse({"type": "meta", "sources": [], "cached": False})
            yield sse({"type": "token", "text": FALLBACK_MSG})
            yield sse({"type": "done", "handoff": True, "wa_link": WA_LINK,
                       "sources": [], "cached": False, "fallback": True})
        return StreamingResponse(_fb_gen(), media_type="text/event-stream",
                                 headers=SSE_HEADERS)

    if is_offtopic(msg):
        reply = ("Mohon maaf, saya hanya bisa membantu seputar produk kami: "
                 "GPS, alat survey, drone mapping, dan telepon satelit. "
                 "Ada yang bisa saya bantu soal itu?")
        async def _ot_gen():
            yield sse({"type": "meta", "sources": [], "cached": False})
            yield sse({"type": "token", "text": reply})
            yield sse({"type": "done", "handoff": False, "wa_link": "",
                       "sources": [], "cached": False})
        return StreamingResponse(_ot_gen(), media_type="text/event-stream",
                                 headers=SSE_HEADERS)

    t_start = time.perf_counter()
    t_r = time.perf_counter()
    hits = kb.search(msg, top_k=5)
    ret_ms = (time.perf_counter() - t_r) * 1000
    ctx = build_context(hits)
    sources = build_sources(hits)

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    stop = threading.Event()

    def _run():
        try:
            for tok in stream_gateway(SYSTEM_PROMPT, ctx, msg, stop):
                loop.call_soon_threadsafe(q.put_nowait, ("tok", tok))
            loop.call_soon_threadsafe(q.put_nowait, ("end", None))
        except Exception as e:
            loop.call_soon_threadsafe(q.put_nowait, ("err", str(e)[:100]))

    sender = asyncio.create_task(asyncio.to_thread(_run))

    async def gen():
        pending = ""
        raw_parts = []
        err = None
        try:
            yield sse({"type": "meta", "sources": sources, "cached": False})
            while True:
                kind, val = await q.get()
                if kind == "tok":
                    pending += val
                    if len(pending) > HOLD:
                        out = pending[:-HOLD]
                        pending = pending[-HOLD:]
                        raw_parts.append(out)
                        yield sse({"type": "token", "text": out})
                elif kind == "end":
                    break
                else:
                    err = val
                    break
        finally:
            stop.set()
            if not sender.done():
                sender.cancel()
        if err:
            log_usage("ai_error", f"{client_ip} stream {err}")
            yield sse({"type": "error",
                       "message": "Maaf, AI sedang gangguan. Coba lagi ya."})
            return
        gw_ms = (time.perf_counter() - t_start) * 1000 - ret_ms
        raw_parts.append(pending)
        reply, handoff, note_added = finalize_reply("".join(raw_parts), msg)
        tail = pending.replace(MARKER, "").strip()
        if tail:
            yield sse({"type": "token", "text": tail})
        if note_added:
            yield sse({"type": "token", "text": NOTE_WA})
        guard.note_ai_call()
        cache_put(nq, reply, sources, handoff, WA_LINK if handoff else "")
        total_ms = (time.perf_counter() - t_start) * 1000
        log_usage("timing",
                  f"{client_ip} stream ret={ret_ms:.0f}ms gw={gw_ms:.0f}ms "
                  f"total={total_ms:.0f}ms cached=0")
        log_usage("ai", f"{client_ip} q={len(msg)} stream")
        yield sse({"type": "done", "handoff": handoff,
                   "wa_link": WA_LINK if handoff else "",
                   "sources": sources, "cached": False})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers=SSE_HEADERS)

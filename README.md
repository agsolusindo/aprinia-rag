# Aprinia RAG Chatbot

Chatbot AI untuk **apriniageosat.net** (toko GPS, alat survey, drone mapping, telepon satelit).
Arsitektur: **Retrieval (TF-IDF, tanpa dependensi ML) → Generation (AI gateway lokal)**.

Widget chat MENGGANTIKAN flying WhatsApp button — AI sebagai lapisan pertama,
tombol "Lanjut ke WhatsApp" selalu tersedia untuk handoff ke manusia.

## Struktur

```
aprinia-rag/
├── crawl.py            # crawler KB (hormati rate limit 1.5 dtk/req)
├── kb/
│   ├── products.json   # hasil crawl: id, name, brand, category, price, specs, url
│   ├── buying_guides.json
│   ├── comparisons.json
│   ├── faq.json
│   ├── glossary.json
│   └── company.json
├── api/
│   ├── .venv/          # venv (fastapi + uvicorn)
│   ├── main.py         # FastAPI app
│   ├── retrieval.py    # TF-IDF retrieval (stdlib only)
│   ├── guard.py        # anti-spam & cost guard
│   └── usage.log       # log pemakaian harian (otomatis)
├── widget/
│   └── chat-widget.js  # widget vanilla JS (tanpa dependensi)
└── test_*.py           # script test
```

## Menjalankan API lokal

```bash
cd ~/workspace/aprinia-rag/api
./.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8931
```

Cek: `curl http://127.0.0.1:8931/api/health`

> Butuh AI gateway di `http://127.0.0.1:20128` (model `rob`).
> Jika gateway butuh API key: `APrinia_GATEWAY_KEY=xxx uvicorn ...`

## Endpoint

**POST /api/chat**
```json
{"message": "GPS yang cocok untuk tambang apa?", "session_id": "abc123"}
```
```json
{"reply": "...", "sources": [{"title","url","price"}],
 "handoff_wa": false, "wa_link": "https://wa.me/6282311162069?..."}
```

**GET /api/health** → status KB + statistik guard harian.

## Proteksi anti-spam (guard.py)

| Proteksi | Aturan |
|---|---|
| Rate limit IP | 10 pesan/menit, 100/jam → HTTP 429 |
| Rate limit sesi | 50 pesan/session_id → minta refresh |
| Validasi pesan | non-kosong, maks 500 karakter, tolak pola spam (link berulang, karakter acak) |
| Cost guard | maks 10.000 request AI/hari → fallback statis tanpa panggil AI |
| Deteksi bot | >5 pesan identik/10 detik dari 1 IP → ban 1 jam |
| Header check | wajib User-Agent browser + Origin/Referer apriniageosat.net (kecuali localhost) |
| Turnstile | opsional, default OFF (`APrinia_TURNSTILE=1` + sitekey di widget) |

Manusia normal tidak akan kena CAPTCHA dalam kondisi normal.

## Deploy (nanti, belum dilakukan)

1. Jalankan API di VPS (systemd, port 8931) di balik reverse proxy `https://rag.apriniageosat.net`.
   Nginx WAJIB teruskan IP asli (untuk rate limit & header check):
   `proxy_set_header X-Forwarded-For $remote_addr;`
2. Sesuaikan `API_BASE` di `widget/chat-widget.js`.
3. Tambahkan `<script src="https://rag.apriniageosat.net/widget/chat-widget.js"></script>`
   di template site + sembunyikan flying WA button lama (widget menggantikannya).

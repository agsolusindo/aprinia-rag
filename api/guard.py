#!/usr/bin/env python3
"""Anti-spam & cost guard for the Aprinia RAG chat API.
All state in-memory (single process). Transparent for normal humans:
no CAPTCHA in normal conditions.
"""
import re, time
from collections import defaultdict, deque

# ---------- tunables ----------
PER_MIN_LIMIT = 10
PER_HOUR_LIMIT = 100
SESSION_LIMIT = 50
MAX_MSG_LEN = 500
DAILY_AI_BUDGET = 10000          # max AI calls per day
BOT_IDENTICAL_WINDOW = 10        # seconds
BOT_IDENTICAL_LIMIT = 5          # identical msgs in window -> temp ban
BOT_BAN_SECONDS = 3600
ALLOWED_ORIGIN_HOST = "apriniageosat.net"

FALLBACK_MSG = ("Mohon maaf, layanan chat sedang sibuk. Tim kami akan segera membantu "
                "Anda via WhatsApp.")

URL_RE = re.compile(r"https?://|www\.", re.I)
RANDOM_RUN_RE = re.compile(r"[A-Za-z0-9]{28,}")   # long random-looking runs

def looks_spammy(msg: str) -> str | None:
    """Return reason if message looks like spam, else None."""
    if not msg or not msg.strip():
        return "Pesan kosong."
    if len(msg) > MAX_MSG_LEN:
        return f"Pesan terlalu panjang (maks {MAX_MSG_LEN} karakter)."
    urls = URL_RE.findall(msg)
    if len(urls) >= 2:
        return "Pesan mengandung terlalu banyak link."
    # hapus URL dulu, lalu cek run alfanumerik tanpa spasi (dengan spasi utuh)
    no_urls = URL_RE.sub("", msg)
    if RANDOM_RUN_RE.search(no_urls):
        return "Pesan mengandung pola mencurigakan."
    # repeated char flooding:  e.g. "aaaaaaa..."
    if re.search(r"(.)\1{15,}", msg):
        return "Pesan mengandung pengulangan karakter."
    return None

class Guard:
    def __init__(self):
        self._min = defaultdict(deque)      # ip -> deque[timestamps]
        self._hour = defaultdict(deque)
        self._sessions = defaultdict(int)   # session_id -> count
        self._recent = defaultdict(deque)   # ip -> deque[(ts, msg_hash)]
        self._banned_until = {}             # ip -> ts
        self._day = None
        self._daily_ai = 0
        self._daily_blocked = 0

    def _now(self):
        return time.time()

    def _today(self):
        return time.strftime("%Y-%m-%d")

    # ----- daily budget -----
    def _roll_day(self):
        today = self._today()
        if self._day != today:
            self._day = today
            self._daily_ai = 0
            self._daily_blocked = 0

    @property
    def daily_ai(self):
        self._roll_day()
        return self._daily_ai

    def budget_exceeded(self) -> bool:
        self._roll_day()
        return self._daily_ai >= DAILY_AI_BUDGET

    def note_ai_call(self):
        self._roll_day()
        self._daily_ai += 1

    # ----- main check -----
    def check(self, ip: str, session_id: str, msg: str, headers: dict,
              internal: bool = False):
        """Return (ok: bool, status: int, reason: str)."""
        now = self._now()

        # temp ban
        if now < self._banned_until.get(ip, 0):
            return False, 429, "Terlalu banyak permintaan. Coba lagi nanti."

        # header check (skip for internal/localhost)
        if not internal:
            ua = headers.get("user-agent", "")
            if not ua or "Mozilla/" not in ua:
                return False, 403, "Akses ditolak."
            origin = headers.get("origin", "") or headers.get("referer", "")
            if origin and ALLOWED_ORIGIN_HOST not in origin:
                return False, 403, "Akses ditolak."

        # message validation
        spam_reason = looks_spammy(msg)
        if spam_reason:
            return False, 400, spam_reason

        # per-IP rate limits
        mq = self._min[ip]
        while mq and mq[0] < now - 60:
            mq.popleft()
        if len(mq) >= PER_MIN_LIMIT:
            return False, 429, "Terlalu banyak pesan. Tunggu sebentar ya."
        hq = self._hour[ip]
        while hq and hq[0] < now - 3600:
            hq.popleft()
        if len(hq) >= PER_HOUR_LIMIT:
            return False, 429, "Batas pesan per jam tercapai. Coba lagi nanti."

        # per-session limit
        if session_id and self._sessions[session_id] >= SESSION_LIMIT:
            return False, 429, "Sesi chat mencapai batas. Silakan refresh halaman untuk sesi baru."

        # bot pattern: identical messages in short window
        rq = self._recent[ip]
        h = hash(msg.strip().lower())
        while rq and rq[0][0] < now - BOT_IDENTICAL_WINDOW:
            rq.popleft()
        same = sum(1 for _, hh in rq if hh == h)
        if same >= BOT_IDENTICAL_LIMIT:
            self._banned_until[ip] = now + BOT_BAN_SECONDS
            return False, 429, "Aktivitas mencurigakan terdeteksi. Akses dibatasi sementara."

        # record
        mq.append(now)
        hq.append(now)
        rq.append((now, h))
        if session_id:
            self._sessions[session_id] += 1
        return True, 200, "ok"

    def stats(self):
        self._roll_day()
        return {"daily_ai_calls": self._daily_ai,
                "daily_budget": DAILY_AI_BUDGET,
                "banned_ips": sum(1 for t in self._banned_until.values()
                                  if t > self._now())}

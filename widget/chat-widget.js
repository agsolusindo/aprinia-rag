/* Aprinia RAG Chat Widget — vanilla JS, tanpa dependensi.
 * Cara pakai: <script src="https://rag.apriniageosat.net/widget/chat-widget.js"></script>
 * Widget MENGGANTIKAN flying WhatsApp button: tombol hijau gaya WA membuka
 * panel AI chat; di dalam panel SELALU ada tombol "Lanjut ke WhatsApp".
 */
(function () {
  "use strict";

  /* ============ KONFIGURASI ============ */
  const API_BASE = "/rag-api";   // same-origin via nginx proxy
  const WA_LINK = "https://wa.me/6282311162069?text=Halo%20Aprinia%20Geosat,%20saya%20mau%20konsultasi.";
  const GREETING = "Halo! Mau tanya soal GPS, alat survey, atau telepon satelit?";
  const TURNSTILE_ENABLED = false;  // default OFF; aktifkan jika serangan spam berat
  const TURNSTILE_SITEKEY = "";     // isi jika TURNSTILE_ENABLED = true


  /* Sembunyikan flying WhatsApp button bawaan site (digantikan widget ini) */
  function hideLegacyWaBtn() {
    document.querySelectorAll('.floating-whatsapp-btn').forEach(function (el) {
      el.style.display = 'none';
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', hideLegacyWaBtn);
  } else { hideLegacyWaBtn(); }
  new MutationObserver(hideLegacyWaBtn).observe(document.documentElement, { childList: true, subtree: true });

  const SESSION_KEY = "aprinia_chat_sid";
  let sessionId = sessionStorage.getItem(SESSION_KEY);
  if (!sessionId) {
    sessionId = "s" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    sessionStorage.setItem(SESSION_KEY, sessionId);
  }

  /* ============ CSS ============ */
  const CSS = `
  #aprinia-chat-btn{position:fixed;right:20px;bottom:20px;width:60px;height:60px;border-radius:50%;
    background:#25D366;border:none;cursor:pointer;z-index:999998;display:flex;align-items:center;
    justify-content:center;box-shadow:0 4px 14px rgba(0,0,0,.25);transition:transform .15s}
  #aprinia-chat-btn:hover{transform:scale(1.06)}
  #aprinia-chat-btn svg{width:32px;height:32px;fill:#fff}
  #aprinia-chat-panel{position:fixed;right:20px;bottom:92px;width:370px;max-width:calc(100vw - 40px);
    height:520px;max-height:calc(100vh - 130px);background:#fff;border-radius:14px;z-index:999999;
    display:none;flex-direction:column;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,.25);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
  #aprinia-chat-panel.open{display:flex}
  #aprinia-chat-head{background:#075E54;color:#fff;padding:12px 14px;display:flex;align-items:center;gap:10px}
  #aprinia-chat-head .ava{width:38px;height:38px;border-radius:50%;background:#25D366;display:flex;
    align-items:center;justify-content:center;font-size:20px}
  #aprinia-chat-head .t1{font-weight:700;font-size:14px}
  #aprinia-chat-head .t2{font-size:11px;opacity:.85}
  #aprinia-chat-head .x{margin-left:auto;background:none;border:none;color:#fff;font-size:20px;cursor:pointer}
  #aprinia-chat-msgs{flex:1;overflow-y:auto;padding:12px;background:#ECE5DD;display:flex;flex-direction:column;gap:8px}
  .amsg{max-width:82%;padding:8px 12px;border-radius:10px;font-size:14px;line-height:1.45;word-wrap:break-word;white-space:pre-wrap}
  .amsg.bot{background:#fff;align-self:flex-start;border-top-left-radius:2px}
  .amsg.user{background:#DCF8C6;align-self:flex-end;border-top-right-radius:2px}
  .amsg.typing{color:#888;font-style:italic}
  .awa-btn{display:inline-block;margin-top:8px;background:#25D366;color:#fff !important;text-decoration:none;
    padding:8px 14px;border-radius:20px;font-size:13px;font-weight:700}
  #aprinia-chat-wa-bar{padding:8px 12px;background:#fff;border-top:1px solid #eee;text-align:center}
  #aprinia-chat-wa-bar a{display:inline-block;background:#25D366;color:#fff;text-decoration:none;
    padding:8px 18px;border-radius:20px;font-size:13px;font-weight:700}
  #aprinia-chat-form{display:flex;border-top:1px solid #ddd;background:#F0F0F0;padding:8px}
  #aprinia-chat-input{flex:1;border:none;border-radius:20px;padding:10px 14px;font-size:14px;outline:none}
  #aprinia-chat-send{background:#25D366;border:none;border-radius:50%;width:42px;height:42px;margin-left:8px;
    cursor:pointer;display:flex;align-items:center;justify-content:center}
  #aprinia-chat-send svg{width:20px;height:20px;fill:#fff}
  @media(max-width:480px){#aprinia-chat-panel{right:10px;bottom:88px}}`;

  const style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);

  /* ============ HTML ============ */
  const CHAT_SVG = '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5.1-1.3A10 10 0 1 0 12 2zm5.4 14.1c-.2.6-1.3 1.2-1.8 1.2-.5.1-1 .2-3.4-.7-2.9-1.2-4.7-4.1-4.9-4.3-.1-.2-1.1-1.5-1.1-2.9s.7-2 1-2.3c.2-.3.5-.3.7-.3h.5c.2 0 .4 0 .6.5l.9 2.1c.1.2.1.4 0 .6l-.4.6-.5.5c-.2.2-.3.4-.1.7.2.3.9 1.5 2 2.4 1.4 1.2 2.5 1.6 2.9 1.8.3.2.5.1.7-.1l1-1.2c.2-.3.4-.2.7-.1l2 1c.3.1.5.2.6.4 0 .1 0 .7-.2 1.3z"/></svg>';
  const SEND_SVG = '<svg viewBox="0 0 24 24"><path d="M2 21l21-9L2 3v7l15 2-15 2z"/></svg>';

  const btn = document.createElement("button");
  btn.id = "aprinia-chat-btn";
  btn.setAttribute("aria-label", "Chat dengan kami");
  btn.innerHTML = CHAT_SVG;

  const panel = document.createElement("div");
  panel.id = "aprinia-chat-panel";
  panel.innerHTML = `
    <div id="aprinia-chat-head">
      <div class="ava">🧭</div>
      <div><div class="t1">Aprinia Assistant</div><div class="t2">Online — siap membantu</div></div>
      <button class="x" aria-label="Tutup">×</button>
    </div>
    <div id="aprinia-chat-msgs"></div>
    <div id="aprinia-chat-wa-bar">
      <a href="${WA_LINK}" target="_blank" rel="noopener">💬 Lanjut ke WhatsApp</a>
    </div>
    <form id="aprinia-chat-form">
      <input id="aprinia-chat-input" type="text" placeholder="Tulis pertanyaan..." autocomplete="off" maxlength="500"/>
      <button id="aprinia-chat-send" type="submit" aria-label="Kirim">${SEND_SVG}</button>
    </form>`;

  document.body.appendChild(btn);
  document.body.appendChild(panel);

  const msgs = panel.querySelector("#aprinia-chat-msgs");
  const form = panel.querySelector("#aprinia-chat-form");
  const input = panel.querySelector("#aprinia-chat-input");

  btn.addEventListener("click", () => {
    panel.classList.toggle("open");
    if (panel.classList.contains("open") && !msgs.children.length) {
      addMsg("bot", GREETING);
    }
  });
  panel.querySelector(".x").addEventListener("click", () => panel.classList.remove("open"));

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function addMsg(who, text, withWaBtn) {
    const d = document.createElement("div");
    d.className = "amsg " + who;
    d.innerHTML = esc(text);
    if (withWaBtn) {
      const a = document.createElement("a");
      a.className = "awa-btn";
      a.href = WA_LINK;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = "💬 Lanjut ke WhatsApp";
      d.appendChild(document.createElement("br"));
      d.appendChild(a);
    }
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
    return d;
  }

  function addWaBtnTo(el) {
    const a = document.createElement("a");
    a.className = "awa-btn";
    a.href = WA_LINK;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = "💬 Lanjut ke WhatsApp";
    el.appendChild(document.createElement("br"));
    el.appendChild(a);
    msgs.scrollTop = msgs.scrollHeight;
  }

  /* Non-streaming fallback (dipakai bila SSE gagal) */
  async function sendNonStream(text, typing, tsToken) {
    const res = await fetch(API_BASE + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sessionId,
                             turnstile_token: tsToken || undefined }),
    });
    const data = await res.json();
    typing.remove();
    if (!res.ok) {
      addMsg("bot", data.error || "Maaf, terjadi gangguan. Coba lagi ya.");
      return;
    }
    addMsg("bot", data.reply || "Maaf, saya belum paham. Bisa diulangi?",
           !!data.handoff_wa);
  }

  /* Streaming SSE: render token progresif; fallback ke non-stream bila gagal */
  async function sendStream(text, typing, tsToken) {
    let gotToken = false;
    try {
    const res = await fetch(API_BASE + "/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sessionId,
                             turnstile_token: tsToken || undefined }),
    });
    if (!res.ok || !res.body || !res.body.getReader) {
      throw new Error("stream tidak tersedia");
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "", acc = "", botEl = null, handoff = false, sawDone = false;
    const ensureBot = () => {
      if (!botEl) { typing.remove(); botEl = addMsg("bot", ""); }
      return botEl;
    };
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const line = raw.split("\n").filter(function (l) {
          return l.indexOf("data:") === 0;
        })[0];
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line.slice(5).trim()); }
        catch (e) { continue; }
        if (ev.type === "token") {
          gotToken = true;
          acc += ev.text;
          ensureBot().textContent = acc;
          msgs.scrollTop = msgs.scrollHeight;
        } else if (ev.type === "done") {
          handoff = !!ev.handoff;
          sawDone = true;
        } else if (ev.type === "error") {
          throw new Error(ev.message || "AI gangguan");
        }
      }
    }
    try { reader.cancel(); } catch (e) {}
    if (!sawDone) throw new Error("stream tidak lengkap");
    typing.remove();
    if (!botEl) {
      addMsg("bot", "Maaf, saya belum paham. Bisa diulangi?");
      return;
    }
    if (handoff) addWaBtnTo(botEl);
    } catch (e) {
      e.streamPartial = gotToken;
      throw e;
    }
  }

  async function sendMsg(text) {
    addMsg("user", text);
    const typing = addMsg("bot", "🔍 Mencari produk yang cocok...", false);
    typing.classList.add("typing");
    // Indikator progres bertahap selagi menunggu AI (murni sisi klien)
    const _t0 = Date.now();
    const _stages = [[3000, "📋 Menyusun rekomendasi..."], [10000, "\u270D\uFE0F Hampir selesai..."]];
    let _si = 0;
    const _timer = setInterval(function () {
      if (!typing.isConnected) { clearInterval(_timer); return; }
      const _el = Date.now() - _t0;
      while (_si < _stages.length && _el >= _stages[_si][0]) {
        if (typing.isConnected) typing.textContent = _stages[_si][1];
        _si++;
      }
    }, 500);
    try {
      // Turnstile hook (default OFF)
      let tsToken = "";
      if (TURNSTILE_ENABLED && window.turnstile) {
        tsToken = await new Promise((res) => window.turnstile.execute(function (t) { res(t); }));
      }
      try {
        await sendStream(text, typing, tsToken);
      } catch (se) {
        if (se && se.streamPartial) {
          // token sudah mengalir lalu putus: biarkan teks parsial + info
          addMsg("bot", "⚠️ Koneksi terputus di tengah. Coba kirim ulang ya.");
        } else {
          // belum ada token keluar: fallback ke non-stream penuh
          await sendNonStream(text, typing, tsToken);
        }
      }
    } catch (e) {
      if (typing.isConnected) typing.remove();
      addMsg("bot", "Koneksi bermasalah. Silakan coba lagi atau hubungi kami via WhatsApp.", true);
    } finally {
      clearInterval(_timer);
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const v = input.value.trim();
    if (!v) return;
    input.value = "";
    sendMsg(v);
  });
})();

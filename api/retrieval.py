#!/usr/bin/env python3
"""Retrieval layer: pure-Python TF-IDF + keyword boost over the Aprinia KB.
No external deps (no sklearn needed). Loads once at startup.
"""
import hashlib, json, math, pickle, re, time
from pathlib import Path
from collections import Counter

KB = Path(__file__).parent.parent / "kb"
IDX_PKL = KB / "tfidf_index.pkl"
KB_FILES = ["products.json", "buying_guides.json", "comparisons.json",
            "faq.json", "glossary.json", "company.json"]

def _kb_fingerprint() -> str:
    """md5 dari nama+ukuran+mtime file KB — untuk invalidasi pickle."""
    h = hashlib.md5()
    for name in KB_FILES:
        p = KB / name
        try:
            st = p.stat()
            h.update(f"{name}:{st.st_size}:{st.st_mtime_ns}".encode())
        except OSError:
            h.update(f"{name}:missing".encode())
    return h.hexdigest()

def tokenize(text: str):
    text = text.lower()
    # keep alphanumerics; split model numbers like "gpsmap" "67" fine
    return re.findall(r"[a-z0-9]+", text)

# pertanyaan yang meminta saran/rekomendasi/perbandingan
# (izinkan sufiks Bahasa Indonesia: bedanya, dibandingkan, dll)
ADVICE_RE = re.compile(
    r"\b(beda|banding|cocok|rekomend|saran|pilih|mana|terbaik|bagus|"
    r"vs)\w*")

class KBIndex:
    def __init__(self):
        self.docs = []          # {id, title, text, source, url, price}
        t0 = time.perf_counter()
        if self._load_pickle():
            print(f"[kb] index dari pickle "
                  f"({(time.perf_counter()-t0)*1000:.0f}ms)", flush=True)
            return
        self._load()
        self._build_tfidf()
        self._save_pickle()
        print(f"[kb] index dibangun "
              f"({(time.perf_counter()-t0)*1000:.0f}ms)", flush=True)

    def _load_pickle(self) -> bool:
        try:
            with open(IDX_PKL, "rb") as f:
                blob = pickle.load(f)
            if blob.get("fp") != _kb_fingerprint():
                return False
            self.docs = blob["docs"]
            self._tf = blob["tf"]
            self._idf = blob["idf"]
            self._norms = blob["norms"]
            return True
        except Exception:
            return False

    def _save_pickle(self):
        try:
            with open(IDX_PKL, "wb") as f:
                pickle.dump({"fp": _kb_fingerprint(), "docs": self.docs,
                             "tf": self._tf, "idf": self._idf,
                             "norms": self._norms}, f,
                            protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as e:
            print(f"[kb] pickle gagal disimpan: {e}", flush=True)

    # ---------- loading ----------
    def _add(self, doc_id, title, text, source, url="", price=""):
        full = f"{title} {text}"
        if price:
            full += f" {price}"
        self.docs.append({"id": doc_id, "title": title, "text": text,
                          "source": source, "url": url, "price": price,
                          "_full": full})

    def _load(self):
        kb = KB
        prods = json.load(open(kb / "products.json"))
        for p in prods:
            self._add("prod:" + p["id"], p["name"],
                      f"Brand: {p.get('brand','')}. Kategori: {p.get('category','')}. "
                      f"Harga: {p.get('price','-')}. Spesifikasi: {p.get('specs','')}",
                      "produk", p.get("url", ""), p.get("price", ""))
        for g in json.load(open(kb / "buying_guides.json")):
            self._add("guide:" + g["category"], "Panduan: " + g["category"],
                      g["guide"], "panduan")
        for c in json.load(open(kb / "comparisons.json")):
            parts = []
            for it in c["items"]:
                parts.append(f"{it['name']} ({it.get('price','-')}): "
                             f"Kelebihan: {'; '.join(it.get('pros', []))}. "
                             f"Kekurangan: {'; '.join(it.get('cons', []))}.")
            rekom = "; ".join(f"{k}: {v}" for k, v in c.get("rekomendasi", {}).items())
            self._add("cmp:" + c["title"], "Perbandingan: " + c["title"],
                      " | ".join(parts) + " Rekomendasi: " + rekom, "perbandingan")
        for f in json.load(open(kb / "faq.json")):
            q = f.get("question") or f.get("page", "")
            a = f.get("answer") or f.get("text", "")
            self._add("faq:" + q[:40], "FAQ: " + q, a, "faq", f.get("url", ""))
        for g in json.load(open(kb / "glossary.json")):
            self._add("glo:" + g["istilah"], "Istilah: " + g["istilah"],
                      g["penjelasan"], "glosarium")
        comp = json.load(open(kb / "company.json"))["company"]
        self._add("company:profil", "Profil " + comp["name"],
                  f"{comp['tagline']}. Layanan: {'; '.join(comp['services'])}. "
                  f"Keunggulan: {'; '.join(comp['advantages'])}. "
                  f"Segmen: {'; '.join(comp['target_segments'])}. "
                  f"Kontak/WhatsApp: {comp['whatsapp']}.", "perusahaan",
                  comp["website"])

    # ---------- TF-IDF ----------
    def _build_tfidf(self):
        N = len(self.docs)
        df = Counter()
        self._tf = []
        for d in self.docs:
            toks = tokenize(d["_full"])
            tf = Counter(toks)
            self._tf.append(tf)
            for t in tf:
                df[t] += 1
        self._idf = {t: math.log((N + 1) / (df_t + 1)) + 1.0
                     for t, df_t in df.items()}
        self._norms = []
        for tf in self._tf:
            n = math.sqrt(sum((c * self._idf[t]) ** 2 for t, c in tf.items()))
            self._norms.append(n or 1.0)

    def _vec(self, text):
        tf = Counter(tokenize(text))
        return {t: c * self._idf.get(t, 1.0) for t, c in tf.items()}

    # ---------- search ----------
    def search(self, query: str, top_k: int = 5):
        qv = self._vec(query)
        qn = math.sqrt(sum(v * v for v in qv.values())) or 1.0
        qtoks = set(tokenize(query))
        # pertanyaan saran/advice -> prioritaskan panduan & perbandingan
        advice_q = bool(ADVICE_RE.search(query.lower()))
        scored = []
        for i, d in enumerate(self.docs):
            dot = sum(qv.get(t, 0.0) * self._tf[i].get(t, 0) * self._idf.get(t, 1.0)
                      for t in qv)
            cos = dot / (qn * self._norms[i])
            # keyword boost: title token overlap + exact phrase hits
            title_toks = set(tokenize(d["title"]))
            overlap = len(qtoks & title_toks)
            boost = 0.0
            if overlap:
                boost += 0.25 * overlap
            # exact product-name-ish phrase boost
            low_q, low_t = query.lower(), d["title"].lower()
            for w in qtoks:
                if len(w) > 3 and w in low_t:
                    boost += 0.05
            score = cos + boost
            if advice_q and d["source"] in ("panduan", "perbandingan"):
                score += 0.35
            if score > 0.01:
                scored.append((score, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, d in scored[:top_k]:
            out.append({"id": d["id"], "title": d["title"], "text": d["text"][:600],
                        "source": d["source"], "url": d["url"], "price": d["price"],
                        "score": round(score, 3)})
        return out

    @property
    def stats(self):
        return {"docs": len(self.docs),
                "products": sum(1 for d in self.docs if d["id"].startswith("prod:"))}

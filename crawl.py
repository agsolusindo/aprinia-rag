#!/usr/bin/env python3
"""Crawl apriniageosat.net: products from sitemap + general info pages.
Respects rate limits: 1 request per 1.5s, single-threaded.
Output: kb/products.json, kb/faq.json
"""
import json, re, time, sys
import urllib.request
from html import unescape
from pathlib import Path

BASE = "https://apriniageosat.net"
KB = Path(__file__).parent / "kb"
HEADERS = {"User-Agent": "Mozilla/5.0 (ApriniaRAG-KB-Builder; contact via site admin)"}

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")

def strip_tags(html):
    # crude text extraction
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    html = unescape(html)
    return re.sub(r"\s+", " ", html).strip()

def get_sitemap_urls():
    xml = fetch(BASE + "/sitemap.xml")
    locs = re.findall(r"<loc>(https?://[^<]+)</loc>", xml)
    return locs

def parse_product(html, url):
    """Parse a product page. Site is DB-driven; extract from meta + visible text."""
    text = strip_tags(html)
    # name: from og:title or <title>
    m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html) or \
        re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    name = m.group(1).strip() if m else ""
    name = re.sub(r"\s*\|\s*Aprinia.*$", "", name).strip()
    # price: Rp X.XXX.XXX
    prices = re.findall(r"Rp\s*([\d\.,]+)", text)
    price = prices[0] if prices else ""
    # brand: known brands
    brand = ""
    for b in ["Garmin", "Thuraya", "Iridium", "Inmarsat", "Topcon", "Sokkia",
              "Gintec", "Alpha Geo", "AlphaGeo", "ALPHA", "Hi-Target", "CHC",
              "South", "Trimble", "Leica", "Stonex", "Ruide", "KOLIDA", "FOIF"]:
        if re.search(r"\b" + re.escape(b) + r"\b", name + " " + text[:500], re.I):
            brand = b.upper().replace("ALPHA GEO", "ALPHA GEO")
            break
    # category from URL slug keywords
    slug = url.split("/produk/")[-1]
    category = "Lainnya"
    if re.search(r"gps|garmin|etrex|montana", slug, re.I): category = "GPS Handheld"
    elif re.search(r"total-station|theodolite", slug, re.I): category = "Total Station"
    elif re.search(r"geodetik|gnss|rtk", slug, re.I): category = "GPS Geodetik"
    elif re.search(r"thuraya|iridium|inmarsat|satelit|satellite|phone", slug, re.I): category = "Telepon Satelit"
    elif re.search(r"drone", slug, re.I): category = "Drone Mapping"
    elif re.search(r"laser|level|waterpass", slug, re.I): category = "Alat Ukur"
    # specs: meta description + first ~600 chars of body text after name
    mdesc = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html)
    specs = (mdesc.group(1).strip() if mdesc else "")
    if len(specs) < 100:
        # fallback: body snippet
        body = text
        idx = body.find(name[:30]) if name else 0
        specs = body[max(0, idx):idx + 700].strip()
    specs = specs[:800]
    return {
        "id": slug,
        "name": name,
        "brand": brand,
        "category": category,
        "price": "Rp " + price if price else "",
        "specs": specs,
        "url": url,
    }

def main():
    KB.mkdir(parents=True, exist_ok=True)
    urls = get_sitemap_urls()
    product_urls = [u for u in urls if "/produk/" in u]
    print(f"sitemap: {len(urls)} urls, {len(product_urls)} produk", flush=True)

    products = []
    for i, u in enumerate(product_urls):
        try:
            html = fetch(u)
            p = parse_product(html, u)
            if p["name"]:
                products.append(p)
            print(f"[{i+1}/{len(product_urls)}] {p['name'][:60]} | {p['price']}", flush=True)
        except Exception as e:
            print(f"[{i+1}/{len(product_urls)}] GAGAL {u}: {e}", flush=True)
        time.sleep(1.5)  # rate limit

    with open(KB / "products.json", "w") as f:
        json.dump(products, f, ensure_ascii=False, indent=1)
    print(f"\nTersimpan: {len(products)} produk -> kb/products.json", flush=True)

    # FAQ / info umum
    faq = []
    for page, label in [("/tentang-kami", "Tentang"), ("/kontak", "Kontak")]:
        try:
            html = fetch(BASE + page)
            text = strip_tags(html)
            # cari info kunci
            faq.append({"page": label, "url": BASE + page, "text": text[:1500]})
            print(f"FAQ {label}: {len(text)} chars", flush=True)
        except Exception as e:
            print(f"FAQ {label} gagal: {e}", flush=True)
        time.sleep(1.5)
    # info statis dari homepage (garansi, pengiriman)
    faq.append({"page": "Layanan", "url": BASE,
                "text": "Produk Original 100% Bergaransi. Stok Alat Survey Tersedia Lengkap. "
                        "Konsultasi Proyek Gratis & Profesional. Pengiriman Cepat Seluruh Indonesia. "
                        "Konsultasi via WhatsApp tersedia di website."})
    with open(KB / "faq.json", "w") as f:
        json.dump(faq, f, ensure_ascii=False, indent=1)
    print(f"Tersimpan: {len(faq)} entri FAQ -> kb/faq.json", flush=True)

if __name__ == "__main__":
    main()

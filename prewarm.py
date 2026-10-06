#!/usr/bin/env python3
"""Pre-warm response cache chatbot Aprinia: kirim 40 pertanyaan umum via /api/chat.
Jalankan di VPS Aprinia (localhost). Sequential, retry 3x saat gateway flaky.
"""
import json, time, urllib.request

API = "http://127.0.0.1:8931/api/chat"

QUESTIONS = [
    # --- harga produk populer ---
    "Berapa harga Garmin GPSMAP 67?",
    "Berapa harga Garmin eTrex SE?",
    "Berapa harga Garmin Montana 710?",
    "Berapa harga Garmin Montana 760i?",
    "Berapa harga Garmin GPSMAP H1?",
    "Berapa harga Garmin inReach Mini 2?",
    "Berapa harga Garmin GPSMAP 65s?",
    "Berapa harga total station Sokkia iM-65?",
    "Berapa harga total station Topcon GM-65?",
    "Berapa harga total station Topcon GM-62?",
    "Berapa harga Thuraya XT-LITE?",
    "Berapa harga Inmarsat IsatPhone 2?",
    "Berapa harga drone DJI Matrice 4T?",
    "Berapa harga GPS geodetik CHCNAV i73+?",
    # --- rekomendasi per kebutuhan ---
    "GPS yang cocok untuk pertambangan apa? budget 10 juta",
    "Rekomendasi GPS handheld untuk hiking",
    "Total station yang bagus untuk konstruksi gedung",
    "Telepon satelit untuk daerah terpencil yang bagus apa?",
    "GPS untuk survei kebun sawit yang cocok apa?",
    "Alat ukur untuk proyek jalan tol",
    "GPS untuk nelayan dan kapal",
    "Rekomendasi drone untuk pemetaan lahan",
    "GPS geodetik untuk pengukuran tanah",
    "Alat yang cocok untuk tim SAR",
    # --- perbandingan ---
    "Apa beda Garmin eTrex SE dan GPSMAP 67?",
    "Bedanya GPSMAP 67 dan Montana 710 apa?",
    "Iridium vs Thuraya bagusan mana?",
    "Total station 2 detik vs 5 detik bedanya apa?",
    "Drone mapping vs GPS geodetik untuk pemetaan, pilih mana?",
    # --- layanan / toko ---
    "Apakah produk di Aprinia original?",
    "Garansi produk berapa lama?",
    "Apakah bisa kirim ke luar Jawa?",
    "Metode pembayaran apa saja yang tersedia?",
    "Bagaimana cara order atau beli?",
    "Apakah ada penawaran resmi untuk perusahaan?",
    "Kontak WhatsApp Aprinia berapa?",
    "Jam operasional toko?",
    "Lokasi toko Aprinia di mana?",
    "Apakah ada training penggunaan alat?",
]

def ask(q, attempt=1):
    body = json.dumps({"message": q, "session_id": "prewarm"}).encode()
    req = urllib.request.Request(API, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read())
        dt = time.time() - t0
        return d.get("cached"), dt, None
    except Exception as e:
        dt = time.time() - t0
        if attempt < 3:
            time.sleep(5)
            return ask(q, attempt + 1)
        return None, dt, str(e)[:80]

def main():
    ok = cached = 0
    t_start = time.time()
    for i, q in enumerate(QUESTIONS, 1):
        c, dt, err = ask(q)
        status = "CACHED" if c else ("MISS" if c is False else "ERROR")
        if err:
            print(f"[{i}/{len(QUESTIONS)}] {dt:5.1f}s {status} {err} :: {q[:45]}", flush=True)
        else:
            print(f"[{i}/{len(QUESTIONS)}] {dt:5.1f}s {status} :: {q[:45]}", flush=True)
            ok += 1
            if c:
                cached += 1
        time.sleep(2)
    print(f"SELESAI: {ok}/{len(QUESTIONS)} ok, {cached} cached, "
          f"total {time.time()-t_start:.0f}s")

if __name__ == "__main__":
    main()

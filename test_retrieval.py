#!/usr/bin/env python3
"""Test akurasi retrieval: 5 pertanyaan contoh -> cek top-1/top-3 relevan."""
import sys
sys.path.insert(0, "/home/hatch/workspace/aprinia-rag/api")
from retrieval import KBIndex

CASES = [
    ("GPS yang cocok untuk tambang apa?",
     ["gps", "garmin", "tambang", "profesional"]),
    ("Berapa harga Garmin GPSMAP 67?",
     ["gpsmap 67", "9.000.000"]),
    ("Apa bedanya total station 2 detik dan 5 detik?",
     ["akurasi", "detik", "total station"]),
    ("Telepon satelit yang jangkauannya global apa?",
     ["iridium", "global"]),
    ("Apakah produk bergaransi dan original?",
     ["garansi", "original"]),
    ("Apa itu multi-band?",
     ["multi-band", "frekuensi"]),
]

def main():
    kb = KBIndex()
    print(f"KB docs: {kb.stats['docs']}, produk: {kb.stats['products']}\n")
    passed = 0
    for q, keywords in CASES:
        hits = kb.search(q, top_k=3)
        top_text = " ".join(h["title"] + " " + h["text"] for h in hits).lower()
        ok = all(k.lower() in top_text for k in keywords)
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'} | Q: {q}")
        for h in hits:
            print(f"       [{h['score']:.2f}] ({h['source']}) {h['title'][:70]}")
        if not ok:
            missing = [k for k in keywords if k.lower() not in top_text]
            print(f"       !! keyword hilang: {missing}")
        print()
    print(f"HASIL: {passed}/{len(CASES)} PASS")

if __name__ == "__main__":
    main()

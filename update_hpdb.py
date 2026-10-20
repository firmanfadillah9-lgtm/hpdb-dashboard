"""
update_hpdb.py
--------------
Rangkaian lengkap pembaruan data HPDB, sekali jalan.

Menggantikan run_hpdb.py yang sudah usang (masih mencari format lama
homepass_linknet_report_daily_*.xlsx dan memanggil sync_hpdb.py dengan
argumen posisi yang kini ditolak argparse).

Langkah:
  1. sync_hpdb.py          HPDB_B2S/.xlsb + HPDB_G2A/.xlsb -> addhp.duckdb   (~10 menit)
  2. track_status.py       catat perubahan status harian (untuk Monthly Progress)
  3. export_parquet.py     addhp.duckdb -> data/hpdb.parquet
  4. export_coords_bulk.py koordinat untuk peta Cek Eligibilitas
  5. release_upload.py     unggah hpdb.parquet ke release hpdb-dashboard
  6. push_status.py        unggah status_history.parquet
  7. push_coords_bulk.py   unggah hpdb_coords_bulk.parquet

Cara pakai:
    python update_hpdb.py                 # semua langkah
    python update_hpdb.py --tanpa-upload  # sampai langkah 4 saja (offline)
    python update_hpdb.py --lanjut        # lewati sync, mulai dari langkah 2
"""
import os
import sys
import time
import subprocess
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

LANGKAH = [
    ("sync_hpdb.py",          [], "Sync .xlsb -> addhp.duckdb",        "sync"),
    ("track_status.py",       [], "Catat perubahan status harian",     "olah"),
    ("export_parquet.py",     [], "Export -> data/hpdb.parquet",       "olah"),
    ("export_coords_bulk.py", [], "Export koordinat bulk",             "olah"),
    ("release_upload.py",     [os.path.join(HERE, "data", "hpdb.parquet")],
                                 "Upload hpdb.parquet",                "upload"),
    ("push_status.py",        [], "Upload status_history.parquet",     "upload"),
    ("push_coords_bulk.py",   [], "Upload hpdb_coords_bulk.parquet",   "upload"),
]


def jalankan(skrip, args, judul, n, total):
    print(f"\n{'='*70}")
    print(f"  [{n}/{total}] {judul}")
    print(f"  {skrip} {' '.join(args)}")
    print("=" * 70)
    if not os.path.exists(os.path.join(HERE, skrip)):
        print(f"  [LEWAT] {skrip} tidak ada di folder ini")
        return None
    t = time.time()
    r = subprocess.run([PY, skrip, *args], cwd=HERE, env=ENV)
    d = (time.time() - t) / 60
    if r.returncode == 0:
        print(f"\n  [OK] selesai dalam {d:.1f} menit")
        return True
    print(f"\n  [GAGAL] kode keluar {r.returncode}  (setelah {d:.1f} menit)")
    return False


def main():
    tanpa_upload = "--tanpa-upload" in sys.argv
    lanjut = "--lanjut" in sys.argv

    tugas = [x for x in LANGKAH
             if not (lanjut and x[3] == "sync")
             and not (tanpa_upload and x[3] == "upload")]

    mulai = time.time()
    print("=" * 70)
    print("  UPDATE DATA HPDB")
    print(f"  {datetime.now():%Y-%m-%d %H:%M:%S}   |   {len(tugas)} langkah")
    print("=" * 70)

    hasil = []
    for i, (skrip, args, judul, _) in enumerate(tugas, 1):
        ok = jalankan(skrip, args, judul, i, len(tugas))
        hasil.append((judul, ok))
        # Langkah sync dan export adalah fondasi; kalau gagal, hentikan.
        if ok is False and skrip in ("sync_hpdb.py", "export_parquet.py"):
            print("\n  Langkah fondasi gagal — rangkaian dihentikan.")
            break

    print("\n" + "=" * 70)
    print("  RINGKASAN")
    print("=" * 70)
    for judul, ok in hasil:
        tanda = "OK    " if ok else ("LEWAT " if ok is None else "GAGAL ")
        print(f"  {tanda} {judul}")
    print(f"\n  Total waktu: {(time.time()-mulai)/60:.1f} menit")

    if all(ok for _, ok in hasil if ok is not None):
        print("\n  Semua langkah berhasil.")
        print("  Buka dashboard lalu tekan 'Refresh Data' di sidebar untuk")
        print("  menarik parquet baru (cache lama akan dihapus).")
    else:
        print("\n  Ada langkah yang gagal — periksa pesan di atas.")


if __name__ == "__main__":
    main()

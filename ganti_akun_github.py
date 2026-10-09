r"""
ganti_akun_github.py
--------------------
Ganti semua referensi akun GitHub lama -> akun baru di seluruh script aktif
di C:\homepass dan C:\hpdb.

  Jomzski  ->  firmanfadillah9-lgtm

File varian lama (dashboard_cur.py, dashboard_v2.py, dll) SENGAJA dilewati
supaya tidak ikut berubah dan bikin bingung.

Cara pakai:
    # 1. Lihat dulu apa saja yang akan berubah (TIDAK menulis apa-apa)
    C:\Users\RYZEN\AppData\Local\Programs\Python\Python312\python.exe C:\homepass\ganti_akun_github.py

    # 2. Kalau sudah yakin, baru eksekusi
    C:\Users\RYZEN\AppData\Local\Programs\Python\Python312\python.exe C:\homepass\ganti_akun_github.py --apply

Setiap file yang diubah otomatis di-backup jadi <nama>.py.bak
Kalau mau balik: tinggal rename .bak kembali.
"""
import os
import sys
import shutil
from datetime import datetime

# ─── KONFIGURASI ────────────────────────────────────────────────────────────
AKUN_LAMA = "Jomzski"
AKUN_BARU = "firmanfadillah9-lgtm"

# Hanya file AKTIF. Varian lama (_cur, _v2, _old, dll) sengaja tidak masuk.
TARGET_FILES = [
    # ── C:\homepass ──────────────────────────────────────────────────────
    r"C:\homepass\dashboard.py",
    r"C:\homepass\push_addhp.py",
    r"C:\homepass\push_history.py",
    r"C:\homepass\push_to_github.py",
    r"C:\homepass\release_upload.py",
    r"C:\homepass\github_config.py",
    r"C:\homepass\telegram_bot.py",
    r"C:\homepass\run.py",
    # ── C:\hpdb ──────────────────────────────────────────────────────────
    r"C:\hpdb\dashboard_hpdb.py",
    r"C:\hpdb\push_coords.py",
    r"C:\hpdb\push_coords_bulk.py",
    r"C:\hpdb\push_status.py",
    r"C:\hpdb\release_upload.py",
    r"C:\hpdb\export_coords_bulk.py",
    r"C:\hpdb\run_hpdb.py",
    r"C:\hpdb\github_config.py",
]


def scan_file(path):
    """Baca file, kembalikan (isi, daftar_baris_yang_kena)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            isi = f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="utf-8-sig") as f:
            isi = f.read()

    hits = []
    for i, baris in enumerate(isi.splitlines(), start=1):
        if AKUN_LAMA in baris:
            hits.append((i, baris.strip()))
    return isi, hits


def main():
    apply_mode = "--apply" in sys.argv

    print("=" * 74)
    print(f"  GANTI AKUN GITHUB : {AKUN_LAMA}  ->  {AKUN_BARU}")
    print(f"  Mode: {'APPLY (menulis file)' if apply_mode else 'PREVIEW (tidak menulis apa-apa)'}")
    print("=" * 74)

    total_file_kena = 0
    total_baris_kena = 0
    tidak_ada = []
    diubah = []

    for path in TARGET_FILES:
        if not os.path.exists(path):
            tidak_ada.append(path)
            continue

        isi, hits = scan_file(path)
        if not hits:
            continue

        total_file_kena += 1
        total_baris_kena += len(hits)

        print(f"\n[{len(hits)} baris] {path}")
        for lineno, baris in hits:
            potong = baris if len(baris) <= 100 else baris[:97] + "..."
            print(f"    L{lineno:<5} {potong}")

        if apply_mode:
            backup = path + ".bak"
            shutil.copy2(path, backup)
            baru = isi.replace(AKUN_LAMA, AKUN_BARU)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(baru)
            diubah.append(path)
            print(f"    -> DIUBAH (backup: {os.path.basename(backup)})")

    # ── Ringkasan ───────────────────────────────────────────────────────────
    print("\n" + "=" * 74)
    print("  RINGKASAN")
    print("=" * 74)
    print(f"  File yang mengandung '{AKUN_LAMA}' : {total_file_kena}")
    print(f"  Total baris yang kena             : {total_baris_kena}")

    if tidak_ada:
        print(f"\n  File tidak ditemukan (dilewati)   : {len(tidak_ada)}")
        for p in tidak_ada:
            print(f"    - {p}")

    if apply_mode:
        print(f"\n  [OK] {len(diubah)} file sudah diubah. Backup .bak dibuat di folder yang sama.")
        print(f"  Waktu: {datetime.now():%Y-%m-%d %H:%M:%S}")
        print("\n  LANGKAH BERIKUTNYA:")
        print("    1. Cek sisa referensi lama:")
        print(r'       Select-String -Path C:\homepass\*.py, C:\hpdb\*.py -Pattern "Jomzski" | Select-Object Filename, LineNumber')
        print("    2. Update token di github_token.txt / github_config.py")
        print("    3. Arahkan ulang git remote:")
        print(f'       git -C C:\\homepass remote set-url origin https://github.com/{AKUN_BARU}/homepass-npd-dashboard.git')
        print(f'       git -C C:\\hpdb     remote set-url origin https://github.com/{AKUN_BARU}/hpdb-dashboard.git')
    else:
        print("\n  Ini baru PREVIEW. Tidak ada file yang berubah.")
        print("  Kalau daftar di atas sudah benar, jalankan ulang dengan --apply :")
        print(r"     ...\python.exe C:\homepass\ganti_akun_github.py --apply")

    print()


if __name__ == "__main__":
    main()

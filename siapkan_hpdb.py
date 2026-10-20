"""
siapkan_hpdb.py - Pilih folder HPDB harian & pastikan file .xlsb SUDAH TERUNDUH dari OneDrive
==============================================================================================

Default: folder KEMARIN (hari ini 20 -> homepass_report_daily_<tgl 19>), karena folder hari ini
biasanya belum lengkap. Kalau folder kemarin belum ada -> folder terbaru sebelum itu (diberi catatan).

    python siapkan_hpdb.py                    # folder kemarin
    python siapkan_hpdb.py --tanggal 20261019 # tanggal tertentu
    python siapkan_hpdb.py --terbaru          # folder paling baru (perilaku lama)

Unduh: file ditandai "Always keep on this device" (attrib +P) lalu dibaca sampai habis supaya
OneDrive menyelesaikan unduhan. Folder yang dulu di-pin skrip ini dilepas lagi (attrib -P +U,
"Free up space" - file tetap aman di cloud) supaya disk tidak penuh.

Baris terakhir: "FOLDER_SIAP: <path>" (dibaca update_hpdb.py). Gagal -> kode keluar 1.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ONEDRIVE_BASE = Path(r"C:\Users\RYZEN\OneDrive - XLSMART\XL HOME - Service Delivery - HPDB")  # = sync_hpdb.py
PIN_STATE = HERE / "hpdb_pin.json"
BATAS_MENIT = 40
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
ATTR_CLOUD = 0x1000 | 0x40000 | 0x400000      # OFFLINE | RECALL_ON_OPEN | RECALL_ON_DATA_ACCESS

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass


def tanggal_folder(f):
    m = re.search(r"(\d{8})$", f.name)
    return m.group(1) if m else ""


def pilih_folder(argv):
    semua = sorted((f for f in ONEDRIVE_BASE.glob("homepass_report_daily_*") if f.is_dir() and tanggal_folder(f)),
                   key=tanggal_folder)
    if not semua:
        return None, f"Tidak ada folder homepass_report_daily_* di {ONEDRIVE_BASE} (OneDrive jalan & sinkron?)"
    if "--terbaru" in argv:
        return semua[-1], "mode --terbaru"
    if "--tanggal" in argv:
        target = argv[argv.index("--tanggal") + 1]
    else:
        target = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    persis = [f for f in semua if tanggal_folder(f) == target]
    if persis:
        return persis[0], f"tanggal {target}"
    lebih_lama = [f for f in semua if tanggal_folder(f) < target]
    if lebih_lama:
        return lebih_lama[-1], (f"folder {target} BELUM ADA -> pakai yang terbaru sebelumnya "
                                f"({tanggal_folder(lebih_lama[-1])})")
    return None, f"Tidak ada folder bertanggal <= {target}"


def di_cloud(f):
    try:
        return bool(os.stat(f).st_file_attributes & ATTR_CLOUD)
    except AttributeError:          # bukan Windows
        return False


def attrib(*args):
    if os.name == "nt":
        subprocess.run(["attrib", *args], capture_output=True, creationflags=NO_WINDOW)


def unduh(files):
    for f in files:
        attrib("+P", "-U", str(f))          # Always keep on this device
    mulai = time.time()
    for f in files:
        ukuran = f.stat().st_size
        status = "masih di cloud -> mengunduh" if di_cloud(f) else "sudah lokal, verifikasi"
        print(f"[UNDUH] {f.name} ({ukuran / 1048576:.0f} MB) {status}")
        dibaca, lapor = 0, time.time()
        with open(f, "rb") as fh:           # membaca memaksa OneDrive menyelesaikan unduhan
            while True:
                blok = fh.read(16 * 1048576)
                if not blok:
                    break
                dibaca += len(blok)
                if time.time() - lapor > 30:
                    print(f"        {dibaca / 1048576:.0f}/{ukuran / 1048576:.0f} MB")
                    lapor = time.time()
                if time.time() - mulai > BATAS_MENIT * 60:
                    print(f"[GAGAL] Unduh lebih dari {BATAS_MENIT} menit - koneksi lambat / OneDrive macet")
                    return False
        if dibaca < ukuran:
            print(f"[GAGAL] {f.name} hanya terbaca {dibaca:,} dari {ukuran:,} byte")
            return False
    print(f"[OK] Semua file lokal ({(time.time() - mulai) / 60:.1f} menit)")
    return True


def lepas_pin_lama(folder):
    try:
        lama = json.loads(PIN_STATE.read_text(encoding="utf-8"))
    except Exception:
        lama = []
    for p in lama:
        if p != str(folder) and Path(p).is_dir():
            for f in Path(p).glob("*.xls*"):
                attrib("-P", "+U", str(f))  # Free up space (file tetap di cloud)
            print(f"[INFO] Pin dilepas: {Path(p).name}")
    PIN_STATE.write_text(json.dumps([str(folder)]), encoding="utf-8")


def main():
    folder, catatan = pilih_folder(sys.argv)
    if not folder:
        print(f"[GAGAL] {catatan}")
        return 1
    files = sorted(f for pola in ("*.xlsb", "*.xlsx") for f in folder.glob(pola) if not f.name.startswith("~$"))
    print(f"[INFO] Folder HPDB: {folder.name} ({catatan})")
    if not files:
        print(f"[GAGAL] Folder {folder.name} kosong / file belum tersinkron")
        return 1
    for f in files:
        print(f"        - {f.name}")
    if not unduh(files):
        return 1
    lepas_pin_lama(folder)
    print(f"FOLDER_SIAP: {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

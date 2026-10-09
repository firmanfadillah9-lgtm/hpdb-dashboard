"""
run_hpdb.py
------------
Orkestrasi pipeline HPDB harian:
1. Pastikan file Excel (main + linknet) untuk tanggal kemarin sudah ter-download
   penuh dari OneDrive (force hydration via sequential read)
2. sync_hpdb.py -> sync ke DuckDB lokal (full replace)
3. export_parquet.py -> export ke Parquet
4. release_upload.py -> upload ke GitHub Release
5. Notifikasi Telegram (sukses/gagal)

Jalankan via Task Scheduler jam 03:00.
"""
import os
import sys
import time
import subprocess
import requests
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from sync_hpdb import ONEDRIVE_BASE

# ─── KONFIGURASI TELEGRAM ──────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    try:
        from telegram_config import TELEGRAM_TOKEN as _T, TELEGRAM_CHAT_ID as _C
        TELEGRAM_TOKEN = TELEGRAM_TOKEN or _T
        TELEGRAM_CHAT_ID = TELEGRAM_CHAT_ID or _C
    except ImportError:
        pass


def send_telegram(message: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"⚠️  Telegram belum dikonfigurasi. Pesan: {message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, data=data, timeout=10)
        if resp.status_code == 200:
            print("📨 Notifikasi Telegram terkirim")
        else:
            print(f"⚠️  Gagal kirim Telegram: {resp.text}")
    except Exception as e:
        print(f"⚠️  Error Telegram: {e}")


def ensure_downloaded(filepath, chunk_size=4 * 1024 * 1024, timeout=1800):
    """Paksa OneDrive Files On-Demand download penuh dengan baca sequential."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(filepath)

    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    print(f"   Memastikan ter-download: {os.path.basename(filepath)} ({size_mb:.1f} MB)...")

    start = time.time()
    read_total = 0
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            read_total += len(chunk)
            if time.time() - start > timeout:
                raise TimeoutError(f"Timeout download {filepath} setelah {timeout}s")

    elapsed = time.time() - start
    print(f"   ✅ OK ({read_total/(1024*1024):.1f} MB dalam {elapsed:.0f}s)")


def run_step(args, step_name):
    print(f"\n>>> {step_name}")
    print(f"    Command: {sys.executable} {' '.join(args)}")
    result = subprocess.run(
        [sys.executable] + args,
        cwd=SCRIPT_DIR,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{step_name} gagal (exit code {result.returncode})")


def main():
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    date_str = (now - timedelta(days=1)).strftime("%Y%m%d")

    print("=" * 60)
    print(f"  HPDB Auto Sync — {now_str}")
    print(f"  Data tanggal   : {date_str}")
    print("=" * 60)

    folder = os.path.join(ONEDRIVE_BASE, f"homepass_report_daily_{date_str}")
    main_file = os.path.join(folder, f"homepass_report_daily_{date_str}.xlsx")
    linknet_file = os.path.join(folder, f"homepass_linknet_report_daily_{date_str}.xlsx")

    start_time = time.time()

    try:
        # ── Step 1: pastikan file sumber ter-download ──────────────────────
        print("\n[1/4] Memastikan file sumber ter-download dari OneDrive...")
        for f in (main_file, linknet_file):
            if not os.path.exists(f):
                raise FileNotFoundError(f"Folder/file belum tersedia: {f}")
            ensure_downloaded(f)

        # ── Step 2: sync ke DuckDB ───────────────────────────────────────────
        run_step(["sync_hpdb.py", date_str], "Sync ke DuckDB")

        # ── Step 3: export ke Parquet ────────────────────────────────────────
        run_step(["export_parquet.py"], "Export ke Parquet")

        # ── Step 4: upload ke GitHub Release ────────────────────────────────
        parquet_path = os.path.join(SCRIPT_DIR, "data", "hpdb.parquet")
        run_step(["release_upload.py", parquet_path], "Upload ke GitHub Release")

        elapsed_min = (time.time() - start_time) / 60
        msg = (
            f"✅ <b>HPDB Sync Berhasil</b>\n\n"
            f"📅 Data tanggal : {date_str}\n"
            f"⏱️ Durasi       : {elapsed_min:.1f} menit\n"
            f"🕐 Selesai      : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        send_telegram(msg)
        print(f"\n🎉 Selesai dalam {elapsed_min:.1f} menit!")

    except Exception as e:
        elapsed_min = (time.time() - start_time) / 60
        msg = (
            f"❌ <b>HPDB Sync Gagal</b>\n\n"
            f"📅 Data tanggal : {date_str}\n"
            f"⏱️ Durasi       : {elapsed_min:.1f} menit\n"
            f"⚠️ Error: {e}"
        )
        send_telegram(msg)
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)

    # ── Sleep PC setelah selesai (kalau AUTO_SLEEP=1) ──────────────────────
    if os.getenv("AUTO_SLEEP", "0") == "1":
        print("\n💤 Mengaktifkan sleep PC dalam 10 detik...")
        time.sleep(10)
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")


if __name__ == "__main__":
    main()

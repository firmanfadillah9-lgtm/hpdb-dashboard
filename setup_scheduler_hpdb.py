"""
setup_scheduler_hpdb.py
-------------------------
Setup Task Scheduler untuk HPDB Auto Sync:
1. Wake PC dari sleep jam 02:55
2. Jalankan run_hpdb.py jam 03:00

Jalankan SEKALI sebagai Administrator:
    python setup_scheduler_hpdb.py

Untuk hapus:
    python setup_scheduler_hpdb.py --remove
"""
import subprocess
import sys
import os

PYTHON_PATH = sys.executable
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
RUN_SCRIPT  = os.path.join(SCRIPT_DIR, "run_hpdb.py")

TASK_WAKE = "HPDB_WakeUp"
TASK_RUN  = "HPDB_AutoSync"


def run_schtasks(args):
    result = subprocess.run(["schtasks"] + args, capture_output=True, text=True)
    print(result.stdout.strip())
    if result.returncode != 0:
        print("STDERR:", result.stderr.strip())
    return result.returncode == 0


def remove_tasks():
    print("Menghapus task yang ada...")
    run_schtasks(["/Delete", "/TN", TASK_WAKE, "/F"])
    run_schtasks(["/Delete", "/TN", TASK_RUN, "/F"])


def create_tasks():
    print("=" * 50)
    print("Setup Task Scheduler - HPDB Auto Sync")
    print("=" * 50)

    print("\n[1/2] Membuat task wake-up jam 02:55...")
    ok1 = run_schtasks([
        "/Create",
        "/TN", TASK_WAKE,
        "/TR", "cmd.exe /c exit",
        "/SC", "DAILY",
        "/ST", "02:55",
        "/RL", "HIGHEST",
        "/F"
    ])
    if ok1:
        print("✅ Task wake-up dibuat.")
        print("⚠️  Pastikan 'Wake the computer to run this task' aktif")
        print("    di Task Scheduler GUI -> HPDB_WakeUp -> Properties -> Conditions")

    print("\n[2/2] Membuat task HPDB Auto Sync jam 03:00...")
    cmd = f'"{PYTHON_PATH}" "{RUN_SCRIPT}"'
    ok2 = run_schtasks([
        "/Create",
        "/TN", TASK_RUN,
        "/TR", cmd,
        "/SC", "DAILY",
        "/ST", "03:00",
        "/RL", "HIGHEST",
        "/F"
    ])
    if ok2:
        print("✅ Task HPDB Auto Sync jam 03:00 dibuat.")

    print("\n" + "=" * 50)
    print("SELESAI - Langkah manual yang masih diperlukan:")
    print("=" * 50)
    print("""
1. Buka Task Scheduler (taskschd.msc)
2. Cari task 'HPDB_WakeUp'
3. Klik kanan -> Properties -> tab 'Conditions'
4. Centang 'Wake the computer to run this task' (kalau belum)
5. Klik OK

Catatan: pipeline HPDB butuh waktu cukup lama (~90-100 menit untuk
6+ juta baris). Pastikan PC tidak digunakan untuk hal lain yang berat
selama jam 03:00-05:00.
""")


if __name__ == "__main__":
    if "--remove" in sys.argv:
        remove_tasks()
    else:
        create_tasks()

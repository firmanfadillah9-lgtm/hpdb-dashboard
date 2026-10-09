"""
deploy_hpdb.py
--------------
Rangkaian deploy project HPDB ke GitHub + GitHub Release, sekali jalan.

Langkah:
  1. Pemeriksaan keselamatan (index.lock, file rahasia, file raksasa)
  2. git commit + set remote + push
  3. setup_github.py  -> bikin release 'latest-data'
  4. Upload data/hpdb.parquet ke release
  5. push_status.py + push_coords_bulk.py
  6. Cetak blok Secrets untuk Streamlit

Cara pakai:
    python deploy_hpdb.py              # pratinjau, tidak mengubah apa pun
    python deploy_hpdb.py --apply      # jalankan beneran

Aman diulang: commit dilewati kalau tidak ada perubahan, remote tidak
diduplikasi, asset lama di release ditimpa.
"""
import os
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
OWNER = "firmanfadillah9-lgtm"
REPO = "hpdb-dashboard"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

RAHASIA = ("secret", "telegram", "token", "session", "csrf")
BATAS_MB = 90          # GitHub menolak file > 100 MB di dalam git
APPLY = "--apply" in sys.argv


def git(*args, timeout=300):
    r = subprocess.run(["git", "-C", HERE, *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def skrip(nama, *args, timeout=900):
    print(f"\n   -> {nama} {' '.join(args)}")
    r = subprocess.run([PY, nama, *args], cwd=HERE, env=ENV, timeout=timeout)
    return r.returncode == 0


def judul(n, teks):
    print(f"\n{'='*70}\n  [{n}] {teks}\n{'='*70}")


def gagal(pesan):
    print(f"\n[BERHENTI] {pesan}\n")
    sys.exit(1)


def main():
    print("=" * 70)
    print(f"  DEPLOY HPDB -> {OWNER}/{REPO}")
    print(f"  Mode: {'APPLY (mengubah beneran)' if APPLY else 'PRATINJAU (tidak mengubah apa pun)'}")
    print("=" * 70)

    # ---------- 1. PEMERIKSAAN ----------
    judul(1, "Pemeriksaan keselamatan")

    lock = os.path.join(HERE, ".git", "index.lock")
    if os.path.exists(lock):
        gagal("Ada .git/index.lock nyangkut. Jalankan dulu di PowerShell:\n"
              "    Remove-Item C:\\hpdb\\.git\\index.lock -Force")

    print("   git add -A (bisa lama, folder ini berisi file besar)...")
    rc, _, err = git("add", "-A", timeout=600)
    if rc != 0:
        gagal(f"git add gagal: {err[:300]}")

    rc, out, _ = git("diff", "--cached", "--name-only")
    staged = [f for f in out.splitlines() if f.strip()]
    print(f"   File siap commit: {len(staged)}")

    bocor = [f for f in staged if any(k in f.lower() for k in RAHASIA)]
    if bocor:
        gagal("File RAHASIA ikut ter-stage:\n     " + "\n     ".join(bocor) +
              "\n   Periksa .gitignore, lalu: git rm -r --cached . -f && git add -A")
    print("   Tidak ada file rahasia -- aman")

    besar = []
    for f in staged:
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            mb = os.path.getsize(p) / 1048576
            if mb > BATAS_MB:
                besar.append(f"{mb:.0f} MB  {f}")
    if besar:
        gagal(f"File di atas {BATAS_MB} MB ikut ter-stage (GitHub akan menolak):\n     "
              + "\n     ".join(besar))
    print(f"   Tidak ada file > {BATAS_MB} MB -- aman")

    parquet = os.path.join(HERE, "data", "hpdb.parquet")
    for p in (parquet,
              os.path.join(HERE, "status_history.parquet"),
              os.path.join(HERE, "hpdb_coords_bulk.parquet")):
        ada = os.path.exists(p)
        mb = f"{os.path.getsize(p)/1048576:.0f} MB" if ada else "-"
        print(f"   {'OK ' if ada else 'TIDAK ADA'}  {os.path.basename(p):<28} {mb}")

    if not APPLY:
        print("\n" + "=" * 70)
        print("  Pratinjau selesai. Semua pemeriksaan lolos.")
        print("  Jalankan ulang dengan --apply untuk benar-benar deploy.")
        print("=" * 70 + "\n")
        return

    # ---------- 2. COMMIT + PUSH ----------
    judul(2, "Commit dan push ke GitHub")

    rc, out, _ = git("rev-list", "--count", "HEAD")
    punya_commit = rc == 0 and out.isdigit() and int(out) > 0

    if staged or not punya_commit:
        rc, out, err = git("commit", "-m", "Deploy HPDB dashboard - akun firmanfadillah9-lgtm")
        print("   " + (out or err).splitlines()[0] if (out or err) else "   commit selesai")
    else:
        print("   Tidak ada perubahan untuk di-commit")

    rc, out, _ = git("remote", "get-url", "origin")
    url = f"https://github.com/{OWNER}/{REPO}.git"
    if rc != 0:
        git("remote", "add", "origin", url)
        print(f"   remote origin ditambahkan")
    else:
        git("remote", "set-url", "origin", url)
        print(f"   remote origin diarahkan ulang")

    print("   Mendorong ke GitHub...")
    r = subprocess.run(["git", "-C", HERE, "push", "-u", "origin", "main"], timeout=900)
    if r.returncode != 0:
        gagal("git push gagal. Kalau diminta password, isi dengan Personal Access Token "
              "(bukan password akun), atau pakai GitHub Desktop.")
    print("   Push berhasil")

    # ---------- 3. RELEASE ----------
    judul(3, "Membuat release 'latest-data'")
    if not skrip("setup_github.py"):
        gagal("setup_github.py gagal")

    # ---------- 4-5. UPLOAD DATA ----------
    judul(4, "Upload data ke release")
    if os.path.exists(parquet):
        if not skrip("release_upload.py", parquet, timeout=1800):
            print("   [PERINGATAN] upload hpdb.parquet gagal")
    else:
        print("   data/hpdb.parquet tidak ada -- dilewati")

    for s in ("push_status.py", "push_coords_bulk.py"):
        if os.path.exists(os.path.join(HERE, s)):
            if not skrip(s, timeout=1800):
                print(f"   [PERINGATAN] {s} gagal")

    # ---------- 6. SECRETS ----------
    judul(5, "Langkah terakhir: deploy di Streamlit")
    tok = ""
    for p in (r"C:\homepass\github_token.txt", os.path.join(HERE, "github_token.txt")):
        if os.path.exists(p):
            tok = open(p, encoding="utf-8").read().strip()
            break

    print(f"""
  share.streamlit.io -> Create app -> Deploy a public app from GitHub

    Repository      : {OWNER}/{REPO}
    Branch          : main
    Main file path  : dashboard_hpdb.py
    Python version  : 3.12   (Advanced settings)

  Secrets -- SENGAJA TANPA blok [osrm], supaya dashboard memakai
  server OSRM publik dan tidak lagi bergantung pada ngrok di PC ini:

[github]
token = "{tok or 'ISI_TOKEN_DI_SINI'}"

[credentials.admin]
password_hash = "GANTI_DENGAN_HASH_BARU"
role = "super_admin"
name = "Fadil"
""")
    print("=" * 70)
    print("  SELESAI")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()

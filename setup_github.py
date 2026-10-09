r"""
setup_github.py
---------------
Siapkan sisi GitHub untuk akun baru, tanpa klik-klik di web:

  1. Cek token valid & login sebagai siapa
  2. Cek repo homepass-npd-dashboard & hpdb-dashboard
       - kalau belum ada  -> dibuat (Private)
       - kalau sudah ada  -> dilaporkan visibility-nya
  3. Cek release 'latest-data' di tiap repo
       - kalau belum ada  -> dibuat
  4. Tampilkan asset yang sudah nempel di tiap release

Cara pakai:
    C:\Users\RYZEN\AppData\Local\Programs\Python\Python312\python.exe C:\hpdb\setup_github.py

    # sekalian paksa kedua repo jadi Private
    ...\python.exe C:\hpdb\setup_github.py --private
"""
import os
import sys
import requests

GITHUB_OWNER = "firmanfadillah9-lgtm"
REPOS        = ["homepass-npd-dashboard", "hpdb-dashboard"]
RELEASE_TAG  = "latest-data"
API          = "https://api.github.com"

TOKEN_PATHS = [
    r"C:\homepass\github_token.txt",
    r"C:\hpdb\github_token.txt",
]


def get_token() -> str:
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        return tok
    for path in TOKEN_PATHS:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                tok = f.read().strip()
            if tok:
                return tok
    raise RuntimeError("Token GitHub tidak ditemukan di env GITHUB_TOKEN maupun github_token.txt")


TOKEN = get_token()
H = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}


def line(char="-", n=74):
    print(char * n)


def cek_token():
    print("[1/4] Cek token...")
    r = requests.get(f"{API}/user", headers=H, timeout=30)
    if r.status_code != 200:
        print(f"   [GAGAL] {r.status_code} - {r.text[:200]}")
        print("   Token salah / sudah dicabut / belum punya scope 'repo'.")
        sys.exit(1)
    u = r.json()
    print(f"   OK  login sebagai: {u['login']}")
    scopes = r.headers.get("x-oauth-scopes", "(tidak terbaca)")
    print(f"   Scope token      : {scopes}")
    if "repo" not in scopes:
        print("   [PERINGATAN] Scope 'repo' tidak terdeteksi. Upload asset kemungkinan gagal.")
    if u["login"].lower() != GITHUB_OWNER.lower():
        print(f"   [PERINGATAN] Token milik '{u['login']}', tapi GITHUB_OWNER di-set '{GITHUB_OWNER}'.")
    return u["login"]


def cek_repo(repo, paksa_private=False):
    r = requests.get(f"{API}/repos/{GITHUB_OWNER}/{repo}", headers=H, timeout=30)

    if r.status_code == 404:
        print(f"   {repo:<26} belum ada -> membuat (Private)...")
        c = requests.post(
            f"{API}/user/repos", headers=H, timeout=30,
            json={"name": repo, "private": True,
                  "description": "Data & dashboard - auto-managed",
                  "auto_init": False})
        if c.status_code not in (200, 201):
            print(f"      [GAGAL] {c.status_code} - {c.text[:200]}")
            return False
        print("      OK  repo dibuat (Private)")
        return True

    if r.status_code != 200:
        print(f"   {repo:<26} [GAGAL] {r.status_code} - {r.text[:150]}")
        return False

    info = r.json()
    vis = "Private" if info["private"] else "PUBLIC"
    print(f"   {repo:<26} sudah ada  | visibility: {vis}")

    if info["private"]:
        return True

    if paksa_private:
        p = requests.patch(f"{API}/repos/{GITHUB_OWNER}/{repo}",
                           headers=H, json={"private": True}, timeout=30)
        if p.status_code == 200:
            print("      -> diubah jadi Private")
        else:
            print(f"      [GAGAL ubah private] {p.status_code} - {p.text[:150]}")
    else:
        print("      -> masih PUBLIC. Jalankan ulang dengan --private untuk mengubahnya.")
    return True


def cek_release(repo):
    r = requests.get(f"{API}/repos/{GITHUB_OWNER}/{repo}/releases/tags/{RELEASE_TAG}",
                     headers=H, timeout=30)

    if r.status_code == 404:
        print(f"   {repo:<26} release '{RELEASE_TAG}' belum ada -> membuat...")
        c = requests.post(
            f"{API}/repos/{GITHUB_OWNER}/{repo}/releases", headers=H, timeout=30,
            json={"tag_name": RELEASE_TAG, "name": "Latest Data",
                  "body": "Asset data terbaru. Dikelola otomatis oleh script push_*.py",
                  "draft": False, "prerelease": False})
        if c.status_code not in (200, 201):
            print(f"      [GAGAL] {c.status_code} - {c.text[:250]}")
            return None
        print("      OK  release dibuat")
        return c.json()

    if r.status_code != 200:
        print(f"   {repo:<26} [GAGAL] {r.status_code} - {r.text[:150]}")
        return None

    print(f"   {repo:<26} release '{RELEASE_TAG}' sudah ada")
    return r.json()


def tampil_asset(repo, rel):
    if not rel:
        return
    assets = rel.get("assets", [])
    print(f"\n   {repo}")
    if not assets:
        print("      (kosong - belum ada data yang di-push)")
        return
    for a in sorted(assets, key=lambda x: x["name"]):
        mb = a["size"] / 1024 / 1024
        print(f"      {a['name']:<34} {mb:>8.2f} MB   {a['updated_at'][:10]}")


def main():
    paksa_private = "--private" in sys.argv

    line("=")
    print(f"  SETUP GITHUB : {GITHUB_OWNER}")
    print(f"  Mode private : {'YA (repo public akan diubah)' if paksa_private else 'tidak (hanya melapor)'}")
    line("=")

    cek_token()

    print("\n[2/4] Cek repo...")
    for repo in REPOS:
        cek_repo(repo, paksa_private)

    print(f"\n[3/4] Cek release '{RELEASE_TAG}'...")
    rels = {repo: cek_release(repo) for repo in REPOS}

    print("\n[4/4] Asset yang sudah ada di tiap release:")
    for repo in REPOS:
        tampil_asset(repo, rels[repo])

    print()
    line("=")
    print("  LANGKAH BERIKUTNYA")
    line("=")
    print("  Arahkan git remote ke akun baru:")
    for folder, repo in ((r"C:\homepass", REPOS[0]), (r"C:\hpdb", REPOS[1])):
        print(f"    git -C {folder:<12} remote set-url origin "
              f"https://github.com/{GITHUB_OWNER}/{repo}.git")
    print()
    print("  Lalu push data:")
    print(r"    python C:\homepass\push_addhp.py")
    print(r"    python C:\homepass\push_history.py")
    print(r"    python C:\hpdb\push_status.py")
    print(r"    python C:\hpdb\push_coords_bulk.py")
    print(r"    python C:\hpdb\release_upload.py")
    print()


if __name__ == "__main__":
    main()

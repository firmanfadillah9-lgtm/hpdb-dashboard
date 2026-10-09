r"""
push_status.py
--------------
Export status_history dari C:\hpdb\addhp.duckdb -> status_history.parquet
lalu upload ke GitHub Release 'latest-data' (repo homepass-npd-dashboard).

Dijalankan setelah track_status.py.

Token GitHub dicari berurutan dari:
  1. Environment variable GITHUB_TOKEN
  2. C:\homepass\github_token.txt
  3. C:\hpdb\github_token.txt
"""
import os
import sys
import duckdb
import requests

DB_PATH      = r"C:\hpdb\addhp.duckdb"
PARQUET_PATH = r"C:\hpdb\status_history.parquet"
ASSET_NAME   = "status_history.parquet"
REPO         = "firmanfadillah9-lgtm/homepass-npd-dashboard"
RELEASE_TAG  = "latest-data"


def get_token() -> str:
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        return tok
    for path in (r"C:\homepass\github_token.txt", r"C:\hpdb\github_token.txt"):
        if os.path.exists(path):
            with open(path) as f:
                tok = f.read().strip()
            if tok:
                return tok
    raise RuntimeError(
        "Token GitHub tidak ditemukan. Set env GITHUB_TOKEN atau buat file "
        "C:\\homepass\\github_token.txt berisi token."
    )


def main():
    print("=" * 50)
    print("  Push status_history.parquet ke GitHub Release")
    print("=" * 50)

    # 1. Export ke parquet
    print("[1/2] Export status_history -> parquet...")
    con = duckdb.connect(DB_PATH, read_only=True)
    n = con.execute("SELECT COUNT(*) FROM status_history").fetchone()[0]
    con.execute(f"COPY status_history TO '{PARQUET_PATH}' (FORMAT PARQUET)")
    con.close()
    size_mb = os.path.getsize(PARQUET_PATH) / 1024 / 1024
    print(f"   OK: {n:,} records -> {size_mb:.2f} MB")

    # 2. Upload ke release
    print(f"[2/2] Upload ke GitHub Release '{RELEASE_TAG}'...")
    token = get_token()
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json"}

    rel = requests.get(
        f"https://api.github.com/repos/{REPO}/releases/tags/{RELEASE_TAG}",
        headers=headers, timeout=30)
    if rel.status_code != 200:
        print(f"   [ERROR] Release '{RELEASE_TAG}' tidak ditemukan: {rel.status_code}")
        sys.exit(1)
    rel_json = rel.json()

    # Hapus asset lama kalau ada
    for asset in rel_json.get("assets", []):
        if asset["name"] == ASSET_NAME:
            requests.delete(
                f"https://api.github.com/repos/{REPO}/releases/assets/{asset['id']}",
                headers=headers, timeout=30)
            print("   Asset lama dihapus")
            break

    upload_url = rel_json["upload_url"].split("{")[0] + f"?name={ASSET_NAME}"
    with open(PARQUET_PATH, "rb") as f:
        up = requests.post(
            upload_url,
            headers={**headers, "Content-Type": "application/octet-stream"},
            data=f.read(), timeout=300)
    if up.status_code not in (200, 201):
        print(f"   [ERROR] Upload gagal: {up.status_code} {up.text[:200]}")
        sys.exit(1)

    print("   Upload berhasil!")
    print(f"   URL: https://github.com/{REPO}/releases/download/{RELEASE_TAG}/{ASSET_NAME}")
    print("\n[DONE]")


if __name__ == "__main__":
    main()

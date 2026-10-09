"""
push_coords.py
---------------
Upload hpdb_coords.parquet ke GitHub Release homepass-npd-dashboard.
Dijalankan dari C:\hpdb\ setelah export_coords.py berhasil.
"""
import os, sys, requests

PARQUET_FILE  = "hpdb_coords.parquet"
GITHUB_OWNER  = "firmanfadillah9-lgtm"
GITHUB_REPO   = "homepass-npd-dashboard"
RELEASE_TAG   = "latest-data"

def get_token():
    try:
        from github_config import GITHUB_TOKEN
        return GITHUB_TOKEN
    except ImportError:
        pass
    return os.getenv("GITHUB_TOKEN", "")

def main():
    print("=" * 50)
    print("  Push hpdb_coords.parquet ke GitHub Release")
    print("=" * 50)

    if not os.path.exists(PARQUET_FILE):
        print(f"❌ File tidak ditemukan: {PARQUET_FILE}")
        print("   Jalankan export_coords.py dulu.")
        sys.exit(1)

    size_mb = os.path.getsize(PARQUET_FILE) / (1024*1024)
    print(f"\nFile: {PARQUET_FILE} ({size_mb:.2f} MB)")

    token = get_token()
    if not token:
        print("❌ GitHub token tidak ditemukan di github_config.py")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    print(f"\nMencari release '{RELEASE_TAG}'...")
    resp = requests.get(
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tags/{RELEASE_TAG}",
        headers=headers
    )
    if resp.status_code != 200:
        print(f"❌ Release tidak ditemukan: {resp.status_code}")
        sys.exit(1)

    release = resp.json()
    print(f"✅ Release ditemukan (id={release['id']})")

    # Hapus asset lama kalau ada
    for asset in release.get("assets", []):
        if asset["name"] == PARQUET_FILE:
            requests.delete(
                f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/assets/{asset['id']}",
                headers=headers
            )
            print(f"   🗑️  Asset lama dihapus")

    # Upload
    print(f"\nMengupload {PARQUET_FILE} ({size_mb:.2f} MB)...")
    upload_url = release["upload_url"].split("{")[0]
    with open(PARQUET_FILE, "rb") as f:
        resp2 = requests.post(
            upload_url,
            headers={**headers, "Content-Type": "application/octet-stream"},
            params={"name": PARQUET_FILE},
            data=f
        )

    if resp2.status_code == 201:
        print(f"✅ Upload berhasil!")
        print(f"   URL: {resp2.json()['browser_download_url']}")
    else:
        print(f"❌ Upload gagal: {resp2.status_code} {resp2.text[:200]}")
        sys.exit(1)

if __name__ == "__main__":
    main()

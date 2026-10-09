import os, sys, requests

sys.path.insert(0, r'C:\hpdb')
from github_config import GITHUB_TOKEN

OWNER   = "firmanfadillah9-lgtm"
REPO    = "homepass-npd-dashboard"
TAG     = "latest-data"
FILE    = "hpdb_coords_bulk.parquet"

headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}

# Cari release
resp = requests.get(f"https://api.github.com/repos/{OWNER}/{REPO}/releases/tags/{TAG}", headers=headers)
release = resp.json()
print(f"Release id: {release['id']}")

# Hapus asset lama kalau ada
for asset in release.get("assets", []):
    if asset["name"] == FILE:
        requests.delete(f"https://api.github.com/repos/{OWNER}/{REPO}/releases/assets/{asset['id']}", headers=headers)
        print(f"Asset lama dihapus")

# Upload
upload_url = release["upload_url"].split("{")[0]
size_mb = os.path.getsize(FILE) / (1024*1024)
print(f"Mengupload {FILE} ({size_mb:.1f} MB)...")

with open(FILE, "rb") as f:
    resp2 = requests.post(
        upload_url,
        headers={**headers, "Content-Type": "application/octet-stream"},
        params={"name": FILE},
        data=f
    )

if resp2.status_code == 201:
    print(f"✅ Upload berhasil!")
    print(f"   URL: {resp2.json()['browser_download_url']}")
else:
    print(f"❌ Gagal: {resp2.status_code} {resp2.text[:200]}")

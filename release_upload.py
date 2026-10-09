"""
release_upload.py
-------------------
Upload/replace file (misal hpdb.parquet) sebagai asset di GitHub Release.
Kalau release dengan tag tertentu belum ada, akan dibuat otomatis.
Kalau asset dengan nama sama sudah ada, akan dihapus dulu lalu di-upload ulang
(supaya URL download tetap konsisten).

Cara pakai:
    python release_upload.py <path_file> [tag]
    (default tag = "latest-data")
"""
import os
import sys
import requests
from github_config import GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO

API_BASE = "https://api.github.com"
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}


def test_connection():
    resp = requests.get(f"{API_BASE}/user", headers=HEADERS)
    if resp.status_code == 200:
        user = resp.json()
        print(f"✅ Token valid. Login sebagai: {user['login']}")
        return True
    else:
        print(f"❌ Token tidak valid: {resp.status_code} {resp.text}")
        return False


def get_or_create_release(tag):
    url = f"{API_BASE}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tags/{tag}"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()

    print(f"   Release '{tag}' belum ada, membuat baru...")
    url = f"{API_BASE}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
    payload = {"tag_name": tag, "name": tag, "body": "Auto-generated data release"}
    resp = requests.post(url, headers=HEADERS, json=payload)
    resp.raise_for_status()
    return resp.json()


def delete_existing_asset(release, filename):
    for asset in release.get("assets", []):
        if asset["name"] == filename:
            print(f"   Menghapus asset lama: {filename}")
            del_url = f"{API_BASE}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/assets/{asset['id']}"
            requests.delete(del_url, headers=HEADERS)


def upload_asset(release, filepath):
    filename = os.path.basename(filepath)
    upload_url = release["upload_url"].split("{")[0]
    params = {"name": filename}
    headers = {**HEADERS, "Content-Type": "application/octet-stream"}

    filesize = os.path.getsize(filepath)
    print(f"   Mengupload {filename} ({filesize/(1024*1024):.1f} MB)...")

    with open(filepath, "rb") as f:
        resp = requests.post(upload_url, headers=headers, params=params, data=f)

    if resp.status_code == 201:
        asset = resp.json()
        print(f"✅ Upload berhasil!")
        print(f"   URL: {asset['browser_download_url']}")
        return asset["browser_download_url"]
    else:
        print(f"❌ Upload gagal: {resp.status_code} {resp.text}")
        return None


def main():
    if len(sys.argv) < 2:
        print("Cara pakai: python release_upload.py <path_file> [tag]")
        sys.exit(1)

    filepath = sys.argv[1]
    tag = sys.argv[2] if len(sys.argv) > 2 else "latest-data"

    if not os.path.exists(filepath):
        print(f"❌ File tidak ditemukan: {filepath}")
        sys.exit(1)

    print("=" * 60)
    print(f"  Upload ke GitHub Release - {GITHUB_OWNER}/{GITHUB_REPO}")
    print("=" * 60)

    if not test_connection():
        sys.exit(1)

    release = get_or_create_release(tag)
    print(f"   Release: {release['tag_name']} (id={release['id']})")

    filename = os.path.basename(filepath)
    delete_existing_asset(release, filename)

    url = upload_asset(release, filepath)
    if url:
        print(f"\n📌 URL download (konsisten, dipakai dashboard):")
        print(f"   {url}")


if __name__ == "__main__":
    main()

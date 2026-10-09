r"""
github_config.py
----------------
Konfigurasi terpusat untuk semua script yang push/pull data ke GitHub Release.
Taruh SATU file ini di C:\homepass\ DAN C:\hpdb\ (isinya sama persis).

Semua script cukup:
    from github_config import GITHUB_OWNER, GITHUB_REPO, GITHUB_TOKEN, RELEASE_TAG, release_url

Token TIDAK ditulis di file ini (biar aman kalau repo ke-push publik).
Token dicari berurutan dari:
    1. Environment variable GITHUB_TOKEN
    2. C:\homepass\github_token.txt
    3. C:\hpdb\github_token.txt
"""
import os

# ─── AKUN & REPO ────────────────────────────────────────────────────────────
GITHUB_OWNER = "firmanfadillah9-lgtm"

# Repo default dipilih otomatis berdasarkan folder script yang jalan.
#   C:\homepass  -> homepass-npd-dashboard
#   C:\hpdb      -> hpdb-dashboard
REPO_HOMEPASS = "homepass-npd-dashboard"
REPO_HPDB     = "hpdb-dashboard"

_here = os.path.dirname(os.path.abspath(__file__)).lower()
GITHUB_REPO = REPO_HPDB if "hpdb" in _here else REPO_HOMEPASS

# Tag release tempat semua parquet ditempel
RELEASE_TAG = "latest-data"

# Kompatibilitas nama lama yang dipakai beberapa script
REPO      = f"{GITHUB_OWNER}/{GITHUB_REPO}"
REPO_FULL = REPO


# ─── TOKEN ──────────────────────────────────────────────────────────────────
TOKEN_PATHS = [
    r"C:\homepass\github_token.txt",
    r"C:\hpdb\github_token.txt",
]


def get_token() -> str:
    """Ambil Personal Access Token GitHub."""
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        return tok
    for path in TOKEN_PATHS:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                tok = f.read().strip()
            if tok:
                return tok
    raise RuntimeError(
        "Token GitHub tidak ditemukan.\n"
        "Buat file C:\\homepass\\github_token.txt berisi Personal Access Token "
        "(classic, scope: repo), tanpa spasi/baris kosong."
    )


# Sebagian script mengimpor konstanta ini langsung.
# Dibuat lazy supaya import github_config tidak langsung error kalau token belum ada.
try:
    GITHUB_TOKEN = get_token()
except RuntimeError:
    GITHUB_TOKEN = ""


def headers() -> dict:
    return {
        "Authorization": f"Bearer {get_token()}",
        "Accept": "application/vnd.github+json",
    }


def release_url(asset_name: str, owner: str = None, repo: str = None) -> str:
    """URL download langsung sebuah asset di release 'latest-data'."""
    owner = owner or GITHUB_OWNER
    repo  = repo  or GITHUB_REPO
    return (f"https://github.com/{owner}/{repo}/releases/download/"
            f"{RELEASE_TAG}/{asset_name}")


def api_release_url(owner: str = None, repo: str = None) -> str:
    owner = owner or GITHUB_OWNER
    repo  = repo  or GITHUB_REPO
    return (f"https://api.github.com/repos/{owner}/{repo}/"
            f"releases/tags/{RELEASE_TAG}")


if __name__ == "__main__":
    print("GITHUB_OWNER :", GITHUB_OWNER)
    print("GITHUB_REPO  :", GITHUB_REPO, f"(dideteksi dari folder: {_here})")
    print("RELEASE_TAG  :", RELEASE_TAG)
    print("TOKEN        :", (GITHUB_TOKEN[:8] + "..." + GITHUB_TOKEN[-4:]) if GITHUB_TOKEN else "(BELUM ADA)")
    print("Contoh URL   :", release_url("hpdb.parquet"))

"""
uji_remote_parquet.py
---------------------
Menguji apakah DuckDB bisa query hpdb.parquet LANGSUNG dari GitHub Release
tanpa mengunduh seluruh 201 MB, memakai HTTP range request.

Kalau ini berhasil, cold start dashboard di Streamlit Cloud berubah dari
"unduh 201 MB dulu" (1-3 menit) menjadi hampir seketika.

Jalankan SETELAH hpdb.parquet terunggah ke release:
    python uji_remote_parquet.py
"""
import time
import duckdb
import requests
from github_config import GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO, RELEASE_TAG

ASSET = "hpdb.parquet"
LOKAL = "data/hpdb.parquet"


def ambil_asset_url():
    h = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    r = requests.get(
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tags/{RELEASE_TAG}",
        headers=h, timeout=30)
    r.raise_for_status()
    for a in r.json().get("assets", []):
        if a["name"] == ASSET:
            return a["url"], a["size"] / 1048576
    raise FileNotFoundError(f"Asset {ASSET} belum ada di release '{RELEASE_TAG}'. "
                            "Jalankan deploy_hpdb.py --apply dulu.")


UJI = [
    ("metadata parquet",   "SELECT COUNT(*) FROM parquet_metadata({src})"),
    ("COUNT(*) semua",     "SELECT COUNT(*) FROM read_parquet({src})"),
    ("DISTINCT REGION",    "SELECT COUNT(DISTINCT REGION) FROM read_parquet({src})"),
    ("DISTINCT VENDOR",    "SELECT COUNT(DISTINCT VENDOR_NAME) FROM read_parquet({src})"),
    ("filter 1 kota",      "SELECT COUNT(*) FROM read_parquet({src}) "
                           "WHERE CITY='KOTA JAKARTA TIMUR'"),
    ("status per city",    "SELECT COUNT(*) FROM (SELECT CITY, HOMEPASS_STATUS, COUNT(*) "
                           "FROM read_parquet({src}) GROUP BY 1,2)"),
]


def jalankan(con, label, src):
    print(f"\n  {label}")
    print(f"  {'-'*60}")
    print(f"  {'QUERY':<22}{'detik':>9}{'hasil':>14}")
    total = 0.0
    for nama, q in UJI:
        t = time.perf_counter()
        try:
            hasil = con.execute(q.format(src=f"'{src}'")).fetchone()[0]
            d = time.perf_counter() - t
            total += d
            print(f"  {nama:<22}{d:>9.2f}{hasil:>14,}")
        except Exception as e:
            print(f"  {nama:<22}    GAGAL  {str(e)[:60]}")
            return None
    print(f"  {'TOTAL':<22}{total:>9.2f}")
    return total


def main():
    print("=" * 70)
    print("  UJI: query parquet JAUH vs LOKAL")
    print("=" * 70)

    url, mb = ambil_asset_url()
    print(f"\n  Asset   : {ASSET} ({mb:.0f} MB)")

    con = duckdb.connect(":memory:")
    con.execute("SET threads=2; SET memory_limit='900MB';")
    try:
        con.execute("INSTALL httpfs; LOAD httpfs;")
        print("  httpfs  : OK")
    except Exception as e:
        print(f"\n  [GAGAL] httpfs tidak bisa dipasang: {str(e)[:200]}")
        print("  Tanpa httpfs, pendekatan ini tidak bisa dipakai.")
        return

    try:
        con.execute(f"""CREATE OR REPLACE SECRET gh (TYPE HTTP,
            EXTRA_HTTP_HEADERS MAP{{'Authorization':'Bearer {GITHUB_TOKEN}',
                                    'Accept':'application/octet-stream'}})""")
        print("  secret  : OK (header auth untuk repo private)")
    except Exception as e:
        print(f"\n  [GAGAL] HTTP secret tidak didukung: {str(e)[:200]}")
        print(f"  Versi DuckDB: {duckdb.__version__} -- butuh 1.1 atau lebih baru.")
        return

    t_jauh = jalankan(con, f"A. JAUH (range request ke GitHub)", url)

    import os
    t_lokal = None
    if os.path.exists(LOKAL):
        t_lokal = jalankan(duckdb.connect(":memory:"), "B. LOKAL (file di disk)", LOKAL)

    print("\n" + "=" * 70)
    print("  KESIMPULAN")
    print("=" * 70)
    if t_jauh is None:
        print("  Query jauh GAGAL -> tetap pakai unduh-dulu seperti sekarang.")
    else:
        print(f"  Query jauh  : {t_jauh:.2f} s, tanpa mengunduh 201 MB")
        if t_lokal:
            print(f"  Query lokal : {t_lokal:.2f} s, tapi perlu unduh {mb:.0f} MB lebih dulu")
            print(f"  Selisih     : {t_jauh - t_lokal:+.2f} s per sesi query")
        print()
        print("  Hitungan yang sebenarnya penting: unduhan 201 MB di cold start")
        print("  hilang sepenuhnya. Kalau selisih di atas masih dalam hitungan")
        print("  detik, pendekatan jauh menang telak karena cold start Streamlit")
        print("  Cloud terjadi setiap kali app reboot (tidur, redeploy, atau OOM).")


if __name__ == "__main__":
    main()

"""
cek_vendor.py — Eksplor data vendor tertentu di HPDB (TBG, ALITA, own-build)
    python cek_vendor.py TBG
    python cek_vendor.py ALITA
"""
import sys
import duckdb

DB_PATH = r"C:\hpdb\addhp.duckdb"
vendor = sys.argv[1] if len(sys.argv) > 1 else "TBG"

con = duckdb.connect(DB_PATH, read_only=True)
w = f"UPPER(VENDOR_NAME) LIKE '%{vendor.upper()}%'"

print("=" * 70)
print(f"  EKSPLOR VENDOR: {vendor}")
print("=" * 70)

print("\n[1] Distribusi status:")
print(con.execute(f"""
    SELECT HOMEPASS_STATUS, COUNT(*) AS jml
    FROM hpdb WHERE {w} GROUP BY 1 ORDER BY 2 DESC
""").fetchdf().to_string())

print(f"\n[2] Total HPID vendor {vendor}: " +
      f"{con.execute(f'SELECT COUNT(*) FROM hpdb WHERE {w}').fetchone()[0]:,}")

print("\n[3] Contoh REMARKS unik (20 teratas):")
print(con.execute(f"""
    SELECT REMARKS, COUNT(*) AS jml
    FROM hpdb WHERE {w} AND REMARKS IS NOT NULL AND TRIM(REMARKS) <> ''
    GROUP BY 1 ORDER BY 2 DESC LIMIT 20
""").fetchdf().to_string())

print("\n[4] Contoh 15 baris lengkap:")
print(con.execute(f"""
    SELECT HOMEPASS_ID, HOMEPASS_STATUS, ACQUISITION_CLASS, ACQUISITION_TIER,
           CITY, CLUSTER_NAME, SUBSTR(REMARKS,1,30) AS remark
    FROM hpdb WHERE {w} LIMIT 15
""").fetchdf().to_string())

print(f"\n[5] HPID vendor {vendor} yang BARU muncul (dari status_history):")
try:
    print(con.execute(f"""
        SELECT change_date, status_to, COUNT(*) AS jml
        FROM status_history
        WHERE UPPER(VENDOR_NAME) LIKE '%{vendor.upper()}%' AND status_from IS NULL
        GROUP BY 1,2 ORDER BY 1 DESC
    """).fetchdf().to_string())
except Exception as e:
    print("  (status_history tidak tersedia:", e, ")")

con.close()
print("\n[DONE]")

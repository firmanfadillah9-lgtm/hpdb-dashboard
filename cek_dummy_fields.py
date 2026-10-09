"""
cek_dummy_fields.py — Scan data 'dummy' di banyak field HPDB
    python cek_dummy_fields.py
    python cek_dummy_fields.py TBG        # filter vendor
    python cek_dummy_fields.py --kw test  # kata kunci lain (default: dummy)
"""
import sys
import duckdb

DB_PATH = r"C:\hpdb\addhp.duckdb"

FIELDS = ["PROJECT_NAME", "CLUSTER_NAME", "STREET_NAME", "DISTRICT",
          "SUB_DISTRICT", "OLT_LOCATION", "FDT_CODE", "REMARKS",
          "HOUSE_NUMBER", "HOMEPASS_ID"]

kw = "dummy"
vendor = None
args = sys.argv[1:]
i = 0
while i < len(args):
    if args[i] == "--kw" and i + 1 < len(args):
        kw = args[i + 1]; i += 2
    else:
        vendor = args[i]; i += 1

con = duckdb.connect(DB_PATH, read_only=True)
vfilter = f" AND UPPER(VENDOR_NAME) LIKE '%{vendor.upper()}%'" if vendor else ""

print("=" * 70)
print(f"  SCAN '{kw}' di {len(FIELDS)} field" + (f" | vendor {vendor}" if vendor else ""))
print("=" * 70)

# 1. Hitung per field berapa baris yang mengandung kw
print(f"\n[1] Jumlah baris mengandung '{kw}' per field:")
total_any_cond = []
for f in FIELDS:
    cnt = con.execute(
        f"SELECT COUNT(*) FROM hpdb WHERE LOWER({f}) LIKE '%{kw}%'{vfilter}"
    ).fetchone()[0]
    print(f"   {f:<16}: {cnt:,}")
    total_any_cond.append(f"LOWER({f}) LIKE '%{kw}%'")

# 2. Total baris unik yang punya kw di SALAH SATU field
any_where = "(" + " OR ".join(total_any_cond) + ")" + vfilter
total = con.execute(f"SELECT COUNT(*) FROM hpdb WHERE {any_where}").fetchone()[0]
print(f"\n[2] Total HPID yang punya '{kw}' di minimal 1 field: {total:,}")

# 3. Breakdown per vendor
print(f"\n[3] Breakdown per vendor:")
print(con.execute(f"""
    SELECT VENDOR_NAME, COUNT(*) AS jml
    FROM hpdb WHERE {any_where}
    GROUP BY 1 ORDER BY 2 DESC
""").fetchdf().to_string())

# 4. Breakdown per status
print(f"\n[4] Breakdown per status:")
print(con.execute(f"""
    SELECT HOMEPASS_STATUS, COUNT(*) AS jml
    FROM hpdb WHERE {any_where}
    GROUP BY 1 ORDER BY 2 DESC
""").fetchdf().to_string())

# 5. Contoh 20 baris
print(f"\n[5] Contoh 20 baris terdampak:")
print(con.execute(f"""
    SELECT HOMEPASS_ID, VENDOR_NAME, HOMEPASS_STATUS, PROJECT_NAME,
           CLUSTER_NAME, STREET_NAME, FDT_CODE
    FROM hpdb WHERE {any_where} LIMIT 20
""").fetchdf().to_string())

con.close()
print("\n[DONE]")

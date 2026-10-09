"""
cek_dummy.py — Cek HPID dengan indikasi 'dummy' di HPDB
Simpan di C:\hpdb\ lalu jalankan:
    python cek_dummy.py
    python cek_dummy.py TBG          # filter vendor tertentu
    python cek_dummy.py --remark kata # cari kata lain di REMARKS
"""
import sys
import duckdb

DB_PATH = r"C:\hpdb\addhp.duckdb"

# Argumen
vendor_filter = None
remark_kw = "dummy"
args = sys.argv[1:]
i = 0
while i < len(args):
    if args[i] == "--remark" and i + 1 < len(args):
        remark_kw = args[i + 1]; i += 2
    else:
        vendor_filter = args[i]; i += 1

con = duckdb.connect(DB_PATH, read_only=True)

print("=" * 70)
print(f"  CEK REMARKS mengandung '{remark_kw}'" +
      (f" | vendor: {vendor_filter}" if vendor_filter else " | semua vendor"))
print("=" * 70)

where = f"LOWER(REMARKS) LIKE '%{remark_kw.lower()}%'"
if vendor_filter:
    where += f" AND UPPER(VENDOR_NAME) LIKE '%{vendor_filter.upper()}%'"

# 1. Ringkasan per vendor + status
print("\n[1] Ringkasan per vendor & status:")
print(con.execute(f"""
    SELECT VENDOR_NAME, HOMEPASS_STATUS, COUNT(*) AS jml
    FROM hpdb
    WHERE {where}
    GROUP BY 1, 2
    ORDER BY 3 DESC
""").fetchdf().to_string())

# 2. Total unik
total = con.execute(f"SELECT COUNT(*) FROM hpdb WHERE {where}").fetchone()[0]
print(f"\n[2] Total HPID dengan '{remark_kw}' di remark: {total:,}")

# 3. Sample 20 baris
print(f"\n[3] Contoh 20 baris:")
print(con.execute(f"""
    SELECT HOMEPASS_ID, VENDOR_NAME, HOMEPASS_STATUS, CITY, CLUSTER_NAME,
           SUBSTR(REMARKS, 1, 40) AS remark_potong
    FROM hpdb
    WHERE {where}
    LIMIT 20
""").fetchdf().to_string())

# 4. Cek juga status DUMMY langsung (kalau ada status bernama dummy)
print(f"\n[4] Cek apakah ada HOMEPASS_STATUS = 'DUMMY':")
print(con.execute("""
    SELECT VENDOR_NAME, HOMEPASS_STATUS, COUNT(*) AS jml
    FROM hpdb
    WHERE UPPER(HOMEPASS_STATUS) LIKE '%DUMMY%'
    GROUP BY 1, 2 ORDER BY 3 DESC
""").fetchdf().to_string())

con.close()
print("\n[DONE]")

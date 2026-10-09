r"""
cari_fat_dummy.py - Cari FAT code dari HPID dummy untuk bahan tes dashboard

Jalankan:
    python cari_fat_dummy.py
    python cari_fat_dummy.py FIBERSTAR      # filter vendor tertentu
"""
import sys
import duckdb

DB = r"C:\hpdb\addhp.duckdb"
vendor = sys.argv[1].upper() if len(sys.argv) > 1 else None

con = duckdb.connect(DB, read_only=True)

FIELDS = ["PROJECT_NAME", "CLUSTER_NAME", "STREET_NAME", "DISTRICT",
          "SUB_DISTRICT", "OLT_LOCATION", "FDT_CODE", "REMARKS",
          "HOUSE_NUMBER", "HOMEPASS_ID", "FAT_CODE", "BUILDING_NAME"]
cond = " OR ".join([f"LOWER({f}) LIKE '%dummy%'" for f in FIELDS])
where = f"({cond})"
if vendor:
    where += f" AND UPPER(VENDOR_NAME) LIKE '%{vendor}%'"

print("=" * 66)
print("  FAT CODE DARI DATA DUMMY" + (f" - vendor {vendor}" if vendor else ""))
print("=" * 66)

total = con.execute(f"SELECT COUNT(*) FROM hpdb WHERE {where}").fetchone()[0]
print(f"\nTotal HPID dummy: {total:,}\n")

if total == 0:
    print("Tidak ada data dummy dengan filter ini.")
    con.close()
    sys.exit(0)

print("[1] FAT CODE dummy (siap dites di FAT Explorer):")
print(con.execute(f"""
    SELECT FAT_CODE, VENDOR_NAME, CITY,
           COUNT(*) AS jml_hpid,
           SUM(CASE WHEN HOMEPASS_STATUS='ASSIGNED' THEN 1 ELSE 0 END) AS assigned,
           SUM(CASE WHEN HOMEPASS_STATUS='ACTIVE' THEN 1 ELSE 0 END) AS active
    FROM hpdb WHERE {where} AND FAT_CODE IS NOT NULL AND TRIM(FAT_CODE) <> ''
    GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 20
""").fetchdf().to_string())

print("\n[2] Contoh HPID dummy (untuk HPID Explorer):")
print(con.execute(f"""
    SELECT HOMEPASS_ID, HOMEPASS_STATUS, VENDOR_NAME, FAT_CODE, CITY,
           SUBSTR(COALESCE(PROJECT_NAME,''),1,28) AS project
    FROM hpdb WHERE {where} LIMIT 15
""").fetchdf().to_string())

print("\n[3] Koordinat dummy (untuk Cek Eligibilitas - copy 'lat, lon'):")
print(con.execute(f"""
    SELECT BUILDING_LATITUDE AS lat, BUILDING_LONGITUDE AS lon,
           FAT_CODE, VENDOR_NAME, CITY
    FROM hpdb WHERE {where}
      AND BUILDING_LATITUDE IS NOT NULL AND TRIM(BUILDING_LATITUDE) <> ''
      AND BUILDING_LATITUDE <> '-'
    LIMIT 10
""").fetchdf().to_string())

print("\n[4] Per vendor:")
print(con.execute(f"""
    SELECT COALESCE(VENDOR_NAME,'(kosong)') AS vendor, COUNT(*) AS jml
    FROM hpdb WHERE {where} GROUP BY 1 ORDER BY 2 DESC
""").fetchdf().to_string())

con.close()
print("\n[DONE]")

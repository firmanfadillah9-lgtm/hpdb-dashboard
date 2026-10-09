"""cek_pola.py — cek apakah pola HPID dummy ada di HPDB"""
import duckdb
con = duckdb.connect(r"C:\hpdb\addhp.duckdb", read_only=True)

print("=== Cari pola '2357-01.BBD%' ===")
print(con.execute("""
    SELECT HOMEPASS_ID, VENDOR_NAME, HOMEPASS_STATUS
    FROM hpdb WHERE HOMEPASS_ID LIKE '2357-01.BBD%' LIMIT 10
""").fetchdf().to_string())

for pola in ["2357-01%", "2254-01%", "2507-01%"]:
    n = con.execute(
        f"SELECT COUNT(*) FROM hpdb WHERE HOMEPASS_ID LIKE '{pola}'"
    ).fetchone()[0]
    print(f"\nTotal HPID LIKE '{pola}': {n:,}")

# Cek vendor own-build ada di HPDB atau tidak
print("\n=== Vendor di HPDB (top 20) ===")
print(con.execute("""
    SELECT VENDOR_NAME, COUNT(*) AS jml FROM hpdb
    GROUP BY 1 ORDER BY 2 DESC LIMIT 20
""").fetchdf().to_string())

# Cek OWNERSHIP OWN BUILT
print("\n=== OWN BUILT di HPDB? ===")
print(con.execute("""
    SELECT OWNERSHIP, COUNT(*) AS jml FROM hpdb
    WHERE UPPER(OWNERSHIP) LIKE '%OWN%'
    GROUP BY 1 ORDER BY 2 DESC
""").fetchdf().to_string())

con.close()

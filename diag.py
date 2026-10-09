"""
diag.py — Diagnosa status_history & status_current
Simpan di C:\hpdb\ lalu jalankan:
    C:\\Users\\RYZEN\\AppData\\Local\\Programs\\Python\\Python312\\python.exe C:\\hpdb\\diag.py
"""
import duckdb

con = duckdb.connect(r"C:\hpdb\addhp.duckdb")

print("=" * 70)
print("  1. TRANSISI PER TANGGAL")
print("=" * 70)
print(con.execute("""
    SELECT change_date,
           COALESCE(status_from, '(BARU)') AS dari,
           status_to AS ke,
           COUNT(*) AS jml
    FROM status_history
    GROUP BY 1, 2, 3
    ORDER BY 1, 4 DESC
""").fetchdf().to_string())

print()
print("=" * 70)
print("  2. DISTRIBUSI STATUS SAAT INI (status_current)")
print("=" * 70)
print(con.execute("""
    SELECT HOMEPASS_STATUS, COUNT(*) AS jml
    FROM status_current
    GROUP BY 1
    ORDER BY 2 DESC
""").fetchdf().to_string())

print()
print("=" * 70)
print("  3. ACTIVE -> AGING : BREAKDOWN PER TANGGAL + CITY (top 20)")
print("=" * 70)
print(con.execute("""
    SELECT change_date, CITY, COUNT(*) AS jml
    FROM status_history
    WHERE status_from = 'ACTIVE' AND status_to = 'AGING'
    GROUP BY 1, 2
    ORDER BY 3 DESC
    LIMIT 20
""").fetchdf().to_string())

print()
print("=" * 70)
print("  4. ACTIVE -> AGING : PER VENDOR")
print("=" * 70)
print(con.execute("""
    SELECT VENDOR_NAME, COUNT(*) AS jml
    FROM status_history
    WHERE status_from = 'ACTIVE' AND status_to = 'AGING'
    GROUP BY 1
    ORDER BY 2 DESC
""").fetchdf().to_string())

print()
print("=" * 70)
print("  5. ASSIGNED -> RESERVED : PER TANGGAL (indikasi penjualan baru?)")
print("=" * 70)
print(con.execute("""
    SELECT change_date, COUNT(*) AS jml
    FROM status_history
    WHERE status_to = 'RESERVED'
    GROUP BY 1
    ORDER BY 1
""").fetchdf().to_string())

con.close()
print("\n[DONE] Diagnosa selesai.")

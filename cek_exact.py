"""cek_exact.py — debug kenapa HPID SUCCESS tidak match di HPDB"""
import duckdb
con = duckdb.connect(r"C:\hpdb\addhp.duckdb", read_only=True)

# Ambil beberapa HPID SUCCESS spesifik dari file, cek exact di HPDB
targets = [
    "2357-01.BBD.011.A02.25",
    "2357-01.BBD.030.A05.25",
    "2254-01.KJB.045.A04.25",
    "2507-01.BDT.016.A02.20",  # dari sample ALITA di Sheet1
]

for t in targets:
    # exact
    ex = con.execute(
        "SELECT HOMEPASS_ID, VENDOR_NAME, HOMEPASS_STATUS FROM hpdb WHERE HOMEPASS_ID = ?", [t]
    ).fetchall()
    print(f"\n[{t}]")
    print(f"  Exact match: {len(ex)} -> {ex[:2]}")
    # cek cluster prefix (tanpa 2 segmen terakhir)
    prefix = ".".join(t.split(".")[:-1])  # sampai sebelum nomor unit
    cnt = con.execute(
        f"SELECT COUNT(*) FROM hpdb WHERE HOMEPASS_ID LIKE '{prefix}%'"
    ).fetchone()[0]
    print(f"  Prefix '{prefix}%': {cnt} HPID di HPDB")
    # tampilkan range nomor yang ADA di cluster ini
    sample = con.execute(
        f"SELECT HOMEPASS_ID FROM hpdb WHERE HOMEPASS_ID LIKE '{prefix}%' ORDER BY HOMEPASS_ID LIMIT 5"
    ).fetchdf()
    print(f"  Contoh yang ada: {sample['HOMEPASS_ID'].tolist()}")

con.close()

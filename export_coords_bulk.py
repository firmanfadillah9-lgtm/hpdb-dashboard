import duckdb, os

con = duckdb.connect(r'data\hpdb.duckdb', read_only=True)
con.execute("""
    COPY (
        SELECT HOMEPASS_ID, HOMEPASS_STATUS,
               BUILDING_LATITUDE, BUILDING_LONGITUDE,
               FAT_CODE, VENDOR_NAME, CLUSTER_NAME
        FROM hpdb
        WHERE BUILDING_LATITUDE IS NOT NULL
          AND BUILDING_LATITUDE NOT IN ('-', '', 'None')
          AND BUILDING_LONGITUDE IS NOT NULL
          AND BUILDING_LONGITUDE NOT IN ('-', '', 'None')
    ) TO 'hpdb_coords_bulk.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)
""")
con.close()
size = os.path.getsize('hpdb_coords_bulk.parquet') / (1024*1024)
print(f'✅ Selesai! Ukuran: {size:.1f} MB')

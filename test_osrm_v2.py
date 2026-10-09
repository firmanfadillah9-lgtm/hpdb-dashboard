"""
test_osrm_v2.py
----------------
Test OSRM tanpa data pole manual.
Pendekatan: snap customer & FAT ke jalan terdekat (nearest), lalu route.

Ground truth dari KML XL (fat_road_distance_m):
  Customer: (-6.167884838, 106.8878169)
  FAT 1 (FKG051S01A03): (-6.167527, 106.886555) -> 188.57
  FAT 2 (DKG5130000):   (-6.167862, 106.886859) -> 142.18
  FAT 3 (FKG051S01A05): (-6.168522, 106.888203) -> 103.99
  FAT 4 (FKG051S01A04): (-6.16806,  106.887461) -> 69.21
"""
import requests
import math

OSRM_BASE = "http://router.project-osrm.org/route/v1"
OSRM_NEAREST = "http://router.project-osrm.org/nearest/v1"

CUSTOMER = (-6.167884838, 106.8878169)

GROUND_TRUTH = [
    ("FKG051S01A03", -6.167527, 106.886555, 188.57),
    ("DKG5130000",   -6.167862, 106.886859, 142.18),
    ("FKG051S01A05", -6.168522, 106.888203, 103.99),
    ("FKG051S01A04", -6.16806,  106.887461, 69.21),
]


def osrm_route(lat1, lon1, lat2, lon2, profile="foot"):
    url = f"{OSRM_BASE}/{profile}/{lon1},{lat1};{lon2},{lat2}"
    try:
        resp = requests.get(url, params={"overview": "false"}, timeout=15)
        data = resp.json()
        if data.get("code") == "Ok":
            return data["routes"][0]["distance"]
    except Exception:
        pass
    return None


def osrm_nearest(lat, lon, profile="foot"):
    """Snap koordinat ke jalan terdekat, return (lat, lon, distance_to_road)"""
    url = f"{OSRM_NEAREST}/{profile}/{lon},{lat}"
    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
        if data.get("code") == "Ok":
            wp = data["waypoints"][0]
            snapped_lon, snapped_lat = wp["location"]
            return snapped_lat, snapped_lon, wp.get("distance", 0)
    except Exception:
        pass
    return None, None, None


print("=" * 75)
print("Pendekatan: Route langsung Customer -> FAT (profile foot)")
print("=" * 75)

for fat_code, flat, flon, ground_truth in GROUND_TRUTH:
    d = osrm_route(CUSTOMER[0], CUSTOMER[1], flat, flon, "foot")
    diff = (d - ground_truth) if d else None
    pct = (d / ground_truth * 100) if d else None
    print(f"{fat_code:15} | GT: {ground_truth:7.2f} | OSRM: {d:7.2f} | "
          f"Selisih: {diff:+7.2f} | Akurasi: {pct:.1f}%")

print()
print("=" * 75)
print("Pendekatan: Snap dulu ke nearest road, baru route")
print("=" * 75)

cust_lat, cust_lon, cust_snap_dist = osrm_nearest(CUSTOMER[0], CUSTOMER[1])
print(f"Customer snap distance to road: {cust_snap_dist:.2f} m")
print()

for fat_code, flat, flon, ground_truth in GROUND_TRUTH:
    fat_snap_lat, fat_snap_lon, fat_snap_dist = osrm_nearest(flat, flon)
    d = osrm_route(cust_lat, cust_lon, fat_snap_lat, fat_snap_lon, "foot")
    if d is not None:
        # Total = jarak snap customer ke jalan + rute + jarak snap FAT ke jalan
        total = cust_snap_dist + d + fat_snap_dist
        diff = total - ground_truth
        pct = total / ground_truth * 100
        print(f"{fat_code:15} | GT: {ground_truth:7.2f} | "
              f"Snap+Route+Snap: {total:7.2f} | Selisih: {diff:+7.2f} | Akurasi: {pct:.1f}%")
    else:
        print(f"{fat_code:15} | Error routing")

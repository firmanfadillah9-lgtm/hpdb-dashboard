"""
test_osrm.py
------------
Test OSRM public API untuk hitung jarak jalan (road distance),
bandingkan dengan ground truth dari tool XL (fat_road_distance_m).

Ground truth dari KML XL:
  Customer: (-6.167884838, 106.8878169)
  Pole terdekat: (-6.168212499999999, 106.88766000000001)
  FAT 1 (FKG051S01A03): (-6.167527, 106.886555) -> road_distance_m: 188.57
  FAT 2 (DKG5130000):   (-6.167862, 106.886859) -> road_distance_m: 142.18
  FAT 3 (FKG051S01A05): (-6.168522, 106.888203) -> road_distance_m: 103.99
  FAT 4 (FKG051S01A04): (-6.16806,  106.887461) -> road_distance_m: 69.21
"""
import requests
import math

OSRM_BASE = "http://router.project-osrm.org/route/v1"

CUSTOMER = (-6.167884838, 106.8878169)
POLE     = (-6.168212499999999, 106.88766000000001)

GROUND_TRUTH = [
    ("FKG051S01A03", -6.167527, 106.886555, 188.57),
    ("DKG5130000",   -6.167862, 106.886859, 142.18),
    ("FKG051S01A05", -6.168522, 106.888203, 103.99),
    ("FKG051S01A04", -6.16806,  106.887461, 69.21),
]


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(a))


def osrm_distance(lat1, lon1, lat2, lon2, profile="foot"):
    """Hitung jarak rute via OSRM. profile: driving/foot/bike"""
    url = f"{OSRM_BASE}/{profile}/{lon1},{lat1};{lon2},{lat2}"
    params = {"overview": "false"}
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        if data.get("code") == "Ok":
            return data["routes"][0]["distance"]
        return None
    except Exception as e:
        print(f"  Error: {e}")
        return None


print("=" * 70)
print("TEST 1: Customer -> Pole (langsung, harusnya dekat dengan air distance)")
print("=" * 70)
air_dist = haversine(CUSTOMER[0], CUSTOMER[1], POLE[0], POLE[1])
print(f"Air distance (haversine): {air_dist:.2f} m")

for profile in ["foot", "driving", "bike"]:
    d = osrm_distance(CUSTOMER[0], CUSTOMER[1], POLE[0], POLE[1], profile)
    print(f"OSRM {profile:10}: {d}")

print()
print("=" * 70)
print("TEST 2: Pole -> FAT (bandingkan dengan ground truth)")
print("=" * 70)

for fat_code, flat, flon, ground_truth in GROUND_TRUTH:
    print(f"\nFAT: {fat_code}")
    print(f"  Ground truth (fat_road_distance_m): {ground_truth}")

    # Air distance customer -> FAT (untuk referensi)
    air_full = haversine(CUSTOMER[0], CUSTOMER[1], flat, flon)
    print(f"  Air distance (customer->FAT)       : {air_full:.2f}")

    for profile in ["foot", "driving"]:
        d_pole_fat = osrm_distance(POLE[0], POLE[1], flat, flon, profile)
        if d_pole_fat is not None:
            total = air_dist + d_pole_fat  # customer->pole (air) + pole->FAT (OSRM)
            diff = total - ground_truth
            print(f"  OSRM {profile:10} pole->FAT: {d_pole_fat:7.2f} | "
                  f"Total (pole_air+route): {total:7.2f} | Selisih: {diff:+.2f}")

    # Coba juga langsung customer -> FAT via OSRM (tanpa pole)
    for profile in ["foot", "driving"]:
        d_direct = osrm_distance(CUSTOMER[0], CUSTOMER[1], flat, flon, profile)
        if d_direct is not None:
            diff2 = d_direct - ground_truth
            print(f"  OSRM {profile:10} direct   : {d_direct:7.2f} | Selisih: {diff2:+.2f}")

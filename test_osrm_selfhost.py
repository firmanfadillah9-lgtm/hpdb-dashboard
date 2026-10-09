"""
test_osrm_selfhost.py
---------------------
Test OSRM self-host (car.lua, port 5001) dengan semua ground truth dari KML XL.
Formula: snap_customer + route(snap_customer->snap_fat) + snap_fat
"""
import requests
import math

OSRM_BASE = "http://localhost:5001"
CUSTOMER = (-6.167884838, 106.8878169)

GROUND_TRUTH = [
    ("FKG051S01A03", -6.167527, 106.886555, 188.57),
    ("DKG5130000",   -6.167862, 106.886859, 142.18),
    ("FKG051S01A05", -6.168522, 106.888203, 103.99),
    ("FKG051S01A04", -6.16806,  106.887461, 69.21),
]


def osrm_nearest(lat, lon, profile="driving"):
    url = f"{OSRM_BASE}/nearest/v1/{profile}/{lon},{lat}"
    resp = requests.get(url, timeout=10)
    data = resp.json()
    if data.get("code") == "Ok":
        wp = data["waypoints"][0]
        slat, slon = wp["location"][1], wp["location"][0]
        return slat, slon, wp.get("distance", 0), wp.get("name", "")
    return None, None, None, None


def osrm_route(lat1, lon1, lat2, lon2, profile="driving"):
    url = f"{OSRM_BASE}/route/v1/{profile}/{lon1},{lat1};{lon2},{lat2}"
    resp = requests.get(url, params={"overview": "false"}, timeout=10)
    data = resp.json()
    if data.get("code") == "Ok":
        return data["routes"][0]["distance"]
    return None


print("=" * 75)
print("Test OSRM Self-Host (car.lua, port 5001)")
print("Formula: snap_customer + route(snap→snap) + snap_fat")
print("=" * 75)

# Snap customer sekali
c_lat, c_lon, c_snap, c_name = osrm_nearest(CUSTOMER[0], CUSTOMER[1])
print(f"\nCustomer: {CUSTOMER}")
print(f"  Snap ke: {c_name} ({c_lat:.6f}, {c_lon:.6f}), jarak snap: {c_snap:.1f}m")
print()

print(f"{'FAT':15} | {'GT':8} | {'Snap_C':8} | {'Route':8} | {'Snap_F':8} | {'Total':8} | {'Selisih':8} | {'Akurasi'}")
print("-" * 85)

for fat_code, flat, flon, gt in GROUND_TRUTH:
    f_lat, f_lon, f_snap, f_name = osrm_nearest(flat, flon)
    route_d = osrm_route(c_lat, c_lon, f_lat, f_lon)

    if route_d is not None:
        total = c_snap + route_d + f_snap
        selisih = total - gt
        akurasi = total / gt * 100
        print(f"{fat_code:15} | {gt:8.2f} | {c_snap:8.1f} | {route_d:8.1f} | {f_snap:8.1f} | "
              f"{total:8.1f} | {selisih:+8.2f} | {akurasi:.1f}%")
    else:
        print(f"{fat_code:15} | {gt:8.2f} | ERROR routing")

print()
print("Ground truth dari KML tool XL 'Homepass Validation' (Olympus)")

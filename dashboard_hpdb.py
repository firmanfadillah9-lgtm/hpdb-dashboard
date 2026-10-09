"""
dashboard_hpdb.py
------------------
Dashboard monitoring HPDB (Homepass Database) - data infrastruktur
gabungan dari homepass_report_daily + homepass_linknet_report_daily.

Data source: Parquet di GitHub Release (didownload & cache lokal),
di-query langsung via DuckDB (tanpa load full ke pandas - hemat RAM).

Cara jalankan:
    streamlit run dashboard_hpdb.py
"""

import streamlit as st
import pandas as pd
import threading
import duckdb
import requests
import os
import hashlib
import io

try:
    OSRM_BASE = st.secrets["osrm"]["url"].rstrip("/")
except Exception:
    OSRM_BASE = "https://router.project-osrm.org"  # fallback ke public server


def osrm_nearest(lat, lon, profile="driving", timeout=8):
    """Snap koordinat ke jalan terdekat. Return (lat, lon, snap_distance_m) atau (None, None, None)."""
    try:
        url = f"{OSRM_BASE}/nearest/v1/{profile}/{lon},{lat}"
        resp = requests.get(url, timeout=timeout)
        data = resp.json()
        if data.get("code") == "Ok":
            wp = data["waypoints"][0]
            snapped_lon, snapped_lat = wp["location"]
            return snapped_lat, snapped_lon, wp.get("distance", 0)
    except Exception:
        pass
    return None, None, None


def osrm_route_distance(lat1, lon1, lat2, lon2, profile="driving", timeout=8):
    """Hitung jarak rute jalan antara 2 titik (yang sudah di-snap). Return distance_m atau None."""
    try:
        url = f"{OSRM_BASE}/route/v1/{profile}/{lon1},{lat1};{lon2},{lat2}"
        resp = requests.get(url, params={"overview": "false"}, timeout=timeout)
        data = resp.json()
        if data.get("code") == "Ok":
            return data["routes"][0]["distance"]
    except Exception:
        pass
    return None


def osrm_route_geometry(lat1, lon1, lat2, lon2, profile="driving", timeout=8):
    """Ambil geometri rute jalan (list [lat, lon]) antara 2 titik. Return list atau None."""
    try:
        url = f"{OSRM_BASE}/route/v1/{profile}/{lon1},{lat1};{lon2},{lat2}"
        resp = requests.get(url, params={"overview": "full", "geometries": "geojson"}, timeout=timeout)
        data = resp.json()
        if data.get("code") == "Ok":
            coords = data["routes"][0]["geometry"]["coordinates"]  # [[lon,lat],...]
            return [[c[1], c[0]] for c in coords]
    except Exception:
        pass
    return None


def calc_road_distance(cust_lat, cust_lon, fat_lat, fat_lon, profile="driving"):
    """
    Hitung road distance dari customer ke FAT, mereplikasi formula tool XL
    "Homepass Validation" (Olympus): snap kedua titik ke jalan terdekat,
    lalu hitung rute antar titik snap tersebut.

    road_distance = snap(customer->jalan) + route(jalan->jalan) + snap(FAT->jalan)

    Return dict: {road_distance_m, success, detail}
    """
    c_lat, c_lon, c_snap = osrm_nearest(cust_lat, cust_lon, profile)
    if c_lat is None:
        return {"road_distance_m": None, "success": False, "detail": "Gagal snap koordinat customer ke jalan"}

    f_lat, f_lon, f_snap = osrm_nearest(fat_lat, fat_lon, profile)
    if f_lat is None:
        return {"road_distance_m": None, "success": False, "detail": "Gagal snap koordinat FAT ke jalan"}

    route_dist = osrm_route_distance(c_lat, c_lon, f_lat, f_lon, profile)
    if route_dist is None:
        return {"road_distance_m": None, "success": False, "detail": "Gagal hitung rute jalan (kemungkinan tidak terhubung)"}

    total = c_snap + route_dist + f_snap
    return {
        "road_distance_m": round(total, 1),
        "success": True,
        "detail": f"snap_customer={c_snap:.1f}m + route={route_dist:.1f}m + snap_fat={f_snap:.1f}m"
    }

from datetime import datetime

# ─── KONFIGURASI ────────────────────────────────────────────────────────────
GITHUB_OWNER = "firmanfadillah9-lgtm"
GITHUB_REPO  = "hpdb-dashboard"
RELEASE_TAG  = "latest-data"
ASSET_NAME   = "hpdb.parquet"
LOCAL_CACHE  = "hpdb_cache.parquet"

st.set_page_config(
    page_title="HPDB — Infrastructure Monitoring",
    page_icon="🏗️",
    layout="wide"
)


# ─── AUTHENTICATION (reuse pattern dari Homepass dashboard) ───────────────
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def get_users():
    try:
        return st.secrets["credentials"]
    except Exception:
        return {}


def check_login():
    if st.session_state.get("authenticated", False):
        return True

    st.title("🔐 Login — HPDB Monitoring")

    users = get_users()
    if not users:
        st.error("⚠️ Belum ada user dikonfigurasi di Secrets.")
        return False

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    if submitted:
        user = users.get(username)
        if user and hash_password(password) == user.get("password_hash"):
            st.session_state["authenticated"] = True
            st.session_state["user_role"] = user.get("role", "viewer")
            st.session_state["user_name"] = user.get("name", username)
            st.rerun()
        else:
            st.error("❌ Username atau password salah")

    return False


if not check_login():
    st.stop()


def logout():
    for k in ("authenticated", "user_role", "user_name"):
        st.session_state.pop(k, None)
    st.rerun()


# ─── DOWNLOAD & CACHE PARQUET (via GitHub API, repo private) ──────────────
def _get_github_token():
    try:
        return st.secrets["github"]["token"]
    except Exception:
        pass
    try:
        from github_config import GITHUB_TOKEN
        return GITHUB_TOKEN
    except ImportError:
        return None


def _get_asset_download_info():
    """Dapatkan asset API url untuk hpdb.parquet dari release (perlu auth, repo private)."""
    token = _get_github_token()
    if not token:
        raise RuntimeError(
            "GitHub token belum dikonfigurasi di Secrets. "
            "Tambahkan [github] token = \"...\" di Streamlit Secrets."
        )
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tags/{RELEASE_TAG}"
    resp = requests.get(api_url, headers=headers, timeout=30)
    resp.raise_for_status()
    release = resp.json()
    for asset in release.get("assets", []):
        if asset["name"] == ASSET_NAME:
            return asset["url"], asset["updated_at"], token
    raise FileNotFoundError(f"Asset '{ASSET_NAME}' tidak ditemukan di release '{RELEASE_TAG}'")


@st.cache_resource(ttl=3600)  # cek update tiap 1 jam
def get_data_path():
    """Download parquet dari GitHub Release (private repo, perlu auth) kalau belum ada."""
    if not os.path.exists(LOCAL_CACHE):
        with st.spinner("📥 Mengunduh data HPDB (≈200MB, pertama kali saja)..."):
            asset_url, updated_at, token = _get_asset_download_info()
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/octet-stream",
            }
            resp = requests.get(asset_url, headers=headers, stream=True, timeout=600)
            resp.raise_for_status()
            with open(LOCAL_CACHE, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    f.write(chunk)
    return LOCAL_CACHE


@st.cache_resource
def get_connection():
    """DuckDB connection, query langsung dari file parquet (lazy/columnar)."""
    path = get_data_path()
    con = duckdb.connect(":memory:")
    # Streamlit Community Cloud memberi ~1 GB per app. Tanpa batas,
    # DuckDB memakai default ~80% RAM HOST (bukan batas container),
    # lalu container dibunuh OOM tanpa traceback -- itu penyebab
    # "Oh no" dan healthz connection reset.
    con.execute("SET memory_limit='500MB'")
    con.execute("SET threads=2")
    con.execute("SET temp_directory='/tmp/duckdb_spill'")
    con.execute(f"CREATE VIEW hpdb AS SELECT * FROM read_parquet('{path}')")
    return con


# ---------------------------------------------------------------------------
# Pembungkus aman-thread untuk DuckDB.
#
# @st.cache_resource membagikan SATU objek koneksi ke semua sesi dan semua
# thread, sementara Streamlit menjalankan tiap rerun di thread terpisah.
# Pola con.execute(...).df() itu dua langkah: execute menaruh hasil di
# koneksi, .df() mengambilnya. Kalau thread lain memanggil execute di antara
# keduanya, hasilnya tertimpa -> .df() mengembalikan None (AttributeError),
# dan pada kasus terburuk state internal DuckDB rusak -> segfault tanpa
# traceback.
#
# Dengan memberi setiap query cursor-nya sendiri, tiap pemanggil punya
# result set terpisah. Cursor DuckDB murah dan berbagi database yang sama.
# ---------------------------------------------------------------------------
class _DuckAmanThread:
    def __init__(self, base):
        self._base = base
        self._kunci = threading.Lock()

    def execute(self, *args, **kwargs):
        with self._kunci:
            cur = self._base.cursor()
        return cur.execute(*args, **kwargs)

    def __getattr__(self, nama):
        return getattr(self._base, nama)


con = _DuckAmanThread(get_connection())


# ---------------------------------------------------------------------------
# Helper ber-cache.
# Streamlit menjalankan ULANG seluruh skrip setiap kali satu widget disentuh.
# Tanpa cache, tab Overview + sidebar memakan ~2,4 detik di SETIAP interaksi.
# Kunci cache-nya hanya string filter, jadi kombinasi yang sama langsung
# dijawab dari memori.
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def opsi_distinct(kolom: str):
    """Daftar nilai unik satu kolom untuk dropdown sidebar."""
    rows = con.execute(
        f"SELECT DISTINCT {kolom} FROM hpdb WHERE {kolom} IS NOT NULL ORDER BY 1"
    ).fetchall()
    return ["Semua"] + [r[0] for r in rows]


@st.cache_data(ttl=3600, show_spinner=False)
def metrik_overview(w: str):
    """Enam metrik Overview dalam SATU kali pembacaan parquet.

    Sebelumnya enam query terpisah (1,95 s). Digabung jadi 1,32 s, lalu
    nol pada interaksi berikutnya karena di-cache.
    """
    return con.execute(f"""
        SELECT COUNT(*) AS total_rows,
               COUNT(*) FILTER (WHERE HOMEPASS_ID <> '-----')       AS total_hp,
               COUNT(*) FILTER (WHERE HOMEPASS_STATUS = 'ACTIVE')   AS aktif,
               COUNT(*) FILTER (WHERE HOMEPASS_STATUS = 'ASSIGNED') AS assigned,
               COUNT(DISTINCT FAT_CODE) FILTER (WHERE FAT_CODE <> '-') AS total_fat,
               COUNT(DISTINCT FAT_CODE) FILTER (
                    WHERE FAT_CODE IS NOT NULL AND FAT_CODE <> '-'
                      AND TRY_CAST(FAT_LATITUDE  AS DOUBLE) IS NOT NULL
                      AND TRY_CAST(FAT_LONGITUDE AS DOUBLE) IS NOT NULL) AS fat_points
        FROM hpdb WHERE {w}
    """).fetchone()


@st.cache_data(ttl=3600, show_spinner=False)
def df_region_status(w: str):
    return con.execute(f"""
        SELECT REGION, HOMEPASS_STATUS, COUNT(*) as jumlah
        FROM hpdb WHERE {w} AND REGION IS NOT NULL
        GROUP BY REGION, HOMEPASS_STATUS ORDER BY REGION
    """).df()


@st.cache_data(ttl=3600, show_spinner=False)
def df_vendor_top(w: str):
    return con.execute(f"""
        SELECT VENDOR_NAME, COUNT(*) as jumlah
        FROM hpdb
        WHERE {w} AND VENDOR_NAME IS NOT NULL AND VENDOR_NAME <> '-'
        GROUP BY VENDOR_NAME ORDER BY jumlah DESC LIMIT 15
    """).df()


# ─── SIDEBAR ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"**{st.session_state.get('user_name', '')}**")
    role_label = "👑 Super Admin" if st.session_state.get("user_role") == "super_admin" else "👤 Viewer"
    st.caption(role_label)
    if st.button("🚪 Logout"):
        logout()
    st.markdown("---")

    st.title("🔍 Filter")

    selected_region = st.selectbox("Region", opsi_distinct("REGION"))
    selected_vendor = st.selectbox("Vendor", opsi_distinct("VENDOR_NAME"))

    if st.button("🔄 Refresh Data"):
        if os.path.exists(LOCAL_CACHE):
            os.remove(LOCAL_CACHE)
        st.cache_resource.clear()
        st.rerun()


# Build WHERE clause dari filter
where_clauses = []
if selected_region != "Semua":
    where_clauses.append(f"REGION = '{selected_region}'")
if selected_vendor != "Semua":
    where_clauses.append(f"VENDOR_NAME = '{selected_vendor}'")
where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"


# ─── HELPER: RENDER DETAIL FAT (dipakai di FAT Explorer & Cek Eligibilitas) ──
def render_fat_detail(con, fat_code):
    """Render detail FAT, utilisasi port, dan daftar homepass untuk fat_code tertentu."""
    detail = con.execute("""
        SELECT FAT_CODE, FDT_CODE, OLT_NAME, OLT_LOCATION, OLT_LOCATION_CODE,
               REGION, MOBILE_REGION, MOBILE_CLUSTER, CITY, CITY_GROUP,
               CLUSTER_NAME, CLUSTER_CODE, PROJECT_NAME, BUILDING_TYPE,
               FAT_LATITUDE, FAT_LONGITUDE, FDT_LATITUDE, FDT_LONGITUDE
        FROM hpdb
        WHERE FAT_CODE = ?
        LIMIT 1
    """, [fat_code]).df()

    if not detail.empty:
        d = detail.iloc[0]
        st.markdown(f"### 📍 FAT: `{d['FAT_CODE']}`")

        dc1, dc2, dc3 = st.columns(3)
        with dc1:
            st.markdown("**Jaringan**")
            st.write(f"FDT Code: {d['FDT_CODE']}")
            st.write(f"OLT Name: {d['OLT_NAME']}")
            st.write(f"OLT Location: {d['OLT_LOCATION']} ({d['OLT_LOCATION_CODE']})")
        with dc2:
            st.markdown("**Lokasi**")
            st.write(f"Region: {d['REGION']}")
            st.write(f"Mobile Region/Cluster: {d['MOBILE_REGION']} / {d['MOBILE_CLUSTER']}")
            st.write(f"City: {d['CITY']} ({d['CITY_GROUP']})")
            st.write(f"Cluster: {d['CLUSTER_NAME']} ({d['CLUSTER_CODE']})")
        with dc3:
            st.markdown("**Proyek & Koordinat**")
            st.write(f"Project: {d['PROJECT_NAME']}")
            st.write(f"Building Type: {d['BUILDING_TYPE']}")
            st.write(f"FAT Coord: {d['FAT_LATITUDE']}, {d['FAT_LONGITUDE']}")
            st.write(f"FDT Coord: {d['FDT_LATITUDE']}, {d['FDT_LONGITUDE']}")

    st.markdown("---")

    # ─── UTILISASI ──────────────────────────────────────────────────────────
    status_counts = con.execute("""
        SELECT HOMEPASS_STATUS, COUNT(*) as jumlah
        FROM hpdb WHERE FAT_CODE = ?
        GROUP BY HOMEPASS_STATUS
        ORDER BY jumlah DESC
    """, [fat_code]).df()

    total_ports = int(status_counts["jumlah"].sum())
    used_ports = int(status_counts[
        status_counts["HOMEPASS_STATUS"].isin(["ACTIVE", "ASSIGNED"])
    ]["jumlah"].sum())
    utilization = (used_ports / total_ports * 100) if total_ports > 0 else 0

    st.markdown("#### 📊 Utilisasi Port")
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Total Port", f"{total_ports}")
    mc2.metric("Terpakai (Active+Assigned)", f"{used_ports}")
    mc3.metric("Utilisasi", f"{utilization:.1f}%")

    status_col, _ = st.columns([1, 2])
    with status_col:
        st.dataframe(
            status_counts, use_container_width=True, hide_index=True,
            column_config={
                "HOMEPASS_STATUS": st.column_config.TextColumn("Status"),
                "jumlah": st.column_config.NumberColumn("Jumlah"),
            }
        )

    st.markdown("---")

    # ─── DAFTAR HOMEPASS ────────────────────────────────────────────────────
    st.markdown("#### 🏠 Daftar Homepass pada FAT ini")

    hpid_list = con.execute("""
        SELECT HOMEPASS_ID, HOMEPASS_STATUS, VENDOR_NAME, NETWORK_ID,
               FRAME, SLOT, PORT, RFS_DATE, BUILDING_NAME, FULL_ADDRESS,
               IP_DEVICE, VLAN_SERVICE, SOURCE_FILE, REMARKS
        FROM hpdb
        WHERE FAT_CODE = ?
        ORDER BY
            CASE WHEN PORT ~ '^[0-9]+$' THEN CAST(PORT AS INTEGER) ELSE 999 END,
            PORT
    """, [fat_code]).df()

    st.dataframe(
        hpid_list,
        use_container_width=True,
        hide_index=True,
        height=400,
        column_config={
            "HOMEPASS_ID": st.column_config.TextColumn("Homepass ID"),
            "HOMEPASS_STATUS": st.column_config.TextColumn("Status"),
            "VENDOR_NAME": st.column_config.TextColumn("Vendor"),
            "NETWORK_ID": st.column_config.TextColumn("Network ID"),
            "FRAME": st.column_config.TextColumn("Frame"),
            "SLOT": st.column_config.TextColumn("Slot"),
            "PORT": st.column_config.TextColumn("Port"),
            "RFS_DATE": st.column_config.TextColumn("RFS Date"),
            "BUILDING_NAME": st.column_config.TextColumn("Building"),
            "FULL_ADDRESS": st.column_config.TextColumn("Alamat"),
            "IP_DEVICE": st.column_config.TextColumn("IP Device"),
            "VLAN_SERVICE": st.column_config.TextColumn("VLAN"),
            "SOURCE_FILE": st.column_config.TextColumn("Source"),
            "REMARKS": st.column_config.TextColumn("Remarks"),
        }
    )
    st.caption(f"Total {len(hpid_list)} baris untuk FAT `{fat_code}`")


# ─── TABS ───────────────────────────────────────────────────────────────────
st.title("🏗️ HPDB — Infrastructure Monitoring")

tab_overview, tab_fat, tab_hpid, tab_eligibility, tab_bulk, tab_progress, tab_dummy = st.tabs(
    ["📊 Network Overview", "🔎 FAT Explorer", "🏠 HPID Explorer", "📍 Cek Eligibilitas", "📋 Bulk Check (Excel)", "📈 Monthly Progress", "🎯 Dummy Monitor"]
)


# ═══════════════════════════════════════════════════════════════════════════
# TAB: NETWORK OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner="Memuat data koordinat HPID...")
def get_coords_con():
    try:
        path = "hpdb_coords_bulk_cache.parquet"
        if not os.path.exists(path):
            token = st.secrets.get("github", {}).get("token", "")
            headers = {"Accept": "application/vnd.github+json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            rel = requests.get(
                "https://api.github.com/repos/firmanfadillah9-lgtm/homepass-npd-dashboard/releases/tags/latest-data",
                headers=headers, timeout=15
            )
            if rel.status_code != 200:
                return None, None
            assets = rel.json().get("assets", [])
            asset_url = next((a["url"] for a in assets if a["name"] == "hpdb_coords_bulk.parquet"), None)
            if not asset_url:
                return None, None
            dl = requests.get(
                asset_url,
                headers={**headers, "Accept": "application/octet-stream"},
                stream=True, timeout=300
            )
            if dl.status_code != 200:
                return None, None
            # Dialirkan per potongan; dl.content akan menahan seluruh
            # berkas (~56 MB) di memori sekaligus.
            with open(path, "wb") as f:
                for chunk in dl.iter_content(chunk_size=1024 * 256):
                    f.write(chunk)
        coords_con = duckdb.connect()
        coords_con.execute("SET memory_limit='250MB'")
        coords_con.execute("SET threads=2")
        coords_con.execute("SET temp_directory='/tmp/duckdb_spill'")
        coords_con.execute(f"CREATE VIEW coords AS SELECT * FROM read_parquet('{path}')")
        coords_con.execute("""
            CREATE VIEW coords_f AS
            SELECT *,
                TRY_CAST(BUILDING_LATITUDE AS DOUBLE) AS blat,
                TRY_CAST(BUILDING_LONGITUDE AS DOUBLE) AS blon
            FROM coords
            WHERE TRY_CAST(BUILDING_LATITUDE AS DOUBLE) IS NOT NULL
              AND TRY_CAST(BUILDING_LONGITUDE AS DOUBLE) IS NOT NULL
        """)
        return _DuckAmanThread(coords_con), path
    except Exception as e:
        return None, None


with tab_overview:

    # Enam metrik sekaligus dari satu query ber-cache.
    (total_rows, total_hp, active, assigned,
     total_fat, total_fat_points) = metrik_overview(where_sql)

    st.caption(f"Total records (sesuai filter): {total_rows:,}")

    # ─── METRICS ────────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Homepass", f"{total_hp:,}")
    col2.metric("Active", f"{active:,}")
    col3.metric("Assigned", f"{assigned:,}")
    col4.metric("Total FAT", f"{total_fat:,}")

    st.markdown("---")

    # ─── BREAKDOWN PER REGION ─────────────────────────────────────────────────
    st.subheader("📍 Breakdown per Region")

    df_region = df_region_status(where_sql)

    if not df_region.empty:
        import plotly.express as px
        fig = px.bar(
            df_region, x="REGION", y="jumlah", color="HOMEPASS_STATUS",
            title="Distribusi Status per Region",
            labels={"jumlah": "Jumlah", "REGION": "Region", "HOMEPASS_STATUS": "Status"}
        )
        fig.update_layout(height=450, xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

    # ─── BREAKDOWN PER VENDOR ─────────────────────────────────────────────────
    st.subheader("🏢 Breakdown per Vendor")

    df_vendor = df_vendor_top(where_sql)

    if not df_vendor.empty:
        import plotly.express as px
        fig2 = px.bar(
            df_vendor, x="VENDOR_NAME", y="jumlah",
            title="Top 15 Vendor by Jumlah Record",
            labels={"jumlah": "Jumlah", "VENDOR_NAME": "Vendor"}
        )
        fig2.update_layout(height=400, xaxis_tickangle=-45)
        st.plotly_chart(fig2, use_container_width=True)

    # ─── PETA CAKUPAN FAT (radius 150m) ───────────────────────────────────────
    st.markdown("---")
    st.subheader("🗺️ Peta Cakupan FAT (radius 150m)")

    MAX_MAP_POINTS = 50_000

    # total_fat_points sudah ikut dihitung di metrik_overview(where_sql)

    if total_fat_points == 0:
        st.info("Tidak ada koordinat FAT untuk ditampilkan sesuai filter saat ini.")
    elif total_fat_points > MAX_MAP_POINTS:
        st.warning(
            f"Ada **{total_fat_points:,}** FAT sesuai filter saat ini — terlalu banyak untuk "
            f"ditampilkan di peta (maks {MAX_MAP_POINTS:,}). "
            f"Persempit dengan filter **Region** dan/atau **Vendor** di sidebar."
        )
    else:
        st.caption(f"{total_fat_points:,} FAT sesuai filter saat ini.")
        show_map = st.checkbox("📍 Tampilkan peta", key="show_fat_map")

        if show_map:
            @st.cache_data(ttl=3600, show_spinner="Memuat titik FAT...")
            def load_fat_points(where_sql):
                return con.execute(f"""
                    SELECT DISTINCT
                        FAT_CODE, CLUSTER_NAME, CITY, REGION,
                        TRY_CAST(FAT_LATITUDE AS DOUBLE) AS lat,
                        TRY_CAST(FAT_LONGITUDE AS DOUBLE) AS lon
                    FROM hpdb
                    WHERE {where_sql} AND FAT_CODE IS NOT NULL AND FAT_CODE != '-'
                      AND TRY_CAST(FAT_LATITUDE AS DOUBLE) IS NOT NULL
                      AND TRY_CAST(FAT_LONGITUDE AS DOUBLE) IS NOT NULL
                """).df()

            df_fat_points = load_fat_points(where_sql)

            st.map(df_fat_points, latitude="lat", longitude="lon", zoom=11, size=15)
            st.caption(
                f"Menampilkan {len(df_fat_points):,} titik lokasi FAT. "
                f"Untuk cek radius 150m presisi pada satu titik, gunakan tab 'Cek Eligibilitas'."
            )


# ═══════════════════════════════════════════════════════════════════════════
# TAB: FAT EXPLORER
# ═══════════════════════════════════════════════════════════════════════════
with tab_fat:
    st.subheader("🔎 FAT Explorer")
    st.caption("Cari FAT Code untuk melihat detail lokasi, utilisasi port, dan daftar Homepass ID.")

    search_term = st.text_input(
        "Cari FAT Code",
        placeholder="Contoh: C04 atau FTI082S02B03 (bisa sebagian)",
        key="fat_search"
    )

    if search_term:
        matches = con.execute("""
            SELECT DISTINCT FAT_CODE, FDT_CODE, REGION, CITY, CLUSTER_NAME
            FROM hpdb
            WHERE FAT_CODE ILIKE ? AND FAT_CODE != '-' AND FAT_CODE IS NOT NULL
            ORDER BY FAT_CODE
            LIMIT 50
        """, [f"%{search_term}%"]).df()

        if matches.empty:
            st.warning("Tidak ditemukan FAT dengan kode tersebut.")
        else:
            if len(matches) > 1:
                st.caption(f"Ditemukan {len(matches)} FAT (maks 50 ditampilkan). Pilih salah satu:")
                option_labels = [
                    f"{row.FAT_CODE} — {row.CLUSTER_NAME} | {row.CITY}, {row.REGION} (FDT: {row.FDT_CODE})"
                    for row in matches.itertuples()
                ]
                selected_idx = st.selectbox(
                    "Pilih FAT", range(len(matches)),
                    format_func=lambda i: option_labels[i],
                    key="fat_select"
                )
            else:
                selected_idx = 0

            selected_fat = matches.iloc[selected_idx]["FAT_CODE"]

            render_fat_detail(con, selected_fat)

    else:
        st.info("Masukkan FAT Code untuk mulai mencari.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB: HPID EXPLORER
# ═══════════════════════════════════════════════════════════════════════════
with tab_hpid:
    st.subheader("🏠 HPID Explorer")
    st.caption("Cari berdasarkan Homepass ID untuk melihat detail lengkap.")

    hpid_search = st.text_input(
        "Cari Homepass ID",
        placeholder="Contoh: 02896851 (bisa sebagian)",
        key="hpid_search"
    )

    if hpid_search:
        term = hpid_search.strip()

        # Coba exact match dulu, kalau tidak ada coba partial
        result = con.execute("""
            SELECT * FROM hpdb WHERE HOMEPASS_ID = ?
        """, [term]).df()

        if result.empty:
            result = con.execute("""
                SELECT * FROM hpdb
                WHERE HOMEPASS_ID ILIKE ? AND HOMEPASS_ID != '-----'
                LIMIT 50
            """, [f"%{term}%"]).df()

        if result.empty:
            st.warning("Homepass ID tidak ditemukan.")
        else:
            if len(result) > 1:
                st.caption(f"Ditemukan {len(result)} hasil. Pilih salah satu:")
                option_labels = [
                    f"{row.HOMEPASS_ID} — {row.HOMEPASS_STATUS} | {row.CLUSTER_NAME}, {row.CITY} ({row.SOURCE_FILE})"
                    for row in result.itertuples()
                ]
                idx = st.selectbox(
                    "Pilih Homepass", range(len(result)),
                    format_func=lambda i: option_labels[i],
                    key="hpid_select"
                )
            else:
                idx = 0

            r = result.iloc[idx]

            def _v(col):
                val = r.get(col)
                if val is None or (isinstance(val, str) and val.strip() in ("", "-", "None", "nan")):
                    return "-"
                return val

            # Status badge
            status_icons = {
                "ACTIVE": "🟢", "ASSIGNED": "🔵", "RESERVED": "🟡",
                "NOT_AVAILABLE": "⚪", "AGING": "🟠", "LOCKED": "🔴",
            }
            icon = status_icons.get(_v("HOMEPASS_STATUS"), "⚫")
            st.markdown(f"### {icon} Homepass `{_v('HOMEPASS_ID')}` — **{_v('HOMEPASS_STATUS')}**")

            full_addr = _v("FULL_ADDRESS")
            if full_addr != "-":
                st.markdown(f"📍 {full_addr}")

            st.markdown("---")

            # 3 kolom layout, ~17 field masing-masing
            col_a = [
                ("Region", "REGION"),
                ("City", "CITY"),
                ("District", "DISTRICT"),
                ("Cluster Name", "CLUSTER_NAME"),
                ("Prefix Address", "PREFIX_ADDRESS"),
                ("Street Name", "STREET_NAME"),
                ("RT", "RT"),
                ("RW", "RW"),
                ("Block", "BLOCK"),
                ("House Number", "HOUSE_NUMBER"),
                ("Acquisition Class", "ACQUISITION_CLASS"),
                ("Acquisition Tier", "ACQUISITION_TIER"),
                ("Competition", "COMPETITION"),
                ("Building Type", "BUILDING_TYPE"),
                ("Ownership", "OWNERSHIP"),
                ("Partner RFS Date", "PARTNER_RFS_DATE"),
            ]
            col_b = [
                ("Vendor Name", "VENDOR_NAME"),
                ("Project Name", "PROJECT_NAME"),
                ("City Code", "CITY_CODE"),
                ("Project ID", "PROJECT_ID"),
                ("Residence", "RESIDENCE_NAME"),
                ("Cluster Code", "CLUSTER_CODE"),
                ("Floor", "FLOOR"),
                ("Sub District", "SUB_DISTRICT"),
                ("Zip Code", "ZIP_CODE"),
                ("OLT Location", "OLT_LOCATION"),
                ("OLT Location Code", "OLT_LOCATION_CODE"),
                ("OLT Device Code", "OLT_DEVICE_CODE"),
                ("OLT Name", "OLT_NAME"),
                ("FDT Code", "FDT_CODE"),
                ("FAT Code", "FAT_CODE"),
                ("Mobile Cluster", "MOBILE_CLUSTER"),
                ("Building Name", "BUILDING_NAME"),
            ]
            col_c = [
                ("FDT Latitude", "FDT_LATITUDE"),
                ("FDT Longitude", "FDT_LONGITUDE"),
                ("FAT Latitude", "FAT_LATITUDE"),
                ("FAT Longitude", "FAT_LONGITUDE"),
                ("Network ID", "NETWORK_ID"),
                ("Frame", "FRAME"),
                ("Slot", "SLOT"),
                ("Port", "PORT"),
                ("IP Device", "IP_DEVICE"),
                ("Vlan Service", "VLAN_SERVICE"),
                ("RFS Date", "RFS_DATE"),
                ("Remarks", "REMARKS"),
                ("Counter", "COUNTER"),
                ("Building Latitude", "BUILDING_LATITUDE"),
                ("Building Longitude", "BUILDING_LONGITUDE"),
                ("Mobile Region", "MOBILE_REGION"),
                ("City Group", "CITY_GROUP"),
            ]

            def render_field_group(fields):
                lines = []
                for label, col in fields:
                    lines.append(f"**{label}**: {_v(col)}  ")
                st.markdown("\n".join(lines))

            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                render_field_group(col_a)
            with fc2:
                render_field_group(col_b)
            with fc3:
                render_field_group(col_c)

            # Metadata tambahan (khusus data LINKNET)
            if _v("SOURCE_FILE") == "LINKNET":
                st.markdown("---")
                st.caption(
                    f"Source: {_v('SOURCE_FILE')} | ID: {_v('ID')} | "
                    f"Created: {_v('CREATED')} | Updated: {_v('UPDATED')}"
                )
            else:
                st.markdown("---")
                st.caption(f"Source: {_v('SOURCE_FILE')}")

    else:
        st.info("Masukkan Homepass ID untuk mulai mencari.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB: CEK ELIGIBILITAS KOORDINAT
# ═══════════════════════════════════════════════════════════════════════════
with tab_eligibility:
    st.subheader("📍 Cek Eligibilitas Koordinat")
    st.caption(
        "Cek apakah sebuah koordinat berada dalam radius 150m dari FAT terdekat "
        "(syarat eligible untuk pemasangan)."
    )

    RADIUS_M = 150

    coord_input = st.text_input(
        "Masukkan koordinat (format: latitude, longitude)",
        placeholder="Contoh: -6.212626, 106.697242",
        key="eligibility_coord"
    )

    if coord_input:
        try:
            parts = [p.strip() for p in coord_input.replace(";", ",").split(",")]
            if len(parts) != 2:
                raise ValueError
            input_lat = float(parts[0])
            input_lon = float(parts[1])
            if not (-90 <= input_lat <= 90 and -180 <= input_lon <= 180):
                raise ValueError
        except ValueError:
            input_lat = None
            input_lon = None
            st.error("Format koordinat tidak valid. Gunakan format: -6.212626, 106.697242")

        if input_lat is not None:
            # Bounding box ±0.003° (~330m, generous) untuk pre-filter sebelum hitung haversine exact
            BUFFER_DEG = 0.003
            lat_min, lat_max = input_lat - BUFFER_DEG, input_lat + BUFFER_DEG
            lon_min, lon_max = input_lon - BUFFER_DEG, input_lon + BUFFER_DEG

            nearby = con.execute("""
                WITH fat_coords AS (
                    SELECT DISTINCT
                        FAT_CODE, FDT_CODE, REGION, CITY, CLUSTER_NAME,
                        TRY_CAST(FAT_LATITUDE AS DOUBLE) AS lat,
                        TRY_CAST(FAT_LONGITUDE AS DOUBLE) AS lon
                    FROM hpdb
                    WHERE FAT_CODE IS NOT NULL AND FAT_CODE != '-'
                      AND TRY_CAST(FAT_LATITUDE AS DOUBLE) IS NOT NULL
                      AND TRY_CAST(FAT_LONGITUDE AS DOUBLE) IS NOT NULL
                      AND TRY_CAST(FAT_LATITUDE AS DOUBLE) BETWEEN ? AND ?
                      AND TRY_CAST(FAT_LONGITUDE AS DOUBLE) BETWEEN ? AND ?
                )
                SELECT *,
                    6371000 * acos(
                        LEAST(1.0, GREATEST(-1.0,
                            cos(radians(?)) * cos(radians(lat)) * cos(radians(lon) - radians(?)) +
                            sin(radians(?)) * sin(radians(lat))
                        ))
                    ) AS distance_m
                FROM fat_coords
                ORDER BY distance_m
            """, [lat_min, lat_max, lon_min, lon_max, input_lat, input_lon, input_lat]).df()

            within_radius = nearby[nearby["distance_m"] <= RADIUS_M] if not nearby.empty else nearby

            if not nearby.empty:
                nearby["distance_m"] = nearby["distance_m"].round(1)

            # ─── HITUNG ROAD DISTANCE untuk top 5 FAT terdekat ──────────────
            top_n = min(5, len(nearby))
            road_results = {}
            if top_n > 0:
                with st.spinner(f"Menghitung jarak jalan (road distance) untuk {top_n} FAT terdekat..."):
                    for idx in range(top_n):
                        row = nearby.iloc[idx]
                        result = calc_road_distance(
                            input_lat, input_lon, row["lat"], row["lon"]
                        )
                        road_results[row["FAT_CODE"]] = result

            # ─── PETA (Folium — satelit + marker interaktif) ─────────────────
            import folium
            from streamlit_folium import st_folium

            fmap = folium.Map(
                location=[input_lat, input_lon], zoom_start=18, max_zoom=21, tiles=None,
            )
            # Satelit Esri: tile native hanya sampai z19 — di atas itu tile z19
            # di-upscale (maxNativeZoom) supaya peta tidak jadi abu-abu kosong.
            folium.TileLayer(
                tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                attr="Esri World Imagery", name="Satelit",
                max_zoom=21, max_native_zoom=19,
            ).add_to(fmap)
            # Layer label jalan di atas satelit
            folium.TileLayer(
                tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
                attr="Esri", name="Labels", overlay=True, control=False,
                max_zoom=21, max_native_zoom=19,
            ).add_to(fmap)

            # Titik input (biru)
            folium.Marker(
                [input_lat, input_lon],
                tooltip="📍 Koordinat yang dicek",
                popup=f"Input: {input_lat}, {input_lon}",
                icon=folium.Icon(color="blue", icon="home", prefix="fa"),
            ).add_to(fmap)

            # Lingkaran radius eligibilitas 150m
            folium.Circle(
                [input_lat, input_lon], radius=RADIUS_M,
                color="#0080FF", fill=True, fill_opacity=0.06, weight=2,
                tooltip=f"Radius {RADIUS_M}m",
            ).add_to(fmap)

            # Marker FAT (hijau = eligible by road, merah = di luar)
            if not nearby.empty:
                for _, r in nearby.iterrows():
                    _rr = road_results.get(r["FAT_CODE"])
                    rd = _rr.get("road_distance_m") if isinstance(_rr, dict) else _rr
                    rd_txt = f"{rd:.0f}m (jalan)" if rd is not None else "?"
                    is_elig = rd is not None and rd <= RADIUS_M
                    folium.Marker(
                        [r["lat"], r["lon"]],
                        tooltip=f"{r['FAT_CODE']} — udara {r['distance_m']:.0f}m | {rd_txt}",
                        popup=folium.Popup(
                            f"<b>{r['FAT_CODE']}</b><br>"
                            f"Jarak udara: {r['distance_m']:.0f}m<br>"
                            f"Jarak jalan: {rd_txt}<br>"
                            f"Cluster: {r.get('CLUSTER_NAME','')}<br>"
                            f"City: {r.get('CITY','')}",
                            max_width=260,
                        ),
                        icon=folium.Icon(
                            color="green" if is_elig else "red",
                            icon="wifi", prefix="fa",
                        ),
                    ).add_to(fmap)
                    # Garis input -> FAT untuk 5 terdekat: MENGIKUTI JALAN (OSRM route)
                    if r["FAT_CODE"] in road_results:
                        _clr = "#2ecc71" if is_elig else "#e74c3c"
                        route_pts = osrm_route_geometry(input_lat, input_lon, r["lat"], r["lon"])
                        if route_pts and len(route_pts) >= 2:
                            # Segmen snap (putus-putus): rumah->jalan dan jalan->FAT
                            folium.PolyLine([[input_lat, input_lon], route_pts[0]],
                                            color=_clr, weight=2, opacity=0.6, dash_array="4").add_to(fmap)
                            folium.PolyLine(route_pts, color=_clr, weight=4, opacity=0.85).add_to(fmap)
                            folium.PolyLine([route_pts[-1], [r["lat"], r["lon"]]],
                                            color=_clr, weight=2, opacity=0.6, dash_array="4").add_to(fmap)
                        else:
                            # Fallback: garis lurus kalau route gagal
                            folium.PolyLine(
                                [[input_lat, input_lon], [r["lat"], r["lon"]]],
                                color=_clr, weight=2, opacity=0.7, dash_array="6",
                            ).add_to(fmap)

            # Titik HPID existing dalam radius 150m (dot kecil, warna per status)
            try:
                _hc, _ = get_coords_con()
                if _hc is not None:
                    _deg = 0.0015  # ~150m bbox
                    _df_hp = _hc.execute("""
                        SELECT HOMEPASS_ID, HOMEPASS_STATUS, blat, blon,
                            6371000 * acos(LEAST(1.0, GREATEST(-1.0,
                                cos(radians(?)) * cos(radians(blat)) *
                                cos(radians(blon) - radians(?)) +
                                sin(radians(?)) * sin(radians(blat))
                            ))) AS dist_m
                        FROM coords_f
                        WHERE blat BETWEEN ? AND ? AND blon BETWEEN ? AND ?
                        ORDER BY dist_m
                        LIMIT 300
                    """, [input_lat, input_lon, input_lat,
                          input_lat - _deg, input_lat + _deg,
                          input_lon - _deg, input_lon + _deg]).df()
                    _df_hp = _df_hp[_df_hp["dist_m"] <= 150]
                    _status_color = {
                        "ASSIGNED": "#3498db", "ACTIVE": "#2ecc71",
                        "RESERVED": "#f39c12", "AGING": "#95a5a6",
                        "NOT_AVAILABLE": "#e74c3c",
                    }
                    for _, h in _df_hp.iterrows():
                        _st = str(h["HOMEPASS_STATUS"]).upper()
                        folium.CircleMarker(
                            [float(h["blat"]), float(h["blon"])],
                            radius=4,
                            color=_status_color.get(_st, "#7f8c8d"),
                            fill=True, fill_opacity=0.9, weight=1,
                            tooltip=f"{h['HOMEPASS_ID']} — {_st} ({h['dist_m']:.0f}m)",
                        ).add_to(fmap)
            except Exception:
                pass

            st_folium(fmap, use_container_width=True, height=450, returned_objects=[])
            st.caption(
                "🔵 Rumah = koordinat yang dicek | 🟢 FAT eligible (road ≤150m) | "
                "🔴 FAT di luar jangkauan | Lingkaran = radius 150m | "
                "Dot kecil = HPID existing (🔵 ASSIGNED, 🟢 ACTIVE, 🟠 RESERVED, ⚪ AGING, 🔴 NOT_AVAILABLE)"
            )

            st.markdown("---")

            # ─── TABEL PERBANDINGAN AIR vs ROAD DISTANCE ────────────────────
            if road_results:
                st.markdown("##### 🛣️ Jarak Jalan (Road Distance) vs Jarak Lurus (Air Distance)")
                st.caption(
                    "Road distance dihitung mengikuti jalan sebenarnya (via OSRM routing), "
                    "lebih akurat untuk estimasi tarikan kabel dibanding jarak garis lurus."
                )
                comp_rows = []
                for idx in range(top_n):
                    row = nearby.iloc[idx]
                    rr = road_results.get(row["FAT_CODE"], {})
                    road_d = rr.get("road_distance_m")
                    comp_rows.append({
                        "FAT_Code": row["FAT_CODE"],
                        "Air_Distance_m": row["distance_m"],
                        "Road_Distance_m": road_d if road_d is not None else "Gagal",
                        "Selisih_m": round(road_d - row["distance_m"], 1) if road_d is not None else "-",
                        "Eligible_Air_150m": "✅" if row["distance_m"] <= RADIUS_M else "❌",
                        "Eligible_Road_150m": ("✅" if road_d <= RADIUS_M else "❌") if road_d is not None else "?",
                    })
                df_comp = pd.DataFrame(comp_rows)
                st.dataframe(df_comp, use_container_width=True, hide_index=True)

                # Cek kalau ada perbedaan eligibility air vs road (case penting!)
                mismatch = [
                    r for r in comp_rows
                    if r["Road_Distance_m"] != "Gagal" and r["Eligible_Air_150m"] != r["Eligible_Road_150m"]
                ]
                if mismatch:
                    st.warning(
                        f"⚠️ **Perhatian:** {len(mismatch)} FAT punya hasil eligibility berbeda antara "
                        f"air distance vs road distance — kemungkinan ada penghalang (jalan besar, gedung) "
                        f"yang membuat jarak lurus menyesatkan. Gunakan road distance sebagai acuan utama."
                    )

            st.markdown("---")

            # ─── HASIL ELIGIBILITAS (berbasis ROAD DISTANCE) ────────────────
            # Tentukan within_radius_road: FAT yang road distance-nya <= 150m
            within_radius_road = []
            for idx in range(top_n):
                row = nearby.iloc[idx]
                rr = road_results.get(row["FAT_CODE"], {})
                road_d = rr.get("road_distance_m")
                if road_d is not None and road_d <= RADIUS_M:
                    within_radius_road.append({**row.to_dict(), "road_distance_m": road_d})

            if not within_radius_road:
                st.error(f"❌ **TIDAK ELIGIBLE** — tidak ada FAT dengan jarak jalan ≤ {RADIUS_M}m.")
                if top_n > 0:
                    nearest = nearby.iloc[0]
                    nearest_road = road_results.get(nearest["FAT_CODE"], {}).get("road_distance_m")
                    if nearest_road is not None:
                        st.info(
                            f"FAT terdekat: **{nearest['FAT_CODE']}** "
                            f"({nearest['CLUSTER_NAME']}, {nearest['CITY']}) — "
                            f"jarak udara **{nearest['distance_m']:.0f}m**, "
                            f"jarak jalan **{nearest_road:.0f}m** (di luar radius)"
                        )
            else:
                st.success(
                    f"✅ **ELIGIBLE** — ditemukan {len(within_radius_road)} FAT "
                    f"dengan jarak jalan ≤ {RADIUS_M}m."
                )

                if len(within_radius_road) > 1:
                    st.caption("Beberapa FAT eligible, pilih salah satu untuk lihat detail:")
                    option_labels = [
                        f"{r['FAT_CODE']} — jalan: {r['road_distance_m']:.0f}m (udara: {r['distance_m']:.0f}m) | "
                        f"{r['CLUSTER_NAME']}, {r['CITY']} ({r['REGION']})"
                        for r in within_radius_road
                    ]
                    elig_idx = st.selectbox(
                        "Pilih FAT", range(len(within_radius_road)),
                        format_func=lambda i: option_labels[i],
                        key="eligibility_fat_select"
                    )
                else:
                    elig_idx = 0
                    nearest = within_radius_road[0]
                    st.write(
                        f"**{nearest['FAT_CODE']}** — jarak jalan **{nearest['road_distance_m']:.0f}m** "
                        f"(udara: {nearest['distance_m']:.0f}m) | "
                        f"{nearest['CLUSTER_NAME']}, {nearest['CITY']} ({nearest['REGION']})"
                    )

                selected_eligible_fat = within_radius_road[elig_idx]["FAT_CODE"]

                st.markdown("---")
                render_fat_detail(con, selected_eligible_fat)

            # ─── CEK HPID TERDEKAT ───────────────────────────────────────────
            st.markdown("---")
            st.markdown("### 🏠 Status HPID di Lokasi")
            st.caption("Cek apakah koordinat ini sudah memiliki HPID terdaftar (radius 3m) atau HPID terdekat dalam 150m.")

            coords_con, _ = get_coords_con()
            if coords_con is None:
                st.warning("⚠️ Data HPID tidak tersedia.")
            else:
                HPID_SNAP_DEG = 0.0015  # ~150m bounding box
                try:
                    df_hpid_nearby = coords_con.execute("""
                        SELECT
                            HOMEPASS_ID, HOMEPASS_STATUS,
                            FAT_CODE, VENDOR_NAME, CLUSTER_NAME,
                            6371000 * acos(
                                LEAST(1.0, GREATEST(-1.0,
                                    cos(radians(?)) * cos(radians(blat)) *
                                    cos(radians(blon) - radians(?)) +
                                    sin(radians(?)) * sin(radians(blat))
                                ))
                            ) AS dist_m
                        FROM coords_f
                        WHERE blat BETWEEN ? AND ?
                          AND blon BETWEEN ? AND ?
                        ORDER BY dist_m
                        LIMIT 10
                    """, [
                        input_lat, input_lon, input_lat,
                        input_lat - HPID_SNAP_DEG, input_lat + HPID_SNAP_DEG,
                        input_lon - HPID_SNAP_DEG, input_lon + HPID_SNAP_DEG
                    ]).df()

                    # Filter dalam 150m
                    df_hpid_nearby = df_hpid_nearby[df_hpid_nearby["dist_m"] <= 150].reset_index(drop=True)

                    # Cek dalam 3m
                    within_3m = df_hpid_nearby[df_hpid_nearby["dist_m"] <= 3]

                    if not within_3m.empty:
                        closest = within_3m.iloc[0]
                        hstatus = str(closest["HOMEPASS_STATUS"]).upper()
                        hid = closest["HOMEPASS_ID"]
                        jarak = round(float(closest["dist_m"]), 1)

                        if hstatus == "ASSIGNED":
                            st.warning(
                                f"⭐ **HPID Tersedia** — `{hid}` ({jarak}m dari koordinat input)\n\n"
                                f"Status: **ASSIGNED** — lokasi ini sudah punya HPID yang bisa diaktivasi, "
                                f"tidak perlu Add Homepass baru."
                            )
                        elif hstatus == "ACTIVE":
                            st.info(
                                f"ℹ️ **Koordinat Sudah Terdaftar** — `{hid}` ({jarak}m dari koordinat input)\n\n"
                                f"Status: **ACTIVE** — lokasi ini sudah ada pelanggan aktif. "
                                f"Kemungkinan multi-unit (apartemen/kos), cek fisik diperlukan."
                            )
                        else:
                            st.info(
                                f"ℹ️ **HPID Ditemukan** — `{hid}` ({jarak}m dari koordinat input)\n\n"
                                f"Status: **{hstatus}** — perlu dicek lebih lanjut."
                            )
                    else:
                        st.success(
                            f"✅ **Tidak ada HPID dalam radius 3m** — lokasi ini belum terdaftar, "
                            f"Add Homepass baru dapat dilakukan."
                        )

                    # Tampilkan tabel HPID terdekat dalam 150m
                    if not df_hpid_nearby.empty:
                        st.markdown(f"**{len(df_hpid_nearby)} HPID terdekat** dalam radius 150m:")
                        df_hpid_display = df_hpid_nearby[
                            ["HOMEPASS_ID", "HOMEPASS_STATUS", "FAT_CODE", "VENDOR_NAME", "dist_m"]
                        ].copy()
                        df_hpid_display["dist_m"] = df_hpid_display["dist_m"].round(1)
                        df_hpid_display.columns = ["HPID", "Status", "FAT", "Vendor", "Jarak (m)"]
                        st.dataframe(
                            df_hpid_display,
                            use_container_width=True,
                            hide_index=True,
                            height=min(50 + len(df_hpid_display) * 35, 300),
                            column_config={
                                "HPID":      st.column_config.TextColumn("HPID"),
                                "Status":    st.column_config.TextColumn("Status"),
                                "FAT":       st.column_config.TextColumn("FAT"),
                                "Vendor":    st.column_config.TextColumn("Vendor"),
                                "Jarak (m)": st.column_config.NumberColumn("Jarak (m)", format="%.1f"),
                            }
                        )
                    else:
                        st.info("Tidak ada HPID dalam radius 150m dari koordinat ini.")

                except Exception as e:
                    st.warning(f"⚠️ Gagal cek HPID: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# TAB: BULK CHECK (EXCEL)
# ═══════════════════════════════════════════════════════════════════════════


with tab_bulk:
    st.subheader("📋 Bulk Check Eligibilitas (Excel)")
    st.caption(
        "Upload file Excel berisi kolom **No**, **Alamat**, **Tikor** (format: `lat,lon`). "
        "Sistem akan cek eligibilitas FAT (radius 150m) dan status HPID terdekat (radius 3m)."
    )

    BULK_RADIUS_M  = 150
    BULK_HPID_RADIUS_M = 3
    BULK_BUFFER_DEG = 0.003
    HPID_BUFFER_DEG = 0.00005  # ~5m bounding box untuk cek HPID

    # Siapkan DuckDB connection ke hpdb_coords_bulk.parquet
    # Download sekali, query via DuckDB (lazy, hemat RAM)
    # get_coords_con() didefinisikan di level global (lihat atas)

    # ── Template Download ─────────────────────────────────────────────────
    st.markdown("**📥 Download Template Excel**")
    st.caption("Gunakan template ini sebagai format input yang benar — 3 kolom: No, Alamat, Tikor.")

    df_template = pd.DataFrame({
        "No":     [1, 2, 3],
        "Alamat": [
            "Jl. Sudirman No. 10, Jakarta Pusat",
            "Jl. Gatot Subroto No. 25, Jakarta Selatan",
            "Jl. Imam Bonjol No. 5, Bandung"
        ],
        "Tikor":  [
            "-6.208763, 106.845599",
            "-6.235678, 106.821234",
            "-6.917464, 107.619123"
        ]
    })
    tmpl_buf = io.BytesIO()
    with pd.ExcelWriter(tmpl_buf, engine="openpyxl") as writer:
        df_template.to_excel(writer, index=False, sheet_name="Tikor")
    tmpl_buf.seek(0)
    st.download_button(
        "⬇️ Download Template Excel",
        data=tmpl_buf,
        file_name="template_bulk_check.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="bulk_template_download"
    )
    st.markdown("---")

    uploaded_file = st.file_uploader("Upload file Excel (.xlsx)", type=["xlsx"], key="bulk_upload")

    if uploaded_file is not None:
        try:
            df_input = pd.read_excel(uploaded_file)
        except Exception as e:
            st.error(f"Gagal membaca file: {e}")
            df_input = None

        if df_input is not None:
            if "Tikor" not in df_input.columns:
                st.error(
                    f"File harus memiliki kolom **Tikor**. "
                    f"Kolom ditemukan: {', '.join(df_input.columns)}"
                )
            else:
                st.write(f"📄 Ditemukan **{len(df_input)} baris**.")
                if len(df_input) > 200:
                    st.warning(
                        f"File berisi {len(df_input)} baris — estimasi ~{len(df_input)*0.5/60:.1f} menit."
                    )

                if st.button("🚀 Proses", key="bulk_process"):
                    # Gunakan DuckDB lazy query (hemat RAM)
                    coords_con, coords_path = get_coords_con()
                    has_coords = coords_con is not None

                    if has_coords:
                        pass  # coords_con sudah siap dari get_coords_con()
                    else:
                        st.warning("⚠️ Data HPID tidak tersedia, cek HPID dilewati.")

                    results = []
                    progress = st.progress(0.0, text="Memproses...")
                    n = len(df_input)

                    for idx, row in df_input.iterrows():
                        tikor_str = str(row.get("Tikor", "")).strip()

                        try:
                            parts = [p.strip() for p in tikor_str.replace(";", ",").split(",")]
                            if len(parts) != 2:
                                raise ValueError
                            in_lat, in_lon = float(parts[0]), float(parts[1])
                            if not (-90 <= in_lat <= 90 and -180 <= in_lon <= 180):
                                raise ValueError
                        except ValueError:
                            results.append({
                                "Status_FAT": "⚠️ Format Tikor Invalid",
                                "FAT_Terdekat": None, "Jarak_FAT_m": None,
                                "Jarak_Road_m": None, "Eligible_Road_150m": None,
                                "Vendor": None, "FDT_Code": None,
                                "Region": None, "City": None, "Cluster": None,
                                "Jumlah_FAT_150m": None,
                                "Status_HPID": None,
                                "Rekomendasi": "⚠️ Tikor tidak valid",
                                "HPID_1": None, "Jarak_HPID_1_m": None, "Status_HPID_1": None,
                                "HPID_2": None, "Jarak_HPID_2_m": None, "Status_HPID_2": None,
                                "HPID_3": None, "Jarak_HPID_3_m": None, "Status_HPID_3": None,
                            })
                            progress.progress((idx + 1) / n, text=f"Memproses {idx + 1}/{n}...")
                            continue

                        lat_min = in_lat - BULK_BUFFER_DEG
                        lat_max = in_lat + BULK_BUFFER_DEG
                        lon_min = in_lon - BULK_BUFFER_DEG
                        lon_max = in_lon + BULK_BUFFER_DEG

                        # ── CEK FAT (radius 150m) ─────────────────────────────
                        nearby = con.execute("""
                            WITH fat_coords AS (
                                SELECT DISTINCT
                                    FAT_CODE, FDT_CODE, REGION, CITY, CLUSTER_NAME,
                                    TRY_CAST(FAT_LATITUDE AS DOUBLE) AS flat,
                                    TRY_CAST(FAT_LONGITUDE AS DOUBLE) AS flon
                                FROM hpdb
                                WHERE FAT_CODE IS NOT NULL AND FAT_CODE != '-'
                                  AND TRY_CAST(FAT_LATITUDE AS DOUBLE) IS NOT NULL
                                  AND TRY_CAST(FAT_LONGITUDE AS DOUBLE) IS NOT NULL
                                  AND TRY_CAST(FAT_LATITUDE AS DOUBLE) BETWEEN ? AND ?
                                  AND TRY_CAST(FAT_LONGITUDE AS DOUBLE) BETWEEN ? AND ?
                            )
                            SELECT *,
                                6371000 * acos(
                                    LEAST(1.0, GREATEST(-1.0,
                                        cos(radians(?)) * cos(radians(flat)) *
                                        cos(radians(flon) - radians(?)) +
                                        sin(radians(?)) * sin(radians(flat))
                                    ))
                                ) AS distance_m
                            FROM fat_coords
                            ORDER BY distance_m
                            LIMIT 50
                        """, [lat_min, lat_max, lon_min, lon_max,
                              in_lat, in_lon, in_lat]).df()

                        if nearby.empty:
                            fat_status = "❌ Tidak Eligible"
                            fat_code = vendor = fdt = region = city = cluster = None
                            jarak_fat = None
                            jarak_road = None
                            jumlah_fat = 0
                        else:
                            within = nearby[nearby["distance_m"] <= BULK_RADIUS_M]
                            nearest = nearby.iloc[0]
                            is_eligible = not within.empty
                            fat_status = "✅ Eligible" if is_eligible else "❌ Tidak Eligible"
                            fat_code = nearest["FAT_CODE"]
                            jarak_fat = round(float(nearest["distance_m"]), 1)
                            fdt = nearest["FDT_CODE"]
                            region = nearest["REGION"]
                            city = nearest["CITY"]
                            cluster = nearest["CLUSTER_NAME"]
                            jumlah_fat = int(len(within))

                            # Road distance (OSRM) ke FAT terdekat — mengikuti jalan sebenarnya
                            jarak_road = None
                            try:
                                _rd = calc_road_distance(in_lat, in_lon,
                                                         float(nearest["flat"]), float(nearest["flon"]))
                                _val = _rd.get("road_distance_m") if isinstance(_rd, dict) else _rd
                                if _val is not None:
                                    jarak_road = round(float(_val), 1)
                            except Exception:
                                jarak_road = None

                            vendor_row = con.execute("""
                                SELECT VENDOR_NAME FROM hpdb
                                WHERE FAT_CODE = ? AND VENDOR_NAME IS NOT NULL AND VENDOR_NAME != '-'
                                GROUP BY VENDOR_NAME ORDER BY COUNT(*) DESC LIMIT 1
                            """, [fat_code]).fetchone()
                            vendor = vendor_row[0] if vendor_row else None

                        # ── CEK HPID (radius 0-3m dan top 3 dalam 150m) ───────
                        hpid_status = rekomendasi = None
                        hpid_cols = {"HPID_1": None, "Jarak_HPID_1_m": None, "Status_HPID_1": None,
                                     "HPID_2": None, "Jarak_HPID_2_m": None, "Status_HPID_2": None,
                                     "HPID_3": None, "Jarak_HPID_3_m": None, "Status_HPID_3": None}

                        if has_coords and coords_con:
                            hlat_min = in_lat - BULK_BUFFER_DEG
                            hlat_max = in_lat + BULK_BUFFER_DEG
                            hlon_min = in_lon - BULK_BUFFER_DEG
                            hlon_max = in_lon + BULK_BUFFER_DEG

                            nearby_hpid = coords_con.execute("""
                                SELECT
                                    HOMEPASS_ID, HOMEPASS_STATUS,
                                    FAT_CODE, VENDOR_NAME, CLUSTER_NAME,
                                    6371000 * acos(
                                        LEAST(1.0, GREATEST(-1.0,
                                            cos(radians(?)) * cos(radians(blat)) *
                                            cos(radians(blon) - radians(?)) +
                                            sin(radians(?)) * sin(radians(blat))
                                        ))
                                    ) AS dist_m
                                FROM coords_f
                                WHERE blat BETWEEN ? AND ?
                                  AND blon BETWEEN ? AND ?
                                ORDER BY dist_m
                                LIMIT 10
                            """, [in_lat, in_lon, in_lat,
                                  hlat_min, hlat_max, hlon_min, hlon_max]).df()

                            # Filter dalam 150m
                            nearby_hpid = nearby_hpid[nearby_hpid["dist_m"] <= 150].reset_index(drop=True)

                            # Isi top 3
                            for i, hrow in nearby_hpid.head(3).iterrows():
                                n_idx = i + 1
                                hpid_cols[f"HPID_{n_idx}"] = hrow["HOMEPASS_ID"]
                                hpid_cols[f"Jarak_HPID_{n_idx}_m"] = round(float(hrow["dist_m"]), 1)
                                hpid_cols[f"Status_HPID_{n_idx}"] = hrow["HOMEPASS_STATUS"]

                            # Cek radius 0-3m
                            within_3m = nearby_hpid[nearby_hpid["dist_m"] <= BULK_HPID_RADIUS_M]

                            if within_3m.empty:
                                hpid_status = "✅ Tidak ada HPID dalam 3m"
                                rekomendasi = "➕ Add Homepass Baru"
                            else:
                                closest = within_3m.iloc[0]
                                hstatus = str(closest["HOMEPASS_STATUS"]).upper()
                                hid = closest["HOMEPASS_ID"]
                                jarak = round(float(closest["dist_m"]), 1)
                                if hstatus == "ASSIGNED":
                                    hpid_status = f"🔵 HPID {hid} ({jarak}m) — ASSIGNED"
                                    rekomendasi = f"⭐ Aktivasi HPID {hid}"
                                elif hstatus == "ACTIVE":
                                    hpid_status = f"🟢 HPID {hid} ({jarak}m) — ACTIVE"
                                    rekomendasi = f"ℹ️ Koordinat sudah terdaftar di HPID {hid}"
                                else:
                                    hpid_status = f"⚪ HPID {hid} ({jarak}m) — {hstatus}"
                                    rekomendasi = f"ℹ️ HPID {hid} ada di lokasi (status: {hstatus})"
                        else:
                            rekomendasi = "➕ Add Homepass Baru (HPID tidak dicek)"

                        results.append({
                            "Status_FAT":     fat_status,
                            "FAT_Terdekat":   fat_code,
                            "Jarak_FAT_m":    jarak_fat,
                            "Jarak_Road_m":   jarak_road,
                            "Eligible_Road_150m": ("✅" if jarak_road <= BULK_RADIUS_M else "❌") if jarak_road is not None else ("?" if fat_code else None),
                            "Vendor":         vendor,
                            "FDT_Code":       fdt,
                            "Region":         region,
                            "City":           city,
                            "Cluster":        cluster,
                            "Jumlah_FAT_150m": jumlah_fat,
                            "Status_HPID":    hpid_status,
                            "Rekomendasi":    rekomendasi,
                            **hpid_cols,
                        })

                        progress.progress((idx + 1) / n, text=f"Memproses {idx + 1}/{n}...")

                    progress.empty()

                    df_result = pd.concat(
                        [df_input.reset_index(drop=True), pd.DataFrame(results)], axis=1
                    )

                    # Summary
                    n_eligible = (df_result["Status_FAT"] == "✅ Eligible").sum()
                    n_add_hp   = df_result["Rekomendasi"].str.startswith("➕", na=False).sum()
                    n_aktivasi = df_result["Rekomendasi"].str.startswith("⭐", na=False).sum()
                    n_exists   = df_result["Rekomendasi"].str.startswith("ℹ️", na=False).sum()

                    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
                    col_s1.metric("✅ Eligible FAT", n_eligible)
                    col_s2.metric("➕ Add HP Baru", n_add_hp)
                    col_s3.metric("⭐ Aktivasi HPID", n_aktivasi)
                    col_s4.metric("ℹ️ Sudah Terdaftar", n_exists)

                    st.dataframe(df_result, use_container_width=True, hide_index=True)

                    # Download Excel
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine="openpyxl") as writer:
                        df_result.to_excel(writer, index=False, sheet_name="Hasil")
                    output.seek(0)

                    st.download_button(
                        "⬇️ Download Hasil (Excel)",
                        data=output,
                        file_name=f"bulk_check_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="bulk_download"
                    )
    else:
        st.info("Upload file Excel untuk mulai proses bulk check.")



# ═══════════════════════════════════════════════════════════════════════════
# TAB: MONTHLY PROGRESS (tracking transisi status HPID)
# ═══════════════════════════════════════════════════════════════════════════
with tab_progress:
    st.subheader("📈 Monthly Progress — Homepass Status Tracking")
    st.caption(
        "Tracking harian perubahan status HPID di HPDB (change-log dari snapshot daily report). "
        "Lifecycle: ASSIGNED (tersedia) → RESERVED (booking sales) → ACTIVE (terpasang) → AGING (churn)."
    )

    @st.cache_data(ttl=600, show_spinner="Memuat data status history...")
    def load_status_history():
        try:
            path = "status_history_cache.parquet"
            token = st.secrets.get("github", {}).get("token", "")
            headers = {"Accept": "application/vnd.github+json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            rel = requests.get(
                "https://api.github.com/repos/firmanfadillah9-lgtm/homepass-npd-dashboard/releases/tags/latest-data",
                headers=headers, timeout=15
            )
            if rel.status_code == 200:
                assets = rel.json().get("assets", [])
                asset_url = next((a["url"] for a in assets if a["name"] == "status_history.parquet"), None)
                if asset_url:
                    dl = requests.get(asset_url,
                                      headers={**headers, "Accept": "application/octet-stream"},
                                      stream=True, timeout=300)
                    if dl.status_code == 200:
                        with open(path, "wb") as f:
                            for chunk in dl.iter_content(chunk_size=1024 * 256):
                                f.write(chunk)
            if not os.path.exists(path):
                return None
            # File 17 MB ini menjadi 1.061 MB di memori kalau dimuat apa
            # adanya -- ketujuh kolomnya bertipe object (objek string Python
            # satu per satu). Plafon Streamlit Cloud sekitar 1 GB, jadi baris
            # ini SENDIRIAN membunuh proses tanpa menyisakan traceback.
            #
            # Dimuat hanya 5 kolom yang dipakai tab ini (VENDOR_NAME dan
            # CLUSTER_NAME tidak terpakai) dengan backend Arrow: 190 MB.
            # Sudah diverifikasi: pivot, groupby, mask isin, dan jumlah baris
            # identik dengan versi lama.
            dfh = pd.read_parquet(
                path,
                columns=["HOMEPASS_ID", "status_from", "status_to",
                         "change_date", "CITY"],
                dtype_backend="pyarrow",
            )
            dfh["change_date"] = pd.to_datetime(dfh["change_date"])
            dfh["status_from"] = dfh["status_from"].fillna("(BARU)")
            return dfh
        except Exception:
            return None

    df_hist = load_status_history()

    if df_hist is None or df_hist.empty:
        st.warning(
            "Data status history belum tersedia. Jalankan di PC:\n\n"
            "`python track_status.py` lalu `python push_status.py`"
        )
    else:
        min_d = df_hist["change_date"].min().date()
        max_d = df_hist["change_date"].max().date()
        st.caption(f"Periode data: {min_d} s/d {max_d} | Total perubahan tercatat: {len(df_hist):,}")

        # ── Bersihkan status kotor dari file sumber ───────────────────────
        # Sesekali ada baris di HPDB yang kolomnya bergeser, sehingga nilai
        # HPID (mis. "04937231" / "BDG.100.0202...") masuk ke kolom status.
        STATUS_SAH = {"ACTIVE", "ASSIGNED", "RESERVED", "AGING",
                      "NOT_AVAILABLE", "LOCKED", "(BARU)"}
        n_awal = len(df_hist)
        mask_sah = df_hist["status_to"].isin(STATUS_SAH) & df_hist["status_from"].isin(STATUS_SAH)
        n_kotor = n_awal - int(mask_sah.sum())
        df_hist = df_hist[mask_sah]
        if n_kotor > 0:
            st.caption(f"⚠️ {n_kotor} baris dengan status tidak sah (data bergeser di file sumber) dikeluarkan.")

        df_f = df_hist.copy()

        # ── 1. Deteksi snapshot PERUBAHAN CAKUPAN DATASET ─────────────────
        # Saat format sumber berganti (mis. main+linknet -> B2S+G2A pada Sep 2026),
        # cakupan HPID melonjak. Snapshot itu terlihat seperti jutaan "HPID baru"
        # dan ratusan ribu transisi, padahal bukan kejadian nyata di lapangan.
        baru_harian = (df_hist[df_hist["status_from"] == "(BARU)"]
                       .groupby(df_hist["change_date"].dt.date).size())
        baseline_days = [d for d, v in baru_harian.items() if v > 100000]

        exclude_baseline = True
        if baseline_days:
            tot_bl = int(sum(baru_harian[d] for d in baseline_days))
            exclude_baseline = st.checkbox(
                f"Exclude snapshot baseline / perubahan cakupan data "
                f"({', '.join(str(d) for d in baseline_days)} — {tot_bl:,} HPID muncul serentak)",
                value=True, key="mp_exclude_baseline",
                help="Pada tanggal ini format file sumber berganti sehingga cakupan HPID "
                     "melonjak. Angkanya bukan pertumbuhan nyata, jadi sebaiknya dikeluarkan "
                     "dari grafik supaya tren harian tetap terbaca."
            )
            if exclude_baseline:
                df_f = df_f[~df_f["change_date"].dt.date.isin(baseline_days)]

        # ── 2. Deteksi bulk event (lonjakan transisi tidak wajar) ─────────
        # Ambang relatif terhadap median harian, jadi ikut menyesuaikan volume data.
        trans_harian = df_f.groupby(df_f["change_date"].dt.date).size()
        bulk_days = []
        if len(trans_harian) > 2:
            med_t = trans_harian.median()
            bulk_days = [d for d, v in trans_harian.items()
                         if med_t > 0 and v > max(10 * med_t, 50000)]

        # Bulk khusus AGING massal (pola lama yang sudah dikenal)
        churn_daily = (df_f[(df_f["status_from"] == "ACTIVE") & (df_f["status_to"] == "AGING")]
                       .groupby(df_f["change_date"].dt.date).size())
        if len(churn_daily) > 0:
            med_c = churn_daily.median()
            for d, v in churn_daily.items():
                if med_c > 0 and v > max(10 * med_c, 5000) and d not in bulk_days:
                    bulk_days.append(d)

        exclude_bulk = True
        if bulk_days:
            tot_bulk = int(sum(trans_harian.get(d, 0) for d in bulk_days))
            exclude_bulk = st.checkbox(
                f"Exclude bulk event sistem ({', '.join(str(d) for d in sorted(bulk_days))} — "
                f"{tot_bulk:,} transisi serentak)",
                value=True, key="mp_exclude_bulk",
                help="Perubahan massal yang dilakukan sistem dalam satu hari "
                     "(mis. aging massal), bukan aktivitas harian normal."
            )
            if exclude_bulk:
                df_f = df_f[~df_f["change_date"].dt.date.isin(bulk_days)]

        if df_f.empty:
            st.info("Semua tanggal terdeteksi sebagai baseline/bulk event. "
                    "Hilangkan centang di atas untuk melihat datanya.")

        # ── Klasifikasi metrik ────────────────────────────────────────────
        def _classify(r):
            f, t = r["status_from"], r["status_to"]
            if t == "RESERVED":
                return "🛒 Booking Sales"
            if t == "ACTIVE" and f == "AGING":
                return "🔁 Reconnect"
            if t == "ACTIVE":
                return "🏠 Installation Done"
            if f == "ACTIVE" and t == "AGING":
                return "📉 Churn"
            if f == "AGING" and t == "ASSIGNED":
                return "♻️ Recycle (Aging→Available)"
            if f == "(BARU)":
                return "🆕 HPID Baru Terbangun"
            return "Lainnya"

        df_f["Metrik"] = df_f.apply(_classify, axis=1)

        # ── Metric cards ──────────────────────────────────────────────────
        metric_names = ["🛒 Booking Sales", "🏠 Installation Done", "🔁 Reconnect", "📉 Churn", "🆕 HPID Baru Terbangun"]
        mcols = st.columns(5)
        for col, m in zip(mcols, metric_names):
            col.metric(m, f"{(df_f['Metrik'] == m).sum():,}")

        st.markdown("---")

        # ── Chart tren harian ─────────────────────────────────────────────
        import plotly.graph_objects as go

        sel_metrics = st.multiselect(
            "Metrik yang ditampilkan:",
            metric_names + ["♻️ Recycle (Aging→Available)"],
            default=["🛒 Booking Sales", "🏠 Installation Done", "🔁 Reconnect"],
            key="mp_metrics"
        )

        df_plot = df_f[df_f["Metrik"].isin(sel_metrics)]
        daily = (df_plot.groupby([df_plot["change_date"].dt.date, "Metrik"])
                 .size().reset_index(name="Jumlah")
                 .rename(columns={"change_date": "Tanggal"}))

        if daily.empty:
            st.info("Belum ada data untuk metrik yang dipilih — akan terisi seiring data harian bertambah.")
        else:
            fig = go.Figure()
            for m in sel_metrics:
                dm = daily[daily["Metrik"] == m]
                if not dm.empty:
                    fig.add_trace(go.Bar(x=dm["Tanggal"], y=dm["Jumlah"], name=m))
            if sel_metrics:
                dm0 = daily[daily["Metrik"] == sel_metrics[0]].sort_values("Tanggal")
                if not dm0.empty:
                    fig.add_trace(go.Scatter(
                        x=dm0["Tanggal"], y=dm0["Jumlah"].cumsum(),
                        name=f"Kumulatif {sel_metrics[0]}", mode="lines+markers+text",
                        text=dm0["Jumlah"].cumsum(), textposition="top center",
                        yaxis="y2", line=dict(width=3)
                    ))
            fig.update_layout(
                barmode="group", height=420,
                yaxis=dict(title="Per Hari"),
                yaxis2=dict(title="Kumulatif", overlaying="y", side="right", showgrid=False),
                legend=dict(orientation="h", y=-0.2),
                margin=dict(t=30, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)

        # ── Pivot per CITY (format PPT) ───────────────────────────────────
        st.markdown("#### 🏙️ Breakdown per City")
        pivot_metric = st.selectbox("Metrik:", metric_names, index=0, key="mp_pivot_metric")
        gran = st.radio("Granularitas:", ["Harian", "Bulanan"], horizontal=True, key="mp_gran")

        df_pv = df_f[df_f["Metrik"] == pivot_metric].copy()
        if df_pv.empty:
            st.info(f"Belum ada data {pivot_metric}.")
        else:
            if gran == "Bulanan":
                df_pv["Periode"] = df_pv["change_date"].dt.strftime("%Y-%m")
            else:
                df_pv["Periode"] = df_pv["change_date"].dt.strftime("%Y-%m-%d")
            pv = pd.pivot_table(df_pv, index="CITY", columns="Periode",
                                values="HOMEPASS_ID", aggfunc="count", fill_value=0)
            pv["Grand Total"] = pv.sum(axis=1)
            pv = pv.sort_values("Grand Total", ascending=False)
            total_row = pv.sum().to_frame().T
            total_row.index = ["GRAND TOTAL"]
            pv_show = pd.concat([pv, total_row])
            st.dataframe(pv_show, use_container_width=True, height=420)

            import io as _io
            _out = _io.BytesIO()
            with pd.ExcelWriter(_out, engine="openpyxl") as _w:
                pv_show.to_excel(_w, sheet_name="PerCity")
                df_f.to_excel(_w, index=False, sheet_name="RawTransisi")
            _out.seek(0)
            st.download_button(
                "⬇️ Download Laporan (Excel)", data=_out,
                file_name=f"monthly_progress_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="mp_dl"
            )

        with st.expander("ℹ️ Catatan definisi metrik"):
            st.markdown("""
- **🛒 Booking Sales** = HPID berubah menjadi RESERVED (dibooking sales untuk calon pelanggan)
- **🏠 Installation Done** = HPID berubah menjadi ACTIVE (instalasi selesai; belum ada datanya di hari-hari awal karena siklus booking→instalasi butuh waktu)
- **🔁 Reconnect** = AGING → ACTIVE (pelanggan lama berlangganan lagi)
- **📉 Churn** = ACTIVE → AGING (berhenti berlangganan). Bulk event sistem (aging massal serentak) otomatis terdeteksi dan bisa di-exclude
- **♻️ Recycle** = AGING → ASSIGNED (HPID kembali available untuk dijual)
- **🆕 HPID Baru Terbangun** = HPID baru muncul di HPDB (hasil pembangunan/additional)
            """)


# ═══════════════════════════════════════════════════════════════════════════
# TAB: DUMMY MONITOR (pantau HPID dummy yang sudah masuk HPDB)
# ═══════════════════════════════════════════════════════════════════════════
with tab_dummy:
    st.subheader("🎯 Dummy Monitor — HPID Dummy di HPDB")
    st.caption(
        "Data dummy = titik placeholder yang disiapkan agar sales bisa langsung mendaftarkan "
        "tanpa proses additional. Halaman ini memantau berapa banyak dummy yang sudah masuk HPDB dan dari vendor mana."
    )

    # Field yang discan untuk mendeteksi 'dummy'
    DUMMY_FIELDS = ["PROJECT_NAME", "CLUSTER_NAME", "STREET_NAME", "DISTRICT",
                    "SUB_DISTRICT", "OLT_LOCATION", "FDT_CODE", "REMARKS",
                    "HOUSE_NUMBER", "HOMEPASS_ID"]
    _dummy_cond = " OR ".join([f"LOWER({f}) LIKE '%dummy%'" for f in DUMMY_FIELDS])
    _dummy_where = f"({_dummy_cond})"

    # Metric cards
    total_dummy = con.execute(f"SELECT COUNT(*) FROM hpdb WHERE {_dummy_where}").fetchone()[0]
    total_all = con.execute("SELECT COUNT(*) FROM hpdb").fetchone()[0]
    n_vendor = con.execute(
        f"SELECT COUNT(DISTINCT VENDOR_NAME) FROM hpdb WHERE {_dummy_where}"
    ).fetchone()[0]
    n_active = con.execute(
        f"SELECT COUNT(*) FROM hpdb WHERE {_dummy_where} AND UPPER(HOMEPASS_STATUS)='ASSIGNED'"
    ).fetchone()[0]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🎯 Total HPID Dummy", f"{total_dummy:,}")
    m2.metric("🏢 Jumlah Vendor", f"{n_vendor}")
    m3.metric("🟢 Siap Dipakai (ASSIGNED)", f"{n_active:,}")
    m4.metric("📊 % dari Total HPDB", f"{(total_dummy/total_all*100):.3f}%" if total_all else "0%")

    st.markdown("---")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Per Vendor")
        df_vendor = con.execute(f"""
            SELECT COALESCE(VENDOR_NAME, '(kosong)') AS Vendor, COUNT(*) AS Jumlah
            FROM hpdb WHERE {_dummy_where}
            GROUP BY 1 ORDER BY 2 DESC
        """).fetchdf()
        st.dataframe(df_vendor, use_container_width=True, hide_index=True)
        if not df_vendor.empty:
            import plotly.express as px
            fig_v = px.bar(df_vendor, x="Jumlah", y="Vendor", orientation="h",
                           text="Jumlah", height=300)
            fig_v.update_layout(margin=dict(t=10, b=10), yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig_v, use_container_width=True)

    with c2:
        st.markdown("#### Per Status")
        df_status = con.execute(f"""
            SELECT HOMEPASS_STATUS AS Status, COUNT(*) AS Jumlah
            FROM hpdb WHERE {_dummy_where}
            GROUP BY 1 ORDER BY 2 DESC
        """).fetchdf()
        st.dataframe(df_status, use_container_width=True, hide_index=True)
        if not df_status.empty:
            import plotly.express as px
            fig_s = px.pie(df_status, names="Status", values="Jumlah", hole=0.4, height=300)
            fig_s.update_layout(margin=dict(t=10, b=10))
            st.plotly_chart(fig_s, use_container_width=True)

    st.markdown("---")
    st.markdown("#### 🏙️ Per Kota (top 15)")
    df_city = con.execute(f"""
        SELECT CITY AS Kota, VENDOR_NAME AS Vendor, COUNT(*) AS Jumlah
        FROM hpdb WHERE {_dummy_where}
        GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 15
    """).fetchdf()
    st.dataframe(df_city, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("#### 📋 Daftar Lengkap HPID Dummy")
    # Filter vendor opsional
    _vendors_dummy = ["Semua"] + [r[0] for r in con.execute(
        f"SELECT DISTINCT COALESCE(VENDOR_NAME,'(kosong)') FROM hpdb WHERE {_dummy_where} ORDER BY 1"
    ).fetchall()]
    _sel_v = st.selectbox("Filter vendor:", _vendors_dummy, key="dummy_vendor_filter")
    _extra = ""
    if _sel_v == "(kosong)":
        _extra = " AND VENDOR_NAME IS NULL"
    elif _sel_v != "Semua":
        _extra = f" AND VENDOR_NAME = '{_sel_v}'"

    df_list = con.execute(f"""
        SELECT HOMEPASS_ID, VENDOR_NAME, HOMEPASS_STATUS,
               ACQUISITION_CLASS, ACQUISITION_TIER,
               REGION, CITY, CLUSTER_NAME, PROJECT_NAME, STREET_NAME,
               FAT_CODE, FDT_CODE, OLT_LOCATION,
               BUILDING_LATITUDE, BUILDING_LONGITUDE, REMARKS
        FROM hpdb WHERE {_dummy_where}{_extra}
        ORDER BY VENDOR_NAME, HOMEPASS_ID
    """).fetchdf()
    st.caption(f"Menampilkan {len(df_list):,} HPID dummy.")
    st.dataframe(df_list, use_container_width=True, height=420, hide_index=True)

    # Download Excel
    import io as _io
    _out = _io.BytesIO()
    with pd.ExcelWriter(_out, engine="openpyxl") as _w:
        df_list.to_excel(_w, index=False, sheet_name="HPID_Dummy")
        df_vendor.to_excel(_w, index=False, sheet_name="Per_Vendor")
        df_city.to_excel(_w, index=False, sheet_name="Per_Kota")
    _out.seek(0)
    st.download_button(
        "⬇️ Download Daftar Dummy (Excel)", data=_out,
        file_name=f"dummy_hpid_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dummy_dl"
    )


# ─── METADATA ───────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(f"Data source: {GITHUB_OWNER}/{GITHUB_REPO} (release: {RELEASE_TAG})")

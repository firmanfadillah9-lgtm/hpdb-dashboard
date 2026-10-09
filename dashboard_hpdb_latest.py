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
GITHUB_OWNER = "Jomzski"
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
    con.execute(f"CREATE VIEW hpdb AS SELECT * FROM read_parquet('{path}')")
    return con


con = get_connection()


# ─── SIDEBAR ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"**{st.session_state.get('user_name', '')}**")
    role_label = "👑 Super Admin" if st.session_state.get("user_role") == "super_admin" else "👤 Viewer"
    st.caption(role_label)
    if st.button("🚪 Logout"):
        logout()
    st.markdown("---")

    st.title("🔍 Filter")

    regions = con.execute("SELECT DISTINCT REGION FROM hpdb WHERE REGION IS NOT NULL ORDER BY 1").fetchall()
    region_options = ["Semua"] + [r[0] for r in regions]
    selected_region = st.selectbox("Region", region_options)

    vendors = con.execute("SELECT DISTINCT VENDOR_NAME FROM hpdb WHERE VENDOR_NAME IS NOT NULL ORDER BY 1").fetchall()
    vendor_options = ["Semua"] + [v[0] for v in vendors]
    selected_vendor = st.selectbox("Vendor", vendor_options)

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

tab_overview, tab_fat, tab_hpid, tab_eligibility, tab_bulk = st.tabs(
    ["📊 Network Overview", "🔎 FAT Explorer", "🏠 HPID Explorer", "📍 Cek Eligibilitas", "📋 Bulk Check (Excel)"]
)


# ═══════════════════════════════════════════════════════════════════════════
# TAB: NETWORK OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════
with tab_overview:

    total_rows = con.execute(f"SELECT COUNT(*) FROM hpdb WHERE {where_sql}").fetchone()[0]
    st.caption(f"Total records (sesuai filter): {total_rows:,}")

    # ─── METRICS ────────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        total_hp = con.execute(
            f"SELECT COUNT(*) FROM hpdb WHERE {where_sql} AND HOMEPASS_ID != '-----'"
        ).fetchone()[0]
        st.metric("Total Homepass", f"{total_hp:,}")

    with col2:
        active = con.execute(
            f"SELECT COUNT(*) FROM hpdb WHERE {where_sql} AND HOMEPASS_STATUS = 'ACTIVE'"
        ).fetchone()[0]
        st.metric("Active", f"{active:,}")

    with col3:
        assigned = con.execute(
            f"SELECT COUNT(*) FROM hpdb WHERE {where_sql} AND HOMEPASS_STATUS = 'ASSIGNED'"
        ).fetchone()[0]
        st.metric("Assigned", f"{assigned:,}")

    with col4:
        total_fat = con.execute(
            f"SELECT COUNT(DISTINCT FAT_CODE) FROM hpdb WHERE {where_sql} AND FAT_CODE != '-'"
        ).fetchone()[0]
        st.metric("Total FAT", f"{total_fat:,}")

    st.markdown("---")

    # ─── BREAKDOWN PER REGION ─────────────────────────────────────────────────
    st.subheader("📍 Breakdown per Region")

    df_region = con.execute(f"""
        SELECT REGION, HOMEPASS_STATUS, COUNT(*) as jumlah
        FROM hpdb
        WHERE {where_sql} AND REGION IS NOT NULL
        GROUP BY REGION, HOMEPASS_STATUS
        ORDER BY REGION
    """).df()

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

    df_vendor = con.execute(f"""
        SELECT VENDOR_NAME, COUNT(*) as jumlah
        FROM hpdb
        WHERE {where_sql} AND VENDOR_NAME IS NOT NULL AND VENDOR_NAME != '-'
        GROUP BY VENDOR_NAME
        ORDER BY jumlah DESC
        LIMIT 15
    """).df()

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

    total_fat_points = con.execute(f"""
        SELECT COUNT(DISTINCT FAT_CODE) FROM hpdb
        WHERE {where_sql} AND FAT_CODE IS NOT NULL AND FAT_CODE != '-'
          AND TRY_CAST(FAT_LATITUDE AS DOUBLE) IS NOT NULL
          AND TRY_CAST(FAT_LONGITUDE AS DOUBLE) IS NOT NULL
    """).fetchone()[0]

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

            # ─── PETA ────────────────────────────────────────────────────────
            map_lat = [input_lat]
            map_lon = [input_lon]
            map_color = ["#0080FF"]  # biru = titik input

            if not nearby.empty:
                map_lat += nearby["lat"].tolist()
                map_lon += nearby["lon"].tolist()
                map_color += ["#FF4040"] * len(nearby)  # merah = FAT

            map_df = pd.DataFrame({"lat": map_lat, "lon": map_lon, "color": map_color})
            st.map(map_df, latitude="lat", longitude="lon", color="color", zoom=16, size=15)
            st.caption("🔵 Titik biru = koordinat yang dicek | 🔴 Titik merah = FAT di sekitarnya")

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

    else:
        st.info("Masukkan koordinat (latitude, longitude) untuk mulai cek eligibilitas.")


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
                    "https://api.github.com/repos/Jomzski/homepass-npd-dashboard/releases/tags/latest-data",
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
                    timeout=300
                )
                if dl.status_code != 200:
                    return None, None
                with open(path, "wb") as f:
                    f.write(dl.content)
            # DuckDB baca langsung dari parquet tanpa load semua ke RAM
            coords_con = duckdb.connect()
            coords_con.execute(f"CREATE VIEW coords AS SELECT * FROM read_parquet('{path}')")
            # Tambah kolom float untuk koordinat
            coords_con.execute("""
                CREATE VIEW coords_f AS
                SELECT *,
                    TRY_CAST(BUILDING_LATITUDE AS DOUBLE) AS blat,
                    TRY_CAST(BUILDING_LONGITUDE AS DOUBLE) AS blon
                FROM coords
                WHERE TRY_CAST(BUILDING_LATITUDE AS DOUBLE) IS NOT NULL
                  AND TRY_CAST(BUILDING_LONGITUDE AS DOUBLE) IS NOT NULL
            """)
            return coords_con, path
        except Exception as e:
            return None, None

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



# ─── METADATA ───────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(f"Data source: {GITHUB_OWNER}/{GITHUB_REPO} (release: {RELEASE_TAG})")

# ============================================================
# Smallow • Realtime Sleep & Environment Dashboard (STEM)
# ============================================================

import time
import requests
import pandas as pd
import numpy as np
import altair as alt
import streamlit as st
from datetime import datetime, timezone

# =================== CONFIG dari Secrets ====================
TOKEN = st.secrets.get("UBIDOTS_TOKEN", "")
DEVICE = st.secrets.get("UBIDOTS_DEVICE", "smallow")
BASE = st.secrets.get("UBIDOTS_BASE", "https://things.ubidots.com")
VARS = [v.strip() for v in st.secrets.get("UBIDOTS_VARS", "temperature,fsr").split(",") if v.strip()]
LOCAL_TZ = st.secrets.get("LOCAL_TZ", "Asia/Jakarta")

HEADERS = {"X-Auth-Token": TOKEN, "Content-Type": "application/json"}

# ===================== Fungsi bantu ==========================

def now_ms():
    """Waktu UTC dalam milidetik"""
    return int(time.time() * 1000)

@st.cache_data(ttl=10)
def fetch_data(var, days=1, limit=300):
    """Ambil data dari Ubidots dengan fallback /lv jika kosong"""
    end = now_ms()
    start = end - days * 24 * 60 * 60 * 1000
    url = f"{BASE}/api/v1.6/devices/{DEVICE}/{var}/values"

    try:
        r = requests.get(url, headers=HEADERS,
                         params={"start": start, "end": end, "page_size": limit},
                         timeout=10)
        # Kalau unauthorized/not found, fallback ke /lv
        if r.status_code in (401, 403, 404):
            lv_url = f"{BASE}/api/v1.6/devices/{DEVICE}/{var}/lv"
            r2 = requests.get(lv_url, headers=HEADERS, timeout=8)
            r2.raise_for_status()
            last = r2.json()
            return pd.DataFrame([{
                "time": pd.to_datetime(last.get("timestamp", end), unit="ms"),
                "value": last.get("value", np.nan)
            }])
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        if not results:
            lv_url = f"{BASE}/api/v1.6/devices/{DEVICE}/{var}/lv"
            r2 = requests.get(lv_url, headers=HEADERS, timeout=8)
            r2.raise_for_status()
            last = r2.json()
            return pd.DataFrame([{
                "time": pd.to_datetime(last.get("timestamp", end), unit="ms"),
                "value": last.get("value", np.nan)
            }])
        rows = [{"time": pd.to_datetime(x["timestamp"], unit="ms"),
                 "value": x["value"]} for x in results[::-1]]
        return pd.DataFrame(rows)
    except Exception as e:
        st.error(f"Gagal ambil data {var}: {e}")
        return pd.DataFrame(columns=["time", "value"])

# ===================== Tampilan utama ========================

st.set_page_config(page_title="Smallow Dashboard", page_icon="😴", layout="wide")
st.title("😴 Smallow • Realtime Sleep & Environment Dashboard")

col1, col2, col3 = st.sidebar.columns(1)
st.sidebar.markdown("## Pengaturan Dashboard")
refresh_sec = st.sidebar.slider("Refresh (detik)", 5, 60, 10)
days = st.sidebar.slider("Rentang data (hari)", 1, 7, 1)
limit = st.sidebar.slider("Jumlah titik data", 50, 500, 300)

st.sidebar.markdown(f"**Device:** `{DEVICE}` | **Vars:** {', '.join(VARS)}")
st.sidebar.markdown("Pastikan menggunakan akun **Ubidots STEM (things.ubidots.com)**")

# ===================== Loop data =============================
all_data = {}
for var in VARS:
    df = fetch_data(var, days, limit)
    if not df.empty:
        all_data[var] = df

if not all_data:
    st.warning("Tidak ada data yang bisa ditampilkan. Cek token/device/variable di Secrets.")
else:
    for var, df in all_data.items():
        st.subheader(f"📊 {var.capitalize()} (terbaru: {df['value'].iloc[-1]:.2f})")
        chart = alt.Chart(df).mark_line(interpolate="monotone").encode(
            x="time:T", y="value:Q"
        ).properties(height=250)
        st.altair_chart(chart, use_container_width=True)

# ===================== Auto-refresh ==========================
st.caption(f"Terakhir diperbarui: {datetime.now().strftime('%H:%M:%S')} (auto refresh {refresh_sec}s)")
st_autorefresh = st.experimental_rerun
time.sleep(refresh_sec)
st_autorefresh()

# app.py — Smallow • Ubidots Realtime + AI Coach (Streamlit Cloud ready)
# ================================================
# Membaca data real-time dari Ubidots STEM (https://things.ubidots.com)
# dan memberikan rekomendasi tidur berbasis AI heuristic.

import time
import requests
import pandas as pd
import numpy as np
import altair as alt
import streamlit as st

# ================== CONFIG ==================
TOKEN = st.secrets.get("UBIDOTS_TOKEN", "")
DEVICE = st.secrets.get("UBIDOTS_DEVICE", "smallow")
BASE = st.secrets.get("UBIDOTS_BASE", "https://things.ubidots.com")
VARS = [v.strip() for v in st.secrets.get("UBIDOTS_VARS", "temperature,humidity,fsr").split(",") if v.strip()]
LOCAL_TZ = st.secrets.get("LOCAL_TZ", "Asia/Jakarta")

HEADERS = {"X-Auth-Token": TOKEN, "Content-Type": "application/json"}

TARGET_SLEEP_H = 8.0  # target durasi tidur ideal (jam)
TARGET_TEMP = (18, 22)
TARGET_HUM = (40, 50)

st.set_page_config(page_title="Smallow • AI Coach", layout="wide")
st.title("😴 Smallow • Realtime Sleep & Environment Dashboard")

# Sidebar
refresh = st.sidebar.slider("Refresh (detik)", 5, 60, 10)
days = st.sidebar.slider("Rentang data (hari)", 1, 7, 1)
limit = st.sidebar.slider("Jumlah titik data", 50, 500, 300)

st.sidebar.caption(f"Device: `{DEVICE}` | Vars: {', '.join(VARS)}")
st.sidebar.caption("Pastikan menggunakan akun **Ubidots STEM (things.ubidots.com)**")

# ================== FETCH ==================
def now_ms():
    return int(time.time() * 1000)

@st.cache_data(ttl=10)
def fetch_data(var):
    """Ambil data var dari Ubidots; fallback ke /lv bila tidak ada values"""
    end = now_ms()
    start = end - days * 24 * 60 * 60 * 1000
    url = f"{BASE}/api/v1.6/devices/{DEVICE}/{var}/values"
    r = requests.get(url, headers=HEADERS, params={"start": start, "end": end, "page_size": limit}, timeout=10)

    if r.status_code in (401, 403, 404):
        # fallback ke last value
        lv_url = f"{BASE}/api/v1.6/devices/{DEVICE}/{var}/lv"
        r2 = requests.get(lv_url, headers=HEADERS)
        if r2.status_code == 200:
            last = r2.json()
            df = pd.DataFrame([{"time": pd.to_datetime(last["timestamp"], unit="ms"), "value": last["value"]}])
            return df
        else:
            raise RuntimeError(f"Gagal akses var {var} (HTTP {r2.status_code})")

    data = r.json()
    results = data.get("results", [])
    rows = [{"time": pd.to_datetime(x["timestamp"], unit="ms"), "value": x["value"]} for x in results[::-1]]
    return pd.DataFrame(rows)

# ================== DISPLAY ==================
df_all = []
for v in VARS:
    try:
        df = fetch_data(v)
        if not df.empty:
            df["variable"] = v
            df_all.append(df)
    except Exception as e:
        st.error(f"Gagal ambil data {v}: {e}")

if not df_all:
    st.warning("Tidak ada data yang bisa ditampilkan. Cek token/device/variable di Secrets.")
    st.stop()

df_all = pd.concat(df_all)
latest = df_all.groupby("variable").tail(1)

cols = st.columns(len(latest))
for i, (_, row) in enumerate(latest.iterrows()):
    cols[i].metric(row["variable"], f"{row['value']:.2f}")
    cols[i].caption(str(row["time"]))

# ================== CHART ==================
chart = (
    alt.Chart(df_all)
    .mark_line()
    .encode(
        x=alt.X("time:T", title="Waktu"),
        y=alt.Y("value:Q", title="Nilai"),
        color="variable:N"
    )
    .properties(height=320)
)
st.altair_chart(chart, use_container_width=True)

# ================== AI REKOMENDASI ==================
st.header("🧠 AI Coach — Analisis Tidur & Rekomendasi")

# Hitung durasi tidur (berdasarkan FSR)
fsr_df = df_all[df_all["variable"] == "fsr"]
sleep_hours = 0.0
if not fsr_df.empty:
    fsr_val = fsr_df["value"]
    fsr_thresh = np.percentile(fsr_val, 30)
    sleep_hours = ((fsr_val > fsr_thresh).sum() / len(fsr_val)) * 8  # asumsi 8 jam data per hari

# Hitung suhu & kelembapan rata-rata
temp_df = df_all[df_all["variable"] == "temperature"]
hum_df = df_all[df_all["variable"] == "humidity"]
temp_mean = temp_df["value"].mean() if not temp_df.empty else None
hum_mean = hum_df["value"].mean() if not hum_df.empty else None

colA, colB = st.columns(2)
with colA:
    st.write(f"- Durasi tidur estimasi: **{sleep_hours:.1f} jam** (target {TARGET_SLEEP_H} jam)")
    if temp_mean is not None:
        st.write(f"- Suhu rata-rata: **{temp_mean:.1f}°C**")
    if hum_mean is not None:
        st.write(f"- Kelembapan rata-rata: **{hum_mean:.0f}%**")

with colB:
    st.subheader("Rekomendasi 💡")
    tips = []
    if sleep_hours < TARGET_SLEEP_H:
        tips.append("Tidur kurang dari 8 jam! Coba tidur lebih cepat malam ini ⏰")
    if temp_mean and not (TARGET_TEMP[0] <= temp_mean <= TARGET_TEMP[1]):
        tips.append("Suhu kamar di luar rentang ideal (18–22°C).")
    if hum_mean and not (TARGET_HUM[0] <= hum_mean <= TARGET_HUM[1]):
        tips.append("Kelembapan tidak ideal (40–50%).")
    if not tips:
        tips.append("Kondisi tidur sudah ideal 😴✨")
    for t in tips:
        st.write(f"• {t}")

time.sleep(refresh)
st.rerun()

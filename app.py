# app.py — Smallow • Ubidots Realtime + MongoDB + AI Coach
# =========================================================
# Menarik data sensor dari Ubidots Industrial/STEM
# Menyimpan ke MongoDB Atlas dan menampilkan analisis AI di Streamlit

import time
from datetime import datetime
import requests
import pandas as pd
import numpy as np
import altair as alt
import streamlit as st
from pymongo import MongoClient

# ================== KONFIGURASI ==================
TOKEN   = st.secrets.get("UBIDOTS_TOKEN", "")
DEVICE  = st.secrets.get("UBIDOTS_DEVICE", "smallow")
BASE    = st.secrets.get("UBIDOTS_BASE", "https://industrial.api.ubidots.com")
VARS    = [v.strip() for v in st.secrets.get("UBIDOTS_VARS", "temperature,FSR,eco2,tvoc").split(",") if v.strip()]
LOCAL_TZ = st.secrets.get("LOCAL_TZ", "Asia/Jakarta")

# MongoDB Atlas URI (buat key di Secrets Streamlit juga)
MONGO_URI = st.secrets.get("MONGO_URI", "mongodb+srv://smallow_user:smallow123@cluster0.ourd1lk.mongodb.net/")
DB_NAME = "smallow"
COLL_NAME = "sensor_data"

HEADERS = {"X-Auth-Token": TOKEN, "Content-Type": "application/json"}

TARGET_SLEEP_H = 8.0
TARGET_TEMP = (18, 22)
TARGET_HUM = (40, 50)

st.set_page_config(page_title="Smallow • AI Sleep Dashboard", layout="wide")
st.title("😴 Smallow • Realtime Sleep & Environment Dashboard")

# Sidebar
refresh = st.sidebar.slider("Refresh (detik)", 5, 60, 10)
days = st.sidebar.slider("Rentang data (hari)", 1, 7, 1)
limit = st.sidebar.slider("Jumlah titik data", 50, 500, 300)
st.sidebar.caption(f"Device: `{DEVICE}` | Vars: {', '.join(VARS)}")
st.sidebar.caption("Sumber data: Ubidots + MongoDB")

# ================== FUNGSI UTAMA ==================
def now_ms(): return int(time.time() * 1000)

@st.cache_data(ttl=15)
def fetch_data(var):
    """Ambil data 1 variabel dari Ubidots"""
    end = now_ms()
    start = end - days * 24 * 60 * 60 * 1000
    url = f"{BASE}/api/v1.6/devices/{DEVICE}/{var}/values"
    r = requests.get(url, headers=HEADERS, params={"start": start, "end": end, "page_size": limit}, timeout=10)

    # Fallback ke last value jika data kosong
    if r.status_code in (401, 403, 404):
        lv_url = f"{BASE}/api/v1.6/devices/{DEVICE}/{var}/lv"
        r2 = requests.get(lv_url, headers=HEADERS)
        if r2.status_code == 200:
            last = r2.json()
            df = pd.DataFrame([{"time": pd.to_datetime(last["timestamp"], unit="ms"), "value": last["value"], "variable": var}])
            return df
        else:
            raise RuntimeError(f"Gagal akses var {var} (HTTP {r2.status_code})")

    data = r.json()
    results = data.get("results", [])
    rows = [{"time": pd.to_datetime(x["timestamp"], unit="ms"), "value": x["value"], "variable": var} for x in results[::-1]]
    return pd.DataFrame(rows)

def save_to_mongo(df_all):
    """Simpan dataframe ke MongoDB"""
    try:
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        coll = db[COLL_NAME]
        docs = []
        for _, row in df_all.iterrows():
            docs.append({
                "timestamp": datetime.utcnow(),
                "variable": row["variable"],
                "value": float(row["value"]),
                "time_utc": row["time"].to_pydatetime()
            })
        if docs:
            coll.insert_many(docs)
        client.close()
        st.success(f"Data tersimpan ke MongoDB ({len(docs)} dokumen).")
    except Exception as e:
        st.warning(f"Gagal menyimpan ke MongoDB: {e}")

# ================== PENGAMBILAN DATA ==================
df_all = []
for v in VARS:
    try:
        df = fetch_data(v)
        if not df.empty:
            df_all.append(df)
    except Exception as e:
        st.error(f"Gagal ambil data {v}: {e}")

if not df_all:
    st.warning("Tidak ada data yang bisa ditampilkan. Cek token/device/variable di Secrets.")
    st.stop()

df_all = pd.concat(df_all)

# Simpan otomatis ke MongoDB
save_to_mongo(df_all)

# ================== TAMPILKAN NILAI TERBARU ==================
latest = df_all.groupby("variable").tail(1)
cols = st.columns(len(latest))
for i, (_, row) in enumerate(latest.iterrows()):
    cols[i].metric(row["variable"], f"{row['value']:.2f}")
    cols[i].caption(str(row["time"]))

# ================== GRAFIK ==================
chart = (
    alt.Chart(df_all)
    .mark_line()
    .encode(
        x=alt.X("time:T", title="Waktu"),
        y=alt.Y("value:Q", title="Nilai"),
        color="variable:N",
        tooltip=["time:T", "variable:N", "value:Q"]
    )
    .properties(height=320)
)
st.altair_chart(chart, use_container_width=True)

# ================== AI ANALISIS & SARAN ==================
st.header("🧠 AI Coach — Analisis Tidur & Rekomendasi")

fsr_df = df_all[df_all["variable"].str.contains("fsr", case=False)]
sleep_hours = 0.0
if not fsr_df.empty:
    fsr_val = fsr_df["value"]
    fsr_thresh = np.percentile(fsr_val, 30)
    sleep_hours = ((fsr_val > fsr_thresh).sum() / len(fsr_val)) * 8

temp_df = df_all[df_all["variable"].str.contains("temp", case=False)]
hum_df = df_all[df_all["variable"].str.contains("hum", case=False)]
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
        tips.append("Tidur kurang dari 8 jam — coba tidur lebih awal malam ini.")
    if temp_mean and not (TARGET_TEMP[0] <= temp_mean <= TARGET_TEMP[1]):
        tips.append("Suhu kamar di luar rentang ideal (18–22°C).")
    if hum_mean and not (TARGET_HUM[0] <= hum_mean <= TARGET_HUM[1]):
        tips.append("Kelembapan tidak ideal (40–50%).")
    if not tips:
        tips.append("Kondisi tidur dan lingkungan sudah optimal 😴✨")
    for t in tips:
        st.write(f"• {t}")

# Refresh otomatis
time.sleep(refresh)
st.rerun()

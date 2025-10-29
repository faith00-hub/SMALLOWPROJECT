# app2.py — Smallow • Ubidots Realtime + MongoDB + AI Coach
# ==========================================================
# Menarik data sensor dari Ubidots Industrial/STEM
# Menyimpan ke MongoDB Atlas dan menampilkan analisis AI di Streamlit

import sys
import time
from datetime import datetime, timezone
import requests
import pandas as pd
import numpy as np
import altair as alt
import streamlit as st

# ---- Guard untuk pymongo agar errornya jelas jika belum ter-install
try:
    from pymongo import MongoClient, UpdateOne
except ModuleNotFoundError:
    st.error(
        "✖ Modul 'pymongo' belum ter-install.\n"
        "Tambahkan baris berikut ke requirements.txt, lalu Clear cache & Reboot app:\n\n"
        "pymongo[srv]==4.9.2"
    )
    st.stop()

# ================== KONFIGURASI via Secrets ==================
TOKEN    = st.secrets.get("UBIDOTS_TOKEN", "")
DEVICE   = st.secrets.get("UBIDOTS_DEVICE", "smallow")
BASE     = st.secrets.get("UBIDOTS_BASE", "https://industrial.api.ubidots.com")
VARS     = [v.strip() for v in st.secrets.get("UBIDOTS_VARS", "temperature,FSR").split(",") if v.strip()]
LOCAL_TZ = st.secrets.get("LOCAL_TZ", "Asia/Jakarta")

# MongoDB Atlas
MONGO_URI = st.secrets.get("MONGO_URI", "")
DB_NAME   = st.secrets.get("MONGO_DB", "smallow")
COLL_NAME = st.secrets.get("MONGO_COLL", "sensor_data")

HEADERS = {"X-Auth-Token": TOKEN, "Content-Type": "application/json"}

# Target/heuristik AI
TARGET_SLEEP_H = 8.0
TARGET_TEMP = (18, 22)   # °C
TARGET_HUM  = (40, 50)   # %

# ================== UI ==================
st.set_page_config(page_title="Smallow • AI Sleep Dashboard", layout="wide")
st.title("😴 Smallow • Realtime Sleep & Environment Dashboard")

refresh = st.sidebar.slider("Refresh (detik)", 5, 60, 10)
days    = st.sidebar.slider("Rentang data (hari)", 1, 30, 7)
limit   = st.sidebar.slider("Jumlah titik/variabel", 50, 1000, 400, step=50)
st.sidebar.caption(f"Device: `{DEVICE}` • Vars: {', '.join(VARS)}")
st.sidebar.caption("Sumber data: Ubidots → (backup) MongoDB")

# Auto-refresh (tanpa sleep blocking)
st.autorefresh(interval=refresh * 1000, key="auto_refresh")

# ================== Helper ==================
def now_ms() -> int:
    return int(time.time() * 1000)

@st.cache_data(ttl=15, show_spinner=False)
def fetch_var_from_ubidots(var: str, days_back: int, limit_points: int) -> pd.DataFrame:
    """
    Ambil 1 variabel dari Ubidots /values dengan fallback /lv.
    Return DataFrame: [time (UTC tz-aware), value, variable]
    """
    end = now_ms()
    start = end - days_back * 24 * 60 * 60 * 1000
    url_values = f"{BASE}/api/v1.6/devices/{DEVICE}/{var}/values"
    try:
        r = requests.get(
            url_values, headers=HEADERS,
            params={"start": start, "end": end, "page_size": min(limit_points, 200)},
            timeout=12
        )
        # Fallback /lv untuk 401/403/404 atau kalau results kosong
        def fetch_lv() -> pd.DataFrame:
            url_lv = f"{BASE}/api/v1.6/devices/{DEVICE}/{var}/lv"
            r2 = requests.get(url_lv, headers=HEADERS, timeout=10)
            r2.raise_for_status()
            last = r2.json()
            return pd.DataFrame([{
                "time": pd.to_datetime(last.get("timestamp", end), unit="ms", utc=True),
                "value": last.get("value", np.nan),
                "variable": var
            }])

        if r.status_code in (401, 403, 404):
            return fetch_lv()

        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        if not results:
            return fetch_lv()

        rows = [{
            "time": pd.to_datetime(x["timestamp"], unit="ms", utc=True),
            "value": x["value"],
            "variable": var
        } for x in results[::-1]]  # urut naik
        return pd.DataFrame(rows)

    except Exception as e:
        # Jangan matikan app: kembalikan DF kosong agar var lain tetap tampil
        st.warning(f"{var}: gagal ambil dari Ubidots → {e}")
        return pd.DataFrame(columns=["time", "value", "variable"])

def save_dataframe_to_mongo(df: pd.DataFrame, uri: str, db_name: str, coll_name: str) -> str:
    """
    Simpan DF ke Mongo sebagai upsert (variable + time_utc unik).
    Buat index unik jika belum ada. Mengembalikan ringkasan hasil.
    """
    if not uri:
        return "Mongo URI kosong (lewati simpan)."

    if df.empty:
        return "Tidak ada data untuk disimpan."

    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=6000)
        db = client[db_name]
        coll = db[coll_name]
        # index unik agar tidak duplikat
        try:
            coll.create_index([("variable", 1), ("time_utc", 1)], unique=True, background=True)
        except Exception:
            pass

        ops = []
        for _, row in df.iterrows():
            doc = {
                "variable": str(row["variable"]),
                "value": float(row["value"]),
                "time_utc": pd.to_datetime(row["time"]).tz_convert("UTC").to_pydatetime()
                              if hasattr(row["time"], "tz_convert") else pd.to_datetime(row["time"], utc=True).to_pydatetime(),
                "saved_at": datetime.utcnow()
            }
            ops.append(
                UpdateOne(
                    {"variable": doc["variable"], "time_utc": doc["time_utc"]},
                    {"$set": doc},
                    upsert=True
                )
            )
        result = coll.bulk_write(ops, ordered=False)
        client.close()
        return f"Mongo upsert OK: matched={result.matched_count}, upserted={len(result.upserted_ids)}, modified={result.modified_count}"
    except Exception as e:
        return f"Mongo save gagal: {e}"

# ================== Ambil data semua variabel ==================
frames = []
for v in VARS:
    df = fetch_var_from_ubidots(v, days, limit)
    if not df.empty:
        frames.append(df)

if not frames:
    st.warning("Tidak ada data yang bisa ditampilkan. Cek token/device/variable di Secrets, atau naikkan rentang hari.")
    st.stop()

df_all = pd.concat(frames, ignore_index=True).sort_values("time")
df_all["time_local"] = df_all["time"].dt.tz_convert(LOCAL_TZ)

# ================== Simpan ke MongoDB (opsional) ==================
with st.expander("📦 Penyimpanan ke MongoDB (log)"):
    msg = save_dataframe_to_mongo(df_all, MONGO_URI, DB_NAME, COLL_NAME)
    st.caption(msg)

# ================== KPI terakhir ==================
latest = df_all.groupby("variable", as_index=False).tail(1).reset_index(drop=True)
cols = st.columns(max(1, min(4, len(latest))))
for i, (_, row) in enumerate(latest.iterrows()):
    c = cols[i % len(cols)]
    val = row["value"]
    label = str(row["variable"])
    ts = row["time_local"]
    try:
        c.metric(label, f"{float(val):.2f}")
    except Exception:
        c.metric(label, str(val))
    c.caption(f"⏱️ {ts}")

# ================== Grafik ==================
st.subheader("📈 Tren Variabel")
sel = st.multiselect("Pilih variabel untuk grafik", options=sorted(df_all["variable"].unique()),
                     default=list(sorted(df_all["variable"].unique()))[:3])
plot_df = df_all[df_all["variable"].isin(sel)].dropna(subset=["value"])
if not plot_df.empty:
    chart = alt.Chart(plot_df).mark_line().encode(
        x=alt.X("time_local:T", title=f"Waktu ({LOCAL_TZ})"),
        y=alt.Y("value:Q", title="Nilai"),
        color="variable:N",
        tooltip=["time_local:T", "variable:N", "value:Q"]
    ).properties(height=320).interactive()
    st.altair_chart(chart, use_container_width=True)
else:
    st.info("Tidak ada data untuk variabel terpilih.")

# ================== AI ANALISIS & SARAN ==================
st.subheader("🧠 AI Coach — Analisis Tidur & Rekomendasi")

# Normalisasi nama kolom agar pencarian fleksibel (fsr vs FSR; temp vs suhu-c)
pivot = df_all.pivot_table(index="time_local", columns="variable", values="value", aggfunc="last").sort_index()
cols_lower = {c: c.lower() for c in pivot.columns}
pivot = pivot.rename(columns=cols_lower)

# Ambil fsr/temp/hum bila ada
fsr_series  = None
temp_series = None
hum_series  = None
for cname in pivot.columns:
    lc = cname.lower()
    if fsr_series is None and ("fsr" in lc):
        fsr_series = pivot[cname].dropna()
    if temp_series is None and (lc in ("temperature", "suhu", "suhu-c") or "temp" in lc):
        temp_series = pivot[cname].dropna()
    if hum_series is None and (lc in ("humidity", "kelembaban", "kelembaban-rh") or "hum" in lc or "rh" in lc):
        hum_series = pivot[cname].dropna()

# Estimasi durasi tidur (FSR tinggi + low activity simple proxy)
sleep_hours = 0.0
if fsr_series is not None and not fsr_series.empty:
    thr = float(np.nanpercentile(fsr_series.values, 30))
    asleep_ratio = float(np.mean(fsr_series.values > thr))
    # Rasio → kali total jam di rentang (approx): gunakan durasi real (min ke jam)
    # tapi agar simpel stabil, gunakan target 8 jam sebagai baseline jika rentang 1 hari
    # dan skala menurut proporsi titik
    # (cukup heuristik, karena data sampling rate bisa bervariasi)
    sleep_hours = asleep_ratio * TARGET_SLEEP_H

temp_mean = float(np.nanmean(temp_series.values)) if temp_series is not None and not temp_series.empty else None
hum_mean  = float(np.nanmean(hum_series.values))  if hum_series is not None and not hum_series.empty else None

colA, colB = st.columns(2)
with colA:
    st.write(f"- Durasi tidur estimasi: **{sleep_hours:.1f} jam** (target {TARGET_SLEEP_H:.0f} jam)")
    if temp_mean is not None:
        st.write(f"- Suhu rata-rata: **{temp_mean:.1f}°C**")
    else:
        st.write("- Suhu: (N/A)")
    if hum_mean is not None:
        st.write(f"- Kelembapan rata-rata: **{hum_mean:.0f}%**")
    else:
        st.write("- Kelembapan: (N/A)")

tips, notes = [], []
if sleep_hours < TARGET_SLEEP_H:
    lack = TARGET_SLEEP_H - sleep_hours
    tips.append(
        f"Tidur **{sleep_hours:.1f} jam** (kurang {lack:.1f} jam). Coba tidur 30–60 menit lebih awal, "
        "jaga jam bangun konsisten, hindari kafein ≥6 jam sebelum tidur."
    )
else:
    notes.append("Durasi tidur sudah memenuhi target. Good job!")

if temp_mean is not None:
    lo, hi = TARGET_TEMP
    if temp_mean < lo:
        tips.append(f"Suhu **{temp_mean:.1f}°C** (terlalu dingin). Naikkan ke ~{(lo+hi)/2:.0f}°C atau tambah selimut tipis.")
    elif temp_mean > hi:
        tips.append(f"Suhu **{temp_mean:.1f}°C** (hangat). Turunkan ke ~{(lo+hi)/2:.0f}°C (AC/kipas mode dry, ventilasi).")
    else:
        notes.append(f"Suhu **{temp_mean:.1f}°C** sudah dalam rentang nyaman ({lo}-{hi}°C).")

if hum_mean is not None:
    lo, hi = TARGET_HUM
    if hum_mean < lo:
        tips.append(f"RH **{hum_mean:.0f}%** (kering). Tambah humidifier hingga ~{(lo+hi)//2}%.")
    elif hum_mean > hi:
        tips.append(f"RH **{hum_mean:.0f}%** (lembap). Aktifkan mode dry/ventilasi; target ~{(lo+hi)//2}%.")
    else:
        notes.append(f"RH **{hum_mean:.0f}%** sudah baik ({lo}-{hi}%).")

if not tips:
    notes.append("Kualitas tidur & lingkungan sudah baik. Lanjutkan kebiasaan yang sama 😴✨")

with colB:
    st.write("**Saran untuk malam berikutnya:**")
    for t in tips: st.write("• " + t)
    if notes:
        st.write("**Catatan:**")
        for n in notes: st.write("- " + n)

st.caption(f"Terakhir diperbarui: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')} — auto refresh {refresh}s")

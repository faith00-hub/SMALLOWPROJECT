# app.py — Smallow • Ubidots Realtime + MongoDB + AI Coach (REVISI)
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

# 📌 REVISI 1: DAFTAR VARIABEL HARUS SESUAI DENGAN main.py
VARS = [
    "temp-c", 
    "hum-rh", 
    "co2-ppm", 
    "tvoc-ppb", 
    "max-red", 
    "max-ir", 
    "fsr1-raw", # FSR1 & FSR2 digunakan untuk deteksi tidur
    "fsr2-raw",
    "eog-mag",  # EOG digunakan untuk deteksi kantuk/aktivitas
    "vibration",
    "lead-off"
]
VARS_STR = ",".join(VARS) # Digunakan untuk Secrets jika perlu default value
VARS     = [v.strip() for v in st.secrets.get("UBIDOTS_VARS", VARS_STR).split(",") if v.strip()]
LOCAL_TZ = st.secrets.get("LOCAL_TZ", "Asia/Jakarta")

# MongoDB Atlas
MONGO_URI = st.secrets.get("MONGO_URI", "")
DB_NAME   = st.secrets.get("MONGO_DB", "smallow")
COLL_NAME = st.secrets.get("MONGO_COLL", "sensor_data")

HEADERS = {"X-Auth-Token": TOKEN, "Content-Type": "application/json"}

# Target/heuristik AI
TARGET_SLEEP_H = 8.0
TARGET_TEMP = (18, 22)   # °C
TARGET_HUM  = (40, 60)   # % (sedikit dilonggarkan karena di main.py menggunakan SHT31)
TARGET_CO2 = 800         # ppm (Target CO2 di bawah 800)
TARGET_TVOC = 250        # ppb (Target TVOC di bawah 250)

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

# ================== Helper & Koneksi Ubidots/Mongo (TIDAK BERUBAH) ==================

def now_ms() -> int:
    return int(time.time() * 1000)

@st.cache_data(ttl=15, show_spinner=False)
def fetch_var_from_ubidots(var: str, days_back: int, limit_points: int) -> pd.DataFrame:
    """Ambil 1 variabel dari Ubidots /values dengan fallback /lv."""
    end = now_ms()
    start = end - days_back * 24 * 60 * 60 * 1000
    url_values = f"{BASE}/api/v1.6/devices/{DEVICE}/{var}/values"
    try:
        r = requests.get(
            url_values, headers=HEADERS,
            params={"start": start, "end": end, "page_size": min(limit_points, 200)},
            timeout=12
        )
        
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
        } for x in results[::-1]]
        return pd.DataFrame(rows)

    except Exception as e:
        st.warning(f"{var}: gagal ambil dari Ubidots → {e}")
        return pd.DataFrame(columns=["time", "value", "variable"])

def save_dataframe_to_mongo(df: pd.DataFrame, uri: str, db_name: str, coll_name: str) -> str:
    """Simpan DF ke Mongo sebagai upsert (variable + time_utc unik)."""
    if not uri: return "Mongo URI kosong (lewati simpan)."
    if df.empty: return "Tidak ada data untuk disimpan."
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=6000)
        db = client[db_name]
        coll = db[coll_name]
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
# Menampilkan KPI dari sensor yang relevan saja (tidak semua 11 var)
kpi_vars = ["temp-c", "hum-rh", "co2-ppm", "eog-mag", "vibration"]
latest_kpi = latest[latest['variable'].isin(kpi_vars)]

cols = st.columns(max(1, min(5, len(latest_kpi))))
for i, (_, row) in enumerate(latest_kpi.iterrows()):
    c = cols[i % len(cols)]
    val = row["value"]
    label = str(row["variable"])
    ts = row["time_local"]
    try:
        c.metric(label, f"{float(val):.2f}")
    except Exception:
        c.metric(label, str(val))
    c.caption(f"⏱️ {ts.strftime('%H:%M:%S')}") # Hanya tampilkan jam/menit

# ================== Grafik (TIDAK BERUBAH) ==================
st.subheader("📈 Tren Variabel")
sel = st.multiselect("Pilih variabel untuk grafik", options=sorted(df_all["variable"].unique()),
                     default=[v for v in ["temp-c", "hum-rh", "fsr1-raw"] if v in df_all["variable"].unique()][:3])
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

# ================== AI ANALISIS & SARAN (REVISI LOGIKA) ==================
st.subheader("🧠 AI Coach — Analisis Tidur & Rekomendasi")

# Normalisasi nama kolom agar pencarian fleksibel
pivot = df_all.pivot_table(index="time_local", columns="variable", values="value", aggfunc="last").sort_index()
cols_lower = {c: c.lower() for c in pivot.columns}
pivot = pivot.rename(columns=cols_lower)

# 📌 REVISI 2: AMBIL SERIES DENGAN NAMA BARU
fsr1_series  = pivot.get("fsr1-raw").dropna() if "fsr1-raw" in pivot.columns else None
fsr2_series  = pivot.get("fsr2-raw").dropna() if "fsr2-raw" in pivot.columns else None
eog_series   = pivot.get("eog-mag").dropna()  if "eog-mag" in pivot.columns else None
temp_series  = pivot.get("temp-c").dropna()   if "temp-c" in pivot.columns else None
hum_series   = pivot.get("hum-rh").dropna()   if "hum-rh" in pivot.columns else None
co2_series   = pivot.get("co2-ppm").dropna()  if "co2-ppm" in pivot.columns else None
tvoc_series  = pivot.get("tvoc-ppb").dropna() if "tvoc-ppb" in pivot.columns else None

# --- Estimasi Durasi Tidur (Gunakan FSR1 & FSR2) ---
sleep_hours = 0.0
# Gabungkan FSR1 dan FSR2 untuk mendapatkan rata-rata tekanan
if fsr1_series is not None and fsr2_series is not None:
    combined_fsr = pd.concat([fsr1_series, fsr2_series]).groupby(level=0).mean()
    if not combined_fsr.empty:
        # Gunakan persentil untuk ambang batas (diasumsikan nilai FSR yang lebih tinggi berarti ada tekanan/tidur)
        thr = float(np.nanpercentile(combined_fsr.values, 30))
        # Rasio waktu di mana tekanan terdeteksi (di atas ambang batas)
        asleep_ratio = float(np.mean(combined_fsr.values > thr))
        # Estimasi durasi tidur berdasarkan rasio * TARGET_SLEEP_H
        sleep_hours = asleep_ratio * TARGET_SLEEP_H

# --- Penghitungan Rata-rata ---
temp_mean = float(np.nanmean(temp_series.values)) if temp_series is not None and not temp_series.empty else None
hum_mean  = float(np.nanmean(hum_series.values))  if hum_series is not None and not hum_series.empty else None
co2_mean  = float(np.nanmean(co2_series.values))  if co2_series is not None and not co2_series.empty else None
tvoc_mean = float(np.nanmean(tvoc_series.values)) if tvoc_series is not None and not tvoc_series.empty else None
# Metrik EOG untuk aktivitas
eog_mean = float(np.nanmean(eog_series.values)) if eog_series is not None and not eog_series.empty else None

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
    
    # Menambahkan KPI baru
    if co2_mean is not None:
        st.write(f"- $\text{CO}_2$ rata-rata: **{co2_mean:.0f} ppm**")
    else:
        st.write("- $\text{CO}_2$: (N/A)")
    
    if tvoc_mean is not None:
        st.write(f"- TVOC rata-rata: **{tvoc_mean:.0f} ppb**")
    else:
        st.write("- TVOC: (N/A)")
    
    if eog_mean is not None:
        st.write(f"- EOG rata-rata: **{eog_mean:.1f} mag** (Proxy Aktivitas Mata)")
    else:
        st.write("- EOG: (N/A)")


# --- Logika Saran ---
tips, notes = [], []
sleep_quality_score = 100 # Mulai dari 100

# 1. Analisis Durasi Tidur
if sleep_hours < TARGET_SLEEP_H:
    lack = TARGET_SLEEP_H - sleep_hours
    tips.append(
        f"Tidur **{sleep_hours:.1f} jam** (kurang {lack:.1f} jam). Coba tidur 30–60 menit lebih awal, "
        "jaga jam bangun konsisten, hindari kafein ≥6 jam sebelum tidur."
    )
    sleep_quality_score -= 10
else:
    notes.append("Durasi tidur sudah memenuhi target. Good job!")

# 2. Analisis Suhu
if temp_mean is not None:
    lo, hi = TARGET_TEMP
    if temp_mean < lo:
        tips.append(f"Suhu **{temp_mean:.1f}°C** (terlalu dingin). Naikkan ke ~{(lo+hi)/2:.0f}°C atau tambah selimut tipis.")
        sleep_quality_score -= 5
    elif temp_mean > hi:
        tips.append(f"Suhu **{temp_mean:.1f}°C** (hangat). Turunkan ke ~{(lo+hi)/2:.0f}°C (AC/kipas mode dry, ventilasi).")
        sleep_quality_score -= 5
    else:
        notes.append(f"Suhu **{temp_mean:.1f}°C** sudah dalam rentang nyaman ({lo}-{hi}°C).")

# 3. Analisis Kelembapan
if hum_mean is not None:
    lo, hi = TARGET_HUM
    if hum_mean < lo:
        tips.append(f"RH **{hum_mean:.0f}%** (kering). Tambah humidifier hingga ~{(lo+hi)//2}%.")
        sleep_quality_score -= 3
    elif hum_mean > hi:
        tips.append(f"RH **{hum_mean:.0f}%** (lembap). Aktifkan mode dry/ventilasi; target ~{(lo+hi)//2}%.")
        sleep_quality_score -= 3
    else:
        notes.append(f"RH **{hum_mean:.0f}%** sudah baik ({lo}-{hi}%).")
        
# 4. Analisis Kualitas Udara (CO2 & TVOC)
if co2_mean is not None and co2_mean > TARGET_CO2:
    tips.append(f"Tingkat $\text{CO}_2$ **{co2_mean:.0f} ppm** (tinggi). Tingkatkan ventilasi atau buka jendela sebentar sebelum tidur.")
    sleep_quality_score -= 7
elif co2_mean is not None:
    notes.append(f"Tingkat $\text{CO}_2$ ({co2_mean:.0f} ppm) sudah baik.")

if tvoc_mean is not None and tvoc_mean > TARGET_TVOC:
    tips.append(f"Tingkat TVOC **{tvoc_mean:.0f} ppb** (tinggi). Hindari produk berbau menyengat (parfum, pembersih) di kamar tidur.")
    sleep_quality_score -= 7
elif tvoc_mean is not None:
    notes.append(f"Tingkat TVOC ({tvoc_mean:.0f} ppb) sudah baik.")
    
# 5. Analisis Aktivitas (EOG)
if eog_mean is not None and eog_mean > 150: # Angka 150 ini adalah contoh heuristik, sesuaikan dengan hasil kalibrasi EOG
    tips.append(f"Aktivitas mata rata-rata (EOG) **tinggi**. Mungkin tidurmu tidak nyenyak (sering terbangun/fase REM aktif). Coba relaksasi mendalam sebelum tidur.")
    sleep_quality_score -= 8
elif eog_mean is not None:
     notes.append(f"Aktivitas mata rata-rata (EOG: {eog_mean:.1f}) menunjukkan tidur yang relatif tenang.")

final_score = max(0, min(100, sleep_quality_score))

with colB:
    st.write(f"**SKOR KUALITAS TIDUR:** **{final_score:.0f}/100**")
    st.write("**Saran untuk malam berikutnya:**")
    for t in tips: st.write("• " + t)
    
    if not tips:
        notes.append("Kualitas tidur & lingkungan sudah sangat baik. Lanjutkan kebiasaan yang sama 😴✨")

    if notes:
        st.write("**Catatan:**")
        for n in notes: st.write("- " + n)

st.caption(f"Terakhir diperbarui: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')} — auto refresh {refresh}s")

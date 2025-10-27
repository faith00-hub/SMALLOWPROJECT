# app.py — Smallow • Ubidots Realtime + AI Coach (Streamlit Cloud • STEM/Things)
from typing import Dict, List, Tuple
import time, requests, numpy as np, pandas as pd, altair as alt, streamlit as st

# ===== CONFIG via SECRETS =====
TOKEN    = st.secrets.get("UBIDOTS_TOKEN", "")
DEVICE   = st.secrets.get("UBIDOTS_DEVICE", "smallow")
BASE     = (st.secrets.get("UBIDOTS_BASE", "https://things.ubidots.com") or "").strip()
VARS     = [v.strip() for v in st.secrets.get("UBIDOTS_VARS", "temperature,humidity,fsr").split(",") if v.strip()]
LOCAL_TZ = st.secrets.get("LOCAL_TZ", "Asia/Jakarta")

# Paksa REST ke STEM/Things (jangan Industrial untuk akun STEM)
if "industrial.api.ubidots.com" in BASE.lower():
    BASE = "https://things.ubidots.com"

HEADERS = {"X-Auth-Token": TOKEN, "Content-Type": "application/json"}

# Heuristik AI
TARGET_TEMP_C=(18,22); TARGET_HUM_PCT=(40,50)
ACCEL_BURST_G=0.15; GYRO_BURST_DPS=20.0; RMS_MOV_LOW_G=0.06; SLEEP_TARGET_H=8.0

# ===== UI =====
st.set_page_config(page_title="Smallow • Ubidots Realtime + AI Coach", layout="wide")
st.title("😴 Smallow • Ubidots Realtime + AI Coach")
st.caption(f"Device: `{DEVICE}` • Vars: {', '.join(VARS)}")

refresh = st.sidebar.slider("Refresh (detik)", 5, 60, 10)
days    = st.sidebar.slider("Rentang data (hari, ≤30)", 1, 30, 3)
limit   = st.sidebar.slider("Batas titik/variabel", 50, 2000, 600, step=50)
agg_on  = st.sidebar.checkbox("Pakai agregasi (avg/1h) jika rentang besar", value=(days>7))
debug   = st.sidebar.checkbox("Tampilkan debug (ringkas)")
if st.sidebar.button("🔄 Clear cache"): st.cache_data.clear(); st.experimental_rerun()
st.sidebar.info(f"REST BASE in use:\n{BASE}")
st.autorefresh(interval=refresh*1000, key="auto_refresh")

def now_ms() -> int: return int(time.time()*1000)

# ===== FETCH =====
@st.cache_data(ttl=15, show_spinner=False)
def fetch_var_values(device: str, var: str, days_back: int, limit_total: int,
                     use_agg: bool) -> Tuple[Dict, pd.DataFrame, str]:
    """
    Coba THINGS → STEM; jika /values 401/402/403/404 atau kosong → fallback /lv.
    Return: (raw_json, df[time,value,variable], mode["values"|"lv"])
    """
    end = now_ms()
    start = end - days_back*24*60*60*1000
    page_size = 200
    total_left = max(1, limit_total)

    def values_url(base): return f"{base}/api/v1.6/devices/{device}/{var}/values"
    def lv_url(base):     return f"{base}/api/v1.6/devices/{device}/{var}/lv"

    bases: List[str] = []
    for b in [BASE, "https://things.ubidots.com", "https://stem.ubidots.com"]:
        if b and b not in bases: bases.append(b)

    params = {"start": start, "end": end}
    if use_agg: params.update({"aggregation": "avg", "resolution": "1h"})

    for base in bases:
        try:
            next_url, params_once = values_url(base), params.copy()
            results_all, left = [], total_left

            while next_url and left > 0:
                r = requests.get(next_url, headers=HEADERS,
                                 params={**params_once, "page_size": min(page_size, left)}, timeout=15)
                # Unauthorized/Payment/Forbidden/Not found -> coba /lv di base ini
                if r.status_code in (401, 402, 403, 404):
                    r2 = requests.get(lv_url(base), headers=HEADERS, timeout=10)
                    r2.raise_for_status()
                    last = r2.json()
                    df = pd.DataFrame([{
                        "time": pd.to_datetime(last["timestamp"], unit="ms", utc=True),
                        "value": last["value"],
                        "variable": var
                    }])
                    return last, df, "lv"

                r.raise_for_status()
                data = r.json()
                results_all += data.get("results", [])
                next_url = data.get("next")
                params_once = {}
                left -= page_size

            if not results_all:
                # values kosong → /lv
                r2 = requests.get(lv_url(base), headers=HEADERS, timeout=10)
                r2.raise_for_status()
                last = r2.json()
                df = pd.DataFrame([{
                    "time": pd.to_datetime(last["timestamp"], unit="ms", utc=True),
                    "value": last["value"],
                    "variable": var
                }])
                return last, df, "lv"

            rows = [{
                "time": pd.to_datetime(it["timestamp"], unit="ms", utc=True),
                "value": it["value"],
                "variable": var
            } for it in results_all[::-1]]
            return data, pd.DataFrame(rows), "values"

        except requests.RequestException:
            continue

    raise RuntimeError(f"{var}: semua endpoint gagal. Cek TOKEN/DEVICE/BASE (pakai things/stem).")

def merge_vars(device: str, vars_: List[str], days_back: int, limit_total: int, use_agg: bool):
    raws, frames, modes = {}, [], {}
    for v in vars_:
        raw, df, mode = fetch_var_values(device, v, days_back, limit_total, use_agg)
        raws[v]=raw; modes[v]=mode; frames.append(df)
    all_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not all_df.empty: all_df["time_local"] = all_df["time"].dt.tz_convert(LOCAL_TZ)
    return raws, all_df, modes

def np_safe(a): a=[x for x in a if x is not None]; return np.array(a, dtype=float) if a else np.array([])
def bursts(arr, thr): return int((np.abs(np.diff(arr)) > thr).sum()) if arr.size > 1 else 0

def estimate_sleep_hours(df_long: pd.DataFrame) -> float:
    if df_long.empty: return 0.0
    pv = df_long.pivot_table(index="time_local", columns="variable", values="value", aggfunc="last").sort_index()
    fsr = pv["fsr"].dropna() if "fsr" in pv.columns else pd.Series(dtype=float)
    if fsr.empty: return 0.0
    have_acc = all(v in pv.columns for v in ("accel_x","accel_y","accel_z"))
    a_mag = (np.sqrt(pv["accel_x"]**2 + pv["accel_y"]**2 + pv["accel_z"]**2).dropna()
             if have_acc else pd.Series(dtype=float))
    fsr_th = float(np.nanpercentile(fsr.values, 30)) if fsr.size else np.inf
    times = pv.index.to_list(); asleep = 0.0
    for i in range(1, len(times)):
        dt = (times[i]-times[i-1]).total_seconds(); dt = max(0.5, min(dt, 60.0))
        fsr_now = pv.iloc[i].get("fsr", np.nan)
        fsr_ok = pd.notna(fsr_now) and fsr_now > fsr_th
        motion_ok = True
        if have_acc and (times[i] in a_mag.index) and (times[i-1] in a_mag.index):
            motion_ok = abs(a_mag.loc[times[i]] - a_mag.loc[times[i-1]]) < RMS_MOV_LOW_G
        if fsr_ok and motion_ok: asleep += dt
    return asleep/3600.0

# ===== LOAD & SHOW =====
try:
    raw_map, df_all, mode_map = merge_vars(DEVICE, VARS, days_back=days, limit_total=limit, use_agg=agg_on)
except RuntimeError as e:
    st.error(f"Gagal mengambil data dari Ubidots (HTTP): {e}")
    st.stop()

if debug:
    st.subheader("Debug (ringkas)")
    st.json({k: ("(lv fallback)" if mode_map.get(k)=="lv" else "(values)") for k in raw_map.keys()})

if df_all.empty:
    st.warning("Tidak ada data pada rentang ini. Pastikan perangkat publish & variabel benar.")
    st.stop()

# KPI
latest = df_all.sort_values("time_local").groupby("variable").tail(1)[["variable","time_local","value"]]
cols = st.columns(min(4, len(latest)))
for i, (_, row) in enumerate(latest.iterrows()):
    cols[i % len(cols)].metric(row["variable"], f"{row['value']:.2f}" if isinstance(row["value"], (int,float)) else str(row["value"]))
    cols[i % len(cols)].caption(f"⏱️ {row['time_local']}")

# Grafik
choices = st.multiselect("Pilih variabel untuk grafik", options=VARS,
                         default=[v for v in VARS if v in ("temperature","humidity","fsr")] or VARS[:3])
plot_df = df_all[df_all["variable"].isin(choices)].dropna(subset=["value"])
if not plot_df.empty:
    chart = alt.Chart(plot_df).mark_line().encode(
        x=alt.X("time_local:T", title=f"Waktu ({LOCAL_TZ})"),
        y=alt.Y("value:Q", title="Nilai"),
        color="variable:N",
        tooltip=["time_local:T","variable:N","value:Q"]
    ).properties(height=320).interactive()
    st.altair_chart(chart, use_container_width=True)

with st.expander("Raw data"):
    st.dataframe(df_all.sort_values(["time_local","variable"]), use_container_width=True)

# ===== AI COACH =====
st.markdown("### 🧠 AI Coach")
pv = df_all.pivot_table(index="time_local", columns="variable", values="value", aggfunc="last").sort_index()
temp_mean = float(np.nanmean(pv["temperature"])) if "temperature" in pv.columns else None
hum_mean  = float(np.nanmean(pv["humidity"]))    if "humidity" in pv.columns else None

accel_bursts = gyro_bursts = 0
if all(v in pv.columns for v in ("accel_x","accel_y","accel_z")):
    ax, ay, az = [np_safe(pv[c].tolist()) for c in ("accel_x","accel_y","accel_z")]
    accel_bursts = bursts(ax, ACCEL_BURST_G) + bursts(ay, ACCEL_BURST_G) + bursts(az, ACCEL_BURST_G)
if all(v in pv.columns for v in ("gyro_x","gyro_y","gyro_z")):
    gx, gy, gz = [np_safe(pv[c].tolist()) for c in ("gyro_x","gyro_y","gyro_z")]
    gyro_bursts = bursts(gx, GYRO_BURST_DPS) + bursts(gy, GYRO_BURST_DPS) + bursts(gz, GYRO_BURST_DPS)
restlessness = min(100, (accel_bursts*0.8 + gyro_bursts*0.2))

sleep_hours = estimate_sleep_hours(df_all)

head_pos = None
if all(v in pv.columns for v in ("accel_x","accel_y","accel_z")):
    mx, my, mz = float(np.nanmean(pv["accel_x"])), float(np.nanmean(pv["accel_y"])), float(np.nanmean(pv["accel_z"]))
    dom = max(abs(mx), abs(my), abs(mz))
    head_pos = "telentang/terlungkup (Z)" if dom == abs(mz) else ("miring (X)" if dom == abs(mx) else "miring (Y)")

colA, colB = st.columns(2)
with colA:
    st.markdown("**Ringkasan:**")
    st.write(f"- Suhu rata-rata: **{temp_mean:.1f}°C**" if temp_mean is not None else "- Suhu: (N/A)")
    st.write(f"- RH rata-rata: **{hum_mean:.0f}%**" if hum_mean is not None else "- RH: (N/A)")
    st.write(f"- Restlessness: **{restlessness:.0f}/100**")
    st.write(f"- Durasi tidur estimasi: **{sleep_hours:.1f} jam** (target {SLEEP_TARGET_H:.0f} jam)")
    if head_pos: st.write(f"- Posisi kepala dominan: **{head_pos}**")

tips, notes = [], []
if sleep_hours < SLEEP_TARGET_H:
    lack = SLEEP_TARGET_H - sleep_hours
    tips.append(f"Durasi tidur **{sleep_hours:.1f} jam** (kurang {lack:.1f} jam). "
                "Coba **tidur 30–60 menit lebih awal**; konsistenkan jam bangun; hindari kafein ≥6 jam sebelum tidur.")
else:
    notes.append(f"Durasi tidur ~{sleep_hours:.1f} jam sudah memenuhi target. Nice!")

if temp_mean is not None:
    lo, hi = TARGET_TEMP_C
    if temp_mean < lo:
        tips.append(f"Suhu **{temp_mean:.1f}°C** (dingin). Naikkan ke ~{(lo+hi)//2}°C atau tambah selimut tipis.")
    elif temp_mean > hi:
        tips.append(f"Suhu **{temp_mean:.1f}°C** (hangat). Turunkan ke ~{(lo+hi)//2}°C (AC/kipas mode dry, ventilasi).")
    else:
        notes.append(f"Suhu **{temp_mean:.1f}°C** sudah nyaman ({lo}-{hi}°C).")

if hum_mean is not None:
    lo, hi = TARGET_HUM_PCT
    if hum_mean < lo:
        tips.append(f"RH **{hum_mean:.0f}%** (kering). Tambah humidifier hingga ~{(lo+hi)//2}%.")
    elif hum_mean > hi:
        tips.append(f"RH **{hum_mean:.0f}%** (lembap). Aktifkan mode dry/ventilasi; target ~{(lo+hi)//2}%.")
    else:
        notes.append(f"RH **{hum_mean:.0f}%** sudah baik ({lo}-{hi}%).")

if restlessness > 60:
    tips.append("Tidur cukup gelisah. Coba napas 4-7-8 10 menit, redupkan cahaya 1 jam sebelum tidur, batasi layar.")
elif restlessness > 30:
    tips.append("Gelisah ringan. Coba peregangan 5 menit & matikan notifikasi HP.")
else:
    notes.append("Gerakan minimal—kualitas tidur kemungkinan baik.")
tips.append("Lepaskan beban pikiran: 2 menit **brain dump** + 5 menit pernapasan pelan sebelum tidur.")

with colB:
    st.markdown("**Saran untuk malam berikutnya:**")
    for t in tips: st.write("• " + t)
    if notes:
        st.markdown("**Catatan:**")
        for n in notes: st.write("- " + n)

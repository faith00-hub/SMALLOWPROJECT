# app.py — Streamlit (Python desktop) — FIXED retention window + /lv fallback
import time, requests, pandas as pd, streamlit as st

# ===== Konfigurasi via Secrets =====
TOKEN  = st.secrets.get("UBIDOTS_TOKEN", "")
DEVICE = st.secrets.get("UBIDOTS_DEVICE", "smallow")
VAR    = st.secrets.get("UBIDOTS_VAR", "temperature")
BASE   = st.secrets.get("UBIDOTS_BASE", "https://industrial.api.ubidots.com")

HEADERS = {"X-Auth-Token": TOKEN, "Content-Type": "application/json"}

st.set_page_config(page_title="Smallow – Temperature", layout="wide")
st.title("🌡️ Smallow – Temperature Monitor")
st.caption(f"Device: `{DEVICE}` • Variable: `{VAR}`")

# Sidebar controls
refresh = st.sidebar.slider("Refresh (detik)", 5, 60, 10)
days    = st.sidebar.slider("Rentang data (hari, ≤30)", 1, 30, 7)
debug   = st.sidebar.checkbox("Tampilkan debug response")

def now_ms():
    return int(time.time() * 1000)

@st.cache_data(ttl=15)
def fetch_values(device, var, days_back=7, limit=200):
    """
    Ambil data dalam jendela 'days_back' terakhir agar tidak melanggar retention.
    Jika 403/404, fallback ke last value (/lv) agar tetap ada tampilan.
    """
    end = now_ms()
    start = end - days_back * 24 * 60 * 60 * 1000  # ms

    url_values = f"{BASE}/api/v1.6/devices/{device}/{var}/values"
    params = {
        "page_size": min(limit, 200),   # batas page_size Ubidots
        "start": start,
        "end": end,
        # Jika ingin mereduksi titik saat days besar, aktifkan agregasi:
        # "aggregation": "avg", "resolution": "1h"
    }
    r = requests.get(url_values, headers=HEADERS, params=params, timeout=12)

    # Fallback bila retention/404
    if r.status_code in (403, 404):
        url_lv = f"{BASE}/api/v1.6/devices/{device}/{var}/lv"
        r2 = requests.get(url_lv, headers=HEADERS, timeout=10)
        if r2.status_code != 200:
            raise RuntimeError(f"HTTP {r2.status_code} (lv): {r2.text[:300]}")
        last = r2.json()  # {"value":..., "timestamp":...}
        df = pd.DataFrame([{
            "time": pd.to_datetime(last["timestamp"], unit="ms"),
            "value": last["value"]
        }])
        return {"fallback": "lv", "raw": last}, df

    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")

    data = r.json()
    results = data.get("results", [])
    rows = [{
        "time": pd.to_datetime(it["timestamp"], unit="ms"),
        "value": it["value"]
    } for it in results[::-1]]  # urut waktu naik
    return data, pd.DataFrame(rows)

try:
    raw, df = fetch_values(DEVICE, VAR, days_back=days, limit=300)

    if debug:
        st.subheader("Debug JSON (ringkas)")
        st.json(raw)

    if df.empty:
        st.warning(
            "Tidak ada data pada rentang ini. "
            "Pastikan ESP32 masih publish dan pilih rentang ≤ 30 hari."
        )
    else:
        latest_val = df.iloc[-1]["value"]
        latest_ts  = df.iloc[-1]["time"]

        c1, c2 = st.columns([1, 2])
        with c1:
            st.metric("Suhu sekarang", f"{latest_val:.1f} °C")
            st.caption(f"⏱️ Updated: {latest_ts}")
        with c2:
            st.line_chart(df.set_index("time")["value"], height=280)

        if latest_val >= 28:
            st.success("🔥 Suhu tinggi")
        else:
            st.info("🌿 Suhu normal")

except RuntimeError as e:
    st.error(f"Gagal mengambil data dari Ubidots: {e}")
except Exception as e:
    st.error(f"Kesalahan tak terduga: {e}")

time.sleep(refresh)
st.rerun()

# app.py — Streamlit (Python desktop)
import os, time, requests, pandas as pd, streamlit as st

# ===== Konfigurasi via Secrets (disarankan) =====
TOKEN  = st.secrets.get("UBIDOTS_TOKEN", "")       # BBUS-...
DEVICE = st.secrets.get("UBIDOTS_DEVICE", "smallow")
VAR    = st.secrets.get("UBIDOTS_VAR", "temperature")
BASE   = st.secrets.get("UBIDOTS_BASE", "https://industrial.api.ubidots.com")

URL = f"{BASE}/api/v1.6/devices/{DEVICE}/{VAR}/values"
HEADERS = {"X-Auth-Token": TOKEN, "Content-Type": "application/json"}

st.set_page_config(page_title="Smallow – Temperature", layout="wide")
st.title("🌡️ Smallow – Temperature Monitor")
st.caption(f"Device: `{DEVICE}` • Variable: `{VAR}`")

refresh = st.sidebar.slider("Refresh (detik)", 5, 60, 10)
debug   = st.sidebar.checkbox("Tampilkan debug response")

@st.cache_data(ttl=15)
def fetch_values(limit=200):
    r = requests.get(URL, headers=HEADERS, timeout=12)
    if r.status_code != 200:
        # lempar pesan yang jelas untuk ditampilkan
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    # Struktur normal Ubidots: {"count": int, "results": [ ... ]}
    results = data.get("results", [])
    rows = []
    for it in results[:limit][::-1]:
        ts = pd.to_datetime(it["timestamp"], unit="ms")
        rows.append({"time": ts, "value": it["value"]})
    return data, pd.DataFrame(rows)

try:
    raw, df = fetch_values(limit=300)

    if debug:
        st.subheader("Debug JSON")
        st.json(raw)

    if df.empty:
        st.warning("Tidak ada data pada variable ini. "
                   "Periksa apakah ESP32 sudah publish dan label device/variable benar.")
    else:
        latest_val = df.iloc[-1]["value"]
        latest_ts  = df.iloc[-1]["time"]
        c1, c2 = st.columns([1,2])
        with c1:
            st.metric("Suhu sekarang", f"{latest_val:.1f} °C")
            st.caption(f"⏱️ Updated: {latest_ts}")
        with c2:
            st.line_chart(df.set_index("time")["value"], height=260)

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

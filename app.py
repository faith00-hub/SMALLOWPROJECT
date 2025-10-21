import time
import pandas as pd
import requests
import streamlit as st

# asumsi BASE, DEVICE, VAR, HEADERS sudah didefinisikan seperti di kode kamu

def now_ms():
    return int(time.time() * 1000)

@st.cache_data(ttl=15)
def fetch_values(limit=200, days=7):
    """
    Ambil data aman dalam window 'days' terakhir untuk menghindari 403 retention.
    Juga sediakan fallback ke /lv (last value) jika /values gagal.
    """
    end = now_ms()
    start = end - days * 24 * 60 * 60 * 1000  # ms
    params = {
        "page_size": min(limit, 200),  # batas aman Ubidots
        "start": start,
        "end": end
        # bisa tambah "aggregation":"avg","resolution":"1h" jika perlu agregasi
    }

    url_values = f"{BASE}/api/v1.6/devices/{DEVICE}/{VAR}/values"
    r = requests.get(url_values, headers=HEADERS, params=params, timeout=12)

    # Jika retention still trigger (403) atau error lain, fallback ke /lv
    if r.status_code == 403 or r.status_code == 404:
        url_lv = f"{BASE}/api/v1.6/devices/{DEVICE}/{VAR}/lv"
        r2 = requests.get(url_lv, headers=HEADERS, timeout=10)
        if r2.status_code != 200:
            raise RuntimeError(f"HTTP {r2.status_code} (lv): {r2.text[:300]}")
        last = r2.json()  # {"value":..., "timestamp":...}
        df = pd.DataFrame([{
            "time": pd.to_datetime(last["timestamp"], unit="ms"),
            "value": last["value"]
        }])
        return {"fallback":"lv","raw":last}, df

    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")

    data = r.json()
    results = data.get("results", [])
    rows = [{
        "time": pd.to_datetime(it["timestamp"], unit="ms"),
        "value": it["value"]
    } for it in results[::-1]]  # urut naik waktu
    return data, pd.DataFrame(rows)

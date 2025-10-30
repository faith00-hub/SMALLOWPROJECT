import sys, platform, importlib
import streamlit as st

st.set_page_config(page_title="Smoke Test", page_icon="🛠️")
st.title("✅ Streamlit Smoke Test")

st.write("Python:", sys.version)
st.write("Platform:", platform.platform())

# Coba import paket inti kamu
pkgs = ["requests", "pandas", "numpy", "altair", "pymongo"]
bad = []
for name in pkgs:
    try:
        importlib.import_module(name)
    except Exception as e:
        bad.append((name, repr(e)))

if bad:
    st.error("Paket bermasalah saat import:")
    for name, err in bad:
        st.code(f"{name}: {err}")
else:
    st.success("Semua paket inti berhasil di-import.")

# Opsional: info versi
try:
    import pandas as pd, numpy as np, altair as alt
    st.write("pandas:", pd.__version__)
    st.write("numpy:", np.__version__)
    st.write("altair:", alt.__version__)
except Exception as e:
    st.warning(f"Gagal cek versi: {e}")

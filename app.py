import streamlit as st
import requests
import pandas as pd
import time

# Token dan device Ubidots
TOKEN = "BBUS-By0MuOFjSKRYVI4fGEKIj34EFUigqd"
DEVICE_LABEL = "smallow"
VARIABLE = "temperature"

URL = f"https://industrial.api.ubidots.com/api/v1.6/devices/{DEVICE_LABEL}/{VARIABLE}/values"
HEADERS = {"X-Auth-Token": TOKEN, "Content-Type": "application/json"}

st.title("🌡️ Smallow Temperature Monitor")
st.write("Data real-time dari ESP32 via Ubidots")

def get_data():
    r = requests.get(URL, headers=HEADERS)
    data = r.json()["results"]
    df = pd.DataFrame([
        {"Time": pd.to_datetime(d["timestamp"], unit="ms"), "Value": d["value"]}
        for d in data
    ])
    return df

df = get_data()
st.line_chart(df.set_index("Time")["Value"])
st.dataframe(df)

time.sleep(10)
st.experimental_rerun()

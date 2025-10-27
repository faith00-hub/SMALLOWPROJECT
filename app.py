@st.cache_data(ttl=15, show_spinner=False)
def fetch_var_values(device: str, var: str, days_back: int, limit_total: int,
                     use_agg: bool) -> Tuple[Dict, pd.DataFrame, str]:
    """
    Ambil data 1 variabel Ubidots dengan fallback otomatis:
    - Coba THINGS → STEM → (opsional) INDUSTRIAL
    - Jika 401/402/403/404 pada values, fallback ke /lv di base yg sama
    - Jika base pertama gagal 401/402, lanjut ke base berikutnya
    """
    end = int(time.time() * 1000)
    start = end - days_back * 24 * 60 * 60 * 1000
    page_size = 200
    total_left = max(1, limit_total)

    # Susun urutan base yang dicoba
    bases = []
    # jika BASE user sudah things/stem, pakai itu dulu
    if "things.ubidots.com" in BASE or "stem.ubidots.com" in BASE:
        bases = [BASE]
    # tambahkan alternatif
    for b in ["https://things.ubidots.com", "https://stem.ubidots.com", "https://industrial.api.ubidots.com"]:
        if b not in bases:
            bases.append(b)

    def values_url(base): return f"{base}/api/v1.6/devices/{device}/{var}/values"
    def lv_url(base):     return f"{base}/api/v1.6/devices/{device}/{var}/lv"

    params = {"start": start, "end": end}
    if use_agg:
        params.update({"aggregation": "avg", "resolution": "1h"})

    # Coba tiap base sampai ada yang sukses
    for base in bases:
        try:
            next_url, params_once = values_url(base), params.copy()
            results_all = []
            left = total_left

            while next_url and left > 0:
                r = requests.get(next_url, headers=HEADERS,
                                 params={**params_once, "page_size": min(page_size, left)}, timeout=15)

                # Jika unauthorized/payment/forbidden/not-found → coba lv di base ini
                if r.status_code in (401, 402, 403, 404):
                    r2 = requests.get(lv_url(base), headers=HEADERS, timeout=10)
                    r2.raise_for_status()
                    last = r2.json()
                    df = pd.DataFrame([{
                        "time": pd.to_datetime(last["timestamp"], unit="ms", utc=True),
                        "value": last["value"], "variable": var
                    }])
                    return last, df, "lv"

                r.raise_for_status()
                data = r.json()
                results_all += data.get("results", [])
                next_url = data.get("next")
                params_once = {}
                left -= page_size

            # Susun DF dari values
            rows = [{
                "time": pd.to_datetime(it["timestamp"], unit="ms", utc=True),
                "value": it["value"], "variable": var
            } for it in results_all[::-1]]
            df = pd.DataFrame(rows)

            if df.empty:
                # coba lv
                r2 = requests.get(lv_url(base), headers=HEADERS, timeout=10)
                r2.raise_for_status()
                last = r2.json()
                df = pd.DataFrame([{
                    "time": pd.to_datetime(last["timestamp"], unit="ms", utc=True),
                    "value": last["value"], "variable": var
                }])
                return last, df, "lv"

            return data, df, "values"

        except requests.RequestException:
            # network error → coba base berikutnya
            continue

    raise RuntimeError(f"{var}: semua endpoint gagal. Cek UBIDOTS_BASE & TOKEN di Secrets.")

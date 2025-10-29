# main.py - REVISI FINAL SESUAI LIBRARY SGP30 & MAX30102
# ======================================================
from machine import I2C, Pin, ADC, PWM
from time import sleep, ticks_ms, ticks_diff
import sys, network, ujson, usocket

# --- Import Semua Driver/Library Pihak Ketiga ---
from sht31 import SHT31
from sgp30 import SGP30
from max30102 import MAX30102
from ad8232 import AD8232  # Pastikan ALPHA_HPF = 0.95 di file ini

# =====================================================
# 1️⃣ KONFIGURASI PIN & KREDENSIAL
# =====================================================
WIFI_SSID = "OPPO A9 2020"
WIFI_PASSWORD = "GoSukses"
UBIDOTS_TOKEN = "BBUS-By0MuOFjSKRYVI4fGEKIj34EFUigqd"
UBIDOTS_DEVICE_LABEL = "smallow"
UBIDOTS_URL = "industrial.api.ubidots.com"  # FIXED
SEND_INTERVAL_MS = 60000  # 60 detik

# I2C
I2C_SDA_PIN, I2C_SCL_PIN, I2C_FREQ = 21, 22, 100000

# Motor DRV8833
MOTOR1_PWM_PIN, MOTOR2_PWM_PIN, PWM_FREQ = 18, 19, 20000

# Analog Sensors
FSR1_ADC_PIN, FSR2_ADC_PIN, EKG_ADC_PIN = 32, 33, 34
LO_PLUS_PIN, LO_MINUS_PIN = 25, 26

# Parameter EOG & Alarm
FSR_TEKANAN_MIN = 1000
EOG_KEDIPAN_MIN_NORMAL = 200
EOG_KEDIPAN_BAWAH_ALARM = 50
DURASI_TIDUR_MAKS_MS = 8 * 3600 * 1000
LEADS_OFF_DEBOUNCE_MS = 1000

# =====================================================
# 2️⃣ UTILITAS & FUNGSI PENDUKUNG
# =====================================================
def connect_wifi(ssid, password):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting Wi-Fi...")
        wlan.connect(ssid, password)
        for _ in range(20):
            if wlan.isconnected():
                break
            print(".", end="")
            sleep(0.5)
    if wlan.isconnected():
        print("\n✅ Wi-Fi connected:", wlan.ifconfig()[0])
    else:
        raise Exception("❌ Gagal konek Wi-Fi")
    return wlan


def send_data_to_ubidots(token, device_label, data_payload):
    url_path = f"/api/v1.6/devices/{device_label}"
    try:
        if not network.WLAN(network.STA_IF).isconnected():
            print("❌ Wi-Fi disconnected")
            return False
        addr = usocket.getaddrinfo(UBIDOTS_URL, 80)[0][-1]
        s = usocket.socket()
        s.connect(addr)
        payload_json = ujson.dumps(data_payload)
        request = (
            f"POST {url_path} HTTP/1.1\r\n"
            f"Host: {UBIDOTS_URL}\r\n"
            f"X-Auth-Token: {token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload_json)}\r\n\r\n"
            f"{payload_json}"
        )
        s.sendall(request.encode())
        resp = s.recv(256)
        code = resp.decode().split()[1] if resp else "N/A"
        print(f"✅ Ubidots Response: {code}")
        s.close()
        return True
    except Exception as e:
        print("❌ Ubidots send failed:", e)
        try:
            s.close()
        except:
            pass
        return False


def set_vibration(level):
    level = max(0, min(1023, level))
    motor1_pwm.duty(level)
    motor2_pwm.duty(level)


def read_fsr(sensor):
    return sensor.read() < FSR_TEKANAN_MIN


# =====================================================
# 3️⃣ WRAPPER SENSOR (DIESESUIKAN DENGAN LIBRARY KAMU)
# =====================================================
def sgp30_read(sgp):
    """Baca eCO2 (ppm) dan TVOC (ppb) dari SGP30."""
    try:
        data = sgp.read_air_quality()  # fungsi dari file sgp30.py kamu
        co2 = data.get("eCO2", -1)
        tvoc = data.get("TVOC", -1)
        return co2, tvoc
    except Exception as e:
        print("SGP30 read error:", e)
        return -1, -1


def max_read_raw(mx):
    """Baca data mentah (Red & IR) dari MAX30102."""
    try:
        red, ir = mx.read_fifo()
        return red, ir
    except Exception as e:
        print("MAX30102 read error:", e)
        return -1, -1


# =====================================================
# 4️⃣ INISIALISASI SISTEM
# =====================================================
print("\n--- SYSTEM INIT ---")
try:
    i2c_bus = I2C(0, sda=Pin(I2C_SDA_PIN), scl=Pin(I2C_SCL_PIN), freq=I2C_FREQ)
    print("I2C devices:", [hex(x) for x in i2c_bus.scan()])

    sht = SHT31(i2c_bus)
    sgp = SGP30(i2c_bus)
    max30102 = MAX30102(i2c_bus)

    fsr1, fsr2 = ADC(Pin(FSR1_ADC_PIN)), ADC(Pin(FSR2_ADC_PIN))
    ekg = AD8232(EKG_ADC_PIN)
    raw_adc = ADC(Pin(EKG_ADC_PIN))
    raw_adc.width(ADC.WIDTH_12BIT); raw_adc.atten(ADC.ATTN_11DB)

    lo_plus, lo_minus = Pin(LO_PLUS_PIN, Pin.IN), Pin(LO_MINUS_PIN, Pin.IN)
    fsr1.width(ADC.WIDTH_12BIT); fsr1.atten(ADC.ATTN_11DB)
    fsr2.width(ADC.WIDTH_12BIT); fsr2.atten(ADC.ATTN_11DB)

    motor1_pwm = PWM(Pin(MOTOR1_PWM_PIN), freq=PWM_FREQ, duty=0)
    motor2_pwm = PWM(Pin(MOTOR2_PWM_PIN), freq=PWM_FREQ, duty=0)

    wlan = connect_wifi(WIFI_SSID, WIFI_PASSWORD)
    print("✅ Init complete.")
except Exception as e:
    print("❌ INIT ERROR:", e)
    sys.exit()

# =====================================================
# 5️⃣ LOOP UTAMA
# =====================================================
start_sleep_time = None
is_fsr_pressed = False
is_leads_off = False
lo_status_start = None
LAST_SEND = ticks_ms()

temp, hum, co2, tvoc, red, ir = -1, -1, -1, -1, -1, -1
print("\n--- START MONITOR ---")

try:
    while True:
        # Leads off check
        current_lo = (lo_plus.value() == 1) or (lo_minus.value() == 1)
        if current_lo and lo_status_start is None:
            lo_status_start = ticks_ms()
        elif not current_lo:
            lo_status_start = None
            is_leads_off = False
        if lo_status_start and ticks_diff(ticks_ms(), lo_status_start) > LEADS_OFF_DEBOUNCE_MS:
            is_leads_off = True

        ekg_val = ekg.read_eog() if not is_leads_off else -1
        fsr1_raw, fsr2_raw = fsr1.read(), fsr2.read()
        fsr1_press, fsr2_press = read_fsr(fsr1), read_fsr(fsr2)
        is_fsr_pressed = fsr1_press or fsr2_press
        raw_val = raw_adc.read()

        # Logika kantuk
        VIB = 0
        status = "NORMAL"
        durasi = 0

        if is_leads_off:
            status = "⚠️ ELEKTRODA LEPAS"
            VIB = 0
            start_sleep_time = None
        elif is_fsr_pressed:
            if start_sleep_time is None:
                start_sleep_time = ticks_ms()
            durasi = ticks_diff(ticks_ms(), start_sleep_time)
            if durasi >= DURASI_TIDUR_MAKS_MS:
                VIB = 1023; status = "⏰ 8 JAM TERLAMPAUI!"
            elif ekg_val >= EOG_KEDIPAN_MIN_NORMAL:
                VIB = 0; status = "AKTIF"
            elif ekg_val < EOG_KEDIPAN_BAWAH_ALARM:
                VIB = 1023; status = "😴 KANTUK BERAT!"
            else:
                VIB = 300; status = "💤 MULAI KANTUK"
        else:
            start_sleep_time = None
            status = "TIDAK ADA TEKANAN"

        set_vibration(VIB)

        # Kirim tiap interval
        if ticks_diff(ticks_ms(), LAST_SEND) >= SEND_INTERVAL_MS:
            try:
                temp, hum = sht.read_data()
                co2, tvoc = sgp30_read(sgp)
                red, ir = max_read_raw(max30102)
            except Exception as e:
                print("Read sensor error:", e)

            payload = {
                "fsr1-raw": fsr1_raw,
                "fsr2-raw": fsr2_raw,
                "eog-mag": ekg_val,
                "vibration": VIB,
                "lead-off": is_leads_off,
                "temp-c": temp,
                "hum-rh": hum,
                "co2-ppm": co2,
                "tvoc-ppb": tvoc,
                "max-red": red,
                "max-ir": ir,
            }
            send_data_to_ubidots(UBIDOTS_TOKEN, UBIDOTS_DEVICE_LABEL, payload)
            LAST_SEND = ticks_ms()

        # Log serial
        print("==========================================================")
        print(f"[{status}] Motor:{VIB}/1023")
        if start_sleep_time and not is_leads_off:
            print(f"Durasi tidur: {durasi/3600000:.2f} jam")
        print(f"FSR1={fsr1_raw}, FSR2={fsr2_raw}, Tekan={is_fsr_pressed}")
        print(f"EOG={ekg_val:.1f}, ADC={raw_val}, LeadsOff={is_leads_off}")
        print(f"Temp={temp:.1f}°C | CO2={co2}ppm | TVOC={tvoc}ppb")
        print(f"MAX(Red)={red} | IR={ir}")
        print("==========================================================")
        sleep(0.5)

except KeyboardInterrupt:
    set_vibration(0)
    print("Program dihentikan.")
except Exception as e:
    set_vibration(0)
    print("❌ Fatal error:", e)

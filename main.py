# main.py - Sistem Deteksi Kantuk dan Alarm + Ubidots Telemetry
from machine import I2C, Pin, ADC, PWM
from time import sleep, ticks_ms, ticks_diff
import sys
import network # WAJIB: Untuk koneksi Wi-Fi
import ujson # WAJIB: Untuk format JSON payload
import usocket # WAJIB: Untuk koneksi HTTP/Socket

# --- Import Semua Driver/Library Pihak Ketiga (Anggap file .py ini sudah ada) ---
from sht31 import SHT31
from sgp30 import SGP30
from max30102 import MAX30102
from ad8232 import AD8232 


# -------------------------------------------------------------------
# --- 1. KONFIGURASI PIN & KREDENSIAL (ISI YANG KOSONG) ---
# -------------------------------------------------------------------

# KREDENSIAL WI-FI DAN UBIDOTS (WAJIB DIUBAH)
WIFI_SSID = "OPPO A9 2020"
WIFI_PASSWORD = "GoSukses"
UBIDOTS_TOKEN = "BBUS-By0MuOFjSKRYVI4fGEKIj34EFUigqd" 
UBIDOTS_DEVICE_LABEL = "smallow"
UBIDOTS_URL = "things.ubidots.com"
SEND_INTERVAL_MS = 60000 # Kirim data setiap 60 detik

# I2C Bus
I2C_SDA_PIN = 21 
I2C_SCL_PIN = 22
I2C_FREQ = 100000 

# Motor Driver DRV8833
MOTOR1_PWM_PIN = 18
MOTOR2_PWM_PIN = 19
PWM_FREQ = 20000

# Analog Sensors
FSR1_ADC_PIN = 32
FSR2_ADC_PIN = 33
EKG_ADC_PIN = 27 


# --- 2. PARAMETER KANTUK & ALARM ---

FSR_TEKANAN_MIN = 1000
EKG_ANOMALI_BAWAH = 1000
EKG_NORMAL_ATAS = 3000
DURASI_TIDUR_MAKS_MS = 8 * 3600 * 1000 


# -------------------------------------------------------------------
# --- 3. FUNGSI UBIDOTS, WI-FI, DAN KONTROL (TIDAK BERUBAH DARI ASLI) ---
# -------------------------------------------------------------------

def connect_wifi(ssid, password):
    """Menghubungkan ESP32 ke jaringan Wi-Fi."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print('Connecting to network...')
        wlan.connect(ssid, password)
        # Menambahkan timeout untuk menghindari loop tak terbatas jika koneksi gagal
        max_attempts = 20
        while not wlan.isconnected() and max_attempts > 0:
            sleep(0.5)
            print('.', end='')
            max_attempts -= 1
        
        if wlan.isconnected():
            print('\n✅ Wi-Fi connected')
            print('IP Address:', wlan.ifconfig()[0])
            return wlan
        else:
            print('\n❌ Wi-Fi Connection FAILED!')
            print(f'Status koneksi: {wlan.status()}')
            raise Exception("Gagal terhubung ke Wi-Fi. Cek SSID/Password.")


def send_data_to_ubidots(token, device_label, data_payload):
    """Mengirim data JSON ke Ubidots melalui HTTP POST."""
    
    url_path = f"/api/v1.6/devices/{device_label}" 
    
    try:
        # Pengecekan status koneksi
        if not network.WLAN(network.STA_IF).isconnected():
             print("❌ UBIDOTS FAILED: Wi-Fi disconnected.")
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
            f"Content-Length: {len(payload_json)}\r\n"
            "\r\n"
            f"{payload_json}"
        )
        
        s.sendall(request.encode('utf-8'))
        
        response = s.recv(1024)
        response_code = response.decode().split()[1] if response else "N/A"
        print(f"✅ Data sent. Ubidots Response Code: {response_code}")
        s.close()
        return True

    except Exception as e:
        print(f"❌ UBIDOTS SEND FAILED: {e}")
        try:
            s.close()
        except NameError:
            pass # Socket belum sempat dibuat/didefinisikan
        return False

def set_vibration(intensity):
    """Mengatur intensitas getaran kedua motor (0-1023)."""
    duty = max(0, min(1023, intensity))
    motor1_pwm.duty(duty)
    motor2_pwm.duty(duty)

def read_fsr(sensor):
    """Membaca nilai FSR, True jika tertekan keras."""
    raw = sensor.read()
    return raw < FSR_TEKANAN_MIN


# -------------------------------------------------------------------
# --- 4. INISIALISASI SISTEM (Perubahan: Menambahkan 'raise Exception') ---
# -------------------------------------------------------------------

print("--- SYSTEM INITIALIZATION ---")

try:
    # 4.1 INISIALISASI I2C DAN SENSOR
    i2c_bus = I2C(0, sda=Pin(I2C_SDA_PIN), scl=Pin(I2C_SCL_PIN), freq=I2C_FREQ)
    
    sgp = SGP30(i2c_bus) 
    max30102 = MAX30102(i2c_bus)
    sht = SHT31(i2c_bus) 

    # 4.2 INISIALISASI ANALOG
    fsr1 = ADC(Pin(FSR1_ADC_PIN)); fsr2 = ADC(Pin(FSR2_ADC_PIN))
    ekg = AD8232(EKG_ADC_PIN)
    fsr1.width(ADC.WIDTH_12BIT); fsr1.atten(ADC.ATTN_11DB)
    fsr2.width(ADC.WIDTH_12BIT); fsr2.atten(ADC.ATTN_11DB)
    
    # 4.3 INISIALISASI MOTOR
    motor1_pwm = PWM(Pin(MOTOR1_PWM_PIN), freq=PWM_FREQ, duty=0)
    motor2_pwm = PWM(Pin(MOTOR2_PWM_PIN), freq=PWM_FREQ, duty=0)
    
    # 4.4 INISIALISASI WI-FI
    # Menangkap hasil return wlan, meski tidak digunakan selanjutnya
    wlan = connect_wifi(WIFI_SSID, WIFI_PASSWORD) 

    print("✅ Semua Sensor dan Driver OK.")
except Exception as e:
    # Jika terjadi error saat inisialisasi (termasuk Wi-Fi error), program keluar
    print(f"❌ INISIALISASI GAGAL: {e}"); sys.exit() 


# -------------------------------------------------------------------
# --- 5. VARIABEL KONTROL WAKTU & LOOP UTAMA ---
# -------------------------------------------------------------------

start_sleep_time = None 
is_fsr_pressed = False
LAST_SEND_TIME = ticks_ms()

# Variabel untuk menahan nilai sensor I2C yang terakhir dibaca
# agar tetap bisa ditampilkan di print log saat data belum dikirim
temp, hum, co2, tvoc, hr, spo2 = -1.0, -1.0, -1, -1, -1, -1 

print("\n--- STARTING MAIN LOOP (Monitor Mode) ---")

try:
    while True:
        # --- Pembacaan Data ---
        ekg_val = ekg.read_ekg()
        fsr1_raw = fsr1.read()
        fsr2_raw = fsr2.read()
        fsr1_pressed = read_fsr(fsr1)
        fsr2_pressed = read_fsr(fsr2)
        
        is_fsr_pressed = fsr1_pressed or fsr2_pressed
        
        # --- Logika Deteksi Kantuk ---
        VIBRATION_INTENSITY = 0 
        status_msg = "NORMAL"
        sleep_duration = 0 # Default

        if is_fsr_pressed:
            if start_sleep_time is None:
                start_sleep_time = ticks_ms() 
                status_msg = "POSISI ISTIRAHAT DITERIMA"
                
            sleep_duration = ticks_diff(ticks_ms(), start_sleep_time)
            
            if sleep_duration >= DURASI_TIDUR_MAKS_MS:
                VIBRATION_INTENSITY = 1023
                status_msg = "ALARM! WAKTU TIDUR MAKS (8 JAM) TERLAMPAUI"
            else:
                if ekg_val > EKG_NORMAL_ATAS:
                    VIBRATION_INTENSITY = 0
                    status_msg = "DIAM - TIDAK ADA TANDA KANTUK"
                elif ekg_val < EKG_ANOMALI_BAWAH:
                    VIBRATION_INTENSITY = 1023
                    status_msg = "KRITIS! KEDIP LEMAH/ANOMALI, GETAR PENUH!"
                else:
                    VIBRATION_INTENSITY = 300
                    status_msg = "AWAL KANTUK/LEMAH, GETAR LAMBAT"
        else:
            start_sleep_time = None
            status_msg = "TIDAK ADA TEKANAN FSR / BERGERAK"

        # --- Eksekusi Aksi ---
        set_vibration(VIBRATION_INTENSITY)
        
        # --- Pengiriman Data ke Ubidots ---
        if ticks_diff(ticks_ms(), LAST_SEND_TIME) >= SEND_INTERVAL_MS:
            # Ambil data I2C
            try:
                temp, hum = sht.read_data()
                # ASUMSI: SGP30 memiliki fungsi read_iaq()
                co2, tvoc = sgp.read_iaq() 
                # ASUMSI: MAX30102 memiliki fungsi read_hr_spo2()
                hr, spo2 = max30102.read_hr_spo2() 
            except Exception as e:
                 print(f"Error reading I2C data for upload: {e}")
                 # Nilai error yang terakhir akan tetap digunakan (-1)

            # Payload JSON untuk Ubidots
            data_payload = {
                "fsr1-raw": fsr1_raw,
                "fsr2-raw": fsr2_raw,
                "ekg-raw": ekg_val,
                "status-getaran": VIBRATION_INTENSITY,
                "suhu-c": temp,
                "kelembaban-rh": hum,
                "co2-iaq": co2,
                "tvoc-iaq": tvoc,
                "detak-jantung-hr": hr,
                "oksigen-spo2": spo2
            }
            
            send_data_to_ubidots(UBIDOTS_TOKEN, UBIDOTS_DEVICE_LABEL, data_payload)
            LAST_SEND_TIME = ticks_ms()
        
        # --- Tampilkan Data ---
        print("==========================================================")
        print(f"[{status_msg}] Motor Intensity: {VIBRATION_INTENSITY}/1023")
        if start_sleep_time is not None:
             hours = sleep_duration / 3600000
             print(f"⏰ Durasi Istirahat Terdeteksi: {hours:.2f} Jam")
        print(f"FSR (Raw): F1={fsr1_raw}, F2={fsr2_raw} | Tekan: {is_fsr_pressed}")
        print(f"EKG (Raw): {ekg_val} | Temp: {temp:.1f}C | CO2: {co2} ppm")
        print("==========================================================")
        
        sleep(0.5)

except KeyboardInterrupt:
    print("\nProgram dihentikan. Mematikan Motor...")
    set_vibration(0)
    
except Exception as e:
    print(f"\n❌ FATAL ERROR: {e}. Program dihentikan. Mematikan Motor...")
    set_vibration(0)

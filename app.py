import network, time, ujson
from machine import Pin
import dht
from umqtt.simple import MQTTClient

# ====== KONFIGURASI ======
SSID = "LABCOM MAN 1 Kota Sukabumi"
PASSWORD = "@Userlabcom1234"

TOKEN = "BBUS-By0MuOFjSKRYVI4fGEKIj34EFUigqd"  # Ubidots TOKEN = username MQTT
DEVICE_LABEL = "smallow"                        # label device di Ubidots
VAR_TEMP = "temperature"                        # label variabel suhu

MQTT_BROKER = "industrial.api.ubidots.com"
MQTT_PORT   = 1883
CLIENT_ID   = b"esp32-" + str(time.ticks_ms()).encode()
TOPIC       = b"/v1.6/devices/" + DEVICE_LABEL.encode()  # publish topic

READ_PERIOD = 10   # detik, interval kirim

# ====== WIFI ======
def connect_wifi():
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    if not sta.isconnected():
        print("Menyambungkan Wi-Fi...")
        sta.connect(SSID, PASSWORD)
        t0 = time.ticks_ms()
        while not sta.isconnected():
            if time.ticks_diff(time.ticks_ms(), t0) > 15000:
                raise RuntimeError("Timeout Wi-Fi")
            time.sleep(0.2)
    print("Wi-Fi OK:", sta.ifconfig())

# ====== DHT11 ======
sensor = dht.DHT11(Pin(4))

def read_temp():
    # coba beberapa kali agar stabil
    for _ in range(3):
        try:
            sensor.measure()
            t = sensor.temperature()
            if 0 <= t <= 60:
                return t
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError("Gagal baca DHT11")

# ====== MQTT ======
def mqtt_connect():
    # username=TOKEN, password boleh kosong
    client = MQTTClient(client_id=CLIENT_ID,
                        server=MQTT_BROKER,
                        port=MQTT_PORT,
                        user=TOKEN,
                        password="",
                        keepalive=30)
    client.connect()
    return client

def publish_temp(client, t):
    payload = {VAR_TEMP: t}            # {"temperature": 29}
    msg = ujson.dumps(payload).encode()
    client.publish(TOPIC, msg)
    print("Published:", msg)

def main():
    connect_wifi()
    client = mqtt_connect()
    print("MQTT connected → Ubidots")
    print("Kirim suhu tiap", READ_PERIOD, "detik. Ctrl+C untuk berhenti.")

    while True:
        try:
            t = read_temp()
            print("Suhu:", t, "°C")
            publish_temp(client, t)
        except Exception as e:
            print("Error:", e)
            # coba perbaiki koneksi MQTT
            try:
                client.disconnect()
            except:
                pass
            time.sleep(1)
            try:
                client = mqtt_connect()
                print("Reconnected MQTT")
            except Exception as e2:
                print("Gagal reconnect MQTT:", e2)
        time.sleep(READ_PERIOD)

main()


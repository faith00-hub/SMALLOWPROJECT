import network, time, ujson, gc
from machine import Pin
import dht

try:
    # robust lebih tahan putus-nyambung; fallback ke simple bila tidak ada
    from umqtt.robust import MQTTClient
except ImportError:
    from umqtt.simple import MQTTClient

# ====== KONFIG ======
SSID = "LABCOM MAN 1 Kota Sukabumi"
PASSWORD = "@Userlabcom1234"

TOKEN = "BBUS-By0MuOFjSKRYVI4fGEKIj34EFUigqd"
DEVICE_LABEL = "smallow"
VAR_TEMP = "temperature"

BROKER = "industrial.api.ubidots.com"
PORT   = 1883
TOPIC  = b"/v1.6/devices/" + DEVICE_LABEL.encode()

READ_PERIOD = 10   # detik
KEEPALIVE   = 60   # detik

sensor = dht.DHT11(Pin(4))
sta = network.WLAN(network.STA_IF)
client = None

def wifi_connect():
    if sta.active() is False:
        sta.active(True)
    if not sta.isconnected():
        print("Wi-Fi: connecting...")
        sta.connect(SSID, PASSWORD)
        t0 = time.ticks_ms()
        while not sta.isconnected():
            if time.ticks_diff(time.ticks_ms(), t0) > 15000:
                raise RuntimeError("Wi-Fi timeout")
            time.sleep(0.2)
        print("Wi-Fi: OK", sta.ifconfig())

def mqtt_connect():
    global client
    cid = b"esp32-" + str(time.ticks_ms()).encode()
    c = MQTTClient(client_id=cid,
                   server=BROKER, port=PORT,
                   user=TOKEN, password="",
                   keepalive=KEEPALIVE)
    # Last-will → tandai offline
    try:
        c.set_last_will(TOPIC, ujson.dumps({"status": 0}), retain=False, qos=0)
    except:
        pass
    c.connect()
    client = c
    print("MQTT: connected to", BROKER)

def ensure_links():
    if not sta.isconnected():
        wifi_connect()
    try:
        client.ping()
    except:
        # socket putus → reconnect
        try:
            client.disconnect()
        except:
            pass
        mqtt_connect()

def read_temp():
    # ambil 3x, pakai nilai terakhir yang valid
    for _ in range(3):
        try:
            sensor.measure()
            t = sensor.temperature()
            if 0 <= t <= 60:
                return t
        except:
            time.sleep(1)
    raise RuntimeError("DHT11 read failed")

def publish_temp(t, with_ts=False):
    if with_ts:
        ms = time.ticks_ms()  # waktu lokal MCU
        payload = {VAR_TEMP: {"value": t, "timestamp": ms}}
    else:
        payload = {VAR_TEMP: t}
    msg = ujson.dumps(payload).encode()
    client.publish(TOPIC, msg)
    print("PUB ->", TOPIC, msg)

def main():
    wifi_connect()
    mqtt_connect()
    # tandai online sekali
    try:
        client.publish(TOPIC, ujson.dumps({"status": 1}))
    except:
        pass

    backoff = 2
    while True:
        try:
            ensure_links()
            t = read_temp()
            publish_temp(t)  # atau publish_temp(t, with_ts=True)
            backoff = 2  # reset backoff
        except Exception as e:
            print("Loop error:", e)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)  # max 60s
        gc.collect()
        time.sleep(READ_PERIOD)

main()

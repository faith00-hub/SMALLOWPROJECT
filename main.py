import network, time, ujson
from machine import Pin
import dht
from umqtt.simple import MQTTClient

SSID = "LABCOM MAN 1 Kota Sukabumi"
PASSWORD = "@Userlabcom1234"
TOKEN = "BBUS-By0MuOFjSKRYVI4fGEKIj34EFUigqd"
DEVICE_LABEL = "smallow"
VAR_TEMP = "temperature"
MQTT_BROKER = "industrial.api.ubidots.com"
TOPIC = b"/v1.6/devices/" + DEVICE_LABEL.encode()

sensor = dht.DHT11(Pin(4))

def connect_wifi():
    wifi = network.WLAN(network.STA_IF)
    wifi.active(True)
    wifi.connect(SSID, PASSWORD)
    while not wifi.isconnected():
        time.sleep(0.5)
    print("Wi-Fi connected:", wifi.ifconfig())

def mqtt_connect():
    client = MQTTClient("esp32", MQTT_BROKER, user=TOKEN, password="")
    client.connect()
    return client

connect_wifi()
client = mqtt_connect()

while True:
    sensor.measure()
    t = sensor.temperature()
    payload = ujson.dumps({VAR_TEMP: t})
    client.publish(TOPIC, payload)
    print("Sent:", payload)
    time.sleep(10)

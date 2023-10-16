# Needs:
# pip install paho-mqtt zeroconf

# Needs:
# pip install paho-mqtt zeroconf

import paho.mqtt.client as mqtt
from zeroconf import ServiceBrowser, Zeroconf
import time
import random
import uuid

SERVICE_TYPE = "_mymasterservice._tcp.local."

# Use the MAC address as the unique name/ID for the remote unit
UNIT_NAME = get_mac_address()
MQTT_TOPIC = f"remote_node/{UNIT_NAME}"

broker_address = None
reconnect_delay = 1  # in seconds
discovery_delay = 5  # in seconds

def get_mac_address():
    mac = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff) for elements in range(0,2*6,2)][::-1])
    return mac

class MyListener:

    def remove_service(self, zeroconf, type, name):
        pass

    def add_service(self, zeroconf, type, name):
        global broker_address
        info = zeroconf.get_service_info(type, name)
        if info:
            broker_address = ".".join(map(str, info.address))

zeroconf = Zeroconf()
listener = MyListener()
browser = ServiceBrowser(zeroconf, SERVICE_TYPE, listener)

# Continuously try service discovery until found
while not broker_address:
    print("Attempting to discover master node...")
    time.sleep(discovery_delay)

print(f"Found master node at {broker_address}")

# MQTT Handlers
def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT broker at {broker_address} with result code {rc}")
    client.publish(MQTT_TOPIC, f"{UNIT_NAME} connected")

def on_disconnect(client, userdata, rc):
    global reconnect_delay
    print(f"Disconnected with result code {rc}. Reconnecting in {reconnect_delay} seconds.")
    time.sleep(reconnect_delay)
    # Exponential back-off with a maximum delay of 60 seconds
    reconnect_delay = min(reconnect_delay * 2, 60)
    client.reconnect()

mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.connect(broker_address, 1883, 60)
mqtt_client.loop_start()

try:
    while True:
        # Simulate capturing and sending audio data
        random_data = random.random()
        print(f"Sending data: {random_data}")
        mqtt_client.publish(MQTT_TOPIC, random_data)
        time.sleep(1)  # Primary function frequency

except KeyboardInterrupt:
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    zeroconf.close()


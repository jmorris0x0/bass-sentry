#!/usr/bin/env python

import signal
import sys
import time
import os

def signal_handler(sig, frame):
    print("Exiting master node...")
    sys.exit(0)


#import paho.mqtt.client as mqtt
#from influxdb_client_3 import InfluxDBClient3, Point, WritePrecision
#import os
import time
#import threading

#MAX_RETRIES = 100
#RETRY_DELAY = 5  # delay in seconds

#healthy_nodes = set()
#last_health_check = {}

#client = None


# def connect_to_influx():
#     bucket = os.environ.get("DOCKER_INFLUXDB_INIT_BUCKET")
#     org = os.environ.get("DOCKER_INFLUXDB_INIT_ORG")
#     user = os.environ.get("DOCKER_INFLUXDB_INIT_USERNAME", "")
#     password = os.environ.get("DOCKER_INFLUXDB_INIT_PASSWORD", "")

#     # It looks like you meant to use some of these values in the client setup.
#     influxdb_url = os.environ.get("INFLUXDB_HOST", "influxdb")  # Assuming a default value if not set.

#     print(f"Attempting to connect to InfluxDB with URL: {influxdb_url}")

#     global client  # Since you want to use the global client variable

#     try:
#         client = InfluxDBClient3(
#             token=password,  # Assuming password is your token here
#             host=influxdb_url,
#             org=org,
#             database=bucket  # Assuming bucket is your database name
#         )
#         # You can also check if the client connection is successful here
#         print("Successfully connected to InfluxDB!")

#     except Exception as e:
#         print(f"Error connecting to InfluxDB: {e}")


# def on_connect(mqtt_client, userdata, flags, rc):
#     mqtt_client.subscribe("#")


# def on_message(mqtt_client, userdata, msg):
#     topic = msg.topic
#     payload = msg.payload.decode('utf-8')

#     if "health check" in payload:
#         handle_health_check(payload)
#     else:
#         handle_data_point(topic, payload)


# def handle_health_check(payload):
#     node_name = payload.split()[0]
#     if node_name not in healthy_nodes:
#         print(f"Discovered new node: {node_name}")
#     healthy_nodes.add(node_name)
#     last_health_check[node_name] = time.time()


# def handle_data_point(topic, payload):
#     data = [
#         {
#             "measurement": topic,
#             "fields": {
#                 "value": payload
#             }
#         }
#     ]
#     try:
#         client.write_points(data)
#     except:
#         print(f"Failed to write data to InfluxDB for topic {topic}")


# def check_unhealthy_nodes():
#     while True:
#         time.sleep(60)
#         current_time = time.time()
#         for node, last_check in last_health_check.items():
#             if current_time - last_check > 120:
#                 if node in healthy_nodes:
#                     print(f"{node} is now unhealthy!")
#                     healthy_nodes.remove(node)


def main():
    print("Starting master node...")
    global client
    #client = connect_to_influx()

    #mqtt_client = mqtt.Client()
    #mqtt_client.on_connect = on_connect
    #mqtt_client.on_message = on_message
    
    #print("Connecting to MQTT broker...")
    #mqtt_client.connect("mosquitto", 1883, 60)

    #print("Starting MQTT loop...")
    #mqtt_client.loop_start()

    #threading.Thread(target=check_unhealthy_nodes, daemon=True).start()

    #print("Master node started successfully!")
    #print("Press Ctrl+C to exit...")

    try:
        while True:
            time.sleep(1)
            print("Hello World!")
    except KeyboardInterrupt:
        #mqtt_client.loop_stop()
        #mqtt_client.disconnect()
        print("Exiting master node...")


if __name__ == "__main__":
    main()


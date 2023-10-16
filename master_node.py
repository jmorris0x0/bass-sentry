import paho.mqtt.client as mqtt
from influxdb import InfluxDBClient
import os
import time
import threading
from influxdb.exceptions import InfluxDBClientError

MAX_RETRIES = 100
RETRY_DELAY = 5  # delay in seconds

healthy_nodes = set()
last_health_check = {}

client = None

def connect_to_influx():
    user = os.environ.get("INFLUXDB_ADMIN_USER", "")
    password = os.environ.get("INFLUXDB_ADMIN_PASSWORD", "")
    influxdb_url = f"influxdb://{user}:{password}@influxdb:8086/mydb"
    print(f"Attempting to connect to InfluxDB with URL: {influxdb_url}")

    db_client = InfluxDBClient.from_dsn(influxdb_url)
    for attempt in range(MAX_RETRIES):
        try:
            if 'mydb' not in [db['name'] for db in db_client.get_list_database()]:
                db_client.create_database('mydb')
            db_client.switch_database('mydb')
            print("Connected to InfluxDB successfully!")
            return db_client
        except InfluxDBClientError as e:
            if e.code == 401:
                print("Authentication error. Please check your credentials.")
                break
            elif attempt < MAX_RETRIES - 1:
                print(f"Error connecting to InfluxDB. Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
            else:
                print("Max retries reached. Exiting.")
                raise


def on_connect(mqtt_client, userdata, flags, rc):
    mqtt_client.subscribe("#")


def on_message(mqtt_client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode('utf-8')

    if "health check" in payload:
        handle_health_check(payload)
    else:
        handle_data_point(topic, payload)


def handle_health_check(payload):
    node_name = payload.split()[0]
    if node_name not in healthy_nodes:
        print(f"Discovered new node: {node_name}")
    healthy_nodes.add(node_name)
    last_health_check[node_name] = time.time()


def handle_data_point(topic, payload):
    data = [
        {
            "measurement": topic,
            "fields": {
                "value": payload
            }
        }
    ]
    try:
        client.write_points(data)
    except:
        print(f"Failed to write data to InfluxDB for topic {topic}")


def check_unhealthy_nodes():
    while True:
        time.sleep(60)
        current_time = time.time()
        for node, last_check in last_health_check.items():
            if current_time - last_check > 120:
                if node in healthy_nodes:
                    print(f"{node} is now unhealthy!")
                    healthy_nodes.remove(node)


def main():
    print("Starting master node...")
    global client
    client = connect_to_influx()

    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    
    print("Connecting to MQTT broker...")
    mqtt_client.connect("mosquitto", 1883, 60)

    print("Starting MQTT loop...")
    mqtt_client.loop_start()

    threading.Thread(target=check_unhealthy_nodes, daemon=True).start()

    print("Master node started successfully!")
    print("Press Ctrl+C to exit...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()


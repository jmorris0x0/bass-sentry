#!/bin/bash

# Get MAC address
get_mac_address() {
    # Obtain the MAC address and format it as required
    mac=$(ifconfig en0 | awk '/ether/{print $2}')
    echo "$mac"
}

# Service details
SERVICE_TYPE="_mymasterservice._tcp."
SERVICE_PORT="1883"
UNIT_NAME=$(get_mac_address)
SERVICE_NAME="$UNIT_NAME"

# Advertise the service using dns-sd
dns-sd -R "$SERVICE_NAME" "$SERVICE_TYPE" . "$SERVICE_PORT"

# Keep the script running to maintain the advertisement
trap "echo 'Service advertisement stopped'; exit" SIGINT SIGTERM

# Infinite loop to keep the advertisement active
while true; do
    sleep 60
done


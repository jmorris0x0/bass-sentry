#!/bin/bash
# Wait for Graylog to be ready and create GELF UDP input
#
# This script is run as a sidecar to auto-configure Graylog

GRAYLOG_URL="${GRAYLOG_URL:-http://graylog:9000}"
GRAYLOG_USER="${GRAYLOG_USER:-admin}"
GRAYLOG_PASS="${GRAYLOG_PASS:-graylog-password}"

echo "Waiting for Graylog to be ready..."

# Wait for Graylog API to be available (can take 1-2 minutes)
max_attempts=60
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if curl -s -u "$GRAYLOG_USER:$GRAYLOG_PASS" "$GRAYLOG_URL/api/system/lbstatus" | grep -q "ALIVE"; then
        echo "Graylog is ready!"
        break
    fi
    attempt=$((attempt + 1))
    echo "Waiting for Graylog... (attempt $attempt/$max_attempts)"
    sleep 5
done

if [ $attempt -eq $max_attempts ]; then
    echo "Graylog did not become ready in time"
    exit 1
fi

# Check if GELF UDP input already exists
existing=$(curl -s -u "$GRAYLOG_USER:$GRAYLOG_PASS" "$GRAYLOG_URL/api/system/inputs" | grep -c "GELFUDPInput")

if [ "$existing" -gt 0 ]; then
    echo "GELF UDP input already exists, skipping creation"
    exit 0
fi

echo "Creating GELF UDP input..."

# Create the GELF UDP input
response=$(curl -s -w "\n%{http_code}" -X POST \
    -u "$GRAYLOG_USER:$GRAYLOG_PASS" \
    -H "Content-Type: application/json" \
    -H "X-Requested-By: graylog-init" \
    "$GRAYLOG_URL/api/system/inputs" \
    -d '{
        "title": "Bass Sentry Nodes",
        "type": "org.graylog2.inputs.gelf.udp.GELFUDPInput",
        "configuration": {
            "bind_address": "0.0.0.0",
            "port": 12201,
            "recv_buffer_size": 262144,
            "decompress_size_limit": 8388608
        },
        "global": true
    }')

http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | head -n -1)

if [ "$http_code" = "201" ]; then
    echo "GELF UDP input created successfully!"
    echo "$body"
else
    echo "Failed to create input (HTTP $http_code): $body"
    exit 1
fi

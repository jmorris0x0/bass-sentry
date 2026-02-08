#!/bin/bash
# Verify Bass Sentry test fleet is working
#
# Usage:
#   ./deployment/test-fleet/verify-fleet.sh
#
# Run this after docker compose up to verify everything is working

set -e

echo "========================================"
echo "Bass Sentry Fleet Verification"
echo "========================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASS="${GREEN}PASS${NC}"
FAIL="${RED}FAIL${NC}"
WARN="${YELLOW}WARN${NC}"

# Counters
PASSED=0
FAILED=0
WARNINGS=0

check() {
    local name="$1"
    local result="$2"

    if [ "$result" = "0" ]; then
        echo -e "  [${PASS}] $name"
        ((PASSED++))
    else
        echo -e "  [${FAIL}] $name"
        ((FAILED++))
    fi
}

warn() {
    local name="$1"
    echo -e "  [${WARN}] $name"
    ((WARNINGS++))
}

# Check services are running
echo "Checking services..."
echo ""

# InfluxDB
if curl -s http://localhost:8086/health | grep -q "pass"; then
    check "InfluxDB is healthy" 0
else
    check "InfluxDB is healthy" 1
fi

# Grafana
if curl -s http://localhost:3001/api/health | grep -q "ok"; then
    check "Grafana is healthy" 0
else
    check "Grafana is healthy" 1
fi

# MQTT (try to connect)
if timeout 2 bash -c "echo > /dev/tcp/localhost/1883" 2>/dev/null; then
    check "MQTT broker is accessible" 0
else
    check "MQTT broker is accessible" 1
fi

# Graylog (may take a while to start)
if curl -s http://localhost:9001/api/system/lbstatus | grep -q "ALIVE"; then
    check "Graylog is healthy" 0
else
    warn "Graylog not ready (may still be starting)"
fi

echo ""
echo "Checking data flow..."
echo ""

# Query InfluxDB for data from nodes
INFLUX_TOKEN="83A24B9B-BBF6-4A19-B9F5-5806D4BA8FBD"

# Check for dBSPL measurements
DB_COUNT=$(curl -s -X POST "http://localhost:8086/api/v2/query?org=myorg" \
    -H "Authorization: Token $INFLUX_TOKEN" \
    -H "Content-Type: application/vnd.flux" \
    -d 'from(bucket: "mybucket") |> range(start: -5m) |> filter(fn: (r) => r["_measurement"] == "dBSPL") |> count()' \
    2>/dev/null | grep -c "_value" || echo "0")

if [ "$DB_COUNT" -gt "0" ]; then
    check "dBSPL data is being received" 0
else
    check "dBSPL data is being received" 1
fi

# Check for correlation data
CORR_COUNT=$(curl -s -X POST "http://localhost:8086/api/v2/query?org=myorg" \
    -H "Authorization: Token $INFLUX_TOKEN" \
    -H "Content-Type: application/vnd.flux" \
    -d 'from(bucket: "mybucket") |> range(start: -5m) |> filter(fn: (r) => r["_measurement"] == "cross_correlation") |> count()' \
    2>/dev/null | grep -c "_value" || echo "0")

if [ "$CORR_COUNT" -gt "0" ]; then
    check "Cross-correlation data is being generated" 0
else
    warn "No cross-correlation data yet (may take a few minutes)"
fi

# Check for node health data
HEALTH_COUNT=$(curl -s -X POST "http://localhost:8086/api/v2/query?org=myorg" \
    -H "Authorization: Token $INFLUX_TOKEN" \
    -H "Content-Type: application/vnd.flux" \
    -d 'from(bucket: "mybucket") |> range(start: -5m) |> filter(fn: (r) => r["_measurement"] == "node_health") |> count()' \
    2>/dev/null | grep -c "_value" || echo "0")

if [ "$HEALTH_COUNT" -gt "0" ]; then
    check "Node health data is being received" 0
else
    warn "No node health data yet"
fi

echo ""
echo "Checking fake Pi nodes..."
echo ""

# Check each node is running
for node in stage dance_floor back_bar neighbor; do
    container="bass-sentry-fake-pi-${node//_/-}-1"
    # Try alternate naming
    if ! docker ps --format '{{.Names}}' | grep -q "$container"; then
        container=$(docker ps --format '{{.Names}}' | grep -i "fake-pi.*${node//_/-}" | head -1)
    fi

    if [ -n "$container" ] && docker ps --format '{{.Names}}' | grep -q "$container"; then
        check "Node '$node' container is running" 0
    else
        check "Node '$node' container is running" 1
    fi
done

echo ""
echo "========================================"
echo "Summary"
echo "========================================"
echo -e "  Passed:   ${GREEN}$PASSED${NC}"
echo -e "  Failed:   ${RED}$FAILED${NC}"
echo -e "  Warnings: ${YELLOW}$WARNINGS${NC}"
echo ""

if [ "$FAILED" -gt "0" ]; then
    echo -e "${RED}Some checks failed. Check the logs:${NC}"
    echo "  docker compose -f docker-compose.test-fleet.yml logs"
    exit 1
else
    echo -e "${GREEN}Fleet is operational!${NC}"
    echo ""
    echo "Access points:"
    echo "  Grafana:  http://localhost:3001 (admin/grafanapass)"
    echo "  InfluxDB: http://localhost:8086 (admin/supersecret)"
    echo "  Graylog:  http://localhost:9001 (admin/graylog-password)"
    echo ""
    echo "View logs:"
    echo "  docker compose -f docker-compose.test-fleet.yml logs -f fake-pi-stage"
    echo "  docker compose -f docker-compose.test-fleet.yml logs -f master-node"
fi

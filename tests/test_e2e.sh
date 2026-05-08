#!/bin/bash
API="http://127.0.0.1:8000"
KEY="OKTZtSllLh8krFYPi1802mVhfERkU+ndPXybYXuw/wc="

echo "=== Create LiveTest user ==="
RESP=$(curl -s -X POST \
  -H "X-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"LiveTest"}' \
  "$API/api/v1/users")
echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
u = d['user']
print(f\"client_id (b64url): {u['client_id']}\")
print(f\"ip: {u['internal_ip']}\")
print(f\"created_at: {u['created_at']}\")
config_preview = d['config'][:120].replace('\\n', ' | ')
print(f\"config preview: {config_preview}\")
"
echo ""

# Extract b64url client_id and ip
CLIENT_ID=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['user']['client_id'])")
IP=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['user']['internal_ip'])")
echo "CLIENT_ID=$CLIENT_ID"
echo "IP=$IP"

if [ -z "$CLIENT_ID" ]; then echo "ERROR: creation failed"; exit 1; fi

echo ""
echo "=== awg show - new peer should have allowed-ips ==="
docker exec amnezia-awg2 awg show awg0 | grep -A4 "$IP" || echo "(peer not found)"

echo ""
echo "=== Get config via API (b64url path) ==="
CONFIG_HTTP=$(curl -s -w "%{http_code}" -o /tmp/livetest.conf \
  -H "X-API-Key: $KEY" "$API/api/v1/users/$CLIENT_ID/config")
echo "Config HTTP: $CONFIG_HTTP"
echo "Config Jc line: $(grep '^Jc' /tmp/livetest.conf)"
echo "Config S1 line: $(grep '^S1' /tmp/livetest.conf)"

echo ""
echo "=== Get QR via API (b64url path) ==="
QR_HTTP=$(curl -s -w "%{http_code}" -o /tmp/livetest_qr.png \
  -H "X-API-Key: $KEY" "$API/api/v1/users/$CLIENT_ID/qr")
QR_SIZE=$(wc -c < /tmp/livetest_qr.png)
echo "QR HTTP: $QR_HTTP, size: $QR_SIZE bytes"

echo ""
echo "=== Latency test: list users ==="
time curl -s -o /dev/null -H "X-API-Key: $KEY" "$API/api/v1/users"

echo ""
echo "=== Delete LiveTest ==="
DEL_HTTP=$(curl -s -w "%{http_code}" -X DELETE \
  -H "X-API-Key: $KEY" "$API/api/v1/users/$CLIENT_ID")
echo "Delete HTTP: $DEL_HTTP"

echo ""
echo "=== awg show after delete - peer should be gone ==="
docker exec amnezia-awg2 awg show awg0 | grep -c "peer:" 
echo "peers remaining ^ (expected: 2)"

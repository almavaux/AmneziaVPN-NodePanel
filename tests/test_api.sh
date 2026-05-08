#!/bin/bash
set -e
API="http://127.0.0.1:8000"
KEY="OKTZtSllLh8krFYPi1802mVhfERkU+ndPXybYXuw/wc="

echo "=== 1. Health ==="
curl -s -w "\nHTTP %{http_code} (%{time_total}s)\n" "$API/health"

echo ""
echo "=== 2. List users ==="
curl -s -H "X-API-Key: $KEY" "$API/api/v1/users"
echo ""

echo ""
echo "=== 3. Create TestUser ==="
RESP=$(curl -s -w "\nHTTP %{http_code} (%{time_total}s)\n" -X POST \
  -H "X-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"TestUser"}' \
  "$API/api/v1/users")
echo "$RESP"
CLIENT_ID=$(echo "$RESP" | head -1 | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['client_id'])" 2>/dev/null || echo "")
echo "CLIENT_ID=$CLIENT_ID"

echo ""
echo "=== 4. awg show inside amnezia-awg2 ==="
docker exec amnezia-awg2 awg show awg0

if [ -n "$CLIENT_ID" ]; then
  echo ""
  echo "=== 5. Get config for $CLIENT_ID ==="
  curl -s -H "X-API-Key: $KEY" "$API/api/v1/users/$CLIENT_ID/config"

  echo ""
  echo "=== 6. Get QR code for $CLIENT_ID ==="
  curl -s -o /tmp/test_qr.png -w "QR HTTP %{http_code} size=%{size_download} bytes\n" \
    -H "X-API-Key: $KEY" "$API/api/v1/users/$CLIENT_ID/qr"

  echo ""
  echo "=== 7. Delete TestUser ==="
  curl -s -w "\nHTTP %{http_code} (%{time_total}s)\n" -X DELETE \
    -H "X-API-Key: $KEY" "$API/api/v1/users/$CLIENT_ID"

  echo ""
  echo "=== 8. List users after delete ==="
  curl -s -H "X-API-Key: $KEY" "$API/api/v1/users"
  echo ""
fi

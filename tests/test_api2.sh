#!/bin/bash
API="http://127.0.0.1:8000"
KEY="OKTZtSllLh8krFYPi1802mVhfERkU+ndPXybYXuw/wc="

# Get client_id of TestUser at 10.8.1.4
CLIENT_ID=$(curl -s -H "X-API-Key: $KEY" "$API/api/v1/users" | \
  python3 -c "import sys,json; users=json.load(sys.stdin); \
    match=[u for u in users if u['internal_ip']=='10.8.1.4']; \
    print(match[0]['client_id'] if match else '')")
echo "CLIENT_ID=$CLIENT_ID"

if [ -z "$CLIENT_ID" ]; then echo "ERROR: no matching user"; exit 1; fi

echo ""
echo "=== 5. Get config ==="
curl -s -w "\nHTTP %{http_code}\n" -H "X-API-Key: $KEY" \
  "$API/api/v1/users/$CLIENT_ID/config"

echo ""
echo "=== 6. Get QR code ==="
curl -s -o /tmp/test_qr.png -w "QR HTTP %{http_code} size=%{size_download} bytes\n" \
  -H "X-API-Key: $KEY" "$API/api/v1/users/$CLIENT_ID/qr"

echo ""
echo "=== 7. Delete TestUser (10.8.1.4) ==="
curl -s -w "HTTP %{http_code} (%{time_total}s)\n" -X DELETE \
  -H "X-API-Key: $KEY" "$API/api/v1/users/$CLIENT_ID"

echo ""
echo "=== 8. Delete old TestUser (10.8.1.3, ZZwBg) ==="
OLD_ID="ZZwBg976QK7bi03Vzf2eu0jgfDPlYrxjbAvpUqAKd38="
curl -s -w "HTTP %{http_code} (%{time_total}s)\n" -X DELETE \
  -H "X-API-Key: $KEY" "$API/api/v1/users/$OLD_ID"

echo ""
echo "=== 9. List users after cleanup ==="
curl -s -H "X-API-Key: $KEY" "$API/api/v1/users"
echo ""

echo ""
echo "=== 10. awg show after cleanup ==="
docker exec amnezia-awg2 awg show awg0

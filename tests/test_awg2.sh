#!/bin/sh
PUB="ZZwBg976QK7bi03Vzf2eu0jgfDPlYrxjbAvpUqAKd38="

echo "=== Test 1: awg set without advanced-security on, using server PSK ==="
cp /opt/amnezia/awg/wireguard_psk.key /tmp/t.key
awg set awg0 peer "$PUB" preshared-key /tmp/t.key allowed-ips 10.8.1.3/32
EXIT=$?
echo "exit=$EXIT"
awg show awg0 | grep -A5 "$PUB"
rm -f /tmp/t.key

echo ""
echo "=== Test 2: awg set WITH advanced-security on ==="
cp /opt/amnezia/awg/wireguard_psk.key /tmp/t.key
awg set awg0 peer "$PUB" preshared-key /tmp/t.key allowed-ips 10.8.1.3/32 advanced-security on 2>&1
EXIT=$?
echo "exit=$EXIT"
rm -f /tmp/t.key

echo ""
echo "=== awg help/usage ==="
awg set 2>&1 | head -10

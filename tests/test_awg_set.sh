#!/bin/sh
PUB="ZZwBg976QK7bi03Vzf2eu0jgfDPlYrxjbAvpUqAKd38="
PSK="$(cat /opt/amnezia/awg/wireguard_psk.key)"

echo "PSK file content length: ${#PSK}"
printf '%s' "$PSK" > /tmp/testpsk.key
echo "Wrote psk to /tmp/testpsk.key"

echo "Running awg set..."
awg set awg0 peer "$PUB" preshared-key /tmp/testpsk.key allowed-ips 10.8.1.3/32 advanced-security on
EXIT=$?
echo "awg set exit code: $EXIT"

rm -f /tmp/testpsk.key

echo "awg show result:"
awg show awg0 peer "$PUB"

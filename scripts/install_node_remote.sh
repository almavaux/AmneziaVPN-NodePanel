#!/usr/bin/env bash
# install_node_remote.sh - unified remote node installer.
# Used by setup.sh remote flow and by web-panel SSH automation.
set -euo pipefail

MASTER_IP=""
ALLOWED_IP=""
PUBLIC_IP=""
MASTER_PORT="8000"
DNS="1.1.1.1"
API_KEY=""
TARGET_DIR="/opt/awg-api"

usage() {
  cat <<EOF
Usage: $0 --master-ip IP --allowed-ip IP --public-ip IP [options]

Required:
  --master-ip IP      Master panel IP/host for node binding
  --allowed-ip IP     IP allowed to call node API (usually master IP)
  --public-ip IP      Node public IP/host for clients

Optional:
  --master-port PORT  Master API port (default: 8000)
  --dns IP            DNS for VPN clients (default: 1.1.1.1)
  --api-key KEY       Node API key (auto-generated if omitted)
  --target-dir PATH   Project directory on remote host (default: /opt/awg-api)
  -h, --help          Show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --master-ip)
      MASTER_IP="${2:-}"
      shift 2
      ;;
    --allowed-ip)
      ALLOWED_IP="${2:-}"
      shift 2
      ;;
    --public-ip)
      PUBLIC_IP="${2:-}"
      shift 2
      ;;
    --master-port)
      MASTER_PORT="${2:-}"
      shift 2
      ;;
    --dns)
      DNS="${2:-}"
      shift 2
      ;;
    --api-key)
      API_KEY="${2:-}"
      shift 2
      ;;
    --target-dir)
      TARGET_DIR="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [ -z "$MASTER_IP" ] || [ -z "$ALLOWED_IP" ] || [ -z "$PUBLIC_IP" ]; then
  echo "ERROR: --master-ip, --allowed-ip and --public-ip are required" >&2
  usage
  exit 1
fi

INSTALL_PROJECT="$TARGET_DIR/scripts/install_project.sh"
if [ ! -f "$INSTALL_PROJECT" ]; then
  echo "ERROR: missing installer: $INSTALL_PROJECT" >&2
  echo "Upload project files to $TARGET_DIR first." >&2
  exit 1
fi

if [ -z "$API_KEY" ]; then
  if command -v openssl >/dev/null 2>&1; then
    API_KEY="$(openssl rand -base64 32)"
  else
    API_KEY="$(dd if=/dev/urandom bs=24 count=1 2>/dev/null | base64)"
  fi
fi

mkdir -p "$TARGET_DIR"
cat > "$TARGET_DIR/.env" <<EOF
AWG_ROLE=node
AWG_API_KEY=${API_KEY}
AWG_SERVER_HOST=${PUBLIC_IP}
AWG_ALLOWED_IPS=${ALLOWED_IP}
AWG_CONTAINER_NAME=amnezia-awg2
AWG_MODE=auto
AWG_CONF_PATH=/opt/amnezia/awg/awg0.conf
AWG_CLIENTS_TABLE_PATH=/opt/amnezia/awg/clientsTable
AWG_PSK_KEY_PATH=/opt/amnezia/awg/wireguard_psk.key
AWG_SERVER_PUBKEY_PATH=/opt/amnezia/awg/wireguard_server_public_key.key
AWG_DNS=${DNS}
AWG_DOCKER_SOCKET=unix:///var/run/docker.sock
AWG_GRPC_PORT=50051
AWG_BOOTSTRAP_ENABLED=true
AWG_BOOTSTRAP_PATH=/node/bootstrap
AWG_STATE_DIR=/service/state
AWG_CA_CERT_PATH=/service/state/pki/ca.crt
AWG_CA_KEY_PATH=/service/state/pki/ca.key
AWG_MASTER_CERT_PATH=/service/state/pki/master.crt
AWG_MASTER_KEY_PATH=/service/state/pki/master.key
AWG_NODE_CERT_PATH=/service/state/pki/node.crt
AWG_NODE_KEY_PATH=/service/state/pki/node.key
AWG_NODE_ID_FILE=/service/state/node_id
AWG_NODE_REGISTRY_FILE=/service/state/nodes.json
AWG_MASTER_IP=${MASTER_IP}
EOF

# Ensure node can be freshly enrolled by master after reinstall.
STATE_DIR="$TARGET_DIR/state"
rm -f \
  "$STATE_DIR/enrolled.flag" \
  "$STATE_DIR/master.lock" \
  "$STATE_DIR/pki/node.crt" \
  "$STATE_DIR/pki/node.key" \
  "$STATE_DIR/pki/ca.crt" \
  "$STATE_DIR/pki/master.crt" \
  "$STATE_DIR/pki/master.key" \
  2>/dev/null || true

chmod +x "$INSTALL_PROJECT"
bash "$INSTALL_PROJECT" --project-dir "$TARGET_DIR"

echo ""
echo "Node installation complete"
echo "Master: ${MASTER_IP}:${MASTER_PORT}"
echo "Node API: http://${PUBLIC_IP}:8000"

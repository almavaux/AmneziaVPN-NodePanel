#!/usr/bin/env bash
# deploy.sh - one-command deploy for awg-api.
# Prompts for target SSH server and required allowed caller IP.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

REMOTE_DIR="/opt/awg-api"
SSH_KEY_DEFAULT=".ssh-live/amnezia_live"
SSH_KNOWN_DEFAULT=".ssh-live/known_hosts"
# Known VPN endpoint host/IP for generated client configs.
KNOWN_HOST_IP="5.101.82.46"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: $1" >&2
    exit 1
  }
}

is_ipv4() {
  local ip="$1"
  [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  local IFS='.'
  read -r o1 o2 o3 o4 <<<"$ip"
  for o in "$o1" "$o2" "$o3" "$o4"; do
    (( o >= 0 && o <= 255 )) || return 1
  done
}

prompt_nonempty() {
  local label="$1"
  local val=""
  while [ -z "$val" ]; do
    read -r -p "$label" val
  done
  printf '%s' "$val"
}

require_cmd ssh
require_cmd scp
require_cmd openssl

echo "== AWG API one-command deploy =="
SERVER_HOST=$(prompt_nonempty "SSH server IP or hostname (example: 5.8.19.22): ")
read -r -p "SSH user [root]: " SERVER_USER_INPUT
if [ -z "$SERVER_USER_INPUT" ]; then
  SERVER_USER="root"
else
  SERVER_USER="$SERVER_USER_INPUT"
fi

read -r -p "SSH private key path [.ssh-live/amnezia_live]: " SSH_KEY
if [ -z "$SSH_KEY" ]; then
  SSH_KEY="$SSH_KEY_DEFAULT"
fi

read -r -p "known_hosts path [.ssh-live/known_hosts]: " SSH_KNOWN
if [ -z "$SSH_KNOWN" ]; then
  SSH_KNOWN="$SSH_KNOWN_DEFAULT"
fi

ALLOWED_CALLER_IP=""
while ! is_ipv4 "$ALLOWED_CALLER_IP"; do
  read -r -p "Allowed caller IPv4 (required, who can call API): " ALLOWED_CALLER_IP
  if ! is_ipv4 "$ALLOWED_CALLER_IP"; then
    echo "Invalid IPv4. Try again."
  fi
done

ROLE_INPUT=""
while [ "$ROLE_INPUT" != "master" ] && [ "$ROLE_INPUT" != "node" ]; do
  read -r -p "Role [master/node]: " ROLE_INPUT
done
AWG_ROLE="$ROLE_INPUT"

MASTER_IP_INPUT=""
if [ "$AWG_ROLE" = "master" ]; then
  read -r -p "Master public IP [${KNOWN_HOST_IP}]: " MASTER_IP_INPUT
  MASTER_IP="${MASTER_IP_INPUT:-$KNOWN_HOST_IP}"
else
  while ! is_ipv4 "$MASTER_IP_INPUT"; do
    read -r -p "Master IPv4 (required for node bootstrap ACL): " MASTER_IP_INPUT
    if ! is_ipv4 "$MASTER_IP_INPUT"; then
      echo "Invalid IPv4. Try again."
    fi
  done
  MASTER_IP="$MASTER_IP_INPUT"
fi

DNS_INPUT=""
read -r -p "Client DNS [1.1.1.1]: " DNS_INPUT
AWG_DNS="${DNS_INPUT:-1.1.1.1}"

API_KEY="${AWG_API_KEY:-$(openssl rand -base64 32 | tr -d '\n')}"
SERVER="${SERVER_USER}@${SERVER_HOST}"
SSH="ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=${SSH_KNOWN} -i ${SSH_KEY}"
SCP="scp -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=${SSH_KNOWN} -i ${SSH_KEY}"

cd "$PROJECT_DIR"

echo "==> Syncing project files to ${SERVER}:${REMOTE_DIR} ..."
$SSH "${SERVER}" "mkdir -p ${REMOTE_DIR}"
$SCP -r app docker requirements.txt .env.example README.md \
  "${SERVER}:${REMOTE_DIR}/"

echo "==> Writing ${REMOTE_DIR}/.env ..."
$SSH "${SERVER}" bash <<REMOTE
set -euo pipefail
cat > "${REMOTE_DIR}/.env" <<EOF
AWG_API_KEY=${API_KEY}
AWG_SERVER_HOST=${KNOWN_HOST_IP}
AWG_ALLOWED_IPS=${ALLOWED_CALLER_IP}
AWG_ROLE=${AWG_ROLE}
AWG_MASTER_IP=${MASTER_IP}
AWG_CONTAINER_NAME=amnezia-awg2
AWG_MODE=auto
AWG_CONF_PATH=/opt/amnezia/awg/awg0.conf
AWG_CLIENTS_TABLE_PATH=/opt/amnezia/awg/clientsTable
AWG_PSK_KEY_PATH=/opt/amnezia/awg/wireguard_psk.key
AWG_SERVER_PUBKEY_PATH=/opt/amnezia/awg/wireguard_server_public_key.key
AWG_DNS=${AWG_DNS}
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
EOF
REMOTE

echo "==> Building and starting awg-api ..."
$SSH "${SERVER}" bash <<REMOTE
set -euo pipefail
cd "${REMOTE_DIR}"
if command -v docker-compose >/dev/null 2>&1; then
  docker-compose -f docker/docker-compose.yml up -d --build
else
  docker compose -f docker/docker-compose.yml up -d --build
fi
REMOTE

echo ""
echo "Deployment complete"
echo "Server: ${SERVER_HOST}"
echo "Role: ${AWG_ROLE}"
echo "Master IP: ${MASTER_IP}"
echo "Host IP (Endpoint): ${KNOWN_HOST_IP}"
echo "Allowed caller IP: ${ALLOWED_CALLER_IP}"
echo "API key: ${API_KEY}"
echo ""
echo "Health check from server:"
echo "ssh -o UserKnownHostsFile=${SSH_KNOWN} -i ${SSH_KEY} ${SERVER} 'curl -s http://127.0.0.1:8000/health'"

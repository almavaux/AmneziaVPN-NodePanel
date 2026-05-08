#!/usr/bin/env bash
# install_project.sh - install/start AWG API from an existing project directory.
set -euo pipefail

PROJECT_DIR=""
SKIP_BUILD="false"
INSTALL_MODE="update"

usage() {
  cat <<EOF
Usage: $0 [--project-dir /opt/awg-api] [--skip-build] [--mode update|clean-reinstall]

Options:
  --project-dir PATH  Project root directory (default: parent of this script)
  --skip-build        Do not run docker compose up -d --build
  --mode MODE         Install mode: update (default) or clean-reinstall
  -h, --help          Show this help
EOF
}

clean_reinstall() {
  echo "==> Clean reinstall mode: stopping containers and removing persistent state"

  eval "$COMPOSE_CMD down --remove-orphans" >/dev/null 2>&1 || true

  # Remove local state to force full re-init (PKI/node registry/node identity).
  rm -rf "$PROJECT_DIR/state" || true

  # Remove runtime env files; installer will recreate from example if available.
  rm -f "$PROJECT_DIR/.env" "$PROJECT_DIR/docker/.env" || true
}

detect_pkg_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "apt"
  elif command -v dnf >/dev/null 2>&1; then
    echo "dnf"
  elif command -v yum >/dev/null 2>&1; then
    echo "yum"
  else
    echo ""
  fi
}

install_pkgs() {
  local pm="$1"
  shift
  local pkgs=("$@")

  case "$pm" in
    apt)
      DEBIAN_FRONTEND=noninteractive apt-get update -y
      DEBIAN_FRONTEND=noninteractive apt-get install -y "${pkgs[@]}"
      ;;
    dnf)
      dnf install -y "${pkgs[@]}"
      ;;
    yum)
      yum install -y "${pkgs[@]}"
      ;;
    *)
      echo "ERROR: no supported package manager found to install: ${pkgs[*]}" >&2
      exit 1
      ;;
  esac
}

ensure_docker() {
  if command -v docker >/dev/null 2>&1; then
    echo "==> docker already installed"
    return
  fi

  echo "==> Installing docker"
  local pm
  pm="$(detect_pkg_manager)"
  case "$pm" in
    apt)
      install_pkgs "$pm" docker.io
      ;;
    dnf|yum)
      install_pkgs "$pm" docker
      ;;
    *)
      echo "ERROR: docker is missing and cannot be installed automatically" >&2
      exit 1
      ;;
  esac

  systemctl enable --now docker >/dev/null 2>&1 || true
}

resolve_compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD='docker compose -f docker/docker-compose.yml'
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD='docker-compose -f docker/docker-compose.yml'
    return
  fi

  echo "==> Installing docker compose"
  local pm
  pm="$(detect_pkg_manager)"
  case "$pm" in
    apt)
      DEBIAN_FRONTEND=noninteractive apt-get update -y
      DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-plugin || \
        DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose
      ;;
    dnf)
      dnf install -y docker-compose-plugin || dnf install -y docker-compose
      ;;
    yum)
      yum install -y docker-compose-plugin || yum install -y docker-compose
      ;;
    *)
      echo "ERROR: docker compose is missing and cannot be installed automatically" >&2
      exit 1
      ;;
  esac

  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD='docker compose -f docker/docker-compose.yml'
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD='docker-compose -f docker/docker-compose.yml'
    return
  fi

  echo "ERROR: docker compose installation failed" >&2
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --project-dir)
      PROJECT_DIR="${2:-}"
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD="true"
      shift
      ;;
    --mode)
      INSTALL_MODE="${2:-}"
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

case "$INSTALL_MODE" in
  update|clean-reinstall)
    ;;
  *)
    echo "ERROR: invalid --mode '$INSTALL_MODE'. Expected: update|clean-reinstall" >&2
    exit 1
    ;;
esac

if [ -z "$PROJECT_DIR" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

if [ ! -d "$PROJECT_DIR" ]; then
  echo "ERROR: project dir does not exist: $PROJECT_DIR" >&2
  exit 1
fi

if [ ! -f "$PROJECT_DIR/docker/docker-compose.yml" ]; then
  echo "ERROR: compose file not found: $PROJECT_DIR/docker/docker-compose.yml" >&2
  exit 1
fi

cd "$PROJECT_DIR"

ensure_docker
resolve_compose_cmd

if [ "$INSTALL_MODE" = "clean-reinstall" ]; then
  clean_reinstall
else
  echo "==> Update mode: preserving .env and state/"
fi

if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp .env.example .env
    echo "==> .env created from .env.example. Update secrets before production use."
  else
    echo "WARNING: .env and .env.example are missing."
  fi
fi

# docker-compose v1 resolves .env next to compose file path.
# Keep a synced copy in docker/.env for compatibility.
if [ -f ".env" ]; then
  mkdir -p docker
  cp .env docker/.env
fi

if [ "$SKIP_BUILD" = "false" ]; then
  # Avoid "container name is already in use" conflicts from previous/manual runs.
  if docker ps -a --format '{{.Names}}' | grep -Fxq 'awg-api'; then
    echo "==> Removing existing awg-api container"
    docker rm -f awg-api >/dev/null 2>&1 || true
  fi

  echo "==> Building and starting containers"
  eval "$COMPOSE_CMD up -d --build"
  echo "==> Service status"
  eval "$COMPOSE_CMD ps"
else
  echo "==> --skip-build enabled. Configuration done, docker compose not started."
fi

echo ""
echo "Done. Project installed from $PROJECT_DIR (mode=$INSTALL_MODE)"
echo "Health check: curl http://127.0.0.1:8000/health"

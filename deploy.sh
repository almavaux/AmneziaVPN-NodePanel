#!/usr/bin/env bash
set -euo pipefail

# One-command server deployer for panel install/update from GitHub.

REPO_URL_DEFAULT="https://github.com/almavaux/AmneziaVPN-NodePanel.git"
TARGET_DIR_DEFAULT="/opt/awg-api"
BRANCH_DEFAULT="main"

MODE=""
REPO_URL="$REPO_URL_DEFAULT"
TARGET_DIR="$TARGET_DIR_DEFAULT"
BRANCH="$BRANCH_DEFAULT"
FORCE="false"

usage() {
  cat <<EOF
Usage:
  bash deploy.sh install [--repo URL] [--branch BRANCH] [--dir PATH] [--force]
  bash deploy.sh update  [--repo URL] [--branch BRANCH] [--dir PATH]

Modes:
  install  Full install (clean-reinstall mode).
  update   Safe update (keeps .env and state/).

Examples:
  bash deploy.sh install
  bash deploy.sh update
  bash deploy.sh install --repo https://github.com/almavaux/AmneziaVPN-NodePanel.git
EOF
}

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run as root (or with sudo)." >&2
    exit 1
  fi
}

need_cmd() {
  local c="$1"
  if ! command -v "$c" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $c" >&2
    exit 1
  fi
}

parse_args() {
  if [ $# -lt 1 ]; then
    usage
    exit 1
  fi

  MODE="$1"
  shift

  case "$MODE" in
    install|update) ;;
    -h|--help|help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown mode '$MODE' (use install|update)." >&2
      usage
      exit 1
      ;;
  esac

  while [ $# -gt 0 ]; do
    case "$1" in
      --repo)
        REPO_URL="${2:-}"
        shift 2
        ;;
      --branch)
        BRANCH="${2:-}"
        shift 2
        ;;
      --dir)
        TARGET_DIR="${2:-}"
        shift 2
        ;;
      --force)
        FORCE="true"
        shift
        ;;
      -h|--help|help)
        usage
        exit 0
        ;;
      *)
        echo "ERROR: unknown argument: $1" >&2
        usage
        exit 1
        ;;
    esac
  done
}

clone_or_update_repo() {
  local autostashed="false"
  local stash_tag="deploy-autostash-$(date +%s)"

  if [ ! -d "$TARGET_DIR/.git" ]; then
    echo "==> Cloning repository to $TARGET_DIR"
    rm -rf "$TARGET_DIR"
    git clone --branch "$BRANCH" "$REPO_URL" "$TARGET_DIR"
    return
  fi

  echo "==> Updating repository in $TARGET_DIR"
  git -C "$TARGET_DIR" remote set-url origin "$REPO_URL"
  git -C "$TARGET_DIR" fetch --all --prune

  if [ "$FORCE" != "true" ]; then
    if ! git -C "$TARGET_DIR" diff --quiet || ! git -C "$TARGET_DIR" diff --cached --quiet; then
      echo "Local changes detected, saving them before update..."
      git -C "$TARGET_DIR" stash push --include-untracked -m "$stash_tag" >/dev/null
      autostashed="true"
    fi
  fi

  git -C "$TARGET_DIR" checkout "$BRANCH"
  if [ "$FORCE" = "true" ]; then
    git -C "$TARGET_DIR" reset --hard "origin/$BRANCH"
  else
    git -C "$TARGET_DIR" pull --ff-only origin "$BRANCH"
    if [ "$autostashed" = "true" ]; then
      echo "Restoring local changes after update..."
      if ! git -C "$TARGET_DIR" stash pop >/dev/null; then
        echo "WARNING: couldn't auto-apply stashed changes cleanly." >&2
        echo "Resolve conflicts manually, then run: git -C \"$TARGET_DIR\" stash list" >&2
      fi
    fi
  fi
}

run_installer() {
  local installer="$TARGET_DIR/scripts/install_project.sh"
  if [ ! -f "$installer" ]; then
    echo "ERROR: installer not found: $installer" >&2
    exit 1
  fi

  chmod +x "$installer"
  if [ "$MODE" = "install" ]; then
    echo "==> Running full install (clean-reinstall)"
    bash "$installer" --project-dir "$TARGET_DIR" --mode clean-reinstall
  else
    echo "==> Running update"
    bash "$installer" --project-dir "$TARGET_DIR" --mode update
  fi
}

install_vvh() {
  local src="$TARGET_DIR/vvh"
  local dst="/usr/local/bin/vvh"
  if [ ! -f "$src" ]; then
    echo "WARNING: vvh script not found in repo ($src), skipping install."
    return
  fi
  chmod +x "$src"
  cp "$src" "$dst"
  chmod +x "$dst"
  echo "==> Installed CLI: $dst"
}

main() {
  parse_args "$@"
  require_root
  need_cmd git
  need_cmd bash

  clone_or_update_repo
  run_installer
  install_vvh

  echo ""
  echo "Done."
  echo "Health: curl http://127.0.0.1:8000/health"
  echo "CLI: vvh menu"
}

main "$@"

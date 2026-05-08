import json
import os
import secrets
import threading
from pathlib import Path

from .config import settings

_LOCK = threading.Lock()


def ensure_state_dirs() -> None:
    Path(settings.state_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.state_dir, "pki").mkdir(parents=True, exist_ok=True)


def load_or_create_node_id() -> str:
    ensure_state_dirs()
    node_id_path = Path(settings.node_id_file)
    if node_id_path.exists():
        value = node_id_path.read_text(encoding="utf-8").strip()
        if value:
            return value
    node_id = f"node-{secrets.token_hex(8)}"
    node_id_path.write_text(node_id + "\n", encoding="utf-8")
    return node_id


def node_enrolled() -> bool:
    return (
        os.path.exists(settings.node_cert_path)
        and os.path.exists(settings.node_key_path)
        and os.path.exists(settings.enrolled_flag_file)
    )


def mark_node_enrolled(master_ip: str) -> None:
    ensure_state_dirs()
    Path(settings.enrolled_flag_file).write_text("enrolled\n", encoding="utf-8")
    Path(settings.master_lock_file).write_text(master_ip.strip() + "\n", encoding="utf-8")


def get_locked_master_ip() -> str:
    path = Path(settings.master_lock_file)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def write_node_registry_entry(target: str, node_id: str) -> None:
    ensure_state_dirs()
    with _LOCK:
        data = {}
        registry_path = Path(settings.node_registry_file)
        if registry_path.exists():
            try:
                data = json.loads(registry_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data[target] = {"node_id": node_id}
        registry_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_node_registry() -> dict:
    registry_path = Path(settings.node_registry_file)
    if not registry_path.exists():
        return {}
    try:
        return json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

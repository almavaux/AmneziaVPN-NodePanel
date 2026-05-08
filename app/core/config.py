from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    panel_version: str = "M0.0.3"
    node_version: str = "N0.0.3"

    # Deployment role: "master" or "node". Default is master (panel + CA).
    role: str = "master"

    # Authentication
    api_key: str = "change-me"

    # Mode: "auto" (detect by probing awg/wg binaries), "new" (awg+awg0), "legacy" (wg+wg0)
    awg_mode: str = "auto"

    # Container (if not found, docker_manager falls back to amnezia-awg2/amnezia-awg)
    container_name: str = "amnezia-awg2"
    conf_path: str = "/opt/amnezia/awg/awg0.conf"
    clients_table_path: str = "/opt/amnezia/awg/clientsTable"
    psk_key_path: str = "/opt/amnezia/awg/wireguard_psk.key"
    server_pubkey_path: str = "/opt/amnezia/awg/wireguard_server_public_key.key"

    # Network
    # Public IP/host of this server (Endpoint in client WG configs, master CA SAN).
    # Empty by default; installer auto-detects the public IP at install time.
    server_host: str = ""
    dns: str = "1.1.1.1,1.0.0.1"
    # Comma-separated API caller allowlist. Empty = filter off. Example: "203.0.113.10,10.0.0.5"
    allowed_ips: str = ""

    # Optional: Docker socket
    docker_socket: str = "unix:///var/run/docker.sock"

    # Database
    db_path: str = "/service/state/awg.db"

    # Master/node bootstrap
    master_ip: str = ""
    bootstrap_enabled: bool = True
    bootstrap_path: str = "/node/bootstrap"
    state_dir: str = "/service/state"

    # gRPC + mTLS
    grpc_port: int = 50051
    ca_cert_path: str = "/service/state/pki/ca.crt"
    ca_key_path: str = "/service/state/pki/ca.key"
    master_cert_path: str = "/service/state/pki/master.crt"
    master_key_path: str = "/service/state/pki/master.key"
    node_cert_path: str = "/service/state/pki/node.crt"
    node_key_path: str = "/service/state/pki/node.key"
    node_id_file: str = "/service/state/node_id"
    node_registry_file: str = "/service/state/nodes.json"
    enrolled_flag_file: str = "/service/state/enrolled.flag"
    master_lock_file: str = "/service/state/master.lock"

    model_config = {"env_file": ".env", "env_prefix": "AWG_", "case_sensitive": False}


settings = Settings()


def get_allowed_ip_set() -> set[str]:
    return {item.strip() for item in settings.allowed_ips.split(",") if item.strip()}

"""
Core AmneziaWG management logic.

Responsibilities:
  - Parse / render awg0.conf and clientsTable
  - Allocate IPs
  - Generate WireGuard keypairs (X25519) and PSKs in pure Python
  - Atomic two-phase write: disk first, then live awg set
  - Rollback on partial failure
  - Build client configs + QR codes
"""
import base64
import io
import ipaddress
import json
import logging
import os
import random
import threading
import zlib
from datetime import datetime, timezone
from typing import Optional

import qrcode
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from .config import settings
from ..infrastructure.docker_manager import docker_manager
from .models import UserCreate, UserCreateResponse, UserData, UserListItem

logger = logging.getLogger(__name__)

_LEGACY_DEFAULT_SPECIAL_JUNK_1 = (
    "<r 2><b 0x858000010001000000000669636c6f756403636f6d0000010001c00c000100010000105a00044d583737>"
)

# One process-level mutex; use single uvicorn worker in production.
_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Runtime mode (populated by detect_mode() during app startup)
# ---------------------------------------------------------------------------

_MODE: str = "unknown"   # "new" | "legacy"
_TOOL: str = "awg"       # binary name inside container: "awg" or "wg"
_IFACE: str = "awg0"     # interface name: "awg0" or "wg0"
_CONF_PATH: str = ""      # in-container path to conf file (set by detect_mode)


def detect_mode() -> str:
    """Detect whether the container uses amneziawg-tools (new) or wireguard-tools (legacy).

    Called once at application startup.
    Can be overridden via AWG_MODE=new|legacy in .env.
    Returns the detected mode string.
    """
    global _MODE, _TOOL, _IFACE, _CONF_PATH

    if settings.awg_mode in ("new", "legacy"):
        _MODE = settings.awg_mode
        logger.info("AWG mode forced by config: %s", _MODE)
    else:
        try:
            docker_manager.exec_run(["awg", "--version"])
            _MODE = "new"
        except Exception:
            _MODE = "legacy"
        logger.info("AWG mode auto-detected: %s", _MODE)

    if _MODE == "legacy":
        _TOOL = "wg"
        _IFACE = "wg0"
        _CONF_PATH = settings.conf_path.replace("awg0.conf", "wg0.conf")
    else:
        _TOOL = "awg"
        _IFACE = "awg0"
        _CONF_PATH = settings.conf_path

    logger.info("AWG tool=%s  iface=%s  conf=%s", _TOOL, _IFACE, _CONF_PATH)
    return _MODE


# ---------------------------------------------------------------------------
# Crypto helpers
# ---------------------------------------------------------------------------

def _generate_keypair() -> tuple[str, str]:
    """Return (private_key_b64, public_key_b64) as WireGuard-compatible strings."""
    priv = X25519PrivateKey.generate()
    priv_b64 = base64.b64encode(priv.private_bytes_raw()).decode()
    pub_b64 = base64.b64encode(priv.public_key().public_bytes_raw()).decode()
    return priv_b64, pub_b64


def _generate_psk() -> str:
    """Generate a cryptographically-random 32-byte preshared key."""
    return base64.b64encode(os.urandom(32)).decode()


# ---------------------------------------------------------------------------
# Config parsing / rendering
# ---------------------------------------------------------------------------

def _parse_conf(content: str) -> dict:
    """
    Parse awg0.conf into:
      {
        "interface": {key: value, ...},
        "interface_comments": ["# I1 = ...", ...],
        "peers": [{key: value, ...}, ...]
      }
    """
    result: dict = {"interface": {}, "interface_comments": [], "peers": []}
    section: Optional[str] = None
    current_peer: dict = {}

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line == "[Interface]":
            section = "interface"
        elif line == "[Peer]":
            if current_peer:
                result["peers"].append(current_peer)
            current_peer = {}
            section = "peer"
        elif line.startswith("#") and section == "interface":
            result["interface_comments"].append(line)
        elif "=" in line and section:
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if section == "interface":
                result["interface"][key] = value
            elif section == "peer":
                current_peer[key] = value

    if current_peer:
        result["peers"].append(current_peer)

    return result


def _render_conf(parsed: dict) -> str:
    """Render parsed config back to awg0.conf string."""
    lines = ["[Interface]"]
    for k, v in parsed["interface"].items():
        lines.append(f"{k} = {v}")
    for comment in parsed.get("interface_comments", []):
        lines.append(comment)
    lines.append("")

    for peer in parsed["peers"]:
        lines.append("[Peer]")
        for k, v in peer.items():
            lines.append(f"{k} = {v}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# IP helpers
# ---------------------------------------------------------------------------

def _find_next_ip(peers: list[dict], iface_addr: str) -> str:
    """
    Return the first free /32 host address in the interface subnet,
    skipping IPs already assigned to existing peers.
    """
    network = ipaddress.ip_network(iface_addr, strict=False)
    used: set[ipaddress.IPv4Address] = set()

    for peer in peers:
        for ip_str in peer.get("AllowedIPs", "").split(","):
            ip_str = ip_str.strip().split("/")[0]
            if ip_str:
                try:
                    used.add(ipaddress.ip_address(ip_str))
                except ValueError:
                    pass

    for host in network.hosts():
        if host not in used:
            return f"{host}/32"

    raise RuntimeError("Subnet exhausted: no free IP addresses available")


# ---------------------------------------------------------------------------
# awg show parser
# ---------------------------------------------------------------------------

def _parse_awg_show(output: str) -> dict[str, dict]:
    """Parse 'awg show' output into {pubkey: {rx, tx, handshake}} mapping."""
    stats: dict[str, dict] = {}
    current: Optional[str] = None

    for line in output.splitlines():
        line = line.strip()
        if line.startswith("peer:"):
            current = line.split("peer:", 1)[1].strip()
            stats[current] = {}
        elif current:
            if "transfer:" in line:
                parts = line.split("transfer:", 1)[1].strip().split(",")
                if len(parts) == 2:
                    stats[current]["rx"] = parts[0].strip().replace(" received", "").strip()
                    stats[current]["tx"] = parts[1].strip().replace(" sent", "").strip()
            elif "latest handshake:" in line:
                stats[current]["handshake"] = line.split("latest handshake:", 1)[1].strip()

    return stats


# ---------------------------------------------------------------------------
# Client config builder
# ---------------------------------------------------------------------------

def _pick_h(range_str: str) -> int:
    """Pick a random integer from an H-value.

    Handles both:
    - New-style range: '1745909952-1748455298'  → random int in [lo, hi]
    - Legacy single value: '683089438'           → that value as-is
    """
    parts = range_str.split("-")
    if len(parts) == 2:
        lo, hi = int(parts[0]), int(parts[1])
        return random.randint(lo, hi)
    return int(parts[0])


def _extract_special_junk(interface_comments: list[str]) -> dict[str, str]:
    """Extract client-side I1-I5 values from server interface comments.

    Legacy AmneziaWG stores these values in the server config as commented lines:
      # I1 = ...
    The client config must contain plain I1/I2/... keys so Amnezia detects the
    legacy 1.5 profile correctly instead of defaulting missing fields.
    """
    special_junk: dict[str, str] = {}

    for comment in interface_comments:
        line = comment.strip()
        if not line.startswith("#") or "=" not in line:
            continue

        key_part, value = line[1:].split("=", 1)
        key = key_part.strip()
        if key in {"I1", "I2", "I3", "I4", "I5"}:
            special_junk[key] = value.strip()

    return special_junk


def _build_client_config(
    private_key: str,
    client_ip: str,
    server_pubkey: str,
    psk: str,
    iface: dict,
    interface_comments: Optional[list[str]] = None,
) -> str:
    """
    Build a complete AmneziaWG client config string.
    H values are randomly sampled from the server's H1-H4 ranges.
    """
    interface_comments = interface_comments or []
    lines = [
        "[Interface]",
        f"PrivateKey = {private_key}",
        f"Address = {client_ip}",
        f"DNS = {settings.dns}",
        "",
    ]

    for param in ("Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4"):
        if param in iface:
            lines.append(f"{param} = {iface[param]}")

    for h in ("H1", "H2", "H3", "H4"):
        if h in iface:
            lines.append(f"{h} = {_pick_h(iface[h])}")

    special_junk = _extract_special_junk(interface_comments)
    if _MODE == "legacy" and not special_junk.get("I1"):
        # Older legacy nodes may not preserve commented I1..I5 lines in wg0.conf.
        # Without I1, Amnezia may treat the profile as a newer protocol variant
        # and apply mismatching defaults, which breaks handshake.
        special_junk["I1"] = _LEGACY_DEFAULT_SPECIAL_JUNK_1

    for key in ("I1", "I2", "I3", "I4", "I5"):
        value = special_junk.get(key)
        # Include non-empty tag expressions; skip malformed/binary placeholders.
        if value and isinstance(value, str) and len(value.strip()) > 0 and "binarydata" not in value.lower():
            lines.append(f"{key} = {value}")

    lines += [
        "",
        "[Peer]",
        f"PublicKey = {server_pubkey}",
        f"PresharedKey = {psk}",
        "AllowedIPs = 0.0.0.0/0, ::/0",
        f"Endpoint = {settings.server_host}:{iface['ListenPort']}",
        "PersistentKeepalive = 25",
    ]

    return "\n".join(lines) + "\n"


def _build_qr_png(config_str: str) -> bytes:
    """Render client config as QR code PNG bytes."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(config_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _split_dns_pair() -> tuple[str, str]:
    parts = [part.strip() for part in settings.dns.split(",") if part.strip()]
    if not parts:
        return "1.1.1.1", "1.0.0.1"
    if len(parts) == 1:
        return parts[0], "1.0.0.1" if parts[0] == "1.1.1.1" else ""
    return parts[0], parts[1]


def _build_amnezia_vpn_config(
    *,
    client_name: str,
    client_private_key: str,
    client_ip: str,
    server_pubkey: str,
    psk: str,
    iface: dict,
    interface_comments: Optional[list[str]] = None,
) -> str:
    """Build Amnezia profile JSON used by vpn:// links."""
    raw_config = _build_client_config(
        private_key=client_private_key,
        client_ip=client_ip,
        server_pubkey=server_pubkey,
        psk=psk,
        iface=iface,
        interface_comments=interface_comments,
    )
    sampled_h: dict[str, str] = {}
    for key in ("H1", "H2", "H3", "H4"):
        if key in iface and str(iface[key]).strip():
            sampled_h[key] = str(_pick_h(str(iface[key])))

    special_junk = _extract_special_junk(interface_comments or [])
    if _MODE == "legacy" and not special_junk.get("I1"):
        special_junk["I1"] = _LEGACY_DEFAULT_SPECIAL_JUNK_1

    client_payload = {
        **sampled_h,
        "Jc": str(iface.get("Jc", "0")),
        "Jmax": str(iface.get("Jmax", "0")),
        "Jmin": str(iface.get("Jmin", "0")),
        "S1": str(iface.get("S1", "0")),
        "S2": str(iface.get("S2", "0")),
        "S3": str(iface.get("S3", "0")),
        "S4": str(iface.get("S4", "0")),
        "I1": special_junk.get("I1", ""),
        "I2": special_junk.get("I2", ""),
        "I3": special_junk.get("I3", ""),
        "I4": special_junk.get("I4", ""),
        "I5": special_junk.get("I5", ""),
    }
    protocol_payload = {
        "H1": client_payload.get("H1", ""),
        "H2": client_payload.get("H2", ""),
        "H3": client_payload.get("H3", ""),
        "H4": client_payload.get("H4", ""),
        "I1": client_payload["I1"],
        "I2": client_payload["I2"],
        "I3": client_payload["I3"],
        "I4": client_payload["I4"],
        "I5": client_payload["I5"],
        "Jc": client_payload["Jc"],
        "Jmax": client_payload["Jmax"],
        "Jmin": client_payload["Jmin"],
        "S1": client_payload["S1"],
        "S2": client_payload["S2"],
        "S3": client_payload["S3"],
        "S4": client_payload["S4"],
        "last_config": raw_config,
        "port": str(iface["ListenPort"]),
        "transport_proto": "udp",
    }
    dns1, dns2 = _split_dns_pair()
    profile = {
        "containers": [
            {
                "container": "amnezia-awg2" if _MODE == "new" else "amnezia-awg",
                "awg": protocol_payload,
            }
        ],
        "defaultContainer": "amnezia-awg2" if _MODE == "new" else "amnezia-awg",
        "description": client_name,
        "dns1": dns1,
        "dns2": dns2,
        "hostName": settings.server_host,
        "nameOverriddenByUser": True,
    }
    return json.dumps(profile, ensure_ascii=False, separators=(",", ":"))


def _to_amnezia_vpn_link(config_text: str) -> str:
    """Encode Amnezia profile JSON into vpn:// format expected by clients."""
    raw = config_text.encode("utf-8")
    packed = len(raw).to_bytes(4, "big") + zlib.compress(raw)
    token = base64.urlsafe_b64encode(packed).decode("utf-8").rstrip("=")
    return f"vpn://{token}"


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def _read_live_conf() -> str:
    """Read running interface config from kernel via '{tool} showconf {iface}'."""
    try:
        return docker_manager.exec_run([_TOOL, "showconf", _IFACE])
    except Exception as exc:
        logger.warning("%s showconf failed (%s), falling back to file read", _TOOL, exc)
        return docker_manager.read_file(_CONF_PATH)


def list_users() -> list[UserListItem]:
    conf_content = _read_live_conf()
    parsed = _parse_conf(conf_content)
    clients_table = _read_clients_table()

    live_stats: dict[str, dict] = {}
    try:
        show_out = docker_manager.exec_run([_TOOL, "show", _IFACE])
        live_stats = _parse_awg_show(show_out)
    except Exception as exc:
        logger.warning("awg show failed: %s", exc)

    # Support both nested userData (Amnezia panel) and flat entries (custom)
    ct_map: dict[str, dict] = {}
    for e in clients_table:
        cid = e.get("clientId", "")
        ud = e.get("userData")
        ct_map[cid] = ud if ud is not None else {k: v for k, v in e.items() if k != "clientId"}

    users = []
    for peer in parsed["peers"]:
        pub = peer.get("PublicKey", "")
        meta = ct_map.get(pub, {})
        stats = live_stats.get(pub, {})
        handshake = stats.get("handshake", "")

        users.append(
            UserListItem(
                client_id=pub,
                name=meta.get("clientName", pub[:16] + "…"),
                internal_ip=peer.get("AllowedIPs", "").split("/")[0],
                created_at=meta.get("creationDate"),
                transfer_rx=stats.get("rx"),
                transfer_tx=stats.get("tx"),
                last_handshake=handshake or None,
                # "recently" means handshake was reported (and not many minutes ago)
                is_online=bool(handshake) and "minutes" not in handshake and "hours" not in handshake,
            )
        )

    return users


def create_user(data: UserCreate) -> tuple[UserData, str, bytes]:
    """
    Create a new AWG peer.

    Returns:
        (UserData, amnezia_vpn_link, qr_png_bytes)

    Flow (atomic under _LOCK):
      1. Generate keypair + PSK
      2. Find next free IP
      3. Write awg0.conf  (persistence layer)
      4. Update clientsTable  (metadata layer; rollback conf on failure)
      5. Live apply via awg set  (runtime layer; best-effort)
    """
    with _LOCK:
        conf_content = docker_manager.read_file(_CONF_PATH)
        parsed = _parse_conf(conf_content)
        clients_table = _read_clients_table()
        server_pubkey = docker_manager.read_file(settings.server_pubkey_path).strip()

        private_key, public_key = _generate_keypair()
        psk = _generate_psk()

        iface_addr = parsed["interface"]["Address"]
        new_ip = _find_next_ip(parsed["peers"], iface_addr)

        new_peer = {
            "PublicKey": public_key,
            "PresharedKey": psk,
            "AllowedIPs": new_ip,
        }

        # ------- PHASE 1: write awg0.conf -------
        parsed["peers"].append(new_peer)
        docker_manager.write_file(_CONF_PATH, _render_conf(parsed))

        # ------- PHASE 2: update clientsTable  -------
        created_at = datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S %Y")
        new_entry = {
            "clientId": public_key,
            "userData": {
                "clientName": data.name,
                "allowedIps": new_ip,
                "creationDate": created_at,
                "privateKey": private_key,
                "presharedKey": psk,
            },
        }
        try:
            clients_table.append(new_entry)
            _write_clients_table(clients_table)
        except Exception:
            # rollback awg0.conf
            parsed["peers"].remove(new_peer)
            try:
                docker_manager.write_file(_CONF_PATH, _render_conf(parsed))
            except Exception as rb_err:
                logger.error("Rollback of awg0.conf failed: %s", rb_err)
            raise

        # ------- PHASE 3: live apply (best-effort) -------
        try:
            _live_add_peer(public_key, psk, new_ip)
        except Exception as exc:
            logger.warning(
                "Live apply failed for %s: %s — peer will activate on next container restart.",
                public_key,
                exc,
            )

        config_text = _build_amnezia_vpn_config(
            client_name=data.name,
            client_private_key=private_key,
            client_ip=new_ip,
            server_pubkey=server_pubkey,
            psk=psk,
            iface=parsed["interface"],
            interface_comments=parsed.get("interface_comments", []),
        )
        vpn_link = _to_amnezia_vpn_link(config_text)
        qr_png = _build_qr_png(vpn_link)

        user = UserData(
            client_id=public_key,
            name=data.name,
            internal_ip=new_ip.split("/")[0],
            created_at=created_at,
        )
        return user, vpn_link, qr_png


def delete_user(client_id: str) -> bool:
    """
    Remove an AWG peer.

    Returns True if found and removed, False if not found.

    Flow:
      1. Remove from awg0.conf
      2. Remove from clientsTable
      3. Live remove via awg set (best-effort)
    """
    with _LOCK:
        conf_content = docker_manager.read_file(_CONF_PATH)
        parsed = _parse_conf(conf_content)
        clients_table = _read_clients_table()

        peer = next((p for p in parsed["peers"] if p.get("PublicKey") == client_id), None)
        if peer is None:
            return False

        # ------- PHASE 1: write awg0.conf -------
        parsed["peers"] = [p for p in parsed["peers"] if p.get("PublicKey") != client_id]
        docker_manager.write_file(_CONF_PATH, _render_conf(parsed))

        # ------- PHASE 2: update clientsTable -------
        clients_table = [e for e in clients_table if e.get("clientId") != client_id]
        try:
            _write_clients_table(clients_table)
        except Exception as exc:
            logger.error(
                "clientsTable update failed after removing %s: %s", client_id, exc
            )

        # ------- PHASE 3: live remove (best-effort) -------
        try:
            docker_manager.exec_run([_TOOL, "set", _IFACE, "peer", client_id, "remove"])
        except Exception as exc:
            logger.warning(
                "Live remove failed for %s: %s — peer will be gone after next restart.",
                client_id,
                exc,
            )

        return True


def get_user_config(client_id: str) -> Optional[str]:
    """
    Return an Amnezia-compatible vpn:// link for an existing peer.
    The underlying AWG client config is re-built from stored keys.
    """
    clients_table = _read_clients_table()
    entry = next((e for e in clients_table if e.get("clientId") == client_id), None)
    if entry is None:
        return None

    ud = entry.get("userData") if isinstance(entry.get("userData"), dict) else {}
    client_name = (
        ud.get("clientName")
        or entry.get("clientName")
        or client_id[:16]
    )
    private_key = ud.get("privateKey") or entry.get("privateKey")
    psk = ud.get("presharedKey") or entry.get("presharedKey")
    client_ip = ud.get("allowedIps") or entry.get("allowedIps", "")

    if not private_key:
        return None  # key was not stored (legacy entry)

    conf_content = docker_manager.read_file(_CONF_PATH)
    parsed = _parse_conf(conf_content)
    server_pubkey = docker_manager.read_file(settings.server_pubkey_path).strip()

    config_text = _build_amnezia_vpn_config(
        client_name=client_name,
        client_private_key=private_key,
        client_ip=client_ip,
        server_pubkey=server_pubkey,
        psk=psk or "",
        iface=parsed["interface"],
        interface_comments=parsed.get("interface_comments", []),
    )
    return _to_amnezia_vpn_link(config_text)


def get_user_qr(client_id: str) -> Optional[bytes]:
    config = get_user_config(client_id)
    if config is None:
        return None
    return _build_qr_png(config)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _live_add_peer(public_key: str, psk: str, allowed_ips: str) -> None:
    """Apply new peer to the running WG/AWG interface without a restart.

    Works for both:
    - New (amneziawg-tools): awg set awg0 peer ...
    - Legacy (wireguard-tools): wg set wg0 peer ...

    PSK is written to a temp file (required by the wg/awg set API).
    """
    safe_psk = psk.replace("'", "")  # PSK is base64; extra guard against injection
    safe_pub = public_key.replace("'", "")
    safe_ips = allowed_ips.replace("'", "")

    shell_cmd = (
        f"printf '%s' '{safe_psk}' > /tmp/._awg_psk.key && "
        f"{_TOOL} set {_IFACE} peer '{safe_pub}' "
        f"preshared-key /tmp/._awg_psk.key "
        f"allowed-ips '{safe_ips}'; "
        f"rm -f /tmp/._awg_psk.key"
    )
    docker_manager.exec_shell(shell_cmd)


def _read_clients_table() -> list[dict]:
    try:
        raw = docker_manager.read_file(settings.clients_table_path)
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _write_clients_table(table: list[dict]) -> None:
    docker_manager.write_file(
        settings.clients_table_path,
        json.dumps(table, indent=4, ensure_ascii=False) + "\n",
    )

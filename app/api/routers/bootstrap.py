import json
from pathlib import Path
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from fastapi import APIRouter, HTTPException, Query, Request
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from pydantic import BaseModel

from ...core.config import settings
from ...core.identity import (
    get_locked_master_ip,
    load_or_create_node_id,
    mark_node_enrolled,
    node_enrolled,
    write_node_registry_entry,
)
from ...core.pki import pki_manager
from ...infrastructure.grpc_server import grpc_node_server

router = APIRouter(prefix="/panel", tags=["panel-bootstrap"])
node_router = APIRouter(prefix="/node/bootstrap", tags=["node-bootstrap"])


class CompleteEnrollmentBody(BaseModel):
    node_cert_pem: str
    ca_cert_pem: str
    master_ip: str


def _caller_allowed(caller: str) -> bool:
    locked = get_locked_master_ip()
    if locked:
        return caller == locked
    if settings.master_ip:
        return caller == settings.master_ip
    return True


@node_router.get("/status")
def node_status(request: Request):
    node_id = load_or_create_node_id()
    caller = request.client.host if request.client else ""
    bootstrap_open = settings.bootstrap_enabled and not node_enrolled()
    locked_master = get_locked_master_ip()
    return {
        "node_id": node_id,
        "bootstrap_open": bootstrap_open,
        "locked_master_ip": locked_master,
        "caller": caller,
    }


@node_router.post("/csr")
def node_csr(request: Request):
    if settings.role != "node":
        raise HTTPException(status_code=403, detail="bootstrap endpoint is only for node role")
    if not settings.bootstrap_enabled or node_enrolled():
        raise HTTPException(status_code=409, detail="node is already enrolled")

    caller = request.client.host if request.client else ""
    if not _caller_allowed(caller):
        raise HTTPException(status_code=403, detail="only configured master IP can enroll this node")

    node_id = load_or_create_node_id()
    node_ip = request.url.hostname or "127.0.0.1"
    csr_pem = pki_manager.create_node_csr(node_id=node_id, node_ip=node_ip, key_path=settings.node_key_path)
    return {"node_id": node_id, "csr_pem": csr_pem.decode("utf-8")}


@node_router.post("/complete")
async def node_complete_enrollment(body: CompleteEnrollmentBody, request: Request):
    if settings.role != "node":
        raise HTTPException(status_code=403, detail="bootstrap endpoint is only for node role")
    if not settings.bootstrap_enabled:
        raise HTTPException(status_code=409, detail="bootstrap disabled")

    caller = request.client.host if request.client else ""
    if not _caller_allowed(caller):
        raise HTTPException(status_code=403, detail="only configured master IP can enroll this node")

    node_id = load_or_create_node_id()
    try:
        issued_cert = x509.load_pem_x509_certificate(body.node_cert_pem.encode("utf-8"))
        issued_ca = x509.load_pem_x509_certificate(body.ca_cert_pem.encode("utf-8"))
        private_key = serialization.load_pem_private_key(
            Path(settings.node_key_path).read_bytes(),
            password=None,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid enrollment payload: {exc}")

    if issued_cert.issuer != issued_ca.subject:
        raise HTTPException(status_code=400, detail="node certificate is not issued by provided CA")

    if issued_cert.public_key().public_numbers() != private_key.public_key().public_numbers():
        raise HTTPException(status_code=400, detail="node certificate does not match node private key")

    cn = ""
    for attr in issued_cert.subject:
        if attr.oid.dotted_string == "2.5.4.3":
            cn = attr.value
            break
    if cn and cn != node_id:
        raise HTTPException(status_code=400, detail="node certificate subject does not match node id")

    Path(settings.node_cert_path).write_text(body.node_cert_pem, encoding="utf-8")
    Path(settings.ca_cert_path).write_text(body.ca_cert_pem, encoding="utf-8")

    mark_node_enrolled(body.master_ip)
    await grpc_node_server.start()

    return {"status": "enrolled"}


@node_router.post("/reset")
async def node_reset_enrollment(request: Request):
    """Reset node enrollment artifacts so master can re-enroll this node."""
    if settings.role != "node":
        raise HTTPException(status_code=403, detail="bootstrap endpoint is only for node role")

    caller = request.client.host if request.client else ""
    if not _caller_allowed(caller):
        raise HTTPException(status_code=403, detail="only configured master IP can reset this node")

    await grpc_node_server.stop()

    reset_paths = [
        settings.node_cert_path,
        settings.node_key_path,
        settings.ca_cert_path,
        settings.enrolled_flag_file,
        settings.master_lock_file,
    ]
    for path in reset_paths:
        try:
            p = Path(path)
            if p.exists():
                p.unlink()
        except Exception:
            pass

    return {"status": "reset"}


@router.post("/register-node")
def register_node(
    target: str = Query(..., description="Node IP or host"),
    force: bool = Query(False, description="Force re-enrollment by resetting node bootstrap state"),
):
    if settings.role != "master":
        raise HTTPException(status_code=403, detail="node registration is available only on master")

    normalized = target.strip().replace("http://", "").replace("https://", "").split("/", 1)[0]
    if ":" in normalized:
        normalized = normalized.split(":", 1)[0]
    if not normalized:
        raise HTTPException(status_code=400, detail="target is required")

    base_url = f"http://{normalized}:8000"

    def _call(method: str, path: str, payload: dict | None = None) -> dict:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urlrequest.Request(url=base_url + path, method=method, data=data, headers=headers)
        try:
            with urlrequest.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urlerror.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise HTTPException(status_code=502, detail=f"node bootstrap failed: {exc.code} {body}")
        except urlerror.URLError as exc:
            raise HTTPException(status_code=502, detail=f"node unreachable: {exc.reason}")

    status_payload = _call("GET", f"{settings.bootstrap_path}/status")
    if not status_payload.get("bootstrap_open"):
        if force:
            _call("POST", f"{settings.bootstrap_path}/reset", {})
            status_payload = _call("GET", f"{settings.bootstrap_path}/status")
            if not status_payload.get("bootstrap_open"):
                raise HTTPException(status_code=502, detail="node reset did not open bootstrap mode")
        else:
            write_node_registry_entry(normalized, status_payload.get("node_id", "unknown"))
            return {
                "status": "already-managed",
                "target": normalized,
                "node_id": status_payload.get("node_id", "unknown"),
            }

    if not status_payload.get("bootstrap_open"):
        write_node_registry_entry(normalized, status_payload.get("node_id", "unknown"))
        return {
            "status": "already-managed",
            "target": normalized,
            "node_id": status_payload.get("node_id", "unknown"),
        }

    csr_payload = _call("POST", f"{settings.bootstrap_path}/csr")
    node_id = csr_payload.get("node_id")
    csr_pem = csr_payload.get("csr_pem", "").encode("utf-8")

    node_cert = pki_manager.sign_node_csr(csr_pem, common_name_fallback=node_id or "node")
    ca_pem = pki_manager.read_ca_pem()

    _call(
        "POST",
        f"{settings.bootstrap_path}/complete",
        {
            "node_cert_pem": node_cert.decode("utf-8"),
            "ca_cert_pem": ca_pem.decode("utf-8"),
            "master_ip": settings.master_ip or settings.server_host,
        },
    )

    write_node_registry_entry(normalized, node_id or "unknown")
    return {"status": "enrolled", "target": normalized, "node_id": node_id}

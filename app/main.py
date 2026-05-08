import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

import grpc
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .core.config import settings
from .infrastructure.docker_manager import docker_manager
from .core.awg_manager import detect_mode
from .core.db import SessionLocal, init_db
from .infrastructure import grpc_client
from .infrastructure.grpc_server import grpc_node_server
from .core.identity import load_or_create_node_id
from .core.pki import pki_manager
from .api.routers.bootstrap import router as panel_bootstrap_router, node_router as node_bootstrap_router
from .api.routers.node_bootstrap import router as node_bootstrap_api_router
from .api.routers.nodes import router as nodes_router
from .api.routers.users import router as users_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Startup: verify Docker connection
    try:
        docker_manager._client.ping()
        logger.info("Docker socket OK")
        container = docker_manager._container()
        logger.info("Container found: %s (status: %s)", container.name, container.status)
        mode = detect_mode()
        logger.info("AWG mode ready: %s", mode)
    except Exception as exc:
        logger.error("Docker connectivity check failed: %s", exc)

    if settings.role == "master":
        pki_manager.ensure_master_ca(settings.server_host)
        logger.info("Master PKI is ready")

    if settings.role == "node":
        node_id = load_or_create_node_id()
        logger.info("Node id: %s", node_id)
        await grpc_node_server.start()

    yield
    await grpc_node_server.stop()
    logger.info("Service shutting down")


app = FastAPI(
    title="AmneziaWG API",
    version="1.0.0",
    description="Lightweight REST API for managing AmneziaWG peers without the web panel.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Only add CORS if you want browser access; restrict origins in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-API-Key", "Content-Type"],
)

app.include_router(users_router, prefix="/api/v1")
app.include_router(panel_bootstrap_router)
app.include_router(node_bootstrap_router)
app.include_router(node_bootstrap_api_router)
app.include_router(nodes_router)

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_NODE_SCHEME = "http"
DEFAULT_NODE_PORT = 8000
NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _normalize_target(target: str) -> str:
    """Normalize target node host value from user input."""
    value = target.strip()
    if not value:
        raise HTTPException(status_code=400, detail="target is required")

    if "://" in value:
        value = value.split("://", 1)[1]
    value = value.split("/", 1)[0]
    if not value:
        raise HTTPException(status_code=400, detail="invalid target host")

    # Standardized setup: host controls always target fixed http:8000.
    if ":" in value and not value.startswith("["):
        value = value.split(":", 1)[0]
    return value


def _proxy_node_request(
    target: str,
    path: str,
    method: str = "GET",
    payload: dict | None = None,
) -> tuple[bytes, str]:
    host = _normalize_target(target)
    url = f"{DEFAULT_NODE_SCHEME}://{host}:{DEFAULT_NODE_PORT}{path}"

    body = None
    headers = {"X-API-Key": settings.api_key}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urlrequest.Request(url=url, data=body, method=method, headers=headers)
    try:
        with urlrequest.urlopen(req, timeout=18) as resp:
            data = resp.read()
            content_type = resp.headers.get("Content-Type", "application/octet-stream")
            return data, content_type
    except urlerror.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        detail = raw or exc.reason
        try:
            parsed = json.loads(raw)
            detail = parsed.get("detail", detail)
        except Exception:
            pass
        raise HTTPException(status_code=exc.code, detail=f"node {host}: {detail}")
    except urlerror.URLError as exc:
        raise HTTPException(status_code=502, detail=f"node {host} is unavailable: {exc.reason}")


def _require_master() -> None:
    if settings.role != "master":
        raise HTTPException(status_code=403, detail="This action is available only on master")


def _grpc_error(exc: grpc.RpcError, host: str) -> HTTPException:
    code = exc.code()
    detail = exc.details() or str(exc)
    if code == grpc.StatusCode.NOT_FOUND:
        return HTTPException(status_code=404, detail=detail)
    if code == grpc.StatusCode.FAILED_PRECONDITION:
        return HTTPException(status_code=409, detail=detail)
    if code in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
        return HTTPException(status_code=502, detail=f"node {host} unavailable via gRPC: {detail}")
    return HTTPException(status_code=500, detail=f"gRPC error from node {host}: {detail}")


@app.get("/", include_in_schema=False)
def panel_index() -> FileResponse:
    """Serve the web control panel."""
    return FileResponse(STATIC_DIR / "index.html", headers=NO_CACHE_HEADERS)


@app.get("/panel", include_in_schema=False)
def panel_alias() -> FileResponse:
    """Alias route for the web control panel."""
    return FileResponse(STATIC_DIR / "index.html", headers=NO_CACHE_HEADERS)


@app.get("/panel/", include_in_schema=False)
def panel_alias_slash() -> FileResponse:
    """Alias route with trailing slash for the web control panel."""
    return FileResponse(STATIC_DIR / "index.html", headers=NO_CACHE_HEADERS)


@app.get("/styles.css", include_in_schema=False)
def panel_styles() -> FileResponse:
    """Serve panel stylesheet for direct browser requests."""
    return FileResponse(STATIC_DIR / "styles.css", headers=NO_CACHE_HEADERS)


@app.get("/panel/styles.css", include_in_schema=False)
def panel_styles_alias() -> FileResponse:
    """Serve panel stylesheet for trailing-slash panel route."""
    return FileResponse(STATIC_DIR / "styles.css", headers=NO_CACHE_HEADERS)


@app.get("/app.js", include_in_schema=False)
def panel_script() -> FileResponse:
    """Serve panel script for direct browser requests."""
    return FileResponse(STATIC_DIR / "app.js", headers=NO_CACHE_HEADERS)


@app.get("/panel/app.js", include_in_schema=False)
def panel_script_alias() -> FileResponse:
    """Serve panel script for trailing-slash panel route."""
    return FileResponse(STATIC_DIR / "app.js", headers=NO_CACHE_HEADERS)


@app.get("/panel/bootstrap", include_in_schema=False)
def panel_bootstrap():
    """Panel defaults for standardized remote node control."""
    return {
        "default_scheme": DEFAULT_NODE_SCHEME,
        "default_port": DEFAULT_NODE_PORT,
        "transport": "grpc+mtls",
        "registration_endpoint": "/panel/register-node",
    }


@app.get("/panel/health", include_in_schema=False)
def panel_health(target: str = Query(..., description="Target node IP or host")):
    _require_master()
    host = _normalize_target(target)
    try:
        reply = grpc_client.health(host)
        return {"status": reply.status, "container": reply.container, "detail": reply.detail}
    except grpc.RpcError as exc:
        raise _grpc_error(exc, host)


@app.get("/panel/nodes", include_in_schema=False)
def panel_list_nodes(target: str = Query(..., description="Target node IP or host")):
    _require_master()
    host = _normalize_target(target)
    try:
        reply = grpc_client.list_users(host)
    except grpc.RpcError as exc:
        raise _grpc_error(exc, host)

    return [
        {
            "client_id": u.client_id,
            "name": u.name,
            "internal_ip": u.internal_ip,
            "created_at": u.created_at,
            "transfer_rx": u.transfer_rx,
            "transfer_tx": u.transfer_tx,
            "last_handshake": u.last_handshake,
            "is_online": u.is_online,
        }
        for u in reply.users
    ]


@app.post("/panel/nodes", include_in_schema=False)
def panel_create_node(body: dict, target: str = Query(..., description="Target node IP or host")):
    _require_master()
    host = _normalize_target(target)
    name = (body or {}).get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        reply = grpc_client.create_user(host, name)
    except grpc.RpcError as exc:
        raise _grpc_error(exc, host)

    return {
        "user": {
            "client_id": reply.user.client_id,
            "name": reply.user.name,
            "internal_ip": reply.user.internal_ip,
            "created_at": reply.user.created_at,
        },
        "user_key": reply.user.client_id,
        "config": reply.config,
    }


@app.delete("/panel/nodes/{client_id}", include_in_schema=False)
def panel_delete_node(client_id: str, target: str = Query(..., description="Target node IP or host")):
    _require_master()
    host = _normalize_target(target)
    try:
        grpc_client.delete_user(host, client_id)
        return Response(status_code=204)
    except grpc.RpcError as exc:
        raise _grpc_error(exc, host)


@app.get("/panel/nodes/{client_id}/config", include_in_schema=False)
def panel_node_config(client_id: str, target: str = Query(..., description="Target node IP or host")):
    _require_master()
    host = _normalize_target(target)
    try:
        reply = grpc_client.get_user_config(host, client_id)
    except grpc.RpcError as exc:
        raise _grpc_error(exc, host)

    return Response(
        content=reply.content,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{client_id[:8]}.vpn"'},
    )


@app.get("/panel/nodes/{client_id}/qr", include_in_schema=False)
def panel_node_qr(client_id: str, target: str = Query(..., description="Target node IP or host")):
    _require_master()
    host = _normalize_target(target)
    try:
        reply = grpc_client.get_user_qr(host, client_id)
    except grpc.RpcError as exc:
        raise _grpc_error(exc, host)

    return Response(content=reply.png, media_type="image/png")


@app.get("/health", tags=["health"])
def health():
    """Liveness probe."""
    try:
        docker_manager._client.ping()
        container = docker_manager._container()
        return {"status": "ok", "container": container.status}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@app.get("/panel/version", include_in_schema=False)
def panel_version():
    return {"panel_version": settings.panel_version, "role": settings.role}


@app.get("/node/version", include_in_schema=False)
def node_version():
    return {"node_version": settings.node_version, "role": settings.role}

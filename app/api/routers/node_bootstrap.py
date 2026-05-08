import secrets
import datetime as dt

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...core.db import SessionLocal, Node, BootstrapToken, MTLSCert
from ...core.config import settings

router = APIRouter(prefix="/api/v1", tags=["bootstrap"])


class CreateBootstrapTokenRequest(BaseModel):
    node_name: str
    ip: str


class CreateBootstrapTokenResponse(BaseModel):
    token: str
    expires_in_hours: int


class NodeRegisterRequest(BaseModel):
    token: str
    node_public_key: str
    node_info: dict = {}


class NodeRegisterResponse(BaseModel):
    status: str
    master_public_key: str


@router.post("/bootstrap/token", response_model=CreateBootstrapTokenResponse)
def create_bootstrap_token(req: CreateBootstrapTokenRequest):
    """Create a bootstrap token for a new node."""
    if settings.role != "master":
        raise HTTPException(status_code=403, detail="Bootstrap is only available on master")

    session = SessionLocal()
    try:
        # Check if node already exists
        existing = session.query(Node).filter_by(ip=req.ip).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Node with IP {req.ip} already exists")

        # Create node record in pending state
        node = Node(name=req.node_name, ip=req.ip, status="pending")
        session.add(node)
        session.commit()

        # Create bootstrap token (valid for 24 hours)
        token = secrets.token_urlsafe(32)
        expires = dt.datetime.utcnow() + dt.timedelta(hours=24)
        bootstrap_token = BootstrapToken(node_id=node.id, token=token, expires_at=expires)
        session.add(bootstrap_token)
        session.commit()

        return CreateBootstrapTokenResponse(token=token, expires_in_hours=24)
    finally:
        session.close()


@router.post("/bootstrap", response_model=NodeRegisterResponse)
def register_node_bootstrap(req: NodeRegisterRequest):
    """Register node with master using bootstrap token."""
    if settings.role != "master":
        raise HTTPException(status_code=403, detail="Bootstrap is only available on master")

    session = SessionLocal()
    try:
        # Find and validate token
        token_rec = session.query(BootstrapToken).filter_by(token=req.token).first()
        if not token_rec:
            raise HTTPException(status_code=401, detail="Invalid bootstrap token")

        if token_rec.used:
            raise HTTPException(status_code=401, detail="Bootstrap token already used")

        if token_rec.expires_at and dt.datetime.utcnow() > token_rec.expires_at:
            raise HTTPException(status_code=401, detail="Bootstrap token expired")

        # Find node
        node = session.query(Node).filter_by(id=token_rec.node_id).first()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")

        # Mark token as used
        token_rec.used = 1
        session.commit()

        # In production, you would exchange keys here
        # For now, just mark node as active
        node.status = "active"
        node.node_id = req.node_info.get("node_id", "unknown")
        session.commit()

        return NodeRegisterResponse(
            status="ok",
            master_public_key="master-public-key-placeholder",
        )
    finally:
        session.close()

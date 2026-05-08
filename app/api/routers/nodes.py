from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import desc
from typing import Optional
import datetime as dt
import secrets

from ...core.db import SessionLocal, Node, SSHTask, BootstrapToken

from ...core.config import settings
from ...infrastructure.ssh_executor import ssh_executor

router = APIRouter(prefix="/api/v1", tags=["nodes"])


class NodeData(BaseModel):
    id: str
    name: str
    ip: str
    status: str
    node_version: str
    node_id: Optional[str] = None
    created_at: Optional[str] = None
    last_seen: Optional[str] = None


class AddNodeRequest(BaseModel):
    mode: str  # "auto" or "manual"
    name: str
    ip: str
    ssh_user: str = "root"
    ssh_password: str = ""
    ssh_key: str = ""


class AddNodeResponse(BaseModel):
    status: str
    node_id: Optional[str] = None
    task_id: Optional[str] = None
    bootstrap_token: Optional[str] = None
    bootstrap_command: Optional[str] = None


class NodeDetailResponse(BaseModel):
    node: NodeData
    task_status: Optional[str] = None
    task_log: Optional[str] = None


class UpdateNodeRequest(BaseModel):
    ssh_user: str = "root"
    ssh_password: str
    ssh_port: int = 22


@router.get("/nodes", response_model=list[NodeData])
def list_nodes():
    """List all nodes."""
    if settings.role != "master":
        raise HTTPException(status_code=403, detail="Node management is only available on master")

    session = SessionLocal()
    try:
        nodes = session.query(Node).order_by(desc(Node.created_at)).all()
        return [
            NodeData(
                id=n.id,
                name=n.name,
                ip=n.ip,
                status=n.status,
                node_version=n.node_version or settings.node_version,
                node_id=n.node_id,
                created_at=n.created_at.isoformat() if n.created_at else None,
                last_seen=n.last_seen.isoformat() if n.last_seen else None,
            )
            for n in nodes
        ]
    finally:
        session.close()


@router.post("/nodes/add", response_model=AddNodeResponse)
def add_node(req: AddNodeRequest, background_tasks: BackgroundTasks):
    """Add a new node (auto SSH or manual bootstrap command)."""
    if settings.role != "master":
        raise HTTPException(status_code=403, detail="Node management is only available on master")

    session = SessionLocal()
    try:
        # Check if node IP already exists
        existing = session.query(Node).filter_by(ip=req.ip).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Node {req.ip} already exists")

        # Create node record
        node = Node(name=req.name, ip=req.ip, status="pending", node_version=settings.node_version)
        session.add(node)
        session.commit()

        if req.mode == "auto":
            if not req.ssh_password and not req.ssh_key:
                session.delete(node)
                session.commit()
                raise HTTPException(status_code=400, detail="SSH password or key required")

            # Create SSH task
            task = SSHTask(node_id=node.id, host=req.ip, user=req.ssh_user)
            session.add(task)
            session.commit()

            # Schedule SSH execution
            background_tasks.add_task(
                ssh_executor.execute_install,
                task.id,
                req.ip,
                22,
                req.ssh_user,
                req.ssh_password,
            )

            return AddNodeResponse(status="installing", node_id=node.id, task_id=task.id)

        else:  # manual
            # Generate bootstrap token linked to the node created above.
            token = secrets.token_urlsafe(32)
            expires = dt.datetime.utcnow() + dt.timedelta(hours=24)
            bootstrap_token = BootstrapToken(node_id=node.id, token=token, expires_at=expires)
            session.add(bootstrap_token)
            session.commit()

            bootstrap_cmd = f"bash -c '$(curl -fsSL http://{settings.server_host}:8000/api/v1/install_node_remote.sh)' -- {token} {settings.server_host}"
            return AddNodeResponse(
                status="bootstrap_ready",
                node_id=node.id,
                bootstrap_token=token,
                bootstrap_command=bootstrap_cmd,
            )
    finally:
        session.close()


@router.get("/nodes/{node_id}", response_model=NodeDetailResponse)
def get_node_detail(node_id: str):
    """Get node details and installation status."""
    if settings.role != "master":
        raise HTTPException(status_code=403, detail="Node management is only available on master")

    session = SessionLocal()
    try:
        node = session.query(Node).filter_by(id=node_id).first()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")

        task = session.query(SSHTask).filter_by(node_id=node_id).order_by(desc(SSHTask.created_at)).first()

        return NodeDetailResponse(
            node=NodeData(
                id=node.id,
                name=node.name,
                ip=node.ip,
                status=node.status,
                node_version=node.node_version or settings.node_version,
                node_id=node.node_id,
                created_at=node.created_at.isoformat() if node.created_at else None,
                last_seen=node.last_seen.isoformat() if node.last_seen else None,
            ),
            task_status=task.status if task else None,
            task_log=task.log if task else None,
        )
    finally:
        session.close()


@router.post("/nodes/{node_id}/update", response_model=AddNodeResponse)
def update_node(node_id: str, req: UpdateNodeRequest, background_tasks: BackgroundTasks):
    """Update an existing node to current release via SSH."""
    if settings.role != "master":
        raise HTTPException(status_code=403, detail="Node management is only available on master")

    if not req.ssh_password:
        raise HTTPException(status_code=400, detail="SSH password is required")

    session = SessionLocal()
    try:
        node = session.query(Node).filter_by(id=node_id).first()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")

        task = SSHTask(node_id=node.id, host=node.ip, user=req.ssh_user, port=req.ssh_port)
        session.add(task)
        node.status = "updating"
        session.commit()

        background_tasks.add_task(
            ssh_executor.execute_update,
            task.id,
            node.ip,
            req.ssh_port,
            req.ssh_user,
            req.ssh_password,
        )

        return AddNodeResponse(status="updating", node_id=node.id, task_id=task.id)
    finally:
        session.close()


@router.delete("/nodes/{node_id}", status_code=204)
def delete_node(node_id: str):
    """Delete a node and all associated data from the database."""
    if settings.role != "master":
        raise HTTPException(status_code=403, detail="Node management is only available on master")

    session = SessionLocal()
    try:
        node = session.query(Node).filter_by(id=node_id).first()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")

        session.query(SSHTask).filter_by(node_id=node_id).delete()
        session.query(BootstrapToken).filter_by(node_id=node_id).delete()
        session.delete(node)
        session.commit()
    finally:
        session.close()

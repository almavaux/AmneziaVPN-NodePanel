from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import grpc

from ..core.awg_manager import create_user, delete_user, get_user_config, get_user_qr, list_users
from ..core.config import settings
from ..infrastructure.docker_manager import docker_manager
from .grpc import node_pb2, node_pb2_grpc
from ..core.models import UserCreate

logger = logging.getLogger(__name__)


def _to_b64url(b64: str) -> str:
    return b64.replace("+", "-").replace("/", "_").rstrip("=")


def _from_b64url(b64url: str) -> str:
    b64 = b64url.replace("-", "+").replace("_", "/")
    pad = (4 - len(b64) % 4) % 4
    return b64 + "=" * pad


class NodeControlServicer(node_pb2_grpc.NodeControlServicer):
    def Health(self, request, context):
        try:
            docker_manager._client.ping()
            container = docker_manager._container()
            return node_pb2.HealthReply(status="ok", container=container.status)
        except Exception as exc:
            return node_pb2.HealthReply(status="error", detail=str(exc))

    def ListUsers(self, request, context):
        users = list_users()
        out = []
        for u in users:
            out.append(
                node_pb2.User(
                    client_id=_to_b64url(u.client_id),
                    name=u.name or "",
                    internal_ip=u.internal_ip or "",
                    created_at=u.created_at or "",
                    transfer_rx=u.transfer_rx or "",
                    transfer_tx=u.transfer_tx or "",
                    last_handshake=u.last_handshake or "",
                    is_online=u.is_online,
                )
            )
        return node_pb2.ListUsersReply(users=out)

    def CreateUser(self, request, context):
        user, config, _ = create_user(UserCreate(name=request.name))
        return node_pb2.CreateUserReply(
            user=node_pb2.User(
                client_id=_to_b64url(user.client_id),
                name=user.name or "",
                internal_ip=user.internal_ip or "",
                created_at=user.created_at or "",
            ),
            config=config,
        )

    def DeleteUser(self, request, context):
        ok = delete_user(_from_b64url(request.client_id))
        if not ok:
            context.abort(grpc.StatusCode.NOT_FOUND, "User not found")
        return node_pb2.DeleteUserReply()

    def GetUserConfig(self, request, context):
        config = get_user_config(_from_b64url(request.client_id))
        if config is None:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Config unavailable: this user was imported from legacy clientsTable without private key. Recreate user to get config and QR.",
            )
        return node_pb2.GetUserConfigReply(
            content=config.encode("utf-8"),
            file_name=f"{request.client_id[:8]}.vpn",
        )

    def GetUserQr(self, request, context):
        png = get_user_qr(_from_b64url(request.client_id))
        if png is None:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "QR unavailable: this user was imported from legacy clientsTable without private key. Recreate user to get config and QR.",
            )
        return node_pb2.GetUserQrReply(png=png)


class GrpcNodeServer:
    def __init__(self) -> None:
        self._server: grpc.aio.Server | None = None

    async def start(self) -> None:
        if self._server is not None:
            return

        cert_path = Path(settings.node_cert_path)
        key_path = Path(settings.node_key_path)
        ca_path = Path(settings.ca_cert_path)
        if not (cert_path.exists() and key_path.exists() and ca_path.exists()):
            logger.info("gRPC server is not started yet: node certificate set is missing")
            return

        private_key = key_path.read_bytes()
        cert_chain = cert_path.read_bytes()
        root_cert = ca_path.read_bytes()

        creds = grpc.ssl_server_credentials(
            [(private_key, cert_chain)],
            root_certificates=root_cert,
            require_client_auth=True,
        )

        server = grpc.aio.server()
        node_pb2_grpc.add_NodeControlServicer_to_server(NodeControlServicer(), server)
        server.add_secure_port(f"0.0.0.0:{settings.grpc_port}", creds)
        await server.start()
        self._server = server
        logger.info("Node gRPC server started on port %s with mTLS", settings.grpc_port)

    async def stop(self) -> None:
        if self._server is not None:
            await self._server.stop(grace=3)
            self._server = None


grpc_node_server = GrpcNodeServer()

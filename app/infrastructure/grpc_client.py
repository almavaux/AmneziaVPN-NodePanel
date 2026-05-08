from __future__ import annotations

from pathlib import Path

import grpc

from ..core.config import settings
from .grpc import node_pb2, node_pb2_grpc


def _mtls_credentials() -> grpc.ChannelCredentials:
    ca = Path(settings.ca_cert_path).read_bytes()
    cert = Path(settings.master_cert_path).read_bytes()
    key = Path(settings.master_key_path).read_bytes()
    return grpc.ssl_channel_credentials(root_certificates=ca, private_key=key, certificate_chain=cert)


def _channel(target: str) -> grpc.Channel:
    creds = _mtls_credentials()
    return grpc.secure_channel(f"{target}:{settings.grpc_port}", creds)


def health(target: str) -> node_pb2.HealthReply:
    with _channel(target) as channel:
        stub = node_pb2_grpc.NodeControlStub(channel)
        return stub.Health(node_pb2.HealthRequest(), timeout=12)


def list_users(target: str) -> node_pb2.ListUsersReply:
    with _channel(target) as channel:
        stub = node_pb2_grpc.NodeControlStub(channel)
        return stub.ListUsers(node_pb2.ListUsersRequest(), timeout=20)


def create_user(target: str, name: str) -> node_pb2.CreateUserReply:
    with _channel(target) as channel:
        stub = node_pb2_grpc.NodeControlStub(channel)
        return stub.CreateUser(node_pb2.CreateUserRequest(name=name), timeout=30)


def delete_user(target: str, client_id: str) -> None:
    with _channel(target) as channel:
        stub = node_pb2_grpc.NodeControlStub(channel)
        stub.DeleteUser(node_pb2.DeleteUserRequest(client_id=client_id), timeout=20)


def get_user_config(target: str, client_id: str) -> node_pb2.GetUserConfigReply:
    with _channel(target) as channel:
        stub = node_pb2_grpc.NodeControlStub(channel)
        return stub.GetUserConfig(node_pb2.GetUserConfigRequest(client_id=client_id), timeout=20)


def get_user_qr(target: str, client_id: str) -> node_pb2.GetUserQrReply:
    with _channel(target) as channel:
        stub = node_pb2_grpc.NodeControlStub(channel)
        return stub.GetUserQr(node_pb2.GetUserQrRequest(client_id=client_id), timeout=20)

from typing import Optional
from pydantic import BaseModel, field_validator


class UserCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        if len(v) > 64:
            raise ValueError("name must be 64 chars or less")
        return v


class UserData(BaseModel):
    client_id: str
    name: str
    internal_ip: str
    created_at: Optional[str] = None


class UserListItem(UserData):
    transfer_rx: Optional[str] = None
    transfer_tx: Optional[str] = None
    last_handshake: Optional[str] = None
    is_online: bool = False


class UserCreateResponse(BaseModel):
    user: UserData
    config: str


class UserConfigResponse(BaseModel):
    client_id: str
    config: str

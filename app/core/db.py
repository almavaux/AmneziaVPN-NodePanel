import datetime as dt
import uuid

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

Base = declarative_base()


class Node(Base):
    __tablename__ = "nodes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False, unique=True)
    ip = Column(String(45), nullable=False, unique=True)
    status = Column(String(32), default="pending")  # pending, active, offline
    node_id = Column(String(64), unique=True, nullable=True)
    mtls_cert_id = Column(String(36), nullable=True)
    node_version = Column(String(32), nullable=False, default=settings.node_version)
    created_at = Column(DateTime, default=dt.datetime.utcnow)
    last_seen = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Node {self.name} ({self.ip}) - {self.status}>"


class BootstrapToken(Base):
    __tablename__ = "bootstrap_tokens"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    node_id = Column(String(36), nullable=False)
    token = Column(String(64), unique=True, nullable=False)
    used = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    def __repr__(self) -> str:
        return f"<BootstrapToken {self.token[:8]}... for node_id {self.node_id}>"


class MTLSCert(Base):
    __tablename__ = "mtls_certs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    node_id = Column(String(36), nullable=False, unique=True)
    cert_pem = Column(Text, nullable=False)
    key_pem = Column(Text, nullable=False)
    ca_pem = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    def __repr__(self) -> str:
        return f"<MTLSCert for node_id {self.node_id}>"


class SSHTask(Base):
    __tablename__ = "ssh_tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    node_id = Column(String(36), nullable=False)
    host = Column(String(64), nullable=False)
    port = Column(Integer, default=22)
    user = Column(String(64), nullable=False)
    status = Column(String(32), default="pending")  # pending, running, success, failed
    log = Column(Text, default="")
    created_at = Column(DateTime, default=dt.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<SSHTask {self.id} - {self.status}>"


def init_db() -> sessionmaker:
    engine = create_engine(f"sqlite:///{settings.db_path}")
    Base.metadata.create_all(engine)

    # Lightweight migration for existing SQLite databases.
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(nodes)"))}
        if "node_version" not in cols:
            conn.execute(text("ALTER TABLE nodes ADD COLUMN node_version VARCHAR(32) DEFAULT 'N0.0.2'"))
            conn.execute(text("UPDATE nodes SET node_version = 'N0.0.2' WHERE node_version IS NULL OR node_version = ''"))

    return sessionmaker(bind=engine)


SessionLocal = init_db()

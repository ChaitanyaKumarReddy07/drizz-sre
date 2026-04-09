from sqlalchemy import Column, String, DateTime, Enum as SAEnum, JSON
from sqlalchemy.sql import func
from app.db import Base
import enum, uuid

class EmulatorStatus(str, enum.Enum):
    IDLE = "idle"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    ASSIGNED = "assigned"
    UNHEALTHY = "unhealthy"
    TERMINATED = "terminated"

class SnapshotLayer(str, enum.Enum):
    BASE = "base"
    APP = "app"
    SESSION = "session"

class Emulator(Base):
    __tablename__ = "emulators"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    status = Column(SAEnum(EmulatorStatus), default=EmulatorStatus.PROVISIONING, nullable=False)
    snapshot_id = Column(String, nullable=True)
    assigned_to = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_health_check = Column(DateTime(timezone=True), nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)

class Snapshot(Base):
    __tablename__ = "snapshots"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    layer = Column(SAEnum(SnapshotLayer), nullable=False)
    app_id = Column(String, nullable=True)
    user_id = Column(String, nullable=True)
    parent_id = Column(String, nullable=True)
    path = Column(String, nullable=False)
    size_mb = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    metadata_ = Column("metadata", JSON, default=dict)

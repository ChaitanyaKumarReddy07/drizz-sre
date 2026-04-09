from sqlalchemy import Column, String, DateTime, Enum as SAEnum, JSON, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db import Base
import enum, uuid

class MissionStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"

class TaskStatus(str, enum.Enum):
    QUEUED = "queued"
    ALLOCATING = "allocating"
    EXECUTING = "executing"
    IDENTITY_GATE = "identity_gate"
    COMPLETING = "completing"
    DONE = "done"
    FAILED = "failed"

class Mission(Base):
    __tablename__ = "missions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    status = Column(SAEnum(MissionStatus), default=MissionStatus.PENDING)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    tasks = relationship("MissionTask", back_populates="mission", cascade="all, delete-orphan")

class MissionTask(Base):
    __tablename__ = "mission_tasks"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    mission_id = Column(String, ForeignKey("missions.id"), nullable=False)
    app_id = Column(String, nullable=False)
    goal = Column(String, nullable=False)
    status = Column(SAEnum(TaskStatus), default=TaskStatus.QUEUED)
    emulator_id = Column(String, nullable=True)
    depends_on = Column(String, nullable=True)
    gate_type = Column(String, nullable=True)
    gate_token = Column(String, nullable=True)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    mission = relationship("Mission", back_populates="tasks")

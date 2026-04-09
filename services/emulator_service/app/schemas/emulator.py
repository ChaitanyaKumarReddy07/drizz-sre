from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.models.emulator import EmulatorStatus, SnapshotLayer

class EmulatorProvisionRequest(BaseModel):
    snapshot_id: Optional[str] = None

class EmulatorResponse(BaseModel):
    id: str
    status: EmulatorStatus
    snapshot_id: Optional[str] = None
    assigned_to: Optional[str] = None
    created_at: Optional[datetime] = None
    last_health_check: Optional[datetime] = None
    model_config = {"from_attributes": True}

class SnapshotCreateRequest(BaseModel):
    layer: SnapshotLayer
    app_id: Optional[str] = None
    user_id: Optional[str] = None
    parent_id: Optional[str] = None

class SnapshotResponse(BaseModel):
    id: str
    layer: SnapshotLayer
    app_id: Optional[str] = None
    user_id: Optional[str] = None
    parent_id: Optional[str] = None
    path: str
    created_at: Optional[datetime] = None
    model_config = {"from_attributes": True}

class PoolStatusResponse(BaseModel):
    warm_pool_size: int
    idle_count: int
    assigned_count: int
    unhealthy_count: int
    total: int

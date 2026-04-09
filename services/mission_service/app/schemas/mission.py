from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.models.mission import MissionStatus, TaskStatus

class TaskInput(BaseModel):
    app_id: str = Field(alias="app")
    goal: str
    depends_on: Optional[str] = None
    model_config = {"populate_by_name": True}

class MissionRequest(BaseModel):
    user_id: str
    tasks: List[TaskInput]

class TaskResponse(BaseModel):
    id: str
    app_id: str
    goal: str
    status: TaskStatus
    depends_on: Optional[str] = None
    emulator_id: Optional[str] = None
    gate_type: Optional[str] = None
    result: Optional[dict] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = {"from_attributes": True}

class MissionResponse(BaseModel):
    id: str
    user_id: str
    status: MissionStatus
    tasks: List[TaskResponse] = []
    created_at: Optional[datetime] = None
    model_config = {"from_attributes": True}

from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.models.session import SessionHealth, SessionTier, LoginMethod

class SessionCreate(BaseModel):
    app_id: str
    login_method: LoginMethod = LoginMethod.PASSWORD
    snapshot_id: Optional[str] = None

class SessionResponse(BaseModel):
    id: str
    user_id: str
    app_id: str
    snapshot_id: Optional[str] = None
    health: SessionHealth
    tier: SessionTier
    login_method: LoginMethod
    use_count: int
    last_used_at: Optional[datetime] = None
    last_verified_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    model_config = {"from_attributes": True}

class HealthEventResponse(BaseModel):
    id: str
    session_id: str
    health: SessionHealth
    checked_at: Optional[datetime] = None
    detail: Optional[dict] = None
    model_config = {"from_attributes": True}

class SessionVerifyResponse(BaseModel):
    session_id: str
    health: SessionHealth
    re_auth_required: bool
    login_method: Optional[LoginMethod] = None

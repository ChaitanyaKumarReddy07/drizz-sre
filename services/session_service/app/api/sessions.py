from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from datetime import datetime, timezone
from app.db import AsyncSessionLocal
from app.models.session import AppSession, SessionHealth, SessionHealthEvent
from app.schemas.session import SessionCreate, SessionResponse, HealthEventResponse, SessionVerifyResponse

router = APIRouter()

def _mon(r): return r.app.state.health_monitor

@router.get("/{user_id}/sessions", response_model=list[SessionResponse])
async def list_sessions(user_id: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AppSession).where(AppSession.user_id == user_id))
        return result.scalars().all()

@router.post("/{user_id}/sessions", response_model=SessionResponse, status_code=201)
async def create_session(user_id: str, body: SessionCreate):
    async with AsyncSessionLocal() as db:
        s = AppSession(user_id=user_id, app_id=body.app_id, login_method=body.login_method, snapshot_id=body.snapshot_id)
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s

@router.post("/{user_id}/sessions/{app_id}/verify", response_model=SessionVerifyResponse)
async def verify(user_id: str, app_id: str, request: Request):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AppSession).where(AppSession.user_id == user_id, AppSession.app_id == app_id))
        s = result.scalar_one_or_none()
        if not s: raise HTTPException(404, "Session not found")
        sid, method, snapshot_id = s.id, s.login_method, s.snapshot_id
        s.use_count += 1
        s.last_used_at = datetime.now(timezone.utc)
        await db.commit()
    health = await _mon(request).verify_session(sid)
    return SessionVerifyResponse(
        session_id=sid,
        health=health,
        re_auth_required=(health == SessionHealth.EXPIRED),
        login_method=method if health == SessionHealth.EXPIRED else None,
        snapshot_id=snapshot_id,
    )

@router.get("/{user_id}/sessions/{app_id}/health-history", response_model=list[HealthEventResponse])
async def history(user_id: str, app_id: str, limit: int = 20):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AppSession).where(AppSession.user_id == user_id, AppSession.app_id == app_id))
        s = result.scalar_one_or_none()
        if not s: raise HTTPException(404, "Session not found")
        ev = await db.execute(select(SessionHealthEvent).where(SessionHealthEvent.session_id == s.id).order_by(SessionHealthEvent.checked_at.desc()).limit(limit))
        return ev.scalars().all()

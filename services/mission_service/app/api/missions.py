from fastapi import APIRouter, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
from app.db import AsyncSessionLocal
from app.models.mission import Mission, MissionTask, TaskStatus
from app.schemas.mission import MissionRequest, MissionResponse
from app.core.executor import MissionExecutor

router = APIRouter()
executor = MissionExecutor()

@router.post("", response_model=MissionResponse, status_code=201)
async def create_mission(body: MissionRequest, bg: BackgroundTasks):
    async with AsyncSessionLocal() as db:
        mission = Mission(user_id=body.user_id)
        db.add(mission)
        await db.flush()

        for t in body.tasks:
            db.add(MissionTask(
                mission_id=mission.id,
                app_id=t.app_id,
                goal=t.goal,
                depends_on=t.depends_on,
            ))
        await db.commit()
        await db.refresh(mission)
        mid = mission.id

    bg.add_task(executor.execute, mid)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Mission)
            .options(selectinload(Mission.tasks))
            .where(Mission.id == mid)
        )
        m = result.scalar_one()
        return m

@router.get("/{mission_id}", response_model=MissionResponse)
async def get_mission(mission_id: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Mission)
            .options(selectinload(Mission.tasks))
            .where(Mission.id == mission_id)
        )
        m = result.scalar_one_or_none()
        if not m:
            raise HTTPException(404, "Mission not found")
        return m

@router.post("/{mission_id}/tasks/{task_id}/approve")
async def approve_gate(mission_id: str, task_id: str):
    async with AsyncSessionLocal() as db:
        task = await db.get(MissionTask, task_id)
        if not task or task.mission_id != mission_id:
            raise HTTPException(404, "Task not found")
        if task.status != TaskStatus.IDENTITY_GATE:
            raise HTTPException(400, f"Task is not at identity gate (status={task.status.value})")
    await executor.approve_gate(task_id)
    return {"task_id": task_id, "approved": True}

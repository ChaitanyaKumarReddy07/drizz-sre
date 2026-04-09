from fastapi import APIRouter, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import uuid
from app.db import AsyncSessionLocal
from app.models.mission import Mission, MissionTask, TaskStatus
from app.schemas.mission import MissionRequest, MissionResponse
from app.core.executor import MissionExecutor

router = APIRouter()
executor = MissionExecutor()
SEQUENTIAL_KEYWORDS = ("pay", "payment", "checkout", "book", "purchase", "renew", "confirm")


def _is_sequential_goal(goal: str) -> bool:
    text = goal.lower()
    return any(k in text for k in SEQUENTIAL_KEYWORDS)


def _plan_tasks(body: MissionRequest) -> list[dict]:
    planned = []
    for idx, task in enumerate(body.tasks):
        task_id = str(uuid.uuid4())
        depends_on = task.depends_on
        if not depends_on and idx > 0 and _is_sequential_goal(task.goal):
            depends_on = planned[idx - 1]["id"]
        planned.append(
            {
                "id": task_id,
                "app_id": task.app_id,
                "goal": task.goal,
                "depends_on": depends_on,
            }
        )
    return planned

@router.post("", response_model=MissionResponse, status_code=201)
async def create_mission(body: MissionRequest, bg: BackgroundTasks):
    planned_tasks = _plan_tasks(body)
    async with AsyncSessionLocal() as db:
        mission = Mission(user_id=body.user_id)
        db.add(mission)
        await db.flush()

        for t in planned_tasks:
            db.add(MissionTask(
                id=t["id"],
                mission_id=mission.id,
                app_id=t["app_id"],
                goal=t["goal"],
                depends_on=t["depends_on"],
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

"""
Mission Executor: state machine that drives each task through
QUEUED -> ALLOCATING -> EXECUTING -> IDENTITY_GATE -> COMPLETING -> DONE/FAILED
"""
import asyncio, random, logging, os, uuid
from datetime import datetime, timezone
from sqlalchemy import select
from app.db import AsyncSessionLocal
from app.models.mission import Mission, MissionTask, MissionStatus, TaskStatus
import httpx

logger = logging.getLogger(__name__)
EMULATOR_URL = os.getenv("EMULATOR_SERVICE_URL", "http://emulator_service:8001")
SESSION_URL  = os.getenv("SESSION_SERVICE_URL",  "http://session_service:8002")
GATE_TIMEOUT = int(os.getenv("GATE_TIMEOUT_SECONDS", "300"))

class MissionExecutor:

    async def execute(self, mission_id: str):
        """Entry point — fan out all tasks, then aggregate."""
        async with AsyncSessionLocal() as db:
            mission = await db.get(Mission, mission_id)
            result  = await db.execute(select(MissionTask).where(MissionTask.mission_id == mission_id))
            tasks   = result.scalars().all()
            mission.status = MissionStatus.RUNNING
            await db.commit()

        independent = [t for t in tasks if not t.depends_on]
        dependent   = [t for t in tasks if t.depends_on]

        # Run independent tasks in parallel
        await asyncio.gather(*[self._run_task(t.id) for t in independent], return_exceptions=True)

        # Run dependent tasks sequentially after their parent
        for t in dependent:
            await self._run_task(t.id)

        await self._finalise_mission(mission_id)

    async def approve_gate(self, task_id: str):
        """Called when identity gate is approved externally."""
        async with AsyncSessionLocal() as db:
            task = await db.get(MissionTask, task_id)
            if task and task.status == TaskStatus.IDENTITY_GATE:
                task.gate_token = "approved"
                await db.commit()
                logger.info(f"Gate approved for task {task_id}")

    # ── private ──────────────────────────────────────────────────────────────

    async def _run_task(self, task_id: str):
        try:
            await self._set_status(task_id, TaskStatus.ALLOCATING)

            # Check session health first
            async with AsyncSessionLocal() as db:
                task = await db.get(MissionTask, task_id)
                user_id = (await db.get(Mission, task.mission_id)).user_id
                app_id  = task.app_id

            session_ok = await self._check_session(user_id, app_id)
            if not session_ok:
                await self._set_status(task_id, TaskStatus.FAILED,
                    result={"error": "re_auth_required", "app": app_id})
                return

            # Allocate emulator
            emulator_id = await self._allocate_emulator()
            if not emulator_id:
                await self._set_status(task_id, TaskStatus.FAILED,
                    result={"error": "no_emulator_available"})
                return

            async with AsyncSessionLocal() as db:
                task = await db.get(MissionTask, task_id)
                task.emulator_id = emulator_id
                task.status = TaskStatus.EXECUTING
                await db.commit()

            logger.info(f"Task {task_id} executing on emulator {emulator_id}")

            # Simulate execution time
            await asyncio.sleep(random.uniform(1.0, 3.0))

            # 30% chance of hitting an identity gate
            if random.random() < 0.30:
                gate_type = random.choice(["otp", "biometric", "payment_approval"])
                await self._set_status(task_id, TaskStatus.IDENTITY_GATE,
                    gate_type=gate_type)
                logger.info(f"Task {task_id} hit identity gate: {gate_type}")

                approved = await self._wait_for_gate(task_id)
                if not approved:
                    await self._set_status(task_id, TaskStatus.FAILED,
                        result={"error": "gate_timeout", "gate_type": gate_type})
                    await self._release_emulator(emulator_id)
                    return

            await self._set_status(task_id, TaskStatus.COMPLETING)
            await asyncio.sleep(0.5)
            await self._set_status(task_id, TaskStatus.DONE,
                result={"success": True, "emulator": emulator_id})
            await self._release_emulator(emulator_id)

        except Exception as e:
            logger.error(f"Task {task_id} error: {e}")
            await self._set_status(task_id, TaskStatus.FAILED, result={"error": str(e)})

    async def _check_session(self, user_id: str, app_id: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{SESSION_URL}/users/{user_id}/sessions/{app_id}/verify")
                if r.status_code == 404:
                    return True  # No session tracked — allow
                data = r.json()
                return not data.get("re_auth_required", False)
        except Exception as e:
            logger.warning(f"Session check failed: {e}")
            return True

    async def _allocate_emulator(self) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(f"{EMULATOR_URL}/emulators", json={})
                if r.status_code == 201:
                    return r.json()["id"]
        except Exception as e:
            logger.error(f"Emulator alloc failed: {e}")
        return None

    async def _release_emulator(self, emulator_id: str):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{EMULATOR_URL}/emulators/{emulator_id}/release")
        except Exception:
            pass

    async def _wait_for_gate(self, task_id: str) -> bool:
        """Poll DB for gate_token=approved, timeout after GATE_TIMEOUT seconds."""
        deadline = asyncio.get_event_loop().time() + GATE_TIMEOUT
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(2)
            async with AsyncSessionLocal() as db:
                task = await db.get(MissionTask, task_id)
                if task and task.gate_token == "approved":
                    return True
        return False

    async def _set_status(self, task_id: str, status: TaskStatus,
                          result=None, gate_type=None):
        async with AsyncSessionLocal() as db:
            task = await db.get(MissionTask, task_id)
            if task:
                task.status = status
                task.updated_at = datetime.now(timezone.utc)
                if result:
                    task.result = result
                if gate_type:
                    task.gate_type = gate_type
                await db.commit()
        logger.info(f"Task {task_id} -> {status.value}")

    async def _finalise_mission(self, mission_id: str):
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(MissionTask).where(MissionTask.mission_id == mission_id))
            tasks  = result.scalars().all()
            mission = await db.get(Mission, mission_id)
            if all(t.status == TaskStatus.DONE for t in tasks):
                mission.status = MissionStatus.DONE
            elif any(t.status == TaskStatus.FAILED for t in tasks):
                mission.status = MissionStatus.FAILED
            else:
                mission.status = MissionStatus.RUNNING
            await db.commit()
        logger.info(f"Mission {mission_id} finalised -> {mission.status.value}")

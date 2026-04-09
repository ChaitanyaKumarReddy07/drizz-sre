"""
Mission Executor: state machine that drives each task through
QUEUED -> ALLOCATING -> EXECUTING -> IDENTITY_GATE -> COMPLETING -> DONE/FAILED
"""
import asyncio, random, logging, os
from datetime import datetime, timezone
from sqlalchemy import select
from app.db import AsyncSessionLocal
from app.models.mission import Mission, MissionTask, MissionStatus, TaskStatus
import httpx

logger = logging.getLogger(__name__)
EMULATOR_URL = os.getenv("EMULATOR_SERVICE_URL", "http://emulator_service:8001")
SESSION_URL = os.getenv("SESSION_SERVICE_URL", "http://session_service:8002")
GATE_TIMEOUT = int(os.getenv("GATE_TIMEOUT_SECONDS", "300"))
GATE_TIMEOUT_POLICY = os.getenv("GATE_TIMEOUT_POLICY", "fail").lower()
MISSION_EVENT_WEBHOOK_URL = os.getenv("MISSION_EVENT_WEBHOOK_URL", "").strip()


class MissionExecutor:

    async def execute(self, mission_id: str):
        """Entry point: fan out independent tasks, then run dependent tasks."""
        async with AsyncSessionLocal() as db:
            mission = await db.get(Mission, mission_id)
            result = await db.execute(select(MissionTask).where(MissionTask.mission_id == mission_id))
            tasks = result.scalars().all()
            mission.status = MissionStatus.RUNNING
            mission.updated_at = datetime.now(timezone.utc)
            await db.commit()

        await self._emit_event("mission_status_changed", {"mission_id": mission_id, "status": MissionStatus.RUNNING.value})

        independent = [t for t in tasks if not t.depends_on]
        dependent = [t for t in tasks if t.depends_on]

        await asyncio.gather(*[self._run_task(t.id) for t in independent], return_exceptions=True)

        for t in dependent:
            dep_ok = await self._is_dependency_done(t.depends_on)
            if not dep_ok:
                await self._set_status(t.id, TaskStatus.FAILED, result={"error": "dependency_not_satisfied", "depends_on": t.depends_on})
                continue
            await self._run_task(t.id)

        await self._finalise_mission(mission_id)

    async def approve_gate(self, task_id: str):
        """Called when identity gate is approved externally."""
        async with AsyncSessionLocal() as db:
            task = await db.get(MissionTask, task_id)
            if task and task.status == TaskStatus.IDENTITY_GATE:
                task.gate_token = "approved"
                task.updated_at = datetime.now(timezone.utc)
                await db.commit()
                logger.info(f"Gate approved for task {task_id}")
                await self._emit_event(
                    "identity_gate_approved",
                    {
                        "mission_id": task.mission_id,
                        "task_id": task_id,
                        "gate_type": task.gate_type,
                    },
                )

    async def _run_task(self, task_id: str):
        emulator_id = None
        try:
            await self._set_status(task_id, TaskStatus.ALLOCATING)

            async with AsyncSessionLocal() as db:
                task = await db.get(MissionTask, task_id)
                mission = await db.get(Mission, task.mission_id)
                user_id = mission.user_id
                app_id = task.app_id

            session_state = await self._check_session(user_id, app_id)
            if not session_state["session_ok"]:
                await self._set_status(
                    task_id,
                    TaskStatus.RE_AUTH_REQUIRED,
                    result={
                        "status": "re_auth_required",
                        "app": app_id,
                        "login_method": session_state.get("login_method"),
                        "snapshot_id": session_state.get("snapshot_id"),
                    },
                )
                return

            emulator_id = await self._allocate_emulator(session_state.get("snapshot_id"))
            if not emulator_id:
                await self._set_status(task_id, TaskStatus.FAILED, result={"error": "no_emulator_available"})
                return

            async with AsyncSessionLocal() as db:
                task = await db.get(MissionTask, task_id)
                task.emulator_id = emulator_id
                task.status = TaskStatus.EXECUTING
                task.updated_at = datetime.now(timezone.utc)
                await db.commit()

            await self._emit_event(
                "task_status_changed",
                {
                    "task_id": task_id,
                    "status": TaskStatus.EXECUTING.value,
                    "emulator_id": emulator_id,
                },
            )

            logger.info(f"Task {task_id} executing on emulator {emulator_id}")
            await asyncio.sleep(random.uniform(1.0, 3.0))

            if random.random() < 0.30:
                gate_type = random.choice(["otp", "biometric", "payment_approval"])
                await self._set_status(task_id, TaskStatus.IDENTITY_GATE, gate_type=gate_type)
                await self._emit_event(
                    "identity_gate_triggered",
                    {
                        "task_id": task_id,
                        "emulator_id": emulator_id,
                        "gate_type": gate_type,
                    },
                )

                approved = await self._wait_for_gate(task_id)
                if not approved:
                    if GATE_TIMEOUT_POLICY == "skip":
                        await self._set_status(
                            task_id,
                            TaskStatus.DONE,
                            result={"success": False, "skipped": True, "reason": "gate_timeout", "gate_type": gate_type},
                        )
                    else:
                        await self._set_status(
                            task_id,
                            TaskStatus.FAILED,
                            result={"error": "gate_timeout", "gate_type": gate_type},
                        )
                    return

            await self._set_status(task_id, TaskStatus.COMPLETING)
            await asyncio.sleep(0.5)
            await self._set_status(task_id, TaskStatus.DONE, result={"success": True, "emulator": emulator_id})

        except Exception as e:
            logger.error(f"Task {task_id} error: {e}")
            await self._set_status(task_id, TaskStatus.FAILED, result={"error": str(e)})
        finally:
            if emulator_id:
                await self._release_emulator(emulator_id)

    async def _check_session(self, user_id: str, app_id: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{SESSION_URL}/users/{user_id}/sessions/{app_id}/verify")
                if r.status_code == 404:
                    return {"session_ok": True, "snapshot_id": None, "login_method": None}
                if r.status_code >= 400:
                    return {"session_ok": True, "snapshot_id": None, "login_method": None}
                data = r.json()
                return {
                    "session_ok": not data.get("re_auth_required", False),
                    "snapshot_id": data.get("snapshot_id"),
                    "login_method": data.get("login_method"),
                }
        except Exception as e:
            logger.warning(f"Session check failed: {e}")
            return {"session_ok": True, "snapshot_id": None, "login_method": None}

    async def _allocate_emulator(self, snapshot_id: str | None) -> str | None:
        try:
            payload = {"snapshot_id": snapshot_id} if snapshot_id else {}
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(f"{EMULATOR_URL}/emulators", json=payload)
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

    async def _set_status(self, task_id: str, status: TaskStatus, result=None, gate_type=None):
        event_payload = {"task_id": task_id, "status": status.value}
        async with AsyncSessionLocal() as db:
            task = await db.get(MissionTask, task_id)
            if task:
                task.status = status
                task.updated_at = datetime.now(timezone.utc)
                if result:
                    task.result = result
                    event_payload["result"] = result
                if gate_type:
                    task.gate_type = gate_type
                    event_payload["gate_type"] = gate_type
                event_payload["mission_id"] = task.mission_id
                await db.commit()
        logger.info(f"Task {task_id} -> {status.value}")
        await self._emit_event("task_status_changed", event_payload)

    async def _is_dependency_done(self, dependency_task_id: str | None) -> bool:
        if not dependency_task_id:
            return True
        async with AsyncSessionLocal() as db:
            task = await db.get(MissionTask, dependency_task_id)
            return bool(task and task.status == TaskStatus.DONE)

    async def _finalise_mission(self, mission_id: str):
        final_status = MissionStatus.RUNNING
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(MissionTask).where(MissionTask.mission_id == mission_id))
            tasks = result.scalars().all()
            mission = await db.get(Mission, mission_id)
            if all(t.status == TaskStatus.DONE for t in tasks):
                final_status = MissionStatus.DONE
            elif any(t.status == TaskStatus.FAILED for t in tasks):
                final_status = MissionStatus.FAILED
            else:
                final_status = MissionStatus.RUNNING
            mission.status = final_status
            mission.updated_at = datetime.now(timezone.utc)
            await db.commit()
        logger.info(f"Mission {mission_id} finalised -> {final_status.value}")
        await self._emit_event("mission_status_changed", {"mission_id": mission_id, "status": final_status.value})

    async def _emit_event(self, event_type: str, payload: dict):
        logger.info(f"MISSION_EVENT {event_type} {payload}")
        if not MISSION_EVENT_WEBHOOK_URL:
            return
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(MISSION_EVENT_WEBHOOK_URL, json={"event": event_type, "payload": payload})
        except Exception as e:
            logger.warning(f"Event delivery failed ({event_type}): {e}")

import os, asyncio, logging, uuid
from datetime import datetime, timezone
from sqlalchemy import select, func
from app.db import AsyncSessionLocal
from app.models.emulator import Emulator, EmulatorStatus, Snapshot, SnapshotLayer
from app.core.mock_android import MockAndroid, MockBootResult

logger = logging.getLogger(__name__)
WARM_POOL_SIZE = int(os.getenv("WARM_POOL_SIZE", "3"))
SNAPSHOTS_DIR = os.getenv("SNAPSHOTS_DIR", "/app/snapshots")

class PoolManager:
    def __init__(self):
        self._instances: dict[str, MockAndroid] = {}
        self._lock = asyncio.Lock()

    async def initialize(self):
        os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
        await self._reconcile_state()
        idle_count = await self._count_runtime_idle()
        shortfall = max(0, WARM_POOL_SIZE - idle_count)
        logger.info(f"Seeding warm pool: target={WARM_POOL_SIZE}, current_idle={idle_count}, shortfall={shortfall}")
        if shortfall > 0:
            await asyncio.gather(*[self._provision_warm() for _ in range(shortfall)], return_exceptions=True)
        logger.info("Pool ready")

    async def provision(self, snapshot_id=None):
        async with self._lock:
            if snapshot_id is None:
                em = await self._grab_idle()
                if em:
                    return em
            return await self._create_emulator(snapshot_id)

    async def snapshot(self, emulator_id, layer, app_id=None, user_id=None, parent_id=None):
        inst = self._instances.get(emulator_id)
        if not inst:
            raise ValueError(f"Emulator {emulator_id} not in runtime")
        snap_id = str(uuid.uuid4())
        path = os.path.join(SNAPSHOTS_DIR, f"{snap_id}.snap")
        await inst.create_snapshot(path)
        async with AsyncSessionLocal() as db:
            snap = Snapshot(id=snap_id, layer=layer, app_id=app_id, user_id=user_id, parent_id=parent_id, path=path, size_mb="~250")
            db.add(snap)
            await db.commit()
            await db.refresh(snap)
        return snap

    async def destroy(self, emulator_id):
        inst = self._instances.pop(emulator_id, None)
        if inst:
            await inst.destroy()
        async with AsyncSessionLocal() as db:
            em = await db.get(Emulator, emulator_id)
            if em:
                em.status = EmulatorStatus.TERMINATED
                em.updated_at = datetime.now(timezone.utc)
                await db.commit()
        asyncio.create_task(self._replenish_pool())

    async def get_status(self, emulator_id):
        async with AsyncSessionLocal() as db:
            return await db.get(Emulator, emulator_id)

    async def pool_stats(self):
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Emulator.status, func.count())
                .where(Emulator.status != EmulatorStatus.TERMINATED)
                .group_by(Emulator.status)
            )
            counts = {r[0]: r[1] for r in result}
        return {
            "warm_pool_size": WARM_POOL_SIZE,
            "idle_count": counts.get(EmulatorStatus.IDLE, 0),
            "assigned_count": counts.get(EmulatorStatus.ASSIGNED, 0),
            "unhealthy_count": counts.get(EmulatorStatus.UNHEALTHY, 0),
            "total": sum(counts.values()),
        }

    async def mark_assigned(self, emulator_id, task_id):
        async with AsyncSessionLocal() as db:
            em = await db.get(Emulator, emulator_id)
            if em:
                em.status = EmulatorStatus.ASSIGNED
                em.assigned_to = task_id
                em.updated_at = datetime.now(timezone.utc)
                await db.commit()

    async def mark_idle(self, emulator_id):
        async with AsyncSessionLocal() as db:
            em = await db.get(Emulator, emulator_id)
            if em:
                em.status = EmulatorStatus.IDLE
                em.assigned_to = None
                em.updated_at = datetime.now(timezone.utc)
                await db.commit()
        asyncio.create_task(self._replenish_pool())

    async def mark_unhealthy(self, emulator_id):
        async with AsyncSessionLocal() as db:
            em = await db.get(Emulator, emulator_id)
            if em:
                em.status = EmulatorStatus.UNHEALTHY
                em.updated_at = datetime.now(timezone.utc)
                await db.commit()
        asyncio.create_task(self.destroy(emulator_id))

    async def run_health_check(self, emulator_id):
        inst = self._instances.get(emulator_id)
        if not inst:
            return {"healthy": False, "reason": "not_found"}
        result = await inst.health_check()
        async with AsyncSessionLocal() as db:
            em = await db.get(Emulator, emulator_id)
            if em:
                em.last_health_check = datetime.now(timezone.utc)
                if not result["healthy"]:
                    em.status = EmulatorStatus.UNHEALTHY
                await db.commit()
        return result

    def get_all_instance_ids(self):
        return list(self._instances.keys())

    async def _grab_idle(self):
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Emulator)
                .where(Emulator.status == EmulatorStatus.IDLE)
                .order_by(Emulator.created_at.asc())
                .limit(10)
            )
            candidates = result.scalars().all()
            for em in candidates:
                inst = self._instances.get(em.id)
                if not inst:
                    em.status = EmulatorStatus.TERMINATED
                    em.updated_at = datetime.now(timezone.utc)
                    continue
                em.status = EmulatorStatus.RUNNING
                em.updated_at = datetime.now(timezone.utc)
                await db.commit()
                await db.refresh(em)
                return em
            if candidates:
                await db.commit()
        return None

    async def _create_emulator(self, snapshot_id):
        eid = str(uuid.uuid4())
        inst = MockAndroid(eid)
        self._instances[eid] = inst
        async with AsyncSessionLocal() as db:
            em = Emulator(id=eid, status=EmulatorStatus.PROVISIONING, snapshot_id=snapshot_id)
            db.add(em)
            await db.commit()
        result = await inst.boot(snapshot_id)
        status = EmulatorStatus.RUNNING if result == MockBootResult.SUCCESS else EmulatorStatus.UNHEALTHY
        async with AsyncSessionLocal() as db:
            em = await db.get(Emulator, eid)
            em.status = status
            em.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(em)
        if status == EmulatorStatus.UNHEALTHY:
            raise RuntimeError(f"Boot failed: {result}")
        return em

    async def _provision_warm(self):
        try:
            em = await self._create_emulator(None)
            async with AsyncSessionLocal() as db:
                rec = await db.get(Emulator, em.id)
                rec.status = EmulatorStatus.IDLE
                await db.commit()
            logger.info(f"Warm emulator ready: {em.id}")
        except Exception as e:
            logger.error(f"Warm provision failed: {e}")

    async def _replenish_pool(self):
        idle_count = await self._count_runtime_idle()
        shortfall = WARM_POOL_SIZE - idle_count
        if shortfall > 0:
            await asyncio.gather(*[self._provision_warm() for _ in range(shortfall)], return_exceptions=True)

    async def _count_runtime_idle(self) -> int:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Emulator.id).where(Emulator.status == EmulatorStatus.IDLE))
            ids = [r[0] for r in result]
        return sum(1 for eid in ids if eid in self._instances)

    async def _reconcile_state(self):
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Emulator).where(Emulator.status != EmulatorStatus.TERMINATED)
            )
            rows = result.scalars().all()
            for em in rows:
                em.status = EmulatorStatus.TERMINATED
                em.assigned_to = None
                em.updated_at = datetime.now(timezone.utc)
            if rows:
                await db.commit()

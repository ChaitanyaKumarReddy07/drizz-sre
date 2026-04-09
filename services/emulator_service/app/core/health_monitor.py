import asyncio, logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
logger = logging.getLogger(__name__)

class HealthMonitor:
    def __init__(self, pool_manager):
        self.pool = pool_manager
        self._sched = AsyncIOScheduler()

    def start(self):
        self._sched.add_job(self._check_all, "interval", seconds=30, id="emu_health")
        self._sched.start()
        logger.info("Emulator health monitor started")

    def stop(self):
        self._sched.shutdown(wait=False)

    async def _check_all(self):
        ids = self.pool.get_all_instance_ids()
        logger.info(f"Health checking {len(ids)} emulators")
        await asyncio.gather(*[self._check_one(eid) for eid in ids], return_exceptions=True)

    async def _check_one(self, eid):
        result = await self.pool.run_health_check(eid)
        if not result["healthy"]:
            logger.warning(f"Emulator {eid} unhealthy ({result['reason']}), replacing")
            await self.pool.mark_unhealthy(eid)

import asyncio, random, logging
from enum import Enum
logger = logging.getLogger(__name__)

class MockBootResult(str, Enum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    ANR = "anr"

class MockAndroid:
    def __init__(self, emulator_id: str):
        self.emulator_id = emulator_id
        self.running = False
        self.current_snapshot = None

    async def boot(self, snapshot_id=None):
        t = random.uniform(2.0, 5.0) if snapshot_id else random.uniform(5.0, 10.0)
        logger.info(f"[{self.emulator_id}] Booting eta={t:.1f}s")
        await asyncio.sleep(t)
        if random.random() < 0.05:
            return MockBootResult.TIMEOUT
        self.running = True
        self.current_snapshot = snapshot_id
        return MockBootResult.SUCCESS

    async def create_snapshot(self, path: str):
        await asyncio.sleep(random.uniform(1.0, 3.0))
        return True

    async def restore_snapshot(self, snapshot_id: str):
        await asyncio.sleep(random.uniform(3.0, 8.0))
        self.current_snapshot = snapshot_id
        self.running = True
        return True

    async def health_check(self):
        await asyncio.sleep(0.3)
        if not self.running:
            return {"healthy": False, "reason": "not_running"}
        if random.random() < 0.03:
            return {"healthy": False, "reason": "anr"}
        return {"healthy": True, "reason": None}

    async def stop(self):
        await asyncio.sleep(0.3)
        self.running = False

    async def destroy(self):
        await self.stop()

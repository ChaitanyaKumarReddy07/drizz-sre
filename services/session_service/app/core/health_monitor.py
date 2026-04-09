import os, asyncio, random, logging
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from app.db import AsyncSessionLocal
from app.models.session import AppSession, SessionHealth, SessionTier, SessionHealthEvent

logger = logging.getLogger(__name__)
HOT_CHECK_INTERVAL_SECONDS = int(os.getenv("HOT_CHECK_INTERVAL_SECONDS", "3600"))
WARM_CHECK_INTERVAL_SECONDS = int(os.getenv("WARM_CHECK_INTERVAL_SECONDS", "21600"))
REBALANCE_INTERVAL_SECONDS = int(os.getenv("REBALANCE_INTERVAL_SECONDS", "21600"))
HOT_FRESHNESS_HOURS = int(os.getenv("HOT_FRESHNESS_HOURS", "24"))
WARM_FRESHNESS_DAYS = int(os.getenv("WARM_FRESHNESS_DAYS", "7"))


class SessionHealthMonitor:
    def __init__(self):
        self._sched = AsyncIOScheduler()

    def start(self):
        self._sched.add_job(self._check_hot, "interval", seconds=HOT_CHECK_INTERVAL_SECONDS, id="hot_check")
        self._sched.add_job(self._check_warm, "interval", seconds=WARM_CHECK_INTERVAL_SECONDS, id="warm_check")
        self._sched.add_job(self._rebalance, "interval", seconds=REBALANCE_INTERVAL_SECONDS, id="rebalance")
        self._sched.start()
        logger.info("Session health monitor started")

    def stop(self):
        self._sched.shutdown(wait=False)

    async def verify_session(self, session_id: str) -> SessionHealth:
        return await self._check_session(session_id)

    async def _check_hot(self):
        await self._check_tier(SessionTier.HOT, timedelta(hours=HOT_FRESHNESS_HOURS))

    async def _check_warm(self):
        await self._check_tier(SessionTier.WARM, timedelta(days=WARM_FRESHNESS_DAYS))

    async def _check_tier(self, tier, interval):
        cutoff = datetime.now(timezone.utc) - interval
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(AppSession.id).where(
                    AppSession.tier == tier,
                    (AppSession.last_verified_at == None) | (AppSession.last_verified_at < cutoff)
                ).limit(50)
            )
            ids = [r[0] for r in result]
        logger.info(f"Tier {tier.value}: checking {len(ids)} sessions")
        await asyncio.gather(*[self._check_session(sid) for sid in ids], return_exceptions=True)

    async def _check_session(self, session_id: str) -> SessionHealth:
        await asyncio.sleep(random.uniform(0.3, 1.0))
        health = SessionHealth.ALIVE if random.random() < 0.8 else SessionHealth.EXPIRED
        async with AsyncSessionLocal() as db:
            session = await db.get(AppSession, session_id)
            if not session:
                return health
            session.health = health
            session.last_verified_at = datetime.now(timezone.utc)
            db.add(SessionHealthEvent(session_id=session_id, health=health, detail={"method": "mock_vision"}))
            await db.commit()
        return health

    async def _rebalance(self):
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(AppSession))
            sessions = result.scalars().all()
            for s in sessions:
                days = (now - s.last_used_at).days if s.last_used_at else 999
                new_tier = SessionTier.HOT if (s.use_count >= 5 and days <= 7) else (SessionTier.COLD if days > 30 else SessionTier.WARM)
                if new_tier != s.tier:
                    logger.info(f"Session {s.id}: {s.tier.value} -> {new_tier.value}")
                    s.tier = new_tier
            await db.commit()

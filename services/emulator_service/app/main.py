from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db import init_db
from app.api.emulators import router as emulator_router
from app.core.pool_manager import PoolManager
from app.core.health_monitor import HealthMonitor
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    pm = PoolManager()
    await pm.initialize()
    hm = HealthMonitor(pm)
    hm.start()
    app.state.pool_manager = pm
    yield
    hm.stop()

app = FastAPI(title="Drizz Emulator Service", lifespan=lifespan)
app.include_router(emulator_router, prefix="/emulators", tags=["emulators"])

@app.get("/health")
async def health():
    return {"status": "ok", "service": "emulator"}

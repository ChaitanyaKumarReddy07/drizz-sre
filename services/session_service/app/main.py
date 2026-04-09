from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db import init_db
from app.api.sessions import router as session_router
from app.core.health_monitor import SessionHealthMonitor
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    mon = SessionHealthMonitor()
    mon.start()
    app.state.health_monitor = mon
    yield
    mon.stop()

app = FastAPI(title="Drizz Session Service", lifespan=lifespan)
app.include_router(session_router, prefix="/users", tags=["sessions"])

@app.get("/health")
async def health():
    return {"status": "ok", "service": "session"}

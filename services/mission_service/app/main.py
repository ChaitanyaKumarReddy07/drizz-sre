from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db import init_db
from app.api.missions import router as mission_router
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="Drizz Mission Service", lifespan=lifespan)
app.include_router(mission_router, prefix="/missions", tags=["missions"])

@app.get("/health")
async def health():
    return {"status": "ok", "service": "mission"}

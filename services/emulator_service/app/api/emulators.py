from fastapi import APIRouter, HTTPException, Request
from app.schemas.emulator import EmulatorProvisionRequest, EmulatorResponse, SnapshotCreateRequest, SnapshotResponse, PoolStatusResponse

router = APIRouter()

def _pool(r): return r.app.state.pool_manager

@router.post("", response_model=EmulatorResponse, status_code=201)
async def provision(body: EmulatorProvisionRequest, request: Request):
    try:
        return await _pool(request).provision(snapshot_id=body.snapshot_id)
    except RuntimeError as e:
        raise HTTPException(503, detail=str(e))

@router.get("/pool/status", response_model=PoolStatusResponse)
async def pool_status(request: Request):
    return await _pool(request).pool_stats()

@router.get("/{emulator_id}", response_model=EmulatorResponse)
async def get_emulator(emulator_id: str, request: Request):
    em = await _pool(request).get_status(emulator_id)
    if not em: raise HTTPException(404, "Not found")
    return em

@router.post("/{emulator_id}/snapshot", response_model=SnapshotResponse, status_code=201)
async def create_snapshot(emulator_id: str, body: SnapshotCreateRequest, request: Request):
    try:
        return await _pool(request).snapshot(emulator_id, body.layer, body.app_id, body.user_id, body.parent_id)
    except ValueError as e:
        raise HTTPException(400, str(e))

@router.post("/{emulator_id}/assign")
async def assign(emulator_id: str, task_id: str, request: Request):
    await _pool(request).mark_assigned(emulator_id, task_id)
    return {"emulator_id": emulator_id, "assigned_to": task_id}

@router.post("/{emulator_id}/release")
async def release(emulator_id: str, request: Request):
    await _pool(request).mark_idle(emulator_id)
    return {"emulator_id": emulator_id, "status": "idle"}

@router.delete("/{emulator_id}", status_code=204)
async def destroy(emulator_id: str, request: Request):
    em = await _pool(request).get_status(emulator_id)
    if not em: raise HTTPException(404, "Not found")
    await _pool(request).destroy(emulator_id)

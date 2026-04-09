from fastapi import FastAPI
app = FastAPI(title="Drizz Mission Service - Coming Soon")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "mission"}

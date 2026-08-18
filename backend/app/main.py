from fastapi import FastAPI
from app.api.chat import router as chat_router
app = FastAPI(title="SmartSupport API", version="0.1.0")
app.include_router(chat_router)

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "smart-support-backend"}

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from config import settings
from config.logging import configure_logging
from .router import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging("model-api")
    app.state.inference_slots = asyncio.Semaphore(settings.OCR_MAX_CONCURRENCY)
    yield


app = FastAPI(title="YOURCOMPANY Digit Detection API", version="1.1.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "model-api"}

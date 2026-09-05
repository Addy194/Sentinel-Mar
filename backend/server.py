import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware

from db import db, client, ensure_indexes
import jobs
import services  # noqa: F401  (registers job handlers)
from routers import ingest, cases, system
from seed import seed_demo
from correlation import ALGORITHM_VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("sentinelmar")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_indexes()
    jobs.start()
    try:
        res = await seed_demo()
        logger.info("seed: %s", res)
    except Exception:
        logger.exception("seed failed")
    yield
    client.close()


app = FastAPI(title="SentinelMar — Oil-Spill Detection & Vessel Correlation", version="0.1.0", lifespan=lifespan)
api = APIRouter(prefix="/api")


@api.get("/")
async def root():
    return {"service": "sentinelmar", "algorithm_version": ALGORITHM_VERSION, "status": "ok"}


@api.post("/seed")
async def reseed():
    return await seed_demo()


api.include_router(ingest.router)
api.include_router(cases.router)
api.include_router(system.router)
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

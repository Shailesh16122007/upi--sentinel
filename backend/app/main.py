import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.graph.network import graph
from app.ml.model import model
from app.seed import ensure_seeded

log = logging.getLogger("sentinel")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    model.load()
    with SessionLocal() as db:
        ensure_seeded(db)
        graph.rebuild(db)
    yield


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan,
              description="UPI Sentinel — reconstruct the transaction, understand the evidence. Evidence-first dispute "
                          "investigation for UPI payments, plus an optional real-time risk-check API.")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["GET", "POST", "PATCH"], allow_headers=["X-API-Key", "Content-Type"])


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("Unhandled error")  # stack trace stays in server logs only
    return JSONResponse(status_code=500, content={"detail": "Internal error. The request was not completed."})


from app.api import cases, misc, transactions  # noqa: E402

app.include_router(transactions.router)
app.include_router(cases.router)
app.include_router(misc.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "model": model.version}

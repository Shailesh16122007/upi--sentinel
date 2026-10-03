import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import SessionLocal, engine
from app.graph.network import graph
from app.migrate import upgrade
from app.ml.model import model
from app.seed import ensure_seeded

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sentinel")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    upgrade(engine)  # additive: creates new tables/columns, never drops data
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    model.load()
    from app.services.accounts import ensure_accounts
    with SessionLocal() as db:
        ensure_seeded(db)
        ensure_accounts(db)
        graph.rebuild(db)
        if settings.seed_demo:
            from app.services.demo_case import seed_background
            try:
                seed_background(db)
            except Exception:  # noqa: BLE001 — demo data must never stop the server
                log.exception("Synthetic background seeding failed")
    from app.api.cases import resume_pending
    n = resume_pending()
    if n:
        log.info("Resumed processing of %d evidence item(s) interrupted by a restart", n)
    yield


app = FastAPI(title=settings.app_name, version="2.0.0", lifespan=lifespan,
              description="UPI Sentinel — from complaint to resolution, one evidence trail. Case management for UPI payment "
                          "disputes across the customer, the bank and the cyber crime authority.")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "X-API-Key", "Content-Type"])


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("Unhandled error")  # stack trace stays in server logs only
    return JSONResponse(status_code=500, content={"detail": "Something went wrong. The request was not completed."})


from app.api import auth, cases, intel, misc, transactions, workflow  # noqa: E402

app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(cases.router)
app.include_router(workflow.router)
app.include_router(intel.router)
app.include_router(misc.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "model": model.version}

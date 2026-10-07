import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.mail_routes import auth_router, router as mail_router
from app.api.swift_routes import process_router, router as swift_router
from app.config.settings import settings
from app.dependencies import processor
from app.services.poller import run_poller


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    task = None
    if settings.poller_enabled:
        task = asyncio.create_task(
            run_poller(processor, settings.poll_interval_seconds, stop)
        )
    try:
        yield
    finally:
        stop.set()
        if task is not None:
            await task


app = FastAPI(
    title="SWIFT Mailbox Monitoring API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mail_router)
app.include_router(auth_router)
app.include_router(swift_router)
app.include_router(process_router)


@app.get("/health")
async def health_check():

    return {
        "status": "UP"
    }

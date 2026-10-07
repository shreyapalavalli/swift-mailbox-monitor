"""Dashboard API consumed by the Flask frontend."""
import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from app.db.repository import SwiftRepository
from app.dependencies import get_processor, get_repository
from app.graph.auth_service import SignInRequiredError
from app.services.processor import SwiftProcessor

router = APIRouter(prefix="/api/swifts", tags=["swifts"])
process_router = APIRouter(prefix="/api/process", tags=["process"])


class SwiftAction(BaseModel):
    reference: str
    graph_message_id: str
    received_at: str | None = None
    format: str | None = None
    message_type: str | None = None
    related_reference: str | None = None
    category: str
    status: str
    priority: str
    sender_bic: str | None = None
    receiver_bic: str | None = None
    currency: str | None = None
    amount: str | None = None
    business_purpose: str | None = None
    narrative: str | None = None
    matched_terms: list[str] = []
    reason: str | None = None
    created_at: str
    updated_at: str

    @field_validator("matched_terms", mode="before")
    @classmethod
    def _decode_terms(cls, v):
        if v is None or v == "":
            return []
        if isinstance(v, str):
            try:
                decoded = json.loads(v)
            except ValueError:
                return []
            return decoded if isinstance(decoded, list) else []
        return v


class StatusUpdate(BaseModel):
    status: Literal["IN_PROGRESS", "RESOLVED"]


def _normalize_since(since: str | None) -> str | None:
    if since is None or since == "":
        return None
    try:
        dt = datetime.fromisoformat(since.strip().replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="since must be an ISO-8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


@router.get("", response_model=list[SwiftAction])
def list_swifts(
    status: str | None = None,
    category: str | None = None,
    since: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    repo: SwiftRepository = Depends(get_repository),
):
    return repo.list_actions(status, category, _normalize_since(since), limit)


@router.get("/alerts", response_model=list[SwiftAction])
def alerts(since: str | None = None, repo: SwiftRepository = Depends(get_repository)):
    return repo.list_actions(status="PRIORITY", since=_normalize_since(since))


@router.get("/metrics")
def metrics(repo: SwiftRepository = Depends(get_repository)):
    return repo.metrics(datetime.now(timezone.utc).strftime("%Y-%m-%d"))


@router.get("/{reference:path}", response_model=SwiftAction)
def get_swift(reference: str, repo: SwiftRepository = Depends(get_repository)):
    row = repo.get_action(reference)
    if row is None:
        raise HTTPException(status_code=404, detail="SWIFT not found")
    return row


@router.patch("/{reference:path}", response_model=SwiftAction)
def update_swift(reference: str, body: StatusUpdate,
                 repo: SwiftRepository = Depends(get_repository)):
    if not repo.update_action_status(reference, body.status):
        raise HTTPException(status_code=404, detail="SWIFT not found")
    return repo.get_action(reference)


@process_router.post("/run")
async def run_process(processor: SwiftProcessor = Depends(get_processor)):
    if processor.is_running:
        raise HTTPException(status_code=409, detail="A processing run is already in progress.")
    try:
        return await processor.run_once()
    except SignInRequiredError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


@process_router.get("/log")
def process_log(limit: int = Query(100, ge=1, le=1000),
                repo: SwiftRepository = Depends(get_repository)):
    return repo.list_processed(limit)

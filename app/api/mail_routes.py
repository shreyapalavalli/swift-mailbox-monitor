import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config.settings import settings
from app.graph.mail_service import GraphMailService
from app.models.email_message import EmailMessage


router = APIRouter(
    prefix="/api/graph",
    tags=["Microsoft Graph"]
)

auth_router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

mail_service = GraphMailService()


def _graph_http_exception(exc: httpx.HTTPStatusError) -> HTTPException:
    status_code = exc.response.status_code

    if status_code == 401:
        detail = (
            "Microsoft Graph rejected the access token. Sign in again at "
            "/auth/login and make sure the app has delegated Mail.ReadWrite "
            "permission with consent."
        )
    elif status_code == 403:
        detail = (
            "Microsoft Graph denied mailbox access. Grant the signed-in "
            "account access to this mailbox and consent to Mail.ReadWrite."
        )
    else:
        detail = "Microsoft Graph request failed."

    return HTTPException(status_code=status_code, detail=detail)


@auth_router.get("/login")
async def login():
    return RedirectResponse(
        mail_service.graph_client.auth_service.get_authorization_url()
    )


async def _complete_auth(request: Request, auth_response: dict):
    try:
        mail_service.graph_client.auth_service.complete_authorization(
            auth_response
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{exc} Open /auth/login to start a new sign-in."
        ) from exc

    return {"authenticated": True}


@auth_router.get("/callback")
async def auth_callback(request: Request):
    return await _complete_auth(
        request,
        dict(request.query_params)
    )


@auth_router.post("/callback")
async def auth_callback_form(request: Request):
    form = await request.form()

    return await _complete_auth(
        request,
        dict(form)
    )


@auth_router.post("/logout")
async def logout():
    mail_service.graph_client.auth_service.logout()
    return {"authenticated": False}


@router.get("/messages", response_model=list[EmailMessage])
async def get_messages():
    try:
        return await mail_service.fetch_messages()
    except httpx.HTTPStatusError as exc:
        raise _graph_http_exception(exc) from exc


@router.get("/messages/unread", response_model=list[EmailMessage])
async def get_unread_messages():
    try:
        return await mail_service.fetch_unread_messages()
    except httpx.HTTPStatusError as exc:
        raise _graph_http_exception(exc) from exc


@router.get("/messages/{message_id}", response_model=EmailMessage)
async def get_message(message_id: str):
    try:
        return await mail_service.fetch_message_by_id(message_id)
    except httpx.HTTPStatusError as exc:
        raise _graph_http_exception(exc) from exc


@router.patch("/messages/{message_id}/read")
async def mark_message_as_read(message_id: str):
    try:
        await mail_service.mark_as_read(message_id)
    except httpx.HTTPStatusError as exc:
        raise _graph_http_exception(exc) from exc

    return {
        "messageId": message_id,
        "action": "MARK_AS_READ",
        "success": True
    }


@router.get("/test-user")
async def test_user():
    return await mail_service.graph_client.get_current_user()
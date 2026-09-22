from fastapi import FastAPI

from app.api.mail_routes import auth_router, router as mail_router


app = FastAPI(
    title="SWIFT Mailbox Monitoring API",
    version="1.0.0"
)


app.include_router(mail_router)
app.include_router(auth_router)


@app.get("/health")
async def health_check():

    return {
        "status": "UP"
    }
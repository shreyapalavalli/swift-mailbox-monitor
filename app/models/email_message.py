from datetime import datetime
from pydantic import BaseModel


class EmailMessage(BaseModel):

    id: str

    subject: str | None = None

    sender: str | None = None

    received_date_time: datetime | None = None

    body: str | None = None

    is_read: bool = False

    has_attachments: bool = False
from datetime import datetime
from typing import Any
from urllib.parse import quote

from app.config.settings import settings
from app.graph.graph_client import GraphClient
from app.models.email_message import EmailMessage


class GraphMailService:

    def __init__(self):
        self.graph_client = GraphClient()

    @staticmethod
    def _mailbox_path() -> str:
        mailbox = settings.swift_mailbox.strip()

        if mailbox.lower() == "me":
            return "me"

        return f"users/{quote(mailbox, safe='')}"

    async def fetch_messages(
        self,
        top: int = 50
    ) -> list[EmailMessage]:

        url = (
            f"{settings.graph_base_url}"
            f"/{self._mailbox_path()}"
            f"/mailFolders/inbox/messages"
        )

        params = {
            "$select": (
                "id,"
                "subject,"
                "from,"
                "receivedDateTime,"
                "body,"
                "isRead,"
                "hasAttachments"
            ),
            "$orderby": "receivedDateTime desc",
            "$top": top,
        }

        messages: list[EmailMessage] = []

        while url:

            response = await self.graph_client.get(
                url,
                params=params
            )

            params = None

            for item in response.get("value", []):

                messages.append(
                    self._map_message(item)
                )

            url = response.get("@odata.nextLink")

        return messages

    async def fetch_unread_messages(
        self,
        top: int = 50
    ) -> list[EmailMessage]:

        url = (
            f"{settings.graph_base_url}"
            f"/{self._mailbox_path()}"
            f"/mailFolders/inbox/messages"
        )

        params = {
            "$filter": "isRead eq false",
            "$select": (
                "id,"
                "subject,"
                "from,"
                "receivedDateTime,"
                "body,"
                "isRead,"
                "hasAttachments"
            ),
            "$orderby": "receivedDateTime desc",
            "$top": top,
        }

        messages: list[EmailMessage] = []

        while url:

            response = await self.graph_client.get(
                url,
                params=params
            )

            params = None

            for item in response.get("value", []):

                messages.append(
                    self._map_message(item)
                )

            url = response.get("@odata.nextLink")

        return messages

    async def fetch_message_by_id(
        self,
        message_id: str
    ) -> EmailMessage:

        url = (
            f"{settings.graph_base_url}"
            f"/{self._mailbox_path()}"
            f"/messages/{message_id}"
        )

        params = {
            "$select": (
                "id,"
                "subject,"
                "from,"
                "receivedDateTime,"
                "body,"
                "isRead,"
                "hasAttachments"
            )
        }

        response = await self.graph_client.get(
            url,
            params=params
        )

        return self._map_message(response)

    async def mark_as_read(
        self,
        message_id: str
    ) -> None:

        url = (
            f"{settings.graph_base_url}"
            f"/{self._mailbox_path()}"
            f"/messages/{message_id}"
        )

        await self.graph_client.patch(
            url,
            {
                "isRead": True
            }
        )

    def _map_message(
        self,
        message: dict[str, Any]
    ) -> EmailMessage:

        sender = self._extract_sender(message)

        body = self._extract_body(message)

        received_date_time = None

        if message.get("receivedDateTime"):

            received_date_time = datetime.fromisoformat(
                message["receivedDateTime"].replace(
                    "Z",
                    "+00:00"
                )
            )

        return EmailMessage(
            id=message["id"],
            subject=message.get("subject"),
            sender=sender,
            received_date_time=received_date_time,
            body=body,
            is_read=message.get(
                "isRead",
                False
            ),
            has_attachments=message.get(
                "hasAttachments",
                False
            ),
        )

    @staticmethod
    def _extract_sender(
        message: dict[str, Any]
    ) -> str | None:

        from_data = message.get("from")

        if not from_data:
            return None

        email_address = from_data.get(
            "emailAddress"
        )

        if not email_address:
            return None

        return email_address.get("address")

    @staticmethod
    def _extract_body(
        message: dict[str, Any]
    ) -> str | None:

        body_data = message.get("body")

        if not body_data:
            return None

        return body_data.get("content")
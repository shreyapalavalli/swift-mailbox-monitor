from datetime import datetime
from typing import Any
from urllib.parse import quote

from app.config.settings import settings
from app.graph.graph_client import GraphClient
from app.models.email_message import EmailMessage


PREFER_TEXT_BODY = {"Prefer": 'outlook.body-content-type="text"'}


class GraphMailService:

    def __init__(self, graph_client: GraphClient | None = None):
        self.graph_client = graph_client or GraphClient()

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
                params=params,
                headers=PREFER_TEXT_BODY
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
        folder: str = "inbox",
        top: int = 50
    ) -> list[EmailMessage]:

        url = (
            f"{settings.graph_base_url}"
            f"/{self._mailbox_path()}"
            f"/mailFolders/{quote(folder, safe='')}/messages"
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
            # No $orderby: combined with this $filter, Graph can reject the query as
            # InefficientFilter (400). Sorted client-side below instead.
            "$top": top,
        }

        messages: list[EmailMessage] = []

        while url:

            response = await self.graph_client.get(
                url,
                params=params,
                headers=PREFER_TEXT_BODY
            )

            params = None

            for item in response.get("value", []):

                message = self._map_message(item)
                message.folder = folder
                messages.append(message)

            url = response.get("@odata.nextLink")

        # Newest first; messages without a received time last.
        messages.sort(
            key=lambda m: (
                m.received_date_time is not None,
                m.received_date_time.timestamp() if m.received_date_time else 0.0,
            ),
            reverse=True,
        )

        return messages

    async def fetch_message_by_id(
        self,
        message_id: str
    ) -> EmailMessage:

        url = (
            f"{settings.graph_base_url}"
            f"/{self._mailbox_path()}"
            f"/messages/{quote(message_id, safe='')}"
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
            params=params,
            headers=PREFER_TEXT_BODY
        )

        return self._map_message(response)

    async def mark_as_read(
        self,
        message_id: str
    ) -> None:

        url = (
            f"{settings.graph_base_url}"
            f"/{self._mailbox_path()}"
            f"/messages/{quote(message_id, safe='')}"
        )

        await self.graph_client.patch(
            url,
            {
                "isRead": True
            }
        )

    async def forward_message(
        self,
        message_id: str,
        to_address: str,
        comment: str
    ) -> None:

        await self.graph_client.post(
            self._message_action_url(message_id, "forward"),
            {
                "comment": comment,
                "toRecipients": [
                    {"emailAddress": {"address": to_address}}
                ],
            }
        )

    async def reply_all(
        self,
        message_id: str,
        comment: str
    ) -> None:

        await self.graph_client.post(
            self._message_action_url(message_id, "replyAll"),
            {"comment": comment}
        )

    def _message_action_url(
        self,
        message_id: str,
        action: str
    ) -> str:

        return (
            f"{settings.graph_base_url}"
            f"/{self._mailbox_path()}"
            f"/messages/{quote(message_id, safe='')}/{action}"
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
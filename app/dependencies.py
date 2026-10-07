"""Process-wide singletons shared by the API routes, the poller and the CLI."""
from app.config.settings import settings
from app.db.repository import SwiftRepository
from app.graph.auth_service import GraphAuthService
from app.graph.graph_client import GraphClient
from app.graph.mail_service import GraphMailService
from app.services.processor import SwiftProcessor

auth_service = GraphAuthService()
graph_client = GraphClient(auth_service=auth_service)
mail_service = GraphMailService(graph_client=graph_client)
repository = SwiftRepository(settings.database_path)
processor = SwiftProcessor(
    mail_service,
    repository,
    settings.poll_folder_list,
    settings.cst_mailbox,
    settings.cancellation_action_mx_type_list,
)


def get_repository() -> SwiftRepository:
    return repository


def get_processor() -> SwiftProcessor:
    return processor

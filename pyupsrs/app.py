"""Main application entry point for the pyupsrs server."""

import logging
import os
import sys

# from pathlib import Path
import click
import falcon.asgi

# import uvicorn
from falcon.asgi import App
from uvicorn.main import main as uvicorn_main

from pyupsrs.api.middleware.auth import AuthMiddleware
from pyupsrs.api.middleware.logging import LoggingMiddleware
from pyupsrs.api.resources.subscriptions import SubscriptionResource, SubscriptionSuspendResource
from pyupsrs.api.resources.websocket_resource import WebSocketResource
from pyupsrs.api.resources.workitems import DICOMJSONHandler, WorkItemResource, WorkItemsResource, WorkItemStateResource
from pyupsrs.config import get_config
from pyupsrs.domain.services.service_provider import ServiceProvider
from pyupsrs.utils.class_logger import configure_logging


def create_app() -> App:
    """Create and configure the Falcon application."""
    # Get configuration
    config = get_config()

    # Initialize middleware
    middleware = [
        LoggingMiddleware(),
    ]

    # Add authentication middleware if enabled
    if config.auth_enabled:
        middleware.append(AuthMiddleware())

    # Create the Falcon application
    app = falcon.asgi.App(middleware=middleware)

    # Get shared services
    service_provider = ServiceProvider.get_instance()

    # Register media handlers

    app.req_options.media_handlers.update(
        {
            "application/dicom+json": DICOMJSONHandler(),
        }
    )
    app.resp_options.media_handlers.update(
        {
            "application/dicom+json": DICOMJSONHandler(),
        }
    )

    # Initialize resources with shared services
    subscription_resource = SubscriptionResource(subscription_service=service_provider.subscription_service)
    subscription_suspend_resource = SubscriptionSuspendResource(subscription_service=service_provider.subscription_service)
    workitem_resource = WorkItemResource(workitem_service=service_provider.workitem_service)
    workitem_state_resource = WorkItemStateResource(workitem_service=service_provider.workitem_service)
    workitems_resource = WorkItemsResource(workitem_service=service_provider.workitem_service)
    websocket_resource = WebSocketResource(connection_manager=service_provider.connection_manager)

    # Register routes
    # the same variable name has to be used in routes that are children of the same parent.
    # so workitem_uid for subscribers is necessary, and needs to be interpreted as
    # a resource ID (well known UIDs for Global and Filtered )
    app.add_route("/workitems/1.2.840.10008.5.1.4.34.5/subscribers/{aetitle}/suspend", subscription_suspend_resource)
    app.add_route("/workitems/1.2.840.10008.5.1.4.34.5.1/subscribers/{aetitle}/suspend", subscription_suspend_resource)
    app.add_route("/workitems/{workitem_uid}/subscribers/{aetitle}", subscription_resource)
    app.add_route("/workitems/{workitem_uid}/state", workitem_state_resource)
    app.add_route("/workitems/{workitem_uid}/cancelrequest", workitem_resource)
    app.add_route("/workitems/{workitem_uid}", workitem_resource)
    app.add_route("/workitems", workitems_resource)

    # Register WebSocket route
    app.add_route("/ws/subscribers/{subscriber_id}", websocket_resource)

    return app


# Create a custom Click command that extends Uvicorn's CLI
@click.command(add_help_option=False, context_settings={"ignore_unknown_options": True})
@click.option(
    "--database-uri",
    help="Database connection URI. [default: sqlite:///ups.db]",
    default=None,
)
@click.option(
    "--auth/--no-auth",
    help="Enable or disable authentication. [default: enabled]",
    default=None,
)
@click.argument("uvicorn_args", nargs=-1, type=click.UNPROCESSED)
def main(
    database_uri: str | None,
    auth: bool | None,
    uvicorn_args: tuple[str, ...],
) -> None:
    """
    DICOM UPS-RS server implementation.

    This command wraps Uvicorn and accepts all Uvicorn CLI options.
    Run with --help to see all available options.
    """
    # Get base configuration
    config = get_config()
    configure_logging(level=logging.getLevelNamesMapping()[str(config.log_level).upper()])
    # Update with command-line arguments if provided
    if database_uri is not None:
        os.environ["PYUPSRS_DATABASE_URI"] = database_uri
    if auth is not None:
        os.environ["PYUPSRS_AUTH_ENABLED"] = str(auth).lower()

    # Setup args for Uvicorn
    app_import = "pyupsrs.app:create_app"
    uvicorn_args = ["uvicorn", app_import] + list(uvicorn_args)

    # If --help is in args, add our custom options to Uvicorn's help
    if "--help" in uvicorn_args:
        sys.argv = ["uvicorn", "--help"]
        try:
            uvicorn_main()
        except SystemExit:
            pass

        click.echo("\nPyUPSRS specific options:")
        click.echo("  --database-uri TEXT     Database connection URI. [default: sqlite:///ups.db]")
        click.echo("  --auth / --no-auth      Enable or disable authentication. [default: disabled]")
        sys.exit(0)

    # Run Uvicorn with our args
    sys.argv = uvicorn_args
    uvicorn_main()


if __name__ == "__main__":
    main()

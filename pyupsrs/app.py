"""Main application entry point for the pyupsrs server."""

import os
import sys
from pathlib import Path
from typing import Optional

import click
import falcon.asgi
import uvicorn
from falcon.asgi import App
from uvicorn.main import main as uvicorn_main

from pyupsrs.api.middleware.auth import AuthMiddleware
from pyupsrs.api.middleware.logging import LoggingMiddleware
from pyupsrs.api.resources.subscriptions import SubscriptionResource, SubscriptionsResource
from pyupsrs.api.resources.workitems import DICOMJSONHandler, WorkItemResource, WorkItemsResource
from pyupsrs.config import get_config


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

    # Register routes
    app.add_route("/workitems", WorkItemsResource())
    app.add_route("/workitems/{workitem_uid}", WorkItemResource())
    app.add_route("/workitems/{workitem_uid}/subscribers", SubscriptionsResource())
    app.add_route("/workitems/{workitem_uid}/subscribers/{subscriber_uid}", SubscriptionResource())

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
    database_uri: Optional[str],
    auth: Optional[bool],
    uvicorn_args: tuple[str, ...],
) -> None:
    """
    DICOM UPS-RS server implementation.

    This command wraps Uvicorn and accepts all Uvicorn CLI options.
    Run with --help to see all available options.
    """
    # Get base configuration
    config = get_config()

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

"""Main application entry point for the pyupsrs server."""

import falcon
import uvicorn
from falcon import App

from pyupsrs.api.middleware.auth import AuthMiddleware
from pyupsrs.api.middleware.logging import LoggingMiddleware
from pyupsrs.api.resources.subscriptions import SubscriptionResource, SubscriptionsResource
from pyupsrs.api.resources.workitems import WorkItemResource, WorkItemsResource
from pyupsrs.config import get_config


def create_app() -> App:
    """Create and configure the Falcon application."""
    # Initialize middleware
    middleware = [
        AuthMiddleware(),
        LoggingMiddleware(),
    ]

    # Create the Falcon application
    app = falcon.App(middleware=middleware)

    # Register routes
    app.add_route("/workitems", WorkItemsResource())
    app.add_route("/workitems/{workitem_uid}", WorkItemResource())
    app.add_route("/workitems/{workitem_uid}/subscribers", SubscriptionsResource())
    app.add_route("/workitems/{workitem_uid}/subscribers/{subscriber_uid}", SubscriptionResource())

    return app


def main() -> None:
    """Run the application server."""
    config = get_config()
    app = create_app()

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        reload=config.debug,
        log_level="debug" if config.debug else "info",
        ws_host=config.ws_host,
        ws_port=config.ws_port,
    )


if __name__ == "__main__":
    main()

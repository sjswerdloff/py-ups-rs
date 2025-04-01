"""Logging middleware for the Falcon application."""

import logging
import time
from typing import Optional

import falcon


class LoggingMiddleware:
    """Middleware for request/response logging."""

    def __init__(self) -> None:
        """Initialize the logging middleware."""
        self.logger = logging.getLogger("pyupsrs.api")

    async def process_request(self, req: falcon.Request, resp: falcon.Response) -> None:
        """
        Process the request before routing it.

        Args:
            req: The HTTP request.
            resp: The HTTP response.

        """
        req.context.start_time = time.time()
        self.logger.info(f"Request: {req.method} {req.path}")

    async def process_response(
        self, req: falcon.Request, resp: falcon.Response, resource: Optional[object], req_succeeded: bool
    ) -> None:
        """
        Process the response after routing.

        Args:
            req: The HTTP request.
            resp: The HTTP response.
            resource: The resource object.
            req_succeeded: Whether the request succeeded.

        """
        duration = time.time() - req.context.start_time
        self.logger.info(f"Response: {req.method} {req.path} -> {resp.status} ({duration:.3f}s)")

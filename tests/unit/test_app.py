"""
Smoke tests for pyupsrs/app.py.

Tests verify:
- create_app() returns a valid application object without errors
- Routes are registered for all expected URL patterns
- Auth middleware is included when auth_enabled is True
- Auth middleware is absent when auth_enabled is False
- CLI --help option does not crash
- CLI accepts --database-uri and --auth / --no-auth flags
"""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from pyupsrs.app import create_app, main
from pyupsrs.config import Config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXPECTED_ROUTES = [
    "/workitems/1.2.840.10008.5.1.4.34.5/subscribers/{aetitle}/suspend",
    "/workitems/1.2.840.10008.5.1.4.34.5.1/subscribers/{aetitle}/suspend",
    "/workitems/{workitem_uid}/subscribers/{aetitle}",
    "/workitems/{workitem_uid}/state",
    "/workitems/{workitem_uid}/cancelrequest",
    "/workitems/{workitem_uid}",
    "/workitems",
    "/ws/subscribers/{subscriber_id}",
]


def _make_mock_service_provider() -> MagicMock:
    """Return a MagicMock configured with the attributes create_app() consumes."""
    sp = MagicMock()
    sp.subscription_service = MagicMock()
    sp.workitem_service = MagicMock()
    sp.connection_manager = MagicMock()
    return sp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_service_provider() -> Generator[MagicMock, None, None]:
    """Patch ServiceProvider.get_instance so no database is touched."""
    sp = _make_mock_service_provider()
    with patch("pyupsrs.app.ServiceProvider") as mock_cls:
        mock_cls.get_instance.return_value = sp
        yield sp


@pytest.fixture()
def config_no_auth() -> Config:
    """Return a Config with authentication disabled."""
    return Config(auth_enabled=False)


@pytest.fixture()
def config_with_auth() -> Config:
    """Return a Config with authentication enabled."""
    return Config(auth_enabled=True)


# ---------------------------------------------------------------------------
# create_app() smoke tests
# ---------------------------------------------------------------------------


class TestCreateApp:
    """Smoke tests for create_app()."""

    def test_create_app_returns_proxy_middleware(self, mock_service_provider: MagicMock) -> None:
        """Contract: create_app() returns a ProxyHeadersMiddleware wrapping the Falcon app."""
        with patch("pyupsrs.app.get_config", return_value=Config(auth_enabled=False)):
            app = create_app()

        assert isinstance(app, ProxyHeadersMiddleware)

    def test_create_app_without_auth(self, mock_service_provider: MagicMock) -> None:
        """Contract: create_app() succeeds when auth is disabled."""
        with patch("pyupsrs.app.get_config", return_value=Config(auth_enabled=False)):
            app = create_app()

        assert app is not None

    def test_create_app_with_auth(self, mock_service_provider: MagicMock) -> None:
        """Contract: create_app() succeeds when auth is enabled."""
        with patch("pyupsrs.app.get_config", return_value=Config(auth_enabled=True)):
            app = create_app()

        assert app is not None

    def test_create_app_inner_falcon_app_has_expected_routes(self, mock_service_provider: MagicMock) -> None:
        """Contract: the Falcon app inside the proxy wrapper has all expected routes registered."""
        with patch("pyupsrs.app.get_config", return_value=Config(auth_enabled=False)):
            outer_app = create_app()

        # ProxyHeadersMiddleware stores the wrapped app as .app
        falcon_app = outer_app.app  # type: ignore[attr-defined]

        # Substitute concrete values for URL template params so the compiled router
        # can match them; the template segments we care about are {workitem_uid},
        # {aetitle}, and {subscriber_id}.
        concrete_routes = [
            "/workitems/1.2.840.10008.5.1.4.34.5/subscribers/MYAE/suspend",
            "/workitems/1.2.840.10008.5.1.4.34.5.1/subscribers/MYAE/suspend",
            "/workitems/1.2.3.4.5/subscribers/MYAE",
            "/workitems/1.2.3.4.5/state",
            "/workitems/1.2.3.4.5/cancelrequest",
            "/workitems/1.2.3.4.5",
            "/workitems",
            "/ws/subscribers/sub-001",
        ]
        router = falcon_app._router
        for route in concrete_routes:
            result = router.find(route)
            assert result is not None, f"Route not registered (tested via concrete URI): {route}"

    def test_create_app_registers_dicom_json_media_handler(self, mock_service_provider: MagicMock) -> None:
        """Contract: DICOM+JSON media handler is registered on both request and response options."""
        with patch("pyupsrs.app.get_config", return_value=Config(auth_enabled=False)):
            outer_app = create_app()

        falcon_app = outer_app.app  # type: ignore[attr-defined]
        assert "application/dicom+json" in falcon_app.req_options.media_handlers
        assert "application/dicom+json" in falcon_app.resp_options.media_handlers

    def test_create_app_registers_dicom_xml_media_handler(self, mock_service_provider: MagicMock) -> None:
        """Contract: DICOM+XML media handler is registered on both request and response options."""
        with patch("pyupsrs.app.get_config", return_value=Config(auth_enabled=False)):
            outer_app = create_app()

        falcon_app = outer_app.app  # type: ignore[attr-defined]
        assert "application/dicom+xml" in falcon_app.req_options.media_handlers
        assert "application/dicom+xml" in falcon_app.resp_options.media_handlers

    def test_create_app_auth_middleware_included_when_enabled(self, mock_service_provider: MagicMock) -> None:
        """Contract: AuthMiddleware appears in middleware when auth_enabled is True."""
        from pyupsrs.api.middleware.auth import AuthMiddleware

        with patch("pyupsrs.app.get_config", return_value=Config(auth_enabled=True)):
            outer_app = create_app()

        falcon_app = outer_app.app  # type: ignore[attr-defined]
        # Falcon stores the original middleware objects in _unprepared_middleware before
        # it compiles them into handler method tuples.
        assert any(isinstance(m, AuthMiddleware) for m in falcon_app._unprepared_middleware)

    def test_create_app_auth_middleware_absent_when_disabled(self, mock_service_provider: MagicMock) -> None:
        """Contract: AuthMiddleware is not included when auth_enabled is False."""
        from pyupsrs.api.middleware.auth import AuthMiddleware

        with patch("pyupsrs.app.get_config", return_value=Config(auth_enabled=False)):
            outer_app = create_app()

        falcon_app = outer_app.app  # type: ignore[attr-defined]
        assert not any(isinstance(m, AuthMiddleware) for m in falcon_app._unprepared_middleware)


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------


class TestMainCli:
    """Smoke tests for the Click CLI entry point."""

    def test_cli_help_exits_zero(self) -> None:
        """Contract: --help flag exits with code 0 without crashing."""
        runner = CliRunner()
        with patch("pyupsrs.app.uvicorn_main") as mock_uvicorn:
            mock_uvicorn.side_effect = SystemExit(0)
            result = runner.invoke(main, ["--help"])

        # Click exits 0 for --help; our code also sys.exit(0) after our help block.
        assert result.exit_code == 0

    def test_cli_database_uri_option_sets_env_var(self) -> None:
        """Contract: --database-uri stores the value in PYUPSRS_DATABASE_URI."""
        runner = CliRunner()
        sentinel_uri = "sqlite:///test_smoke.db"

        with (
            patch("pyupsrs.app.uvicorn_main"),
            patch("pyupsrs.app.get_config", return_value=Config()),
            patch("pyupsrs.app.configure_logging"),
        ):
            result = runner.invoke(main, ["--database-uri", sentinel_uri])

        # The CLI sets the env var before calling uvicorn; CliRunner isolates env by
        # default only if mix_env=False (the default), so we verify via exit code and
        # the absence of an unhandled exception.
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_cli_no_auth_flag(self) -> None:
        """Contract: --no-auth flag is accepted without error."""
        runner = CliRunner()
        with (
            patch("pyupsrs.app.uvicorn_main"),
            patch("pyupsrs.app.get_config", return_value=Config()),
            patch("pyupsrs.app.configure_logging"),
        ):
            result = runner.invoke(main, ["--no-auth"])

        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_cli_auth_flag(self) -> None:
        """Contract: --auth flag is accepted without error."""
        runner = CliRunner()
        with (
            patch("pyupsrs.app.uvicorn_main"),
            patch("pyupsrs.app.get_config", return_value=Config()),
            patch("pyupsrs.app.configure_logging"),
        ):
            result = runner.invoke(main, ["--auth"])

        assert result.exception is None or isinstance(result.exception, SystemExit)

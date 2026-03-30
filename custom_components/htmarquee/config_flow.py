"""Config flow for htMarquee."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .api import HtMarqueeApi, HtMarqueeApiError, HtMarqueeAuthError
from .const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_TOKEN, CONF_USE_SSL, CONF_USERNAME, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _parse_host_input(host_input: str) -> tuple[str, int | None, bool | None]:
    """Extract hostname, port, and ssl preference from user input.

    Handles bare hostnames/IPs, and full URLs like https://myhost:443/path.
    Returns (hostname, port_or_None, use_ssl_or_None).
    """
    host_input = host_input.strip().rstrip("/")

    # If it looks like a URL (has a scheme), parse it
    if "://" in host_input:
        parsed = urlparse(host_input)
        hostname = parsed.hostname or host_input
        port = parsed.port  # None if not specified
        use_ssl = True if parsed.scheme == "https" else (False if parsed.scheme == "http" else None)
        return hostname, port, use_ssl

    # Handle host:port without a scheme (e.g. "myhost:8443")
    if ":" in host_input:
        parts = host_input.rsplit(":", 1)
        try:
            port = int(parts[1])
            return parts[0], port, None
        except ValueError:
            pass

    return host_input, None, None

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default="htmarquee.local"): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_USE_SSL, default=True): bool,
    }
)

STEP_AUTH_PASSWORD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME, default="admin"): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_AUTH_PIN_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): str,
    }
)


class HtMarqueeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for htMarquee."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str = ""
        self._port: int = DEFAULT_PORT
        self._use_ssl: bool = True
        self._auth_mode: str = "password"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial host/port step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            hostname, parsed_port, parsed_ssl = _parse_host_input(user_input[CONF_HOST])
            self._host = hostname
            self._port = parsed_port if parsed_port is not None else user_input[CONF_PORT]
            self._use_ssl = parsed_ssl if parsed_ssl is not None else user_input[CONF_USE_SSL]

            api = HtMarqueeApi(self._host, self._port, self._use_ssl)
            try:
                await api.async_get_health()
            except HtMarqueeApiError:
                errors["base"] = "cannot_connect"
            else:
                # Check if auth is required
                try:
                    auth_status = await api.async_get_auth_status()
                    auth_enabled = auth_status.get("auth_mode", "none") != "none"
                except HtMarqueeApiError:
                    auth_enabled = False

                if auth_enabled:
                    self._auth_mode = auth_status.get("auth_mode", "password")
                    await api.close()
                    return await self.async_step_auth()

                # No auth — create entry directly
                await api.close()
                await self.async_set_unique_id(f"htmarquee_{self._host}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"htMarquee ({self._host})",
                    data={
                        CONF_HOST: self._host,
                        CONF_PORT: self._port,
                        CONF_USE_SSL: self._use_ssl,
                    },
                )
            finally:
                await api.close()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle authentication step."""
        errors: dict[str, str] = {}
        is_pin = self._auth_mode == "pin"

        if user_input is not None:
            username = user_input.get(CONF_USERNAME, "admin")
            api = HtMarqueeApi(self._host, self._port, self._use_ssl)
            try:
                token = await api.async_login(
                    username,
                    user_input[CONF_PASSWORD],
                )
            except HtMarqueeAuthError:
                errors["base"] = "invalid_auth"
            except HtMarqueeApiError:
                errors["base"] = "cannot_connect"
            else:
                await api.close()
                await self.async_set_unique_id(f"htmarquee_{self._host}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"htMarquee ({self._host})",
                    data={
                        CONF_HOST: self._host,
                        CONF_PORT: self._port,
                        CONF_USE_SSL: self._use_ssl,
                        CONF_TOKEN: token,
                    },
                )
            finally:
                await api.close()

        schema = STEP_AUTH_PIN_SCHEMA if is_pin else STEP_AUTH_PASSWORD_SCHEMA
        step_id = "auth_pin" if is_pin else "auth"
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=errors,
        )

    async def async_step_auth_pin(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle PIN authentication (delegates to async_step_auth)."""
        return await self.async_step_auth(user_input)


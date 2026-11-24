"""Config flow for htMarquee."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .api import HtMarqueeApi, HtMarqueeApiError, HtMarqueeAuthError
from .const import (
    API_TOKEN_PREFIX,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_TOKEN,
    CONF_USE_SSL,
    CONF_USERNAME,
    DEFAULT_PORT,
    DOMAIN,
)

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

STEP_API_TOKEN_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TOKEN): str,
    }
)


def uses_api_token(entry_data: Mapping[str, Any]) -> bool:
    """True when a config entry signs in with an API token rather than a password.

    A token-based entry stores only the token. A password-based entry also
    stores a token (the last login session), so the password's absence plus
    the reserved prefix is what tells them apart.
    """
    token = entry_data.get(CONF_TOKEN) or ""
    return not entry_data.get(CONF_PASSWORD) and token.startswith(API_TOKEN_PREFIX)


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
            except HtMarqueeApiError as err:
                _LOGGER.error("Failed to connect to htMarquee at %s:%s (ssl=%s): %s", self._host, self._port, self._use_ssl, err)
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
                    return await self.async_step_auth_method()

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

    async def async_step_auth_method(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose how Home Assistant signs in.

        An API token (htMarquee 1.6.0+, Premiere) is the better choice: it
        can be revoked on its own and Home Assistant never stores the admin
        password. The password/PIN path stays for older firmware and Matinee.
        The menu options are step ids; the second one depends on the
        device's auth mode so the next form asks for the right thing.
        """
        return self.async_show_menu(
            step_id="auth_method",
            menu_options=["api_token", "auth_pin" if self._auth_mode == "pin" else "auth"],
        )

    async def _async_check_api_token(self, token: str) -> str | None:
        """Try a pasted API token against the device. Returns an error key, or None if it works."""
        if not token.startswith(API_TOKEN_PREFIX):
            # Catches a pasted password or a truncated copy before a network
            # round trip, with a message that says what a token looks like.
            return "invalid_token_format"
        api = HtMarqueeApi(self._host, self._port, self._use_ssl, token=token)
        try:
            await api.async_validate_token()
        except HtMarqueeAuthError:
            return "invalid_token"
        except HtMarqueeApiError:
            return "cannot_connect"
        finally:
            await api.close()
        return None

    async def async_step_api_token(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in with an API token created in htMarquee (Settings → Integrations)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            error = await self._async_check_api_token(token)
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(f"htmarquee_{self._host}")
                self._abort_if_unique_id_configured()
                # No username or password is stored: that is the point.
                return self.async_create_entry(
                    title=f"htMarquee ({self._host})",
                    data={
                        CONF_HOST: self._host,
                        CONF_PORT: self._port,
                        CONF_USE_SSL: self._use_ssl,
                        CONF_TOKEN: token,
                    },
                )

        return self.async_show_form(
            step_id="api_token",
            data_schema=STEP_API_TOKEN_SCHEMA,
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
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
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

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Credentials stopped working — ask for them again.

        Reached when the coordinator raises ConfigEntryAuthFailed, which
        happens after the device's admin password or PIN is changed (that
        invalidates every existing token). Without this the integration would
        just retry a dead credential forever.
        """
        self._host = entry_data[CONF_HOST]
        self._port = entry_data[CONF_PORT]
        self._use_ssl = entry_data.get(CONF_USE_SSL, True)

        # Re-probe rather than assume: the device can be switched between
        # password and PIN mode, and that is one reason the old token died.
        api = HtMarqueeApi(self._host, self._port, self._use_ssl)
        try:
            auth_status = await api.async_get_auth_status()
            self._auth_mode = auth_status.get("auth_mode", "password")
        except HtMarqueeApiError:
            self._auth_mode = "password"
        finally:
            await api.close()

        # An entry that signs in with an API token has no password to ask
        # for: the token was revoked or expired, so ask for a new token.
        if uses_api_token(entry_data):
            return await self.async_step_reauth_api_token()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_api_token(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect and verify a replacement API token."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None

        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            error = await self._async_check_api_token(token)
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_TOKEN: token}
                )

        return self.async_show_form(
            step_id="reauth_api_token",
            data_schema=STEP_API_TOKEN_SCHEMA,
            errors=errors,
            description_placeholders={"host": self._host},
        )

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect and verify replacement credentials."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None

        if user_input is not None:
            username = user_input.get(CONF_USERNAME, "admin")
            api = HtMarqueeApi(self._host, self._port, self._use_ssl)
            try:
                token = await api.async_login(username, user_input[CONF_PASSWORD])
            except HtMarqueeAuthError:
                errors["base"] = "invalid_auth"
            except HtMarqueeApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        **entry.data,
                        CONF_TOKEN: token,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
            finally:
                await api.close()

        schema = (
            STEP_AUTH_PIN_SCHEMA if self._auth_mode == "pin" else STEP_AUTH_PASSWORD_SCHEMA
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"host": self._host},
        )


"""Token refresh manager for the Aula integration."""

from __future__ import annotations

import asyncio
import copy
import ssl
import time
from typing import TYPE_CHECKING, Any

import httpx
from aula import AulaAuthenticationError, TokenStorage, create_client
from aula.auth.exceptions import MitIDAuthError
from aula.auth.mitid_client import MitIDAuthClient
from aula.http_httpx import HttpxHttpClient

from .const import CONF_TOKEN_DATA, LOGGER, REJECTION_REBUILD_COOLDOWN

if TYPE_CHECKING:
    from aula import AulaApiClient
    from homeassistant.core import HomeAssistant

    from .data import AulaConfigEntry

_NO_REFRESH_TOKEN_MSG = "No refresh token available"  # noqa: S105


class AulaConfigEntryTokenStorage(TokenStorage):
    """
    Store the tokens the aula package refreshes by itself in the config entry.

    ``create_client`` must get a copy of the stored token data: the package
    rewrites the dict it is given on every refresh, and saves it through here.
    """

    def __init__(self, hass: HomeAssistant, entry: AulaConfigEntry) -> None:
        """Initialize the storage."""
        self._hass = hass
        self._entry = entry

    async def load(self) -> dict[str, Any] | None:
        """Return a copy of the stored token data."""
        return copy.deepcopy(self._entry.data.get(CONF_TOKEN_DATA))

    async def save(self, data: dict[str, Any]) -> None:
        """Persist a copy of the token data the package refreshed."""
        self._hass.config_entries.async_update_entry(
            self._entry,
            data={**self._entry.data, CONF_TOKEN_DATA: copy.deepcopy(data)},
        )


class AulaTokenManager:
    """Manages token refresh for the Aula integration."""

    def __init__(self, hass: HomeAssistant, entry: AulaConfigEntry) -> None:
        """Initialize the token manager."""
        self._hass = hass
        self._entry = entry
        self._lock = asyncio.Lock()
        self._last_rejection_rebuild: float | None = None
        self.token_storage = AulaConfigEntryTokenStorage(hass, entry)

    async def async_refresh_token(self) -> tuple[AulaApiClient, dict[str, Any]]:
        """Refresh token and return a new client for setup-time use."""
        async with self._lock:
            token_data = self._entry.data[CONF_TOKEN_DATA]
            refresh_token = token_data.get("tokens", {}).get("refresh_token")
            if not refresh_token:
                raise AulaAuthenticationError(_NO_REFRESH_TOKEN_MSG, 0)

            new_token_data = await self._async_do_refresh(token_data, refresh_token)
            self._async_persist_token_data(new_token_data)
            client = await self._async_create_client(new_token_data)
            return client, new_token_data

    async def async_refresh_and_rebuild_client(
        self, failed_client: AulaApiClient
    ) -> AulaApiClient:
        """
        Refresh the token, rebuild the client, and update all coordinators.

        ``failed_client`` is the client the caller's request failed on. When
        another caller has already replaced it, the current client is returned
        without a second refresh.
        """
        async with self._lock:
            current = self._entry.runtime_data.client
            if current is not failed_client:
                return current
            return await self._async_rebuild(current)

    async def async_rebuild_after_rejection(self, failed_client: AulaApiClient) -> bool:
        """
        Rebuild the client after Aula refused a request as unauthorized.

        Aula has refused every call on a session the aula package had just
        refreshed by itself, until a new client was built. Returns whether the
        caller now has a new client. A rebuild happens at most once per
        REJECTION_REBUILD_COOLDOWN, so a refusal a new session does not fix
        is not rebuilt on every poll.
        """
        async with self._lock:
            current = self._entry.runtime_data.client
            if current is not failed_client:
                return True
            now = time.monotonic()
            if (
                self._last_rejection_rebuild is not None
                and now - self._last_rejection_rebuild < REJECTION_REBUILD_COOLDOWN
            ):
                return False
            self._last_rejection_rebuild = now
            LOGGER.warning("Aula refused the session, building a new one")
            await self._async_rebuild(current)
            return True

    async def _async_rebuild(self, old_client: AulaApiClient) -> AulaApiClient:
        """Refresh the token and swap a new client in for ``old_client``."""
        token_data = self._entry.data[CONF_TOKEN_DATA]
        refresh_token = token_data.get("tokens", {}).get("refresh_token")
        if not refresh_token:
            raise AulaAuthenticationError(_NO_REFRESH_TOKEN_MSG, 0)

        new_token_data = await self._async_do_refresh(token_data, refresh_token)
        self._async_persist_token_data(new_token_data)

        new_client = await self._async_create_client(new_token_data)

        self._entry.runtime_data.client = new_client
        self._update_coordinator_clients(new_client)

        await old_client.close()

        return new_client

    async def _async_do_refresh(
        self, token_data: dict[str, Any], refresh_token: str
    ) -> dict[str, Any]:
        """Perform the actual token refresh via MitIDAuthClient."""
        ssl_context = await self._hass.async_add_executor_job(
            ssl.create_default_context,
        )
        httpx_client = httpx.AsyncClient(
            verify=ssl_context,
            follow_redirects=False,
            timeout=30,
        )
        try:
            auth_client = MitIDAuthClient(
                mitid_username="",
                httpx_client=httpx_client,
            )
            new_tokens = await auth_client.refresh_access_token(refresh_token)
        except MitIDAuthError as err:
            msg = f"Token refresh failed: {err}"
            raise AulaAuthenticationError(msg, 0) from err
        finally:
            await httpx_client.aclose()

        username = token_data.get("username", "")
        cookies = token_data.get("cookies", {})
        return {
            "timestamp": time.time(),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "username": username,
            "tokens": new_tokens,
            "cookies": cookies,
        }

    async def _async_create_client(self, token_data: dict[str, Any]) -> AulaApiClient:
        """Create a new AulaApiClient from token data."""
        cookies = token_data.get("cookies", {})
        http_client = await self._hass.async_add_executor_job(HttpxHttpClient, cookies)
        try:
            return await create_client(
                copy.deepcopy(token_data),
                http_client=http_client,
                token_storage=self.token_storage,
            )
        except Exception:
            await http_client.close()
            raise

    def _async_persist_token_data(self, new_token_data: dict[str, Any]) -> None:
        """Persist updated token data to the config entry."""
        self._hass.config_entries.async_update_entry(
            self._entry,
            data={**self._entry.data, CONF_TOKEN_DATA: new_token_data},
        )

    def _update_coordinator_clients(self, new_client: AulaApiClient) -> None:
        """Update the client reference on all coordinators."""
        for coord in self._entry.runtime_data.all_coordinators:
            coord.client = new_client  # type: ignore[attr-defined]  # all coordinators have .client
        LOGGER.debug("Updated all coordinator clients after token refresh")

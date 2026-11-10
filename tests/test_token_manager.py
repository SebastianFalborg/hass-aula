"""Tests for the AulaTokenManager."""

from __future__ import annotations

import asyncio
import copy
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aula import AulaAuthenticationError
from aula.auth.exceptions import OAuthError
from homeassistant.core import HomeAssistant

from custom_components.hass_aula.const import (
    CONF_TOKEN_DATA,
    REJECTION_REBUILD_COOLDOWN,
)
from custom_components.hass_aula.token_manager import (
    AulaConfigEntryTokenStorage,
    AulaTokenManager,
)

from .conftest import MOCK_TOKEN_DATA

if TYPE_CHECKING:
    from collections.abc import Iterator


def _make_entry(hass: HomeAssistant) -> MagicMock:
    """Create a mock config entry with token data."""
    entry = MagicMock()
    entry.data = {CONF_TOKEN_DATA: MOCK_TOKEN_DATA}
    entry.entry_id = "test_entry_id"

    # Mock hass.config_entries.async_update_entry
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()

    return entry


def _make_refreshed_tokens() -> dict:
    """Create mock refreshed token response."""
    return {
        "token_type": "Bearer",
        "expires_in": 3600,
        "access_token": "new_access_token",
        "refresh_token": "new_refresh_token",
        "expires_at": time.time() + 3600,
    }


@contextmanager
def _patched_refresh(
    new_tokens: dict, new_client: AsyncMock
) -> Iterator[tuple[MagicMock, MagicMock]]:
    """Patch the OIDC refresh and client creation; yield the auth and create mocks."""
    with (
        patch(
            "custom_components.hass_aula.token_manager.MitIDAuthClient"
        ) as mock_auth_cls,
        patch("custom_components.hass_aula.token_manager.ssl.create_default_context"),
        patch(
            "custom_components.hass_aula.token_manager.httpx.AsyncClient",
            return_value=AsyncMock(),
        ),
        patch(
            "custom_components.hass_aula.token_manager.create_client",
            return_value=new_client,
        ) as mock_create,
        patch("custom_components.hass_aula.token_manager.HttpxHttpClient"),
    ):
        mock_auth = MagicMock()
        mock_auth.refresh_access_token = AsyncMock(return_value=new_tokens)
        mock_auth_cls.return_value = mock_auth
        yield mock_auth, mock_create


def _runtime_entry(hass: HomeAssistant, client: AsyncMock) -> MagicMock:
    """Create a mock entry whose runtime data holds ``client``."""
    entry = _make_entry(hass)
    entry.data = {CONF_TOKEN_DATA: copy.deepcopy(MOCK_TOKEN_DATA)}
    entry.runtime_data = MagicMock()
    entry.runtime_data.client = client
    entry.runtime_data.all_coordinators = [MagicMock()]
    return entry


async def test_async_refresh_token_success(hass: HomeAssistant) -> None:
    """Test successful token refresh returns new client and token data."""
    entry = _make_entry(hass)
    tm = AulaTokenManager(hass, entry)
    new_tokens = _make_refreshed_tokens()

    mock_client = AsyncMock()

    with (
        patch(
            "custom_components.hass_aula.token_manager.MitIDAuthClient"
        ) as mock_auth_cls,
        patch("custom_components.hass_aula.token_manager.ssl.create_default_context"),
        patch(
            "custom_components.hass_aula.token_manager.httpx.AsyncClient"
        ) as mock_httpx,
        patch(
            "custom_components.hass_aula.token_manager.create_client",
            return_value=mock_client,
        ) as mock_create,
        patch("custom_components.hass_aula.token_manager.HttpxHttpClient"),
    ):
        mock_httpx_inst = AsyncMock()
        mock_httpx.return_value = mock_httpx_inst

        mock_auth = MagicMock()
        mock_auth.refresh_access_token = AsyncMock(return_value=new_tokens)
        mock_auth_cls.return_value = mock_auth

        client, token_data = await tm.async_refresh_token()

        assert client is mock_client
        assert token_data["tokens"] is new_tokens
        mock_auth.refresh_access_token.assert_called_once_with("mock_refresh_token")
        mock_create.assert_called_once()
        hass.config_entries.async_update_entry.assert_called_once()
        mock_httpx_inst.aclose.assert_called_once()


async def test_async_refresh_token_no_refresh_token(hass: HomeAssistant) -> None:
    """Test refresh raises when no refresh_token is available."""
    entry = _make_entry(hass)
    # Remove refresh_token from token data
    token_data_no_refresh = {
        **MOCK_TOKEN_DATA,
        "tokens": {
            "token_type": "Bearer",
            "access_token": "mock_access_token",
        },
    }
    entry.data = {CONF_TOKEN_DATA: token_data_no_refresh}
    tm = AulaTokenManager(hass, entry)

    with pytest.raises(AulaAuthenticationError, match="No refresh token"):
        await tm.async_refresh_token()


async def test_async_refresh_token_oauth_error(hass: HomeAssistant) -> None:
    """Test refresh raises AulaAuthenticationError on OAuthError."""
    entry = _make_entry(hass)
    tm = AulaTokenManager(hass, entry)

    with (
        patch(
            "custom_components.hass_aula.token_manager.MitIDAuthClient"
        ) as mock_auth_cls,
        patch("custom_components.hass_aula.token_manager.ssl.create_default_context"),
        patch(
            "custom_components.hass_aula.token_manager.httpx.AsyncClient"
        ) as mock_httpx,
    ):
        mock_httpx_inst = AsyncMock()
        mock_httpx.return_value = mock_httpx_inst

        mock_auth = MagicMock()
        mock_auth.refresh_access_token = AsyncMock(
            side_effect=OAuthError("Token expired")
        )
        mock_auth_cls.return_value = mock_auth

        with pytest.raises(AulaAuthenticationError, match="Token refresh failed"):
            await tm.async_refresh_token()

        mock_httpx_inst.aclose.assert_called_once()


async def test_async_refresh_and_rebuild_client(hass: HomeAssistant) -> None:
    """Test runtime refresh rebuilds client and updates coordinators."""
    entry = _make_entry(hass)

    # Set up runtime_data with coordinators
    old_client = AsyncMock()
    new_client = AsyncMock()

    presence_coord = MagicMock()
    calendar_coord = MagicMock()
    notifications_coord = MagicMock()
    all_coords = [presence_coord, calendar_coord, notifications_coord]
    runtime_data = MagicMock()
    runtime_data.client = old_client
    runtime_data.all_coordinators = all_coords
    entry.runtime_data = runtime_data

    tm = AulaTokenManager(hass, entry)
    new_tokens = _make_refreshed_tokens()

    with _patched_refresh(new_tokens, new_client):
        result = await tm.async_refresh_and_rebuild_client(old_client)

    assert result is new_client
    assert runtime_data.client is new_client
    for coord in all_coords:
        assert coord.client is new_client
    old_client.close.assert_called_once()


async def test_refresh_and_rebuild_skips_a_client_already_replaced(
    hass: HomeAssistant,
) -> None:
    """A caller whose client another caller already replaced gets the new one."""
    entry = _make_entry(hass)

    existing_client = AsyncMock()
    runtime_data = MagicMock()
    runtime_data.client = existing_client
    entry.runtime_data = runtime_data

    tm = AulaTokenManager(hass, entry)
    with patch.object(tm, "_async_do_refresh") as do_refresh:
        result = await tm.async_refresh_and_rebuild_client(AsyncMock())

    assert result is existing_client
    do_refresh.assert_not_called()


async def test_refresh_and_rebuild_ignores_a_fresh_expires_at(
    hass: HomeAssistant,
) -> None:
    """
    A fresh expires_at does not stop the rebuild.

    The aula package refreshes the token by itself, so a fresh expiry says
    nothing about whether the session still works.
    """
    entry = _make_entry(hass)
    entry.data = {
        CONF_TOKEN_DATA: {
            **MOCK_TOKEN_DATA,
            "tokens": {**MOCK_TOKEN_DATA["tokens"], "expires_at": time.time() + 3600},
        }
    }
    old_client = AsyncMock()
    new_client = AsyncMock()
    runtime_data = MagicMock()
    runtime_data.client = old_client
    runtime_data.all_coordinators = []
    entry.runtime_data = runtime_data

    tm = AulaTokenManager(hass, entry)
    with _patched_refresh(_make_refreshed_tokens(), new_client):
        result = await tm.async_refresh_and_rebuild_client(old_client)

    assert result is new_client


async def test_concurrent_refresh_only_one_call(hass: HomeAssistant) -> None:
    """Test concurrent refresh calls result in only one actual refresh."""
    entry = _make_entry(hass)
    entry.data = {
        CONF_TOKEN_DATA: {
            **MOCK_TOKEN_DATA,
            "tokens": {
                **MOCK_TOKEN_DATA["tokens"],
                "expires_at": time.time() - 100,
            },
        }
    }

    old_client = AsyncMock()
    new_client = AsyncMock()
    runtime_data = MagicMock()
    runtime_data.client = old_client
    runtime_data.all_coordinators = [MagicMock(), MagicMock(), MagicMock()]
    entry.runtime_data = runtime_data

    # Make async_update_entry actually update entry.data so the early-exit check works
    def fake_update(_entry: MagicMock, **kwargs: Any) -> None:
        if "data" in kwargs:
            _entry.data = kwargs["data"]

    hass.config_entries.async_update_entry = MagicMock(side_effect=fake_update)

    tm = AulaTokenManager(hass, entry)
    new_tokens = _make_refreshed_tokens()
    call_count = 0

    original_do_refresh = tm._async_do_refresh

    async def counting_refresh(token_data: dict, refresh_token: str) -> dict:
        nonlocal call_count
        call_count += 1
        return await original_do_refresh(token_data, refresh_token)

    with (
        patch(
            "custom_components.hass_aula.token_manager.MitIDAuthClient"
        ) as mock_auth_cls,
        patch("custom_components.hass_aula.token_manager.ssl.create_default_context"),
        patch(
            "custom_components.hass_aula.token_manager.httpx.AsyncClient"
        ) as mock_httpx,
        patch(
            "custom_components.hass_aula.token_manager.create_client",
            return_value=new_client,
        ),
        patch("custom_components.hass_aula.token_manager.HttpxHttpClient"),
        patch.object(tm, "_async_do_refresh", side_effect=counting_refresh),
    ):
        mock_httpx.return_value = AsyncMock()
        mock_auth = MagicMock()
        mock_auth.refresh_access_token = AsyncMock(return_value=new_tokens)
        mock_auth_cls.return_value = mock_auth

        results = await asyncio.gather(
            tm.async_refresh_and_rebuild_client(old_client),
            tm.async_refresh_and_rebuild_client(old_client),
        )

    # First call does the refresh, second gets early exit
    assert call_count == 1
    # Both return a valid client
    assert all(r is not None for r in results)


async def test_rebuild_after_rejection_builds_a_new_client(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A refused session is replaced by a new client on every coordinator."""
    old_client = AsyncMock()
    new_client = AsyncMock()
    entry = _runtime_entry(hass, old_client)
    tm = AulaTokenManager(hass, entry)

    with _patched_refresh(_make_refreshed_tokens(), new_client):
        assert await tm.async_rebuild_after_rejection(old_client) is True

    assert entry.runtime_data.client is new_client
    assert entry.runtime_data.all_coordinators[0].client is new_client
    old_client.close.assert_awaited_once()
    assert "Aula refused the session, building a new one" in caplog.text


async def test_rebuild_after_rejection_once_for_concurrent_callers(
    hass: HomeAssistant,
) -> None:
    """Coordinators refused on the same client share one rebuild."""
    old_client = AsyncMock()
    entry = _runtime_entry(hass, old_client)
    tm = AulaTokenManager(hass, entry)

    with _patched_refresh(_make_refreshed_tokens(), AsyncMock()) as (auth, _create):
        results = await asyncio.gather(
            tm.async_rebuild_after_rejection(old_client),
            tm.async_rebuild_after_rejection(old_client),
        )

    assert results == [True, True]
    auth.refresh_access_token.assert_awaited_once()


async def test_rebuild_after_rejection_waits_out_the_cooldown(
    hass: HomeAssistant,
) -> None:
    """A refusal the new session does not fix waits for the cooldown."""
    old_client = AsyncMock()
    new_client = AsyncMock()
    newest_client = AsyncMock()
    entry = _runtime_entry(hass, old_client)
    tm = AulaTokenManager(hass, entry)
    monotonic = "custom_components.hass_aula.token_manager.time.monotonic"

    with (
        _patched_refresh(_make_refreshed_tokens(), new_client),
        patch(monotonic, return_value=1000.0),
    ):
        assert await tm.async_rebuild_after_rejection(old_client) is True

    with _patched_refresh(_make_refreshed_tokens(), newest_client) as (auth, _c):
        with patch(monotonic, return_value=1000.0 + REJECTION_REBUILD_COOLDOWN - 1):
            assert await tm.async_rebuild_after_rejection(new_client) is False
        auth.refresh_access_token.assert_not_awaited()
        assert entry.runtime_data.client is new_client

        with patch(monotonic, return_value=1000.0 + REJECTION_REBUILD_COOLDOWN):
            assert await tm.async_rebuild_after_rejection(new_client) is True
        assert entry.runtime_data.client is newest_client


async def test_rebuild_after_rejection_failure_still_starts_the_cooldown(
    hass: HomeAssistant,
) -> None:
    """A failed rebuild is not retried on the next poll."""
    old_client = AsyncMock()
    entry = _runtime_entry(hass, old_client)
    tm = AulaTokenManager(hass, entry)

    with (
        patch.object(
            tm,
            "_async_do_refresh",
            side_effect=AulaAuthenticationError("Token refresh failed", 0),
        ),
        pytest.raises(AulaAuthenticationError),
    ):
        await tm.async_rebuild_after_rejection(old_client)

    with patch.object(tm, "_async_do_refresh") as do_refresh:
        assert await tm.async_rebuild_after_rejection(old_client) is False
    do_refresh.assert_not_called()


async def test_created_client_gets_a_copy_and_the_entry_storage(
    hass: HomeAssistant,
) -> None:
    """
    The package refreshes into its own copy and saves it through the storage.

    It used to rewrite the config entry's dict in place, which reached disk
    only when something else happened to save the entry.
    """
    entry = _runtime_entry(hass, AsyncMock())
    tm = AulaTokenManager(hass, entry)
    new_tokens = _make_refreshed_tokens()

    with _patched_refresh(new_tokens, AsyncMock()) as (_auth, create):
        await tm.async_refresh_and_rebuild_client(entry.runtime_data.client)

    passed = create.await_args.args[0]
    assert passed["tokens"] == new_tokens
    assert (
        passed
        is not hass.config_entries.async_update_entry.call_args.kwargs["data"][
            CONF_TOKEN_DATA
        ]
    )
    assert create.await_args.kwargs["token_storage"] is tm.token_storage


async def test_token_storage_saves_and_loads_copies(hass: HomeAssistant) -> None:
    """The storage never shares a dict with the package or the entry."""
    entry = _make_entry(hass)
    entry.data = {"other": "kept", CONF_TOKEN_DATA: copy.deepcopy(MOCK_TOKEN_DATA)}
    storage = AulaConfigEntryTokenStorage(hass, entry)

    refreshed = {**MOCK_TOKEN_DATA, "tokens": _make_refreshed_tokens()}
    await storage.save(refreshed)

    saved = hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved["other"] == "kept"
    assert saved[CONF_TOKEN_DATA] == refreshed
    assert saved[CONF_TOKEN_DATA] is not refreshed

    loaded = await storage.load()
    assert loaded == entry.data[CONF_TOKEN_DATA]
    assert loaded is not entry.data[CONF_TOKEN_DATA]

"""Tests for the Aula actions."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol
import yaml
from aula import (
    ActivityType,
    AulaAuthenticationError,
    AulaConnectionError,
    HttpRequestError,
)
from aula.api_client import ThreadScanLimitError
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.service import async_get_all_descriptions
from homeassistant.util import dt as dt_util

from custom_components.hass_aula import services
from custom_components.hass_aula.const import (
    DOMAIN,
    SERVICE_GET_THREAD_MESSAGES,
    SERVICE_MARK_THREAD_READ,
    SERVICE_UPDATE_PRESENCE,
)

from .conftest import make_config_entry, mock_child, mock_message, mock_profile

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant.common import MockConfigEntry


async def _setup_integration(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
    children: list[MagicMock] | None = None,
) -> MockConfigEntry:
    """Set up the integration and return the config entry."""
    if children is not None:
        mock_aula_client.get_profile.return_value = mock_profile(children)
    entry = make_config_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _device_id(hass: HomeAssistant, child_id: int) -> str:
    """Return the registry device ID for a child."""
    [device] = dr.async_get(hass).async_get_devices(
        identifiers={(DOMAIN, str(child_id))},
    )
    return device.id


async def _call(hass: HomeAssistant, **data: Any) -> None:
    """Call update_presence with the given data."""
    await hass.services.async_call(
        DOMAIN,
        SERVICE_UPDATE_PRESENCE,
        data,
        blocking=True,
    )


async def test_service_registered(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """The action is registered."""
    await _setup_integration(hass, mock_aula_client)
    assert hass.services.has_service(DOMAIN, SERVICE_UPDATE_PRESENCE)


async def test_service_description_loads(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """services.yaml describes every field the action accepts."""
    await _setup_integration(hass, mock_aula_client)
    descriptions = await async_get_all_descriptions(hass)

    description = descriptions[DOMAIN][SERVICE_UPDATE_PRESENCE]
    assert set(description["fields"]) == {
        "entry_time",
        "exit_time",
        "date",
        "activity_type",
        "exit_with",
        "comment",
        "repeat",
        "expires_at",
    }
    assert "target" in description


def test_services_yaml_matches_hassfest_rules() -> None:
    """
    Mirror the hassfest rules that services.yaml keeps tripping over.

    Custom integrations may only use these top-level keys, and a device filter
    on target is rejected outright. Both fail in CI otherwise.
    """
    allowed = {"fields", "target", "name", "description"}
    path = Path(services.__file__).parent / "services.yaml"
    definitions = yaml.safe_load(path.read_text(encoding="utf-8"))

    for name, definition in definitions.items():
        extra = set(definition) - allowed
        assert not extra, f"{name}: hassfest rejects top-level key(s) {sorted(extra)}"

        target = definition.get("target")
        if target is not None:
            assert "device" not in target, (
                f"{name}: use a device selector field, not a target device filter"
            )


async def test_update_presence_by_device(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """A device target updates that child with the given times."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.update_presence_template = AsyncMock(return_value=True)

    await _call(
        hass,
        **{ATTR_DEVICE_ID: [_device_id(hass, 1)]},
        entry_time="08:00:00",
        exit_time="15:30:00",
        date="2026-08-11",
        exit_with="Nick Nissen (Far)",
        comment="Går til fodbold",
    )

    mock_aula_client.update_presence_template.assert_awaited_once_with(
        institution_profile_id=1,
        by_date=date(2026, 8, 11),
        entry_time="08:00",
        exit_time="15:30",
        activity_type=ActivityType.PICKED_UP_BY,
        exit_with="Nick Nissen (Far)",
        comment="Går til fodbold",
        template_id=None,
        repeat_pattern="Never",
        expires_at=None,
    )


async def test_update_presence_defaults_to_today(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Omitting the date targets today."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.update_presence_template = AsyncMock(return_value=True)

    await _call(
        hass,
        **{ATTR_DEVICE_ID: [_device_id(hass, 1)]},
        entry_time="08:00:00",
        exit_time="15:30:00",
        activity_type="self_decider",
    )

    kwargs = mock_aula_client.update_presence_template.await_args.kwargs
    assert kwargs["by_date"] == dt_util.now().date()
    assert kwargs["activity_type"] is ActivityType.SELF_DECIDER


async def test_update_presence_reuses_existing_template_id(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """An existing template for the date is updated instead of duplicated."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.update_presence_template = AsyncMock(return_value=True)

    day = MagicMock()
    day.id = 987
    day.by_date = "2026-08-11T00:00:00"
    profile = MagicMock()
    profile.id = 1
    week_template = MagicMock()
    week_template.institution_profile = profile
    week_template.day_templates = [day]
    mock_aula_client.get_presence_templates = AsyncMock(return_value=[week_template])

    await _call(
        hass,
        **{ATTR_DEVICE_ID: [_device_id(hass, 1)]},
        entry_time="08:00:00",
        exit_time="15:30:00",
        date="2026-08-11",
        exit_with="Mor",
    )

    kwargs = mock_aula_client.update_presence_template.await_args.kwargs
    assert kwargs["template_id"] == 987


async def test_update_presence_multiple_children(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Two device targets produce one call per child."""
    children = [mock_child(1, "Emilie"), mock_child(2, "Karla")]
    await _setup_integration(hass, mock_aula_client, children)
    mock_aula_client.update_presence_template = AsyncMock(return_value=True)

    await _call(
        hass,
        **{ATTR_DEVICE_ID: [_device_id(hass, 1), _device_id(hass, 2)]},
        entry_time="08:00:00",
        exit_time="15:30:00",
        exit_with="Far",
    )

    assert mock_aula_client.update_presence_template.await_count == 2
    updated = {
        call.kwargs["institution_profile_id"]
        for call in mock_aula_client.update_presence_template.await_args_list
    }
    assert updated == {1, 2}


async def test_update_presence_by_entity(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """An entity target resolves to that entity's child device."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.update_presence_template = AsyncMock(return_value=True)

    await _call(
        hass,
        **{ATTR_ENTITY_ID: ["sensor.test_child_presence_status"]},
        entry_time="08:00:00",
        exit_time="15:30:00",
        exit_with="Far",
    )

    kwargs = mock_aula_client.update_presence_template.await_args.kwargs
    assert kwargs["institution_profile_id"] == 1


async def test_update_presence_refreshes_presence_coordinator(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """The presence coordinator refreshes after a successful update."""
    entry = await _setup_integration(hass, mock_aula_client)
    mock_aula_client.update_presence_template = AsyncMock(return_value=True)
    before = mock_aula_client.get_daily_overview.await_count

    await _call(
        hass,
        **{ATTR_DEVICE_ID: [_device_id(hass, 1)]},
        entry_time="08:00:00",
        exit_time="15:30:00",
        exit_with="Far",
    )
    await hass.async_block_till_done()

    assert entry.runtime_data.presence_coordinator.last_update_success
    assert mock_aula_client.get_daily_overview.await_count > before


async def test_exit_with_required_for_pickup(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """picked_up_by without exit_with is rejected."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.update_presence_template = AsyncMock(return_value=True)

    with pytest.raises(ServiceValidationError):
        await _call(
            hass,
            **{ATTR_DEVICE_ID: [_device_id(hass, 1)]},
            entry_time="08:00:00",
            exit_time="15:30:00",
        )

    mock_aula_client.update_presence_template.assert_not_awaited()


async def test_exit_with_not_required_for_self_decider(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """self_decider does not need a pickup person."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.update_presence_template = AsyncMock(return_value=True)

    await _call(
        hass,
        **{ATTR_DEVICE_ID: [_device_id(hass, 1)]},
        entry_time="08:00:00",
        exit_time="15:30:00",
        activity_type="self_decider",
    )

    mock_aula_client.update_presence_template.assert_awaited_once()


async def test_invalid_time_range(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """An exit time at or before the entry time is rejected."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.update_presence_template = AsyncMock(return_value=True)

    with pytest.raises(ServiceValidationError):
        await _call(
            hass,
            **{ATTR_DEVICE_ID: [_device_id(hass, 1)]},
            entry_time="15:30:00",
            exit_time="08:00:00",
            exit_with="Far",
        )

    mock_aula_client.update_presence_template.assert_not_awaited()


async def test_no_target(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """A call with no target is rejected."""
    await _setup_integration(hass, mock_aula_client)

    with pytest.raises(ServiceValidationError):
        await _call(hass, entry_time="08:00:00", exit_time="15:30:00", exit_with="Far")


async def test_unknown_device(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """A device that is not an Aula child is rejected."""
    await _setup_integration(hass, mock_aula_client)

    with pytest.raises(ServiceValidationError):
        await _call(
            hass,
            **{ATTR_DEVICE_ID: ["does-not-exist"]},
            entry_time="08:00:00",
            exit_time="15:30:00",
            exit_with="Far",
        )


async def test_account_device_is_not_a_valid_target(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """The profile-level device cannot be targeted."""
    entry = await _setup_integration(hass, mock_aula_client)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, "profile_42"), entry.entry_id
    )
    assert device is not None

    with pytest.raises(ServiceValidationError):
        await _call(
            hass,
            **{ATTR_DEVICE_ID: [device.id]},
            entry_time="08:00:00",
            exit_time="15:30:00",
            exit_with="Far",
        )


async def test_entry_not_loaded(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Targeting a child of an unloaded entry is a user error."""
    entry = await _setup_integration(hass, mock_aula_client)
    device_id = _device_id(hass, 1)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await _call(
            hass,
            **{ATTR_DEVICE_ID: [device_id]},
            entry_time="08:00:00",
            exit_time="15:30:00",
            exit_with="Far",
        )


async def test_auth_error_refreshes_and_retries(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """An auth failure triggers a session refresh and one retry."""
    entry = await _setup_integration(hass, mock_aula_client)
    mock_aula_client.update_presence_template = AsyncMock(
        side_effect=[AulaAuthenticationError("expired", 401), True]
    )
    refresh = AsyncMock(return_value=mock_aula_client)
    entry.runtime_data.token_manager.async_refresh_and_rebuild_client = refresh

    await _call(
        hass,
        **{ATTR_DEVICE_ID: [_device_id(hass, 1)]},
        entry_time="08:00:00",
        exit_time="15:30:00",
        exit_with="Far",
    )

    refresh.assert_awaited_once()
    assert mock_aula_client.update_presence_template.await_count == 2


async def test_auth_error_after_refresh_raises(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """A second auth failure surfaces as a HomeAssistantError."""
    entry = await _setup_integration(hass, mock_aula_client)
    mock_aula_client.update_presence_template = AsyncMock(
        side_effect=AulaAuthenticationError("expired", 401)
    )
    entry.runtime_data.token_manager.async_refresh_and_rebuild_client = AsyncMock(
        return_value=mock_aula_client
    )

    with pytest.raises(HomeAssistantError):
        await _call(
            hass,
            **{ATTR_DEVICE_ID: [_device_id(hass, 1)]},
            entry_time="08:00:00",
            exit_time="15:30:00",
            exit_with="Far",
        )


async def test_connection_error_raises(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """A connection failure surfaces as a HomeAssistantError."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.update_presence_template = AsyncMock(
        side_effect=AulaConnectionError("boom", 500)
    )

    with pytest.raises(HomeAssistantError):
        await _call(
            hass,
            **{ATTR_DEVICE_ID: [_device_id(hass, 1)]},
            entry_time="08:00:00",
            exit_time="15:30:00",
            exit_with="Far",
        )


async def test_api_error_envelope_raises(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """An error code in a 200 response surfaces as a HomeAssistantError."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.update_presence_template = AsyncMock(
        side_effect=HttpRequestError("Aula rejected method (status code 1)", 200)
    )

    with pytest.raises(HomeAssistantError):
        await _call(
            hass,
            **{ATTR_DEVICE_ID: [_device_id(hass, 1)]},
            entry_time="08:00:00",
            exit_time="15:30:00",
            exit_with="Far",
        )


async def test_get_thread_messages_returns_full_content(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """The action returns plain and markdown content for each message."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.get_messages_for_thread = AsyncMock(
        return_value=[mock_message(message_id="9", content="Kære forældre")]
    )

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_THREAD_MESSAGES,
        {"thread_id": "42"},
        blocking=True,
        return_response=True,
    )

    mock_aula_client.get_messages_for_thread.assert_awaited_once_with("42", limit=5)
    assert response == {
        "thread_id": "42",
        "messages": [
            {
                "id": "9",
                "content": "Kære forældre",
                "content_markdown": "Kære forældre",
            }
        ],
    }


async def test_get_thread_messages_honours_limit(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """An explicit limit is passed through to the client."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.get_messages_for_thread = AsyncMock(return_value=[])

    await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_THREAD_MESSAGES,
        {"thread_id": "42", "limit": 25},
        blocking=True,
        return_response=True,
    )

    mock_aula_client.get_messages_for_thread.assert_awaited_once_with("42", limit=25)


@pytest.mark.parametrize("limit", [0, 51])
async def test_get_thread_messages_rejects_out_of_range_limit(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
    limit: int,
) -> None:
    """A limit outside 1-50 is rejected by the schema."""
    await _setup_integration(hass, mock_aula_client)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_THREAD_MESSAGES,
            {"thread_id": "42", "limit": limit},
            blocking=True,
            return_response=True,
        )


async def test_get_thread_messages_does_not_fetch_thread_list(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Reading a thread costs one request, not a thread-list lookup as well."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.get_messages_for_thread = AsyncMock(return_value=[])
    before = mock_aula_client.get_message_threads.await_count

    await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_THREAD_MESSAGES,
        {"thread_id": "42"},
        blocking=True,
        return_response=True,
    )

    assert mock_aula_client.get_message_threads.await_count == before


async def test_get_thread_messages_explicit_config_entry(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """An explicit config_entry_id selects the account."""
    entry = await _setup_integration(hass, mock_aula_client)
    mock_aula_client.get_messages_for_thread = AsyncMock(return_value=[])

    await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_THREAD_MESSAGES,
        {"thread_id": "42", "config_entry_id": entry.entry_id},
        blocking=True,
        return_response=True,
    )

    mock_aula_client.get_messages_for_thread.assert_awaited_once()


async def test_get_thread_messages_unknown_config_entry(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """An unknown config_entry_id is a user error."""
    await _setup_integration(hass, mock_aula_client)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_THREAD_MESSAGES,
            {"thread_id": "42", "config_entry_id": "nope"},
            blocking=True,
            return_response=True,
        )


async def test_get_thread_messages_no_loaded_account(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """With the only account unloaded the action reports that, not entries[0]."""
    entry = await _setup_integration(hass, mock_aula_client)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_THREAD_MESSAGES,
            {"thread_id": "42"},
            blocking=True,
            return_response=True,
        )


async def test_get_thread_messages_ambiguous_account(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Two loaded accounts require an explicit config_entry_id."""
    await _setup_integration(hass, mock_aula_client)
    second = make_config_entry(unique_id="second_user")
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_THREAD_MESSAGES,
            {"thread_id": "42"},
            blocking=True,
            return_response=True,
        )


async def test_get_thread_messages_auth_error_refreshes_and_retries(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Reads share the presence action's refresh-and-retry behaviour."""
    entry = await _setup_integration(hass, mock_aula_client)
    mock_aula_client.get_messages_for_thread = AsyncMock(
        side_effect=[AulaAuthenticationError("expired", 401), []]
    )
    refresh = AsyncMock(return_value=mock_aula_client)
    entry.runtime_data.token_manager.async_refresh_and_rebuild_client = refresh

    await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_THREAD_MESSAGES,
        {"thread_id": "42"},
        blocking=True,
        return_response=True,
    )

    refresh.assert_awaited_once()
    assert mock_aula_client.get_messages_for_thread.await_count == 2


async def test_get_thread_messages_connection_error_raises(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """A connection failure surfaces as a HomeAssistantError."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.get_messages_for_thread = AsyncMock(
        side_effect=AulaConnectionError("boom", 500)
    )

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_THREAD_MESSAGES,
            {"thread_id": "42"},
            blocking=True,
            return_response=True,
        )


async def test_mark_thread_read_marks_and_refreshes(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """The action marks the thread and refreshes the unread count."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.mark_thread_read = AsyncMock(return_value=True)
    threads_fetched = mock_aula_client.get_message_threads.await_count

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_MARK_THREAD_READ,
        {"thread_id": "42"},
        blocking=True,
        return_response=True,
    )

    mock_aula_client.mark_thread_read.assert_awaited_once_with("42")
    assert response == {"thread_id": "42", "marked": True}
    assert mock_aula_client.get_message_threads.await_count > threads_fetched


async def test_mark_thread_read_without_response(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """The action can be called without asking for a response."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.mark_thread_read = AsyncMock(return_value=False)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_MARK_THREAD_READ,
        {"thread_id": "42"},
        blocking=True,
    )

    mock_aula_client.mark_thread_read.assert_awaited_once_with("42")


async def test_mark_thread_read_refuses_shared_inbox(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """A thread outside the guardian's own mailbox is a user error."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.mark_thread_read = AsyncMock(
        side_effect=ValueError("thread is not in the guardian's own mailbox")
    )

    with pytest.raises(ServiceValidationError) as exc_info:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_MARK_THREAD_READ,
            {"thread_id": "42"},
            blocking=True,
        )

    assert exc_info.value.translation_key == "thread_not_in_own_mailbox"


@pytest.mark.parametrize(
    "error",
    [
        ThreadScanLimitError("no message in the first 50 pages"),
        HttpRequestError("Aula did not confirm the read marker", 200),
    ],
)
async def test_mark_thread_read_failure_raises(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
    error: Exception,
) -> None:
    """A thread aula could not mark surfaces as a HomeAssistantError."""
    await _setup_integration(hass, mock_aula_client)
    mock_aula_client.mark_thread_read = AsyncMock(side_effect=error)

    with pytest.raises(HomeAssistantError) as exc_info:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_MARK_THREAD_READ,
            {"thread_id": "42"},
            blocking=True,
        )

    assert exc_info.value.translation_key == "action_failed"

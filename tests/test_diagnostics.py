"""Tests for Aula diagnostics."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from aula import AulaConnectionError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import JSONEncoder

from custom_components.hass_aula.const import WIDGET_MEEBOOK
from custom_components.hass_aula.diagnostics import async_get_config_entry_diagnostics

from .conftest import (
    make_config_entry,
    make_widget_config_entry,
    mock_child,
    mock_daily_overview,
    mock_meebook_student_plan,
    mock_meebook_task,
    mock_profile,
)


async def test_diagnostics_redacts_pii(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test that diagnostics redacts PII."""
    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["profile"]["display_name"] == "**REDACTED**"
    assert result["profile"]["children"][0]["name"] == "**REDACTED**"
    assert result["profile"]["children_count"] == 1


async def test_diagnostics_redacts_account_identifiers(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test that Aula ids and schools are left out, keyed by child position."""
    profile = mock_profile(
        children=[
            mock_child(child_id=48151, institution_name="Northside School"),
            mock_child(child_id=62342, institution_name="Southside School"),
        ]
    )
    profile.profile_id = 77001
    mock_aula_client.get_profile = AsyncMock(return_value=profile)

    entry = make_widget_config_entry(widgets=[WIDGET_MEEBOOK])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["profile"]["profile_id"] == "**REDACTED**"
    assert result["profile"]["children"] == [
        {"id": "child_1", "name": "**REDACTED**", "institution_name": "**REDACTED**"},
        {"id": "child_2", "name": "**REDACTED**", "institution_name": "**REDACTED**"},
    ]
    assert set(result["presence"]) == {"child_1", "child_2"}
    assert set(result["calendar_event_counts"]) == {"child_1", "child_2"}
    assert set(result["widgets"]["meebook"]) == {"child_1", "child_2"}
    serialized = json.dumps(result, cls=JSONEncoder)
    for secret in ("48151", "62342", "77001", "Northside", "Southside"):
        assert secret not in serialized


async def test_diagnostics_structure(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test diagnostics output structure."""
    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert "profile" in result
    assert "presence" in result
    assert "calendar_event_counts" in result
    assert "profile_id" in result["profile"]
    assert "children" in result["profile"]


async def test_diagnostics_presence_data(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test diagnostics includes presence data."""
    mock_aula_client.get_daily_overview = AsyncMock(
        return_value=mock_daily_overview(location="Room 1")
    )

    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert "child_1" in result["presence"]
    presence = result["presence"]["child_1"]
    assert "status" in presence
    assert "check_in_time" in presence
    # aula delivers this as a PresenceLocation, which cannot be JSON-encoded;
    # diagnostics are downloaded as JSON, so the name is what goes in.
    assert presence["location"] == "Room 1"
    json.dumps(result, cls=JSONEncoder)


async def test_diagnostics_calendar_counts(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test diagnostics includes calendar event counts."""
    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert "child_1" in result["calendar_event_counts"]
    assert isinstance(result["calendar_event_counts"]["child_1"], int)


@pytest.mark.parametrize("next_count", [0, 2, None])
async def test_diagnostics_meebook_week_counts(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
    next_count: int | None,
) -> None:
    """Test diagnostics reports separate current and next Meebook counts."""
    plan = mock_meebook_student_plan(name="Test Child")
    mock_aula_client.widgets.get_meebook_weekplan = AsyncMock(
        side_effect=[
            [plan],
            AulaConnectionError("private response", 0)
            if next_count is None
            else [
                mock_meebook_student_plan(
                    name="Test Child", tasks=[mock_meebook_task()] * next_count
                )
            ],
        ]
    )

    entry = make_widget_config_entry(widgets=[WIDGET_MEEBOOK])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["widgets"]["meebook"]["child_1"] == {
        "current_week": 1,
        "next_week": next_count,
    }
    serialized = json.dumps(result["widgets"]["meebook"], cls=JSONEncoder)
    assert "Weekly Activity" not in serialized
    assert "private response" not in serialized

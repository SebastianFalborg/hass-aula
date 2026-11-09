"""Tests for Aula integration setup and teardown."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from aula import AulaAuthenticationError, AulaConnectionError, HttpRequestError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.hass_aula.const import (
    CONF_WIDGETS,
    CONFIG_ENTRY_MINOR_VERSION,
    DOMAIN,
    LEGACY_WIDGET_EASYIQ,
    WIDGET_BIBLIOTEKET,
    WIDGET_EASYIQ_HOMEWORK,
    WIDGET_EASYIQ_WEEKPLAN,
    WIDGET_MEEBOOK,
    WIDGET_MEEBOOK_OVERVIEW,
    WIDGET_MIN_UDDANNELSE_SSO,
    WIDGET_MIN_UDDANNELSE_TASKS,
    WIDGET_MIN_UDDANNELSE_UGEPLAN,
)

from .conftest import (
    make_config_entry,
    make_widget_config_entry,
    mock_child,
    mock_profile,
)


def _make_refreshed_client() -> AsyncMock:
    """Create a mock client as returned by token refresh."""
    client = AsyncMock()
    client.get_profile = AsyncMock(return_value=mock_profile())
    client.get_daily_overview = AsyncMock(return_value=None)
    client.get_calendar_events = AsyncMock(return_value=[])
    client.get_notifications_for_active_profile = AsyncMock(return_value=[])
    client.close = AsyncMock()
    return client


async def test_setup_entry(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test successful setup of a config entry."""
    entry = make_config_entry()
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not None
    assert entry.runtime_data.client is mock_aula_client


async def test_setup_entry_auth_error(
    hass: HomeAssistant,
) -> None:
    """Test setup fails with auth error when refresh also fails."""
    with (
        patch(
            "custom_components.hass_aula.create_client",
            side_effect=AulaAuthenticationError("Auth failed", 401),
        ),
        patch(
            "custom_components.hass_aula.AulaTokenManager.async_refresh_token",
            side_effect=AulaAuthenticationError("Refresh failed", 0),
        ),
    ):
        entry = make_config_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_entry_auth_error_refresh_succeeds(
    hass: HomeAssistant,
) -> None:
    """Test setup recovers when create_client fails but refresh succeeds."""
    refreshed_client = _make_refreshed_client()

    with (
        patch(
            "custom_components.hass_aula.create_client",
            side_effect=AulaAuthenticationError("Auth failed", 401),
        ),
        patch(
            "custom_components.hass_aula.AulaTokenManager.async_refresh_token",
            return_value=(refreshed_client, {"tokens": {}}),
        ),
    ):
        entry = make_config_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data.client is refreshed_client


async def test_setup_entry_connection_error(
    hass: HomeAssistant,
) -> None:
    """Test setup retries with connection error."""
    with patch(
        "custom_components.hass_aula.create_client",
        side_effect=AulaConnectionError("Connection failed", 0),
    ):
        entry = make_config_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_api_error_envelope(
    hass: HomeAssistant,
) -> None:
    """Test setup retries when Aula answers with an error code in the body."""
    with patch(
        "custom_components.hass_aula.create_client",
        side_effect=HttpRequestError("Aula rejected method (status code 1)", 200),
    ):
        entry = make_config_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_profile_auth_error(
    hass: HomeAssistant,
) -> None:
    """Test setup fails when get_profile raises auth error and refresh fails."""
    with (
        patch("custom_components.hass_aula.create_client") as mock_create,
        patch(
            "custom_components.hass_aula.AulaTokenManager.async_refresh_token",
            side_effect=AulaAuthenticationError("Refresh failed", 0),
        ),
    ):
        client = AsyncMock()
        client.get_profile = AsyncMock(
            side_effect=AulaAuthenticationError("Auth failed", 401)
        )
        client.close = AsyncMock()
        mock_create.return_value = client

        entry = make_config_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.SETUP_ERROR
        client.close.assert_called_once()


async def test_setup_entry_profile_auth_error_refresh_succeeds(
    hass: HomeAssistant,
) -> None:
    """Test setup recovers when get_profile fails but refresh succeeds."""
    refreshed_client = _make_refreshed_client()

    with (
        patch("custom_components.hass_aula.create_client") as mock_create,
        patch(
            "custom_components.hass_aula.AulaTokenManager.async_refresh_token",
            return_value=(refreshed_client, {"tokens": {}}),
        ),
    ):
        client = AsyncMock()
        client.get_profile = AsyncMock(
            side_effect=AulaAuthenticationError("Auth failed", 401)
        )
        client.close = AsyncMock()
        mock_create.return_value = client

        entry = make_config_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data.client is refreshed_client
        client.close.assert_called_once()


async def test_setup_entry_profile_connection_error(
    hass: HomeAssistant,
) -> None:
    """Test setup retries when get_profile raises connection error."""
    with patch("custom_components.hass_aula.create_client") as mock_create:
        client = AsyncMock()
        client.get_profile = AsyncMock(
            side_effect=AulaConnectionError("Connection failed", 0)
        )
        client.close = AsyncMock()
        mock_create.return_value = client

        entry = make_config_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.SETUP_RETRY
        client.close.assert_called_once()


async def test_unload_entry(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test successful unload of a config entry."""
    entry = make_config_entry()
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    mock_aula_client.close.assert_called_once()


async def test_stale_device_removal(
    hass: HomeAssistant,
) -> None:
    """Test that devices for removed children are cleaned up."""
    child1 = mock_child(child_id=1, name="Child 1")
    child2 = mock_child(child_id=2, name="Child 2")
    profile_with_two = mock_profile(children=[child1, child2])

    with patch("custom_components.hass_aula.create_client") as mock_create:
        client = AsyncMock()
        client.get_profile = AsyncMock(return_value=profile_with_two)
        client.get_daily_overview = AsyncMock(return_value=None)
        client.get_calendar_events = AsyncMock(return_value=[])
        client.get_notifications_for_active_profile = AsyncMock(return_value=[])
        client.close = AsyncMock()
        mock_create.return_value = client

        entry = make_config_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED

        # Now reload with only one child
        profile_with_one = mock_profile(children=[child1])
        client.get_profile = AsyncMock(return_value=profile_with_one)

        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        # Verify second child device was removed
        device_registry = dr.async_get(hass)
        devices = [d for d in device_registry.devices if (DOMAIN, "2") in d.identifiers]
        assert len(devices) == 0


async def test_migrate_combined_easyiq_widget(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test the retired combined EasyIQ ID becomes the weekplan and homework IDs."""
    entry = make_widget_config_entry(
        widgets=[WIDGET_BIBLIOTEKET, LEGACY_WIDGET_EASYIQ],
        minor_version=1,
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.minor_version == CONFIG_ENTRY_MINOR_VERSION
    assert set(entry.data[CONF_WIDGETS]) == {
        WIDGET_BIBLIOTEKET,
        WIDGET_EASYIQ_WEEKPLAN,
        WIDGET_EASYIQ_HOMEWORK,
    }
    # Both EasyIQ views must still be served after the migration.
    assert entry.runtime_data.easyiq_coordinator is not None


async def test_migrate_leaves_other_widgets_alone(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test migration only bumps the version when no legacy EasyIQ ID is stored."""
    entry = make_widget_config_entry(widgets=[WIDGET_MEEBOOK], minor_version=1)
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == CONFIG_ENTRY_MINOR_VERSION
    assert entry.data[CONF_WIDGETS] == [WIDGET_MEEBOOK]
    assert entry.runtime_data.easyiq_coordinator is None


async def test_meebook_enabled_by_overview_widget(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test the advertised Meebook overblik widget enables Meebook data."""
    entry = make_widget_config_entry(widgets=[WIDGET_MEEBOOK_OVERVIEW])
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.meebook_coordinator is not None


async def test_meebook_overview_widget_keeps_the_api_contract(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test 0119 only enables the feature; the API call is unchanged."""
    entry = make_widget_config_entry(widgets=[WIDGET_MEEBOOK_OVERVIEW])
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    calls = mock_aula_client.widgets.get_meebook_weekplan.await_args_list
    assert calls
    for c in calls:
        assert not c.args
        assert set(c.kwargs) == {
            "child_filter",
            "institution_filter",
            "week",
            "session_uuid",
        }
        # The package mints the Meebook token itself; 0119 must never be
        # passed down as a token scope.
        assert WIDGET_MEEBOOK_OVERVIEW not in str(c.kwargs)


async def test_meebook_both_provider_widgets_create_one_coordinator(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test selecting both Meebook providers does not duplicate coordinators."""
    entry = make_widget_config_entry(widgets=[WIDGET_MEEBOOK, WIDGET_MEEBOOK_OVERVIEW])
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.meebook_coordinator is not None
    # One coordinator refresh means one current-week and one next-week request.
    assert mock_aula_client.widgets.get_meebook_weekplan.await_count == 2


async def test_mu_tasks_enabled_by_the_sso_widget_alone(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test a school listing only the SSO widget still gets MU tasks."""
    entry = make_widget_config_entry(widgets=[WIDGET_MIN_UDDANNELSE_SSO])
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data.mu_tasks_coordinator
    assert coordinator is not None
    assert coordinator.widget_id == WIDGET_MIN_UDDANNELSE_SSO


async def test_mu_tasks_prefers_the_opgaver_widget(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test the opgaver widget wins when the account lists both."""
    entry = make_widget_config_entry(
        widgets=[WIDGET_MIN_UDDANNELSE_SSO, WIDGET_MIN_UDDANNELSE_TASKS]
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data.mu_tasks_coordinator
    assert coordinator is not None
    # Order comes from the widget list, not from what the user happened to
    # select first, so the endpoint's own widget leads.
    assert coordinator.widget_id == WIDGET_MIN_UDDANNELSE_TASKS


async def test_mu_ugeplan_enabled_by_the_sso_widget_alone(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test a school listing only the SSO widget still gets weekly letters."""
    entry = make_widget_config_entry(widgets=[WIDGET_MIN_UDDANNELSE_SSO])
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data.mu_ugeplan_coordinator
    assert coordinator is not None
    assert coordinator.widget_id == WIDGET_MIN_UDDANNELSE_SSO


async def test_mu_ugeplan_prefers_the_ugenoter_widget(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test the Ugenoter widget wins when the account lists both."""
    entry = make_widget_config_entry(
        widgets=[WIDGET_MIN_UDDANNELSE_SSO, WIDGET_MIN_UDDANNELSE_UGEPLAN]
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data.mu_ugeplan_coordinator
    assert coordinator is not None
    assert coordinator.widget_id == WIDGET_MIN_UDDANNELSE_UGEPLAN


async def test_mu_tasks_absent_without_either_widget(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test no MU tasks coordinator when neither widget is on the account."""
    entry = make_widget_config_entry(widgets=[WIDGET_MEEBOOK])
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.mu_tasks_coordinator is None

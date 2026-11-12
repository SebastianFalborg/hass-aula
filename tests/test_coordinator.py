"""Tests for Aula coordinators."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from aula import (
    AulaAuthenticationError,
    AulaConnectionError,
    AulaRateLimitError,
    AulaRejectedError,
    AulaServerError,
    HttpRequestError,
)
from aula.widgets import EasyIQChildNotInPortal, EasyIQWrongChildSession
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.hass_aula.const import (
    MAX_PREVIEW_CHARS,
    TRANSIENT_FAILURE_TOLERANCE,
    WIDGET_MIN_UDDANNELSE_SSO,
    WIDGET_MIN_UDDANNELSE_TASKS,
    WIDGET_MIN_UDDANNELSE_UGEPLAN,
)
from custom_components.hass_aula.coordinator import (
    AulaCalendarCoordinator,
    AulaEasyIQCoordinator,
    AulaHuskelistenCoordinator,
    AulaLibraryCoordinator,
    AulaMeebookCoordinator,
    AulaMessagesCoordinator,
    AulaMUTasksCoordinator,
    AulaMUUgeplanCoordinator,
    AulaPresenceCoordinator,
)
from custom_components.hass_aula.data import (
    WidgetContext,
)

from .conftest import (
    mock_appointment,
    mock_calendar_event,
    mock_child,
    mock_daily_overview,
    mock_easyiq_homework,
    mock_library_loan,
    mock_library_status,
    mock_meebook_student_plan,
    mock_meebook_task,
    mock_message,
    mock_message_thread,
    mock_mu_task,
    mock_mu_weekly_letter,
    mock_mu_weekly_person,
    mock_profile,
    mock_team_reminder,
    mock_user_reminders,
)


def _create_config_entry():
    """Create a mock config entry for coordinator tests."""
    return MagicMock()


def _create_widget_context() -> WidgetContext:
    """Create a test widget context."""
    return WidgetContext(
        child_filter=["1000"],
        institution_filter=["inst_1"],
        session_uuid="session_123",
    )


def _create_token_manager() -> AsyncMock:
    """Create a mock token manager for coordinator tests."""
    tm = AsyncMock()
    tm.async_refresh_and_rebuild_client = AsyncMock()
    return tm


# --- Presence Coordinator Tests ---


async def test_presence_coordinator_fetch(hass: HomeAssistant) -> None:
    """Test presence coordinator fetches data for all children."""
    client = AsyncMock()
    overview = mock_daily_overview()
    client.get_daily_overview = AsyncMock(return_value=overview)
    client.get_presence_templates = AsyncMock(return_value=[])

    profile = mock_profile()
    tm = _create_token_manager()
    coordinator = AulaPresenceCoordinator(hass, client, profile, tm)

    entry = _create_config_entry()
    coordinator.config_entry = entry

    data = await coordinator._async_update_data()

    assert 1 in data
    assert data[1].overview is overview
    assert data[1].self_decider_start is None
    assert data[1].self_decider_end is None
    client.get_daily_overview.assert_called_once_with(1)


async def test_presence_coordinator_auth_error(hass: HomeAssistant) -> None:
    """Test presence coordinator raises ConfigEntryAuthFailed on auth error."""
    client = AsyncMock()
    client.get_daily_overview = AsyncMock(
        side_effect=AulaAuthenticationError("Auth failed", 401)
    )
    client.get_presence_templates = AsyncMock(return_value=[])

    profile = mock_profile()
    tm = _create_token_manager()
    tm.async_refresh_and_rebuild_client = AsyncMock(
        side_effect=AulaAuthenticationError("Refresh failed", 0)
    )
    coordinator = AulaPresenceCoordinator(hass, client, profile, tm)

    entry = _create_config_entry()
    coordinator.config_entry = entry

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_presence_coordinator_auth_error_refresh_succeeds(
    hass: HomeAssistant,
) -> None:
    """Test presence coordinator raises UpdateFailed after successful refresh."""
    client = AsyncMock()
    client.get_daily_overview = AsyncMock(
        side_effect=AulaAuthenticationError("Auth failed", 401)
    )
    client.get_presence_templates = AsyncMock(return_value=[])

    profile = mock_profile()
    tm = _create_token_manager()
    coordinator = AulaPresenceCoordinator(hass, client, profile, tm)

    entry = _create_config_entry()
    coordinator.config_entry = entry

    with pytest.raises(UpdateFailed, match="Session refreshed"):
        await coordinator._async_update_data()
    tm.async_refresh_and_rebuild_client.assert_awaited_once_with(client)


def _rejecting_presence_coordinator(
    hass: HomeAssistant, err: HttpRequestError
) -> tuple[AulaPresenceCoordinator, AsyncMock, AsyncMock]:
    """Create a presence coordinator whose daily overview read raises ``err``."""
    client = AsyncMock()
    client.get_daily_overview = AsyncMock(side_effect=err)
    client.get_presence_templates = AsyncMock(return_value=[])
    tm = _create_token_manager()
    tm.async_rebuild_after_rejection = AsyncMock(return_value=True)
    coordinator = AulaPresenceCoordinator(hass, client, mock_profile(), tm)
    coordinator.config_entry = _create_config_entry()
    return coordinator, client, tm


def _authorization_denied(
    status_code: int = 200, sub_code: int | None = None
) -> AulaRejectedError:
    """Create the error aula raises when Aula answers with code 10."""
    detail = "status code 10"
    if sub_code is not None:
        detail += f", sub-code {sub_code}"
    return AulaRejectedError(
        f"Aula rejected x ({detail}, HTTP {status_code})",
        status_code,
        code=10,
        sub_code=sub_code,
        api_method="x",
    )


@pytest.mark.parametrize(
    ("status_code", "sub_code"),
    [(200, None), (403, 33)],
)
async def test_authorization_denied_rebuilds_the_session(
    hass: HomeAssistant, status_code: int, sub_code: int | None
) -> None:
    """Aula refusing the session builds a new one instead of polling it forever."""
    coordinator, client, tm = _rejecting_presence_coordinator(
        hass, _authorization_denied(status_code, sub_code)
    )

    with pytest.raises(UpdateFailed, match="built a new session, retrying"):
        await coordinator._async_update_data()
    tm.async_rebuild_after_rejection.assert_awaited_once_with(client)


async def test_authorization_denied_rebuilds_the_client_the_request_used(
    hass: HomeAssistant,
) -> None:
    """A client swapped in mid-request is not the one reported as refused."""
    coordinator, client, tm = _rejecting_presence_coordinator(
        hass, _authorization_denied()
    )

    async def swap_then_reject(_child_id: int) -> None:
        coordinator.client = AsyncMock()
        raise _authorization_denied()

    client.get_daily_overview.side_effect = swap_then_reject

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    tm.async_rebuild_after_rejection.assert_awaited_once_with(client)


async def test_authorization_denied_within_the_cooldown(hass: HomeAssistant) -> None:
    """Without a rebuild the poll fails with Aula's rejection alone."""
    coordinator, _client, tm = _rejecting_presence_coordinator(
        hass, _authorization_denied()
    )
    tm.async_rebuild_after_rejection.return_value = False

    with pytest.raises(UpdateFailed) as exc:
        await coordinator._async_update_data()
    assert str(exc.value) == (
        "Error communicating with Aula API: Aula rejected x (status code 10, HTTP 200)"
    )


async def test_authorization_denied_rebuild_auth_failure_reauthenticates(
    hass: HomeAssistant,
) -> None:
    """A rebuild whose token refresh fails needs a new login."""
    coordinator, _client, tm = _rejecting_presence_coordinator(
        hass, _authorization_denied()
    )
    tm.async_rebuild_after_rejection.side_effect = AulaAuthenticationError(
        "Token refresh failed", 0
    )

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_authorization_denied_rebuild_connection_failure(
    hass: HomeAssistant,
) -> None:
    """A rebuild that cannot reach Aula fails the poll and says so."""
    coordinator, _client, tm = _rejecting_presence_coordinator(
        hass, _authorization_denied()
    )
    tm.async_rebuild_after_rejection.side_effect = AulaConnectionError("timeout")

    with pytest.raises(UpdateFailed, match="building a new session failed: timeout"):
        await coordinator._async_update_data()


@pytest.mark.parametrize(
    "err",
    [
        AulaRejectedError(
            "Aula rejected x (status code 1, HTTP 200)", 200, code=1, api_method="x"
        ),
        # Only aula's typed rejection counts, not a message that mentions code 10.
        HttpRequestError("Aula rejected x (status code 10)", 200),
        HttpRequestError("HTTP 400", 400),
        AulaServerError("HTTP 503", 503),
    ],
)
async def test_other_errors_do_not_rebuild_the_session(
    hass: HomeAssistant, err: HttpRequestError
) -> None:
    """Only an authorization denial rebuilds the session."""
    coordinator, _client, tm = _rejecting_presence_coordinator(hass, err)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    tm.async_rebuild_after_rejection.assert_not_awaited()


async def test_presence_coordinator_connection_error(hass: HomeAssistant) -> None:
    """Test presence coordinator raises UpdateFailed on connection error."""
    client = AsyncMock()
    client.get_daily_overview = AsyncMock(
        side_effect=AulaConnectionError("Connection failed", 0)
    )
    client.get_presence_templates = AsyncMock(return_value=[])

    profile = mock_profile()
    tm = _create_token_manager()
    coordinator = AulaPresenceCoordinator(hass, client, profile, tm)

    entry = _create_config_entry()
    coordinator.config_entry = entry

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_presence_coordinator_server_error(hass: HomeAssistant) -> None:
    """Test presence coordinator raises UpdateFailed on server error."""
    client = AsyncMock()
    client.get_daily_overview = AsyncMock(
        side_effect=AulaServerError("Server error", 500)
    )

    profile = mock_profile()
    tm = _create_token_manager()
    coordinator = AulaPresenceCoordinator(hass, client, profile, tm)

    entry = _create_config_entry()
    coordinator.config_entry = entry

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_presence_coordinator_tolerates_transient_failures(
    hass: HomeAssistant,
) -> None:
    """Test a short-lived 5xx keeps the previous data instead of going stale."""
    client = AsyncMock()
    overview = mock_daily_overview()
    client.get_daily_overview = AsyncMock(return_value=overview)
    client.get_presence_templates = AsyncMock(return_value=[])

    profile = mock_profile()
    tm = _create_token_manager()
    coordinator = AulaPresenceCoordinator(hass, client, profile, tm)
    coordinator.config_entry = _create_config_entry()

    coordinator.data = await coordinator._async_update_data()
    previous = coordinator.data

    client.get_daily_overview = AsyncMock(
        side_effect=AulaServerError("Server error", 503)
    )
    for _ in range(TRANSIENT_FAILURE_TOLERANCE):
        assert await coordinator._async_update_data() is previous

    # A sustained outage still surfaces, and keeps surfacing.
    for _ in range(2):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    # Recovery resets the budget.
    client.get_daily_overview = AsyncMock(return_value=overview)
    coordinator.data = await coordinator._async_update_data()
    client.get_daily_overview = AsyncMock(
        side_effect=AulaServerError("Server error", 503)
    )
    assert await coordinator._async_update_data() is coordinator.data


async def test_presence_coordinator_transient_tolerance_needs_data(
    hass: HomeAssistant,
) -> None:
    """Test the first-ever poll still fails loudly, with nothing to fall back on."""
    client = AsyncMock()
    client.get_daily_overview = AsyncMock(
        side_effect=AulaServerError("Server error", 503)
    )

    profile = mock_profile()
    tm = _create_token_manager()
    coordinator = AulaPresenceCoordinator(hass, client, profile, tm)
    coordinator.config_entry = _create_config_entry()

    assert coordinator.data is None
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_presence_coordinator_rate_limit_error(hass: HomeAssistant) -> None:
    """Test presence coordinator raises UpdateFailed on rate limit error."""
    client = AsyncMock()
    client.get_daily_overview = AsyncMock(
        side_effect=AulaRateLimitError("Rate limited", 429)
    )

    profile = mock_profile()
    tm = _create_token_manager()
    coordinator = AulaPresenceCoordinator(hass, client, profile, tm)

    entry = _create_config_entry()
    coordinator.config_entry = entry

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_presence_coordinator_api_error_envelope(hass: HomeAssistant) -> None:
    """Test an error code in a 200 response fails the update cleanly."""
    client = AsyncMock()
    # aula raises the base class itself for an explicit error envelope.
    client.get_daily_overview = AsyncMock(
        side_effect=HttpRequestError("Aula rejected method (status code 1)", 200)
    )

    profile = mock_profile()
    tm = _create_token_manager()
    coordinator = AulaPresenceCoordinator(hass, client, profile, tm)
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


# --- Calendar Coordinator Tests ---


async def test_calendar_coordinator_fetch(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Test the coordinator keeps aula's per-child calendars for 30 whole days."""
    freezer.move_to("2024-01-14T12:00:00+00:00")
    # Twins share a lesson: aula lists it under both.
    shared = mock_calendar_event(event_id=1, belongs_to=1, profiles=[1, 2])
    calendars = {1: [shared], 2: [shared]}
    client = AsyncMock()
    client.get_calendar_events_by_child = AsyncMock(return_value=calendars)

    profile = mock_profile([mock_child(1), mock_child(2, name="Second Child")])
    coordinator = AulaCalendarCoordinator(
        hass, client, profile, _create_token_manager()
    )
    coordinator.config_entry = _create_config_entry()

    data = await coordinator._async_update_data()

    assert data == calendars
    child_ids, start, end = client.get_calendar_events_by_child.await_args.args
    assert child_ids == [1, 2]
    assert (start.date(), end.date()) == (date(2024, 1, 14), date(2024, 2, 13))
    assert (start.hour, start.minute) == (0, 0)


async def test_calendar_coordinator_auth_error(hass: HomeAssistant) -> None:
    """Test calendar coordinator raises ConfigEntryAuthFailed on auth error."""
    client = AsyncMock()
    client.get_calendar_events_by_child = AsyncMock(
        side_effect=AulaAuthenticationError("Auth failed", 401)
    )

    profile = mock_profile()
    tm = _create_token_manager()
    tm.async_refresh_and_rebuild_client = AsyncMock(
        side_effect=AulaAuthenticationError("Refresh failed", 0)
    )
    coordinator = AulaCalendarCoordinator(hass, client, profile, tm)

    entry = _create_config_entry()
    coordinator.config_entry = entry

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_calendar_coordinator_connection_error(hass: HomeAssistant) -> None:
    """Test calendar coordinator raises UpdateFailed on connection error."""
    client = AsyncMock()
    client.get_calendar_events_by_child = AsyncMock(
        side_effect=AulaConnectionError("Connection failed", 0)
    )

    profile = mock_profile()
    tm = _create_token_manager()
    coordinator = AulaCalendarCoordinator(hass, client, profile, tm)

    entry = _create_config_entry()
    coordinator.config_entry = entry

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


# --- Library Coordinator Tests ---


async def test_library_coordinator_fetch(hass: HomeAssistant) -> None:
    """Test library coordinator fetches and distributes loans to children."""
    client = AsyncMock()
    loan = mock_library_loan(patron_display_name="Test Child")
    longterm = mock_library_loan(
        loan_id=2, title="Long Book", patron_display_name="Test Child"
    )
    status = mock_library_status(
        loans=[loan], longterm_loans=[longterm], reservations=[{"id": 1}]
    )
    client.widgets = MagicMock()
    client.widgets.get_library_status = AsyncMock(return_value=status)

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaLibraryCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    data = await coordinator._async_update_data()

    assert 1 in data
    assert len(data[1].loans) == 1
    assert data[1].loans[0] is loan
    assert len(data[1].longterm_loans) == 1
    assert data[1].longterm_loans[0] is longterm
    assert len(data[1].reservations) == 1


async def test_library_coordinator_auth_error(hass: HomeAssistant) -> None:
    """Test library coordinator raises ConfigEntryAuthFailed on auth error."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_library_status = AsyncMock(
        side_effect=AulaAuthenticationError("Auth failed", 401)
    )

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    tm.async_refresh_and_rebuild_client = AsyncMock(
        side_effect=AulaAuthenticationError("Refresh failed", 0)
    )
    coordinator = AulaLibraryCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_library_coordinator_connection_error(hass: HomeAssistant) -> None:
    """Test library coordinator raises UpdateFailed on connection error."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_library_status = AsyncMock(
        side_effect=AulaConnectionError("Connection failed", 0)
    )

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaLibraryCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_library_coordinator_multi_child(hass: HomeAssistant) -> None:
    """Test library coordinator distributes loans to correct children."""
    from .conftest import mock_child

    child1 = mock_child(child_id=1, name="Alice")
    child2 = mock_child(child_id=2, name="Bob")
    profile = mock_profile(children=[child1, child2])

    loan_alice = mock_library_loan(loan_id=1, patron_display_name="Alice")
    loan_bob = mock_library_loan(loan_id=2, patron_display_name="Bob")
    status = mock_library_status(loans=[loan_alice, loan_bob])

    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_library_status = AsyncMock(return_value=status)

    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaLibraryCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    data = await coordinator._async_update_data()

    assert len(data[1].loans) == 1
    assert data[1].loans[0] is loan_alice
    assert len(data[2].loans) == 1
    assert data[2].loans[0] is loan_bob


# --- MU Tasks Coordinator Tests ---


async def test_mu_tasks_coordinator_uses_the_given_widget(hass: HomeAssistant) -> None:
    """Test the coordinator mints its token with the widget it was given."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_mu_tasks = AsyncMock(return_value=[])

    coordinator = AulaMUTasksCoordinator(
        hass,
        client,
        mock_profile(),
        _create_widget_context(),
        _create_token_manager(),
        WIDGET_MIN_UDDANNELSE_SSO,
    )
    coordinator.config_entry = _create_config_entry()

    await coordinator._async_update_data()

    # A school without the opgaver widget still has opgaver; the endpoint
    # accepts an SSO token with the same parameters.
    assert client.widgets.get_mu_tasks.call_args.kwargs["widget_id"] == (
        WIDGET_MIN_UDDANNELSE_SSO
    )


async def test_mu_tasks_coordinator_fetch(hass: HomeAssistant) -> None:
    """Test MU tasks coordinator fetches and distributes tasks."""
    client = AsyncMock()
    task = mock_mu_task(student_name="Test Child")
    client.widgets = MagicMock()
    client.widgets.get_mu_tasks = AsyncMock(return_value=[task])

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaMUTasksCoordinator(
        hass, client, profile, ctx, tm, WIDGET_MIN_UDDANNELSE_TASKS
    )
    coordinator.config_entry = _create_config_entry()

    data = await coordinator._async_update_data()

    assert 1 in data
    assert len(data[1]) == 1
    assert data[1][0] is task


async def test_mu_tasks_coordinator_auth_error(hass: HomeAssistant) -> None:
    """Test MU tasks coordinator raises ConfigEntryAuthFailed on auth error."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_mu_tasks = AsyncMock(
        side_effect=AulaAuthenticationError("Auth failed", 401)
    )

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    tm.async_refresh_and_rebuild_client = AsyncMock(
        side_effect=AulaAuthenticationError("Refresh failed", 0)
    )
    coordinator = AulaMUTasksCoordinator(
        hass, client, profile, ctx, tm, WIDGET_MIN_UDDANNELSE_TASKS
    )
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_mu_tasks_coordinator_connection_error(hass: HomeAssistant) -> None:
    """Test MU tasks coordinator raises UpdateFailed on connection error."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_mu_tasks = AsyncMock(
        side_effect=AulaConnectionError("Connection failed", 0)
    )

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaMUTasksCoordinator(
        hass, client, profile, ctx, tm, WIDGET_MIN_UDDANNELSE_TASKS
    )
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


# --- EasyIQ Coordinator Tests ---


async def test_easyiq_coordinator_fetch(hass: HomeAssistant) -> None:
    """Test EasyIQ coordinator fetches weekplan and homework per child."""
    client = AsyncMock()
    appt = mock_appointment()
    hw = mock_easyiq_homework()
    client.widgets = MagicMock()
    client.widgets.get_easyiq_weekplan = AsyncMock(return_value=[appt])
    client.widgets.get_easyiq_weekplan_text = AsyncMock(
        return_value="Generelt: husk gympakke"
    )
    client.widgets.get_easyiq_homework = AsyncMock(return_value=[hw])

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaEasyIQCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    data = await coordinator._async_update_data()

    assert 1 in data
    assert len(data[1].weekplan) == 1
    assert data[1].weekplan[0] is appt
    assert len(data[1].homework) == 1
    assert data[1].homework[0] is hw
    assert data[1].week_text == "Generelt: husk gympakke"


async def test_easyiq_coordinator_week_text_failure_keeps_the_grid(
    hass: HomeAssistant,
) -> None:
    """A failed week-text read costs the text, not the lesson grid."""
    client = AsyncMock()
    appt = mock_appointment()
    client.widgets = MagicMock()
    client.widgets.get_easyiq_weekplan = AsyncMock(return_value=[appt])
    client.widgets.get_easyiq_weekplan_text = AsyncMock(
        side_effect=AulaConnectionError("Connection failed", 0)
    )
    client.widgets.get_easyiq_homework = AsyncMock(return_value=[])

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaEasyIQCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    data = await coordinator._async_update_data()

    assert len(data[1].weekplan) == 1
    assert data[1].week_text == ""


async def test_easyiq_coordinator_passes_portal_identifiers(
    hass: HomeAssistant,
) -> None:
    """Test EasyIQ calls carry the identifiers the school portal requires."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_easyiq_weekplan = AsyncMock(return_value=[])
    client.widgets.get_easyiq_weekplan_text = AsyncMock(return_value="")
    client.widgets.get_easyiq_homework = AsyncMock(return_value=[])

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaEasyIQCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    await coordinator._async_update_data()

    for api_call in (
        client.widgets.get_easyiq_weekplan.call_args,
        client.widgets.get_easyiq_homework.call_args,
    ):
        # The child's UniLogin identifies the child, their institution profile
        # ID identifies the row owner, and the portal filters on every child.
        assert api_call.kwargs["child_id"] == "1000"
        assert api_call.kwargs["child_profile_id"] == "1"
        assert api_call.kwargs["all_child_user_ids"] == ["1000"]


async def test_easyiq_coordinator_auth_error(hass: HomeAssistant) -> None:
    """Test EasyIQ coordinator raises ConfigEntryAuthFailed on auth error."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_easyiq_weekplan = AsyncMock(
        side_effect=AulaAuthenticationError("Auth failed", 401)
    )
    client.widgets.get_easyiq_homework = AsyncMock(return_value=[])

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    tm.async_refresh_and_rebuild_client = AsyncMock(
        side_effect=AulaAuthenticationError("Refresh failed", 0)
    )
    coordinator = AulaEasyIQCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_easyiq_coordinator_connection_error(hass: HomeAssistant) -> None:
    """Test EasyIQ coordinator raises UpdateFailed on connection error."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_easyiq_weekplan = AsyncMock(
        side_effect=AulaConnectionError("Connection failed", 0)
    )
    client.widgets.get_easyiq_homework = AsyncMock(return_value=[])

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaEasyIQCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_easyiq_coordinator_passes_guardian_institutions(
    hass: HomeAssistant,
) -> None:
    """Test EasyIQ narrows the read to one child but opens the session to all."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_easyiq_weekplan = AsyncMock(return_value=[])
    client.widgets.get_easyiq_weekplan_text = AsyncMock(return_value="")
    client.widgets.get_easyiq_homework = AsyncMock(return_value=[])

    # A guardian with a child at each of two schools. Reading child 1's week
    # needs their institution alone as the filter, but the portal session has
    # to be established under both or the second school's child is not found
    # (aula 1.8.0).
    profile = mock_profile(children=[mock_child(1), mock_child(2)])
    ctx = WidgetContext(
        child_filter=["1000", "2000"],
        institution_filter=["inst_1", "inst_2"],
        session_uuid="session_123",
    )
    tm = _create_token_manager()
    coordinator = AulaEasyIQCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    await coordinator._async_update_data()

    for mock in (
        client.widgets.get_easyiq_weekplan,
        client.widgets.get_easyiq_homework,
    ):
        by_child = {
            call.kwargs["child_id"]: call.kwargs for call in mock.call_args_list
        }
        assert by_child["1000"]["institution_filter"] == ["inst_1"]
        assert by_child["2000"]["institution_filter"] == ["inst_2"]
        for kwargs in by_child.values():
            assert kwargs["all_institution_filter"] == ["inst_1", "inst_2"]


async def test_easyiq_coordinator_child_not_in_portal(hass: HomeAssistant) -> None:
    """Test a child EasyIQ has no record of empties only their own data."""
    appt = mock_appointment()
    hw = mock_easyiq_homework()
    unknown_child = "EasyIQ's portal lists no child matching 2000"

    def _weekplan(**kwargs: object) -> list[object]:
        if kwargs["child_id"] != "1000":
            raise EasyIQChildNotInPortal(unknown_child)
        return [appt]

    def _homework(**kwargs: object) -> list[object]:
        if kwargs["child_id"] != "1000":
            raise EasyIQChildNotInPortal(unknown_child)
        return [hw]

    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_easyiq_weekplan = AsyncMock(side_effect=_weekplan)
    client.widgets.get_easyiq_homework = AsyncMock(side_effect=_homework)

    # Child 2 is at a daycare, which is not on EasyIQ at all. Before aula 1.8.0
    # that read returned a sibling's week; now it raises, and one such child
    # must not take the whole update down with them.
    profile = mock_profile(children=[mock_child(1), mock_child(2)])
    ctx = WidgetContext(
        child_filter=["1000", "2000"],
        institution_filter=["inst_1", "inst_2"],
        session_uuid="session_123",
    )
    tm = _create_token_manager()
    coordinator = AulaEasyIQCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    data = await coordinator._async_update_data()

    assert data[1].weekplan == [appt]
    assert data[1].homework == [hw]
    assert data[2].weekplan == []
    assert data[2].homework == []


async def test_easyiq_coordinator_wrong_child_session(hass: HomeAssistant) -> None:
    """Test a session on the wrong child fails the update instead of publishing."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_easyiq_weekplan = AsyncMock(
        side_effect=EasyIQWrongChildSession("session is on another child")
    )
    client.widgets.get_easyiq_homework = AsyncMock(return_value=[])

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaEasyIQCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_easyiq_coordinator_children_not_identified(
    hass: HomeAssistant,
) -> None:
    """Test aula's refusal to guess between several children fails the update."""
    client = AsyncMock()
    client.widgets = MagicMock()
    refusal = RuntimeError("EasyIQ's portal did not identify the children")
    client.widgets.get_easyiq_weekplan = AsyncMock(side_effect=refusal)
    client.widgets.get_easyiq_homework = AsyncMock(side_effect=refusal)

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaEasyIQCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(UpdateFailed, match="could not tell the children apart"):
        await coordinator._async_update_data()


# --- Meebook Coordinator Tests ---


@pytest.mark.parametrize(
    ("now", "weeks"),
    [
        (datetime(2026, 8, 17, 12, tzinfo=UTC), ("2026-W34", "2026-W35")),
        (datetime(2026, 12, 28, 12, tzinfo=UTC), ("2026-W53", "2027-W01")),
        (datetime(2027, 1, 1, 12, tzinfo=UTC), ("2026-W53", "2027-W01")),
    ],
)
async def test_meebook_coordinator_fetch(
    hass: HomeAssistant, now: datetime, weeks: tuple[str, str]
) -> None:
    """Test Meebook coordinator fetches current and next week."""
    client = AsyncMock()
    current_task = mock_meebook_task(title="Current week")
    next_task = mock_meebook_task(task_id=2, title="Next week")
    current_plan = mock_meebook_student_plan(name="Test Child", tasks=[current_task])
    next_plan = mock_meebook_student_plan(name="Test Child", tasks=[next_task])
    client.widgets = MagicMock()
    client.widgets.get_meebook_weekplan = AsyncMock(
        side_effect=[[current_plan], [next_plan]]
    )

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaMeebookCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    with patch(
        "custom_components.hass_aula.coordinator.dt_util.now",
        return_value=now,
    ):
        data = await coordinator._async_update_data()

    assert data.current[1] == [current_task]
    assert data.next_week is not None
    assert data.next_week[1] == [next_task]
    assert client.widgets.get_meebook_weekplan.await_args_list == [
        call(
            child_filter=ctx.child_filter,
            institution_filter=ctx.institution_filter,
            week=week,
            session_uuid=ctx.session_uuid,
        )
        for week in weeks
    ]


async def test_meebook_coordinator_fetch_uses_home_assistant_timezone(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Test the requested weeks follow HA's timezone, not UTC."""
    await hass.config.async_set_time_zone("Pacific/Auckland")
    # 23:00 UTC on Sunday of 2026-W33 is already Monday of 2026-W34 in Auckland.
    freezer.move_to("2026-08-16T23:00:00+00:00")

    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_meebook_weekplan = AsyncMock(return_value=[])
    coordinator = AulaMeebookCoordinator(
        hass, client, mock_profile(), _create_widget_context(), _create_token_manager()
    )
    coordinator.config_entry = _create_config_entry()

    await coordinator._async_update_data()

    assert [
        c.kwargs["week"] for c in client.widgets.get_meebook_weekplan.await_args_list
    ] == ["2026-W34", "2026-W35"]


@pytest.mark.parametrize(
    "error_type", [AulaConnectionError, AulaServerError, AulaRateLimitError]
)
async def test_meebook_next_week_failure_recovers(
    hass: HomeAssistant,
    error_type: type[Exception],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keep current data, clear stale next tasks, and recover on refresh."""
    client = AsyncMock()
    plan = mock_meebook_student_plan(name="Test Child")
    client.widgets.get_meebook_weekplan.side_effect = [
        [plan],
        [plan],
        [plan],
        error_type("private upstream response", 503),
        [plan],
        [],
    ]
    coordinator = AulaMeebookCoordinator(
        hass, client, mock_profile(), _create_widget_context(), _create_token_manager()
    )
    coordinator.config_entry = _create_config_entry()
    await coordinator.async_refresh()
    assert coordinator.data.next_week is not None
    assert coordinator.data.next_week[1]
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data.current[1]
    assert coordinator.data.next_week is None
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings
    # The warning names the problem, never the upstream payload.
    assert all("private upstream response" not in r.getMessage() for r in warnings)
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data.next_week == {1: []}


async def test_meebook_coordinator_refresh_across_week_boundary(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Test a refresh in a new week relabels nothing and drops old tasks."""
    await hass.config.async_set_time_zone("Europe/Copenhagen")
    freezer.move_to("2026-12-28T09:00:00+01:00")

    client = AsyncMock()
    client.widgets = MagicMock()
    this_week = mock_meebook_student_plan(
        name="Test Child", tasks=[mock_meebook_task(title="Week 53")]
    )
    new_year = mock_meebook_student_plan(
        name="Test Child", tasks=[mock_meebook_task(task_id=2, title="Week 1")]
    )
    client.widgets.get_meebook_weekplan = AsyncMock(
        side_effect=[[this_week], [new_year], [new_year], []]
    )
    coordinator = AulaMeebookCoordinator(
        hass, client, mock_profile(), _create_widget_context(), _create_token_manager()
    )
    coordinator.config_entry = _create_config_entry()

    await coordinator.async_refresh()
    assert [t.title for t in coordinator.data.current[1]] == ["Week 53"]
    assert coordinator.data.next_week is not None
    assert [t.title for t in coordinator.data.next_week[1]] == ["Week 1"]

    freezer.move_to("2027-01-04T09:00:00+01:00")
    await coordinator.async_refresh()

    assert [t.title for t in coordinator.data.current[1]] == ["Week 1"]
    assert coordinator.data.next_week == {1: []}
    assert [
        c.kwargs["week"] for c in client.widgets.get_meebook_weekplan.await_args_list
    ] == ["2026-W53", "2027-W01", "2027-W01", "2027-W02"]


@pytest.mark.parametrize("refresh_fails", [False, True])
async def test_meebook_next_week_auth_error(
    hass: HomeAssistant, refresh_fails: bool
) -> None:
    """Next-week authentication failures must still refresh or reauthenticate."""
    client = AsyncMock()
    client.widgets.get_meebook_weekplan.side_effect = [
        [],
        AulaAuthenticationError("expired", 401),
    ]
    tm = _create_token_manager()
    if refresh_fails:
        tm.async_refresh_and_rebuild_client.side_effect = AulaAuthenticationError(
            "expired", 401
        )
    coordinator = AulaMeebookCoordinator(
        hass, client, mock_profile(), _create_widget_context(), tm
    )
    with pytest.raises(ConfigEntryAuthFailed if refresh_fails else UpdateFailed):
        await coordinator._async_update_data()
    tm.async_refresh_and_rebuild_client.assert_awaited_once()


async def test_meebook_coordinator_auth_error(hass: HomeAssistant) -> None:
    """Test Meebook coordinator raises ConfigEntryAuthFailed on auth error."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_meebook_weekplan = AsyncMock(
        side_effect=AulaAuthenticationError("Auth failed", 401)
    )

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    tm.async_refresh_and_rebuild_client = AsyncMock(
        side_effect=AulaAuthenticationError("Refresh failed", 0)
    )
    coordinator = AulaMeebookCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_meebook_coordinator_connection_error(hass: HomeAssistant) -> None:
    """Test Meebook coordinator raises UpdateFailed on connection error."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_meebook_weekplan = AsyncMock(
        side_effect=AulaConnectionError("Connection failed", 0)
    )

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaMeebookCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    # A failed current week must not trigger the optional next-week request.
    assert client.widgets.get_meebook_weekplan.await_count == 1


# --- Huskelisten Coordinator Tests ---


async def test_huskelisten_coordinator_fetch(hass: HomeAssistant) -> None:
    """Test Huskelisten coordinator fetches and distributes reminders."""
    client = AsyncMock()
    team_r = mock_team_reminder()
    ur = mock_user_reminders(user_name="Test Child", team_reminders=[team_r])
    client.widgets = MagicMock()
    client.widgets.get_momo_reminders = AsyncMock(return_value=[ur])

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaHuskelistenCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    data = await coordinator._async_update_data()

    assert 1 in data
    assert len(data[1].team_reminders) == 1
    assert data[1].team_reminders[0] is team_r


async def test_huskelisten_coordinator_auth_error(hass: HomeAssistant) -> None:
    """Test Huskelisten coordinator raises ConfigEntryAuthFailed on auth error."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_momo_reminders = AsyncMock(
        side_effect=AulaAuthenticationError("Auth failed", 401)
    )

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    tm.async_refresh_and_rebuild_client = AsyncMock(
        side_effect=AulaAuthenticationError("Refresh failed", 0)
    )
    coordinator = AulaHuskelistenCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_huskelisten_coordinator_connection_error(hass: HomeAssistant) -> None:
    """Test Huskelisten coordinator raises UpdateFailed on connection error."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_momo_reminders = AsyncMock(
        side_effect=AulaConnectionError("Connection failed", 0)
    )

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaHuskelistenCoordinator(hass, client, profile, ctx, tm)
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


# --- MU Ugeplan Coordinator Tests ---


async def test_mu_ugeplan_coordinator_fetch(hass: HomeAssistant) -> None:
    """Test MU ugeplan coordinator fetches and distributes weekly notes."""
    client = AsyncMock()
    person = mock_mu_weekly_person(name="Test Child")
    next_person = mock_mu_weekly_person(
        name="Test Child",
        letters=[mock_mu_weekly_letter(group_name="3A", week_number=6)],
    )
    client.widgets = MagicMock()
    client.widgets.get_ugeplan = AsyncMock(side_effect=[[person], [next_person]])

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaMUUgeplanCoordinator(
        hass, client, profile, ctx, tm, WIDGET_MIN_UDDANNELSE_UGEPLAN
    )
    coordinator.config_entry = _create_config_entry()

    data = await coordinator._async_update_data()

    assert 1 in data.current
    assert len(data.current[1]) == 1
    assert data.current[1][0].group_name == "3A"
    assert 1 in data.next_week
    assert len(data.next_week[1]) == 1
    assert data.next_week[1][0].week_number == 6


async def test_mu_ugeplan_coordinator_uses_its_widget(hass: HomeAssistant) -> None:
    """Test the coordinator mints tokens with the widget it was given."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_ugeplan = AsyncMock(return_value=[])

    coordinator = AulaMUUgeplanCoordinator(
        hass,
        client,
        mock_profile(),
        _create_widget_context(),
        _create_token_manager(),
        WIDGET_MIN_UDDANNELSE_SSO,
    )
    coordinator.config_entry = _create_config_entry()

    await coordinator._async_update_data()

    for request in client.widgets.get_ugeplan.await_args_list:
        assert request.kwargs["widget_id"] == WIDGET_MIN_UDDANNELSE_SSO


async def test_mu_ugeplan_coordinator_auth_error(hass: HomeAssistant) -> None:
    """Test MU ugeplan coordinator raises ConfigEntryAuthFailed on auth error."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_ugeplan = AsyncMock(
        side_effect=AulaAuthenticationError("Auth failed", 401)
    )

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    tm.async_refresh_and_rebuild_client = AsyncMock(
        side_effect=AulaAuthenticationError("Refresh failed", 0)
    )
    coordinator = AulaMUUgeplanCoordinator(
        hass, client, profile, ctx, tm, WIDGET_MIN_UDDANNELSE_UGEPLAN
    )
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_mu_ugeplan_coordinator_connection_error(hass: HomeAssistant) -> None:
    """Test MU ugeplan coordinator raises UpdateFailed on connection error."""
    client = AsyncMock()
    client.widgets = MagicMock()
    client.widgets.get_ugeplan = AsyncMock(
        side_effect=AulaConnectionError("Connection failed", 0)
    )

    profile = mock_profile()
    ctx = _create_widget_context()
    tm = _create_token_manager()
    coordinator = AulaMUUgeplanCoordinator(
        hass, client, profile, ctx, tm, WIDGET_MIN_UDDANNELSE_UGEPLAN
    )
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_messages_coordinator_builds_previews(hass: HomeAssistant) -> None:
    """Test messages coordinator shapes threads and messages into previews."""
    client = AsyncMock()
    threads = [
        mock_message_thread(thread_id="1", subject="Skolefest"),
        mock_message_thread(thread_id="2", subject="Lejrskole"),
    ]
    client.get_message_threads = AsyncMock(
        side_effect=lambda filter_on=None: (
            threads[:1] if filter_on == "unread" else threads
        )
    )
    client.get_messages_for_thread = AsyncMock(
        return_value=[mock_message(content="Kære forældre", sender="Anne Jensen")]
    )

    coordinator = AulaMessagesCoordinator(hass, client, _create_token_manager())
    coordinator.config_entry = _create_config_entry()

    data = await coordinator._async_update_data()

    assert data.unread_count == 1
    assert len(data.messages) == 2
    assert data.messages[0].subject == "Skolefest"
    assert data.messages[0].sender == "Anne Jensen"
    assert data.messages[0].date == "2026-08-10T07:15:00+00:00"
    assert data.messages[0].preview == "Kære forældre"
    assert data.messages[0].unread is True
    assert data.messages[1].unread is False


async def test_messages_coordinator_clips_preview(hass: HomeAssistant) -> None:
    """Test messages coordinator clips long message bodies."""
    client = AsyncMock()
    client.get_message_threads = AsyncMock(return_value=[mock_message_thread()])
    client.get_messages_for_thread = AsyncMock(
        return_value=[mock_message(content="x" * 500)]
    )

    coordinator = AulaMessagesCoordinator(hass, client, _create_token_manager())
    coordinator.config_entry = _create_config_entry()

    data = await coordinator._async_update_data()

    assert len(data.messages[0].preview) == MAX_PREVIEW_CHARS


async def test_messages_coordinator_skips_failed_thread(hass: HomeAssistant) -> None:
    """Test a failing per-thread fetch does not fail the whole update."""
    client = AsyncMock()
    client.get_message_threads = AsyncMock(return_value=[mock_message_thread()])
    client.get_messages_for_thread = AsyncMock(side_effect=TimeoutError("boom"))

    coordinator = AulaMessagesCoordinator(hass, client, _create_token_manager())
    coordinator.config_entry = _create_config_entry()

    data = await coordinator._async_update_data()

    assert len(data.messages) == 1
    assert data.messages[0].preview == ""
    assert data.messages[0].sender is None
    # Falls back to the thread's own timestamp.
    assert data.messages[0].date == "2026-08-10T07:00:00+00:00"


async def test_messages_coordinator_auth_error(hass: HomeAssistant) -> None:
    """Test messages coordinator raises ConfigEntryAuthFailed on auth error."""
    client = AsyncMock()
    client.get_message_threads = AsyncMock(
        side_effect=AulaAuthenticationError("Auth failed", 401)
    )

    tm = _create_token_manager()
    tm.async_refresh_and_rebuild_client = AsyncMock(
        side_effect=AulaAuthenticationError("Refresh failed", 0)
    )
    coordinator = AulaMessagesCoordinator(hass, client, tm)
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_messages_coordinator_connection_error(hass: HomeAssistant) -> None:
    """Test messages coordinator raises UpdateFailed on connection error."""
    client = AsyncMock()
    client.get_message_threads = AsyncMock(
        side_effect=AulaConnectionError("Connection failed", 0)
    )

    coordinator = AulaMessagesCoordinator(hass, client, _create_token_manager())
    coordinator.config_entry = _create_config_entry()

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

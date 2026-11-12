"""Tests for Aula sensor platform."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from aula import AulaConnectionError, AulaServerError
from aula.models.presence import PresenceState
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import JSONEncoder

from custom_components.hass_aula.const import (
    MAX_MESSAGE_ITEMS,
    TRANSIENT_FAILURE_TOLERANCE,
    WIDGET_BIBLIOTEKET,
    WIDGET_EASYIQ_HOMEWORK,
    WIDGET_EASYIQ_WEEKPLAN,
    WIDGET_HUSKELISTEN,
    WIDGET_MEEBOOK,
    WIDGET_MEEBOOK_OVERVIEW,
    WIDGET_MIN_UDDANNELSE_TASKS,
    WIDGET_MIN_UDDANNELSE_UGEPLAN,
)
from custom_components.hass_aula.sensor import MAX_ATTRIBUTE_ITEMS

from .conftest import (
    make_config_entry,
    make_widget_config_entry,
    mock_appointment,
    mock_assignment_reminder,
    mock_daily_overview,
    mock_easyiq_homework,
    mock_library_loan,
    mock_library_status,
    mock_meebook_student_plan,
    mock_meebook_task,
    mock_mu_task,
    mock_mu_weekly_letter,
    mock_mu_weekly_person,
    mock_presence_templates,
    mock_team_reminder,
    mock_user_reminders,
)


async def test_presence_status_sensor(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test presence status sensor reports correct state."""
    overview = mock_daily_overview(status=PresenceState.PRESENT)
    mock_aula_client.get_daily_overview = AsyncMock(return_value=overview)

    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_presence_status")
    assert state is not None
    assert state.state == "present"


async def test_presence_status_sick(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test presence status sensor when child is sick."""
    overview = mock_daily_overview(status=PresenceState.SICK)
    mock_aula_client.get_daily_overview = AsyncMock(return_value=overview)

    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_presence_status")
    assert state is not None
    assert state.state == "sick"


async def test_presence_status_not_present(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test presence status sensor when child is not present."""
    overview = mock_daily_overview(status=PresenceState.NOT_PRESENT)
    mock_aula_client.get_daily_overview = AsyncMock(return_value=overview)

    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_presence_status")
    assert state is not None
    assert state.state == "not_present"


async def test_presence_sensor_attributes(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that check-in/out times and location are exposed as attributes."""
    freezer.move_to("2024-01-15 12:00:00+00:00")
    check_in = datetime(2024, 1, 15, 8, 30, tzinfo=UTC)
    check_out = datetime(2024, 1, 15, 15, 0, tzinfo=UTC)
    entry_time = datetime(2024, 1, 15, 8, 25, tzinfo=UTC)
    exit_time = datetime(2024, 1, 15, 15, 5, tzinfo=UTC)
    overview = mock_daily_overview(
        check_in_time=check_in,
        check_out_time=check_out,
        entry_time=entry_time,
        exit_time=exit_time,
        exit_with="Parent",
        location="Room 1",
        sleep_intervals=[
            {"id": 27707363, "startTime": "12:05:00", "endTime": "13:15:00"}
        ],
    )
    mock_aula_client.get_daily_overview = AsyncMock(return_value=overview)
    mock_aula_client.get_presence_templates = AsyncMock(
        return_value=mock_presence_templates(
            child_id=1,
            by_date="2024-01-15",
            self_decider_start="14:00",
            self_decider_end="16:30",
        )
    )

    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_presence_status")
    assert state is not None
    assert state.attributes["check_in_time"] == check_in
    assert state.attributes["check_out_time"] == check_out
    assert state.attributes["entry_time"] == entry_time
    assert state.attributes["exit_time"] == exit_time
    assert state.attributes["exit_with"] == "Parent"
    assert state.attributes["self_decider_start_time"] == "14:00"
    assert state.attributes["self_decider_end_time"] == "16:30"
    # aula delivers this as a PresenceLocation; the attribute stays the name.
    assert state.attributes["location"] == "Room 1"
    # Naps are passed through as the institution registered them, keys and all.
    assert state.attributes["sleep_intervals"] == [
        {"id": 27707363, "startTime": "12:05:00", "endTime": "13:15:00"}
    ]
    # The recorder and the websocket API both JSON-encode state attributes, so
    # publishing the object itself breaks them rather than the assertion above.
    json.dumps(dict(state.attributes), cls=JSONEncoder)


async def test_presence_sensor_survives_a_transient_api_failure(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test one failed poll does not flip the sensor to unavailable."""
    mock_aula_client.get_daily_overview = AsyncMock(
        return_value=mock_daily_overview(location="Room 1")
    )
    mock_aula_client.get_presence_templates = AsyncMock(return_value=[])

    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_id = "sensor.test_child_presence_status"
    assert hass.states.get(entity_id).state != STATE_UNAVAILABLE

    # Aula answers a poll with 503, as it does sporadically in practice.
    mock_aula_client.get_daily_overview = AsyncMock(
        side_effect=AulaServerError("Server error", 503)
    )
    await entry.runtime_data.presence_coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state != STATE_UNAVAILABLE
    assert state.attributes["location"] == "Room 1"

    # A sustained outage still marks it unavailable.
    for _ in range(TRANSIENT_FAILURE_TOLERANCE):
        await entry.runtime_data.presence_coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


async def test_sensor_unavailable_when_no_overview(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test sensors show unavailable when overview is None."""
    mock_aula_client.get_daily_overview = AsyncMock(return_value=None)

    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_presence_status")
    assert state is not None
    assert state.state == "unknown"


async def test_all_presence_states(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test that all presence states are correctly reported."""
    expected_states = {
        PresenceState.NOT_PRESENT: "not_present",
        PresenceState.SICK: "sick",
        PresenceState.REPORTED_ABSENT: "reported_absent",
        PresenceState.PRESENT: "present",
        PresenceState.FIELDTRIP: "fieldtrip",
        PresenceState.SLEEPING: "sleeping",
        PresenceState.SPARE_TIME_ACTIVITY: "spare_time_activity",
        PresenceState.PHYSICAL_PLACEMENT: "physical_placement",
        PresenceState.CHECKED_OUT: "checked_out",
    }

    for presence_state, expected_value in expected_states.items():
        overview = mock_daily_overview(status=presence_state)
        mock_aula_client.get_daily_overview = AsyncMock(return_value=overview)

        entry = make_config_entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("sensor.test_child_presence_status")
        assert state is not None
        assert state.state == expected_value, (
            f"Expected {expected_value} for {presence_state}"
        )

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()


# --- Notification Sensor Tests ---


async def test_notifications_sensor_counts_all(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test that notifications sensor counts all notifications."""
    from .conftest import mock_notification

    n1 = mock_notification(notification_id="1")
    n2 = mock_notification(notification_id="2")
    n3 = mock_notification(notification_id="3")
    mock_aula_client.get_notifications_for_active_profile = AsyncMock(
        return_value=[n1, n2, n3]
    )

    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_parent_unread_notifications")
    assert state is not None
    assert state.state == "3"


async def test_latest_messages_sensor_state_and_attributes(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test latest messages sensor reports unread count and message details."""
    from .conftest import mock_message, mock_message_thread

    threads = [
        mock_message_thread(thread_id="1", subject="Skolefest"),
        mock_message_thread(thread_id="2", subject="Lejrskole"),
    ]
    mock_aula_client.get_message_threads = AsyncMock(
        side_effect=lambda filter_on=None: (
            threads[:1] if filter_on == "unread" else threads
        )
    )
    mock_aula_client.get_messages_for_thread = AsyncMock(
        return_value=[mock_message(content="Kære forældre", sender="Anne Jensen")]
    )

    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_parent_latest_messages")
    assert state is not None
    # One of the two threads is unread.
    assert state.state == "1"

    messages = state.attributes["messages"]
    assert len(messages) == 2
    # thread_id lets an automation feed get_thread_messages straight from here.
    assert messages[0]["thread_id"] == "1"
    assert messages[1]["thread_id"] == "2"
    assert messages[0]["subject"] == "Skolefest"
    assert messages[0]["sender"] == "Anne Jensen"
    assert messages[0]["preview"] == "Kære forældre"
    assert messages[0]["date"] == "2026-08-10T07:15:00+00:00"
    assert messages[0]["unread"] is True
    # Second thread is not in the unread list.
    assert messages[1]["unread"] is False


async def test_latest_messages_sensor_truncates_to_five(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test latest messages sensor caps the attribute list at MAX_MESSAGE_ITEMS."""
    from .conftest import mock_message, mock_message_thread

    threads = [
        mock_message_thread(thread_id=str(i), subject=f"Thread {i}") for i in range(8)
    ]
    mock_aula_client.get_message_threads = AsyncMock(return_value=threads)
    mock_aula_client.get_messages_for_thread = AsyncMock(return_value=[mock_message()])

    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_parent_latest_messages")
    assert state is not None
    # Unread count reflects every unread thread, not just the listed five.
    assert state.state == "8"
    assert len(state.attributes["messages"]) == MAX_MESSAGE_ITEMS


async def test_latest_messages_sensor_empty_inbox(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test latest messages sensor with no threads."""
    mock_aula_client.get_message_threads = AsyncMock(return_value=[])

    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_parent_latest_messages")
    assert state is not None
    assert state.state == "0"
    assert "messages" not in state.attributes


async def test_latest_messages_sensor_survives_thread_failure(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test one failing thread fetch does not fail the whole update."""
    from .conftest import mock_message, mock_message_thread

    threads = [
        mock_message_thread(thread_id="1", subject="Skolefest"),
        mock_message_thread(thread_id="2", subject="Lejrskole"),
    ]
    mock_aula_client.get_message_threads = AsyncMock(return_value=threads)
    mock_aula_client.get_messages_for_thread = AsyncMock(
        side_effect=[TimeoutError("boom"), [mock_message(content="Hej")]]
    )

    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_parent_latest_messages")
    assert state is not None
    messages = state.attributes["messages"]
    assert len(messages) == 2
    # The failed thread still lists, falling back to thread-level metadata.
    assert messages[0]["subject"] == "Skolefest"
    assert messages[0]["preview"] == ""
    assert messages[0]["sender"] is None
    assert messages[0]["date"] == "2026-08-10T07:00:00+00:00"
    assert messages[1]["preview"] == "Hej"


async def test_child_notifications_per_child(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test per-child notification sensors filter by institution_profile_id."""
    from .conftest import mock_child, mock_notification, mock_profile

    child_a = mock_child(child_id=1, name="Child A")
    child_b = mock_child(child_id=2, name="Child B")
    profile = mock_profile(children=[child_a, child_b])
    mock_aula_client.get_profile = AsyncMock(return_value=profile)

    notifications = [
        mock_notification(
            notification_id="1",
            title="Msg A1",
            event_type="new_message",
            institution_profile_id=1,
        ),
        mock_notification(
            notification_id="2",
            title="Msg A2",
            event_type="new_post",
            institution_profile_id=1,
        ),
        mock_notification(
            notification_id="3",
            title="Msg B1",
            event_type="new_message",
            institution_profile_id=2,
        ),
        mock_notification(
            notification_id="4",
            title="No child",
            event_type="new_message",
            institution_profile_id=None,
        ),
    ]
    mock_aula_client.get_notifications_for_active_profile = AsyncMock(
        return_value=notifications
    )

    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Child A: 2 notifications (ids 1, 2)
    state_a = hass.states.get("sensor.child_a_unread_notifications")
    assert state_a is not None
    assert state_a.state == "2"
    assert state_a.attributes["by_type"] == {"new_message": 1, "new_post": 1}
    assert len(state_a.attributes["recent"]) == 2

    # Child B: 1 notification (id 3)
    state_b = hass.states.get("sensor.child_b_unread_notifications")
    assert state_b is not None
    assert state_b.state == "1"
    assert state_b.attributes["by_type"] == {"new_message": 1}

    # Profile total counts all notifications including institution_profile_id=None
    state_total = hass.states.get("sensor.test_parent_unread_notifications")
    assert state_total is not None
    assert state_total.state == "4"


# --- Library Sensor Tests ---


async def test_library_loans_sensor(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test library loans sensor shows correct count and attributes."""
    loan1 = mock_library_loan(
        loan_id=1, title="Book A", patron_display_name="Test Child"
    )
    loan2 = mock_library_loan(
        loan_id=2, title="Book B", patron_display_name="Test Child"
    )
    status = mock_library_status(loans=[loan1], longterm_loans=[loan2])
    mock_aula_client.widgets.get_library_status = AsyncMock(return_value=status)

    entry = make_widget_config_entry(widgets=[WIDGET_BIBLIOTEKET])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_library_loans")
    assert state is not None
    assert state.state == "2"
    assert len(state.attributes["loans"]) == 2
    assert state.attributes["loans"][0]["title"] == "Book A"


async def test_library_sensor_not_created_when_widget_disabled(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test library sensor is not created when widget is not enabled."""
    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_library_loans")
    assert state is None


async def test_library_sensor_empty_data(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test library sensor with no loans."""
    status = mock_library_status()
    mock_aula_client.widgets.get_library_status = AsyncMock(return_value=status)

    entry = make_widget_config_entry(widgets=[WIDGET_BIBLIOTEKET])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_library_loans")
    assert state is not None
    assert state.state == "0"


# --- MU Tasks Sensor Tests ---


async def test_mu_tasks_sensor(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test MU tasks sensor shows incomplete task count."""
    task1 = mock_mu_task(task_id="1", is_completed=False, student_name="Test Child")
    task2 = mock_mu_task(task_id="2", is_completed=True, student_name="Test Child")
    mock_aula_client.widgets.get_mu_tasks = AsyncMock(return_value=[task1, task2])

    entry = make_widget_config_entry(widgets=[WIDGET_MIN_UDDANNELSE_TASKS])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_mu_tasks")
    assert state is not None
    assert state.state == "1"  # only incomplete tasks
    assert len(state.attributes["tasks"]) == 2


async def test_mu_tasks_sensor_not_created_when_disabled(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test MU tasks sensor is not created when widget is disabled."""
    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_mu_tasks")
    assert state is None


# --- EasyIQ Sensor Tests ---


async def test_easyiq_weekplan_sensor(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test EasyIQ weekplan sensor shows appointment count."""
    appt = mock_appointment()
    mock_aula_client.widgets.get_easyiq_weekplan = AsyncMock(return_value=[appt])
    mock_aula_client.widgets.get_easyiq_weekplan_text = AsyncMock(
        return_value="<p>Generelt om ugen</p>"
    )
    mock_aula_client.widgets.get_easyiq_homework = AsyncMock(return_value=[])

    entry = make_widget_config_entry(
        widgets=[WIDGET_EASYIQ_WEEKPLAN, WIDGET_EASYIQ_HOMEWORK]
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_weekplan")
    assert state is not None
    assert state.state == "1"
    assert len(state.attributes["appointments"]) == 1
    assert state.attributes["appointments"][0]["title"] == "Science Class"
    assert state.attributes["week_text"] == "<p>Generelt om ugen</p>"


async def test_easyiq_weekplan_sensor_omits_an_empty_week_text(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """A week without a general text leaves the attribute out entirely."""
    appt = mock_appointment()
    mock_aula_client.widgets.get_easyiq_weekplan = AsyncMock(return_value=[appt])
    mock_aula_client.widgets.get_easyiq_weekplan_text = AsyncMock(return_value="")
    mock_aula_client.widgets.get_easyiq_homework = AsyncMock(return_value=[])

    entry = make_widget_config_entry(widgets=[WIDGET_EASYIQ_WEEKPLAN])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_weekplan")
    assert state is not None
    assert "week_text" not in state.attributes


async def test_easyiq_weekplan_sensor_keeps_a_text_only_week(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """A week with a general text but no lessons still shows the text."""
    mock_aula_client.widgets.get_easyiq_weekplan = AsyncMock(return_value=[])
    mock_aula_client.widgets.get_easyiq_weekplan_text = AsyncMock(
        return_value="<p>Uge 47: temauge</p>"
    )
    mock_aula_client.widgets.get_easyiq_homework = AsyncMock(return_value=[])

    entry = make_widget_config_entry(widgets=[WIDGET_EASYIQ_WEEKPLAN])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_weekplan")
    assert state is not None
    assert state.state == "0"
    assert state.attributes["week_text"] == "<p>Uge 47: temauge</p>"
    assert "appointments" not in state.attributes


async def test_easyiq_homework_sensor(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test EasyIQ homework sensor shows incomplete homework count."""
    hw1 = mock_easyiq_homework(hw_id="1", is_completed=False)
    hw2 = mock_easyiq_homework(hw_id="2", is_completed=True)
    mock_aula_client.widgets.get_easyiq_weekplan = AsyncMock(return_value=[])
    mock_aula_client.widgets.get_easyiq_homework = AsyncMock(return_value=[hw1, hw2])

    entry = make_widget_config_entry(
        widgets=[WIDGET_EASYIQ_WEEKPLAN, WIDGET_EASYIQ_HOMEWORK]
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_homework")
    assert state is not None
    assert state.state == "1"  # only incomplete
    assert len(state.attributes["homework"]) == 2


async def test_easyiq_sensors_not_created_when_disabled(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test EasyIQ sensors are not created when widget is disabled."""
    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.test_child_weekplan") is None
    assert hass.states.get("sensor.test_child_homework") is None


# --- Meebook Sensor Tests ---


@pytest.mark.parametrize(
    "widgets",
    [
        [WIDGET_MEEBOOK],
        [WIDGET_MEEBOOK_OVERVIEW],
        [WIDGET_MEEBOOK, WIDGET_MEEBOOK_OVERVIEW],
    ],
)
async def test_meebook_weekplan_sensor(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
    widgets: list[str],
) -> None:
    """Test Meebook weekplan sensor for both advertised widget IDs."""
    plan = mock_meebook_student_plan(name="Test Child")
    next_plan = mock_meebook_student_plan(
        name="Test Child", tasks=[mock_meebook_task(title="Next task")] * 2
    )
    mock_aula_client.widgets.get_meebook_weekplan = AsyncMock(
        side_effect=[[plan], [next_plan]]
    )

    entry = make_widget_config_entry(widgets=widgets)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_meebook_weekplan")
    assert state is not None
    assert state.state == "1"
    assert len(state.attributes["tasks"]) == 1
    assert state.attributes["tasks"][0]["title"] == "Weekly Activity"
    assert len(state.attributes["next_week_tasks"]) == 2
    assert state.attributes["next_week_tasks"][0]["title"] == "Next task"
    assert state.attributes["next_week_available"] is True
    assert mock_aula_client.widgets.get_meebook_weekplan.await_count == 2
    assert (
        len([s for s in hass.states.async_all() if "meebook_weekplan" in s.entity_id])
        == 1
    )


@pytest.mark.parametrize(
    ("current_count", "next_count"),
    [(0, 0), (1, 0), (0, 2), (MAX_ATTRIBUTE_ITEMS + 1, MAX_ATTRIBUTE_ITEMS + 2)],
)
async def test_meebook_task_attributes(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
    current_count: int,
    next_count: int,
) -> None:
    """Empty lists are omitted and each week's attributes are capped separately."""
    task = mock_meebook_task()
    mock_aula_client.widgets.get_meebook_weekplan.side_effect = [
        [mock_meebook_student_plan(name="Test Child", tasks=[task] * count)]
        for count in (current_count, next_count)
    ]
    entry = make_widget_config_entry(widgets=[WIDGET_MEEBOOK])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.test_child_meebook_weekplan")
    assert state is not None
    assert state.state == str(current_count)
    assert state.attributes["next_week_available"] is True
    for key, count in (("tasks", current_count), ("next_week_tasks", next_count)):
        if count:
            assert state.attributes[key] == [
                {"title": task.title, "type": task.type, "content": task.content}
            ] * min(count, MAX_ATTRIBUTE_ITEMS)
        else:
            assert key not in state.attributes


async def test_meebook_sensor_partial_failure_and_recovery(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Refresh updates HA state and drops stale future tasks on failure."""
    plan = mock_meebook_student_plan(name="Test Child")
    mock_aula_client.widgets.get_meebook_weekplan.side_effect = [
        [plan],
        [plan],
        [plan],
        AulaConnectionError("offline", 0),
        [],
        [plan],
        *(
            AulaConnectionError("offline", 0)
            for _ in range(TRANSIENT_FAILURE_TOLERANCE + 1)
        ),
    ]
    entry = make_widget_config_entry(widgets=[WIDGET_MEEBOOK])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data.meebook_coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.test_child_meebook_weekplan")
    assert state is not None
    assert state.state == "1"
    assert state.attributes["next_week_available"] is False
    assert "next_week_tasks" not in state.attributes
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.test_child_meebook_weekplan")
    assert state is not None
    assert state.state == "0"
    assert state.attributes["next_week_available"] is True
    assert len(state.attributes["next_week_tasks"]) == 1
    # A failed current week keeps the previous data through a transient blip
    # and only marks the sensor unavailable once the failures persist.
    for _ in range(TRANSIENT_FAILURE_TOLERANCE):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        state = hass.states.get("sensor.test_child_meebook_weekplan")
        assert state is not None
        assert state.state == "0"
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.test_child_meebook_weekplan")
    assert state is not None
    assert state.state == "unavailable"
    assert (
        mock_aula_client.widgets.get_meebook_weekplan.await_count
        == 7 + TRANSIENT_FAILURE_TOLERANCE
    )


async def test_meebook_weekplan_sensor_next_week_when_current_empty(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test next-week Meebook tasks remain visible with an empty current week."""
    next_task = mock_meebook_task(title="Next week activity")
    next_plan = mock_meebook_student_plan(name="Test Child", tasks=[next_task])
    mock_aula_client.widgets.get_meebook_weekplan = AsyncMock(
        side_effect=[[], [next_plan]]
    )

    entry = make_widget_config_entry(widgets=[WIDGET_MEEBOOK_OVERVIEW])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_meebook_weekplan")
    assert state is not None
    assert state.state == "0"
    assert "tasks" not in state.attributes
    assert len(state.attributes["next_week_tasks"]) == 1
    assert state.attributes["next_week_tasks"][0]["title"] == "Next week activity"


async def test_meebook_sensor_not_created_when_disabled(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test Meebook sensor is not created when widget is disabled."""
    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.test_child_meebook_weekplan") is None


# --- Huskelisten Sensor Tests ---


async def test_huskelisten_sensor(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test Huskelisten sensor shows reminder count."""
    team_r = mock_team_reminder()
    assign_r = mock_assignment_reminder()
    ur = mock_user_reminders(
        user_name="Test Child",
        team_reminders=[team_r],
        assignment_reminders=[assign_r],
    )
    mock_aula_client.widgets.get_momo_reminders = AsyncMock(return_value=[ur])

    entry = make_widget_config_entry(widgets=[WIDGET_HUSKELISTEN])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_reminders")
    assert state is not None
    assert state.state == "2"
    assert len(state.attributes["reminders"]) == 2
    assert state.attributes["reminders"][0]["text"] == "Remember to bring gym clothes"
    assert state.attributes["reminders"][1]["text"] == "Complete worksheet"


async def test_huskelisten_sensor_not_created_when_disabled(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test Huskelisten sensor is not created when widget is disabled."""
    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.test_child_reminders") is None


async def test_huskelisten_sensor_empty(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test Huskelisten sensor with no reminders."""
    mock_aula_client.widgets.get_momo_reminders = AsyncMock(return_value=[])

    entry = make_widget_config_entry(widgets=[WIDGET_HUSKELISTEN])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_reminders")
    assert state is not None
    assert state.state == "0"


# --- MU Weekly Notes Sensor Tests ---


async def test_mu_weekly_notes_sensor(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test MU weekly notes sensor shows note count and attributes."""
    letter1 = mock_mu_weekly_letter(group_name="3A", week_number=5)
    letter2 = mock_mu_weekly_letter(group_id=2, group_name="3B", week_number=5)
    next_letter = mock_mu_weekly_letter(group_name="3A", week_number=6)
    person = mock_mu_weekly_person(name="Test Child", letters=[letter1, letter2])
    next_person = mock_mu_weekly_person(name="Test Child", letters=[next_letter])
    mock_aula_client.widgets.get_ugeplan = AsyncMock(
        side_effect=[[person], [next_person]]
    )

    entry = make_widget_config_entry(widgets=[WIDGET_MIN_UDDANNELSE_UGEPLAN])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_weekly_notes")
    assert state is not None
    assert state.state == "2"
    assert len(state.attributes["notes"]) == 2
    assert state.attributes["notes"][0] == "<p>Weekly update</p>"
    assert len(state.attributes["next_week_notes"]) == 1
    assert state.attributes["next_week_notes"][0] == "<p>Weekly update</p>"


async def test_mu_weekly_notes_sensor_not_created_when_disabled(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test MU weekly notes sensor is not created when feature is disabled."""
    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_weekly_notes")
    assert state is None


async def test_mu_weekly_notes_sensor_empty(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """Test MU weekly notes sensor with no notes."""
    mock_aula_client.widgets.get_ugeplan = AsyncMock(side_effect=[[], []])

    entry = make_widget_config_entry(widgets=[WIDGET_MIN_UDDANNELSE_UGEPLAN])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_weekly_notes")
    assert state is not None
    assert state.state == "0"


async def test_easyiq_weekplan_sensor_keeps_notice_text_and_day(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """A "Vigtig information" notice keeps its body and the day it belongs to."""
    notice = mock_appointment(
        title="Vigtig information",
        start="2024-01-18T00:00:00",
        end="2024-01-18T00:00:00",
        activities="",
        description="<p>Tur til Karlsgaarde med bus. Husk gummistoevler.</p>",
        is_notice=True,
    )
    mock_aula_client.widgets.get_easyiq_weekplan = AsyncMock(return_value=[notice])
    mock_aula_client.widgets.get_easyiq_homework = AsyncMock(return_value=[])

    entry = make_widget_config_entry(
        widgets=[WIDGET_EASYIQ_WEEKPLAN, WIDGET_EASYIQ_HOMEWORK]
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_weekplan")
    assert state is not None
    appointment = state.attributes["appointments"][0]
    assert appointment["is_notice"] is True
    # Without the body the notice is just a heading and the text is lost.
    assert "Karlsgaarde" in appointment["description"]
    # The day the notice was filed under, rather than the top of the week.
    assert appointment["start"] == "2024-01-18T00:00:00"


async def test_easyiq_weekplan_sensor_marks_lessons_as_not_notices(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """An ordinary lesson is not flagged as a notice."""
    mock_aula_client.widgets.get_easyiq_weekplan = AsyncMock(
        return_value=[mock_appointment()]
    )
    mock_aula_client.widgets.get_easyiq_homework = AsyncMock(return_value=[])

    entry = make_widget_config_entry(
        widgets=[WIDGET_EASYIQ_WEEKPLAN, WIDGET_EASYIQ_HOMEWORK]
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_child_weekplan")
    assert state is not None
    assert state.attributes["appointments"][0]["is_notice"] is False


async def test_latest_messages_sensor_reports_attachments(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """A message carrying an attachment is flagged as such."""
    from .conftest import mock_message, mock_message_thread

    threads = [
        mock_message_thread(thread_id="1", subject="Skolefest"),
        mock_message_thread(thread_id="2", subject="Lejrskole"),
    ]
    mock_aula_client.get_message_threads = AsyncMock(
        side_effect=lambda filter_on=None: [] if filter_on == "unread" else threads
    )
    mock_aula_client.get_messages_for_thread = AsyncMock(
        side_effect=lambda thread_id, **_: [
            mock_message(content="Se vedhaeftede", has_attachments=thread_id == "1")
        ]
    )

    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_parent_latest_messages")
    assert state is not None
    messages = state.attributes["messages"]
    assert messages[0]["has_attachments"] is True
    assert messages[1]["has_attachments"] is False


async def test_latest_messages_sensor_reports_no_attachments_on_failure(
    hass: HomeAssistant,
    mock_aula_client: AsyncMock,
) -> None:
    """An unreadable thread is not evidence of an attachment."""
    from .conftest import mock_message_thread

    mock_aula_client.get_message_threads = AsyncMock(
        side_effect=lambda filter_on=None: (
            [] if filter_on == "unread" else [mock_message_thread(thread_id="1")]
        )
    )
    mock_aula_client.get_messages_for_thread = AsyncMock(
        side_effect=AulaConnectionError("boom")
    )

    entry = make_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_parent_latest_messages")
    assert state is not None
    assert state.attributes["messages"][0]["has_attachments"] is False

"""Sensor platform for the Aula integration."""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)

from .const import PARALLEL_UPDATES as PARALLEL_UPDATES  # noqa: PLC0414
from .coordinator import (
    AulaEasyIQCoordinator,
    AulaHuskelistenCoordinator,
    AulaLibraryCoordinator,
    AulaMeebookCoordinator,
    AulaMessagesCoordinator,
    AulaMUTasksCoordinator,
    AulaMUUgeplanCoordinator,
    AulaNotificationsCoordinator,
    AulaPresenceCoordinator,
    _PresenceChildData,
)
from .entity import AulaAccountEntity, AulaEntity

if TYPE_CHECKING:
    from aula import Child, Profile
    from aula.models.meebook_weekplan import MeebookTask
    from aula.models.mu_weekly_letter import MUWeeklyLetter
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .data import (
        AulaConfigEntry,
        EasyIQChildData,
        HuskelistenChildData,
        LibraryChildData,
        MessagesData,
    )

MAX_ATTRIBUTE_ITEMS = 20

PRESENCE_SENSOR_DESCRIPTION = SensorEntityDescription(
    key="presence_status",
    translation_key="presence_status",
    device_class=SensorDeviceClass.ENUM,
    options=[
        "not_present",
        "sick",
        "reported_absent",
        "present",
        "fieldtrip",
        "sleeping",
        "spare_time_activity",
        "physical_placement",
        "checked_out",
    ],
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: AulaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Aula sensors."""
    runtime = entry.runtime_data
    profile = runtime.profile

    entities: list[SensorEntity] = [
        AulaPresenceSensor(coordinator=runtime.presence_coordinator, child=child)
        for child in profile.children
    ]
    entities.append(
        AulaNotificationsSensor(
            coordinator=runtime.notifications_coordinator, profile=profile
        )
    )
    entities.append(
        AulaLatestMessagesSensor(
            coordinator=runtime.messages_coordinator, profile=profile
        )
    )
    entities.extend(
        AulaChildNotificationsSensor(
            coordinator=runtime.notifications_coordinator, child=child
        )
        for child in profile.children
    )

    # Widget sensors — only created if the coordinator exists
    if runtime.library_coordinator:
        entities.extend(
            AulaLibraryLoansSensor(coordinator=runtime.library_coordinator, child=child)
            for child in profile.children
        )

    if runtime.mu_tasks_coordinator:
        entities.extend(
            AulaMUTasksSensor(coordinator=runtime.mu_tasks_coordinator, child=child)
            for child in profile.children
        )

    if runtime.mu_ugeplan_coordinator:
        entities.extend(
            AulaMUWeeklyNotesSensor(
                coordinator=runtime.mu_ugeplan_coordinator, child=child
            )
            for child in profile.children
        )

    if runtime.easyiq_coordinator:
        for child in profile.children:
            entities.extend(
                [
                    AulaEasyIQWeekplanSensor(
                        coordinator=runtime.easyiq_coordinator, child=child
                    ),
                    AulaEasyIQHomeworkSensor(
                        coordinator=runtime.easyiq_coordinator, child=child
                    ),
                ]
            )

    if runtime.meebook_coordinator:
        entities.extend(
            AulaMeebookWeekplanSensor(
                coordinator=runtime.meebook_coordinator, child=child
            )
            for child in profile.children
        )

    if runtime.huskelisten_coordinator:
        entities.extend(
            AulaHuskelistenSensor(
                coordinator=runtime.huskelisten_coordinator, child=child
            )
            for child in profile.children
        )

    async_add_entities(entities)


class AulaPresenceSensor(AulaEntity[AulaPresenceCoordinator], SensorEntity):
    """Representation of an Aula presence sensor."""

    entity_description = PRESENCE_SENSOR_DESCRIPTION

    def __init__(
        self,
        coordinator: AulaPresenceCoordinator,
        child: Child,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{child.id}_presence_status"

    @property
    def _child_data(self) -> _PresenceChildData | None:
        return self.coordinator.data.get(self._child.id)

    @property
    def native_value(self) -> str | None:
        """Return the presence status."""
        child_data = self._child_data
        if not child_data or not child_data.overview:
            return None
        overview = child_data.overview
        return overview.status.name.lower() if overview.status else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return time and location details as attributes."""
        child_data = self._child_data
        if not child_data or not child_data.overview:
            return {}
        overview = child_data.overview
        return {
            "check_in_time": overview.check_in_time,
            "check_out_time": overview.check_out_time,
            "entry_time": overview.entry_time,
            "exit_time": overview.exit_time,
            "exit_with": overview.exit_with,
            "self_decider_start_time": child_data.self_decider_start,
            "self_decider_end_time": child_data.self_decider_end,
            # Naps as the institution registered them, e.g.
            # [{"id": 27707363, "startTime": "12:05:00", "endTime": "13:15:00"}].
            # These are dicts of JSON scalars, so unlike `location` they
            # serialize into a state attribute as-is. Staff often register or
            # correct a nap after the fact, so this is more trustworthy than
            # watching the presence state flip to SLEEPING between five-minute
            # polls. Passed through untouched: the keys are whatever the API
            # sends, and the shape of an in-progress nap has not been observed.
            "sleep_intervals": overview.sleep_intervals,
            # aula 1.7.0 turned this into a PresenceLocation object, which is
            # not JSON-serializable and so cannot go in a state attribute.
            # Keep publishing the name, which is what this attribute has always
            # held and what existing dashboards and automations read.
            "location": overview.location.name if overview.location else None,
        }


class AulaNotificationsSensor(
    AulaAccountEntity[AulaNotificationsCoordinator], SensorEntity
):
    """Sensor showing unread notification count for the active profile."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "unread_notifications"

    def __init__(
        self,
        coordinator: AulaNotificationsCoordinator,
        profile: Profile,
    ) -> None:
        """Initialize the notifications sensor."""
        super().__init__(coordinator, profile)
        self._attr_unique_id = f"{profile.profile_id}_unread_notifications"

    @property
    def native_value(self) -> int:
        """Return the number of notifications."""
        notifications = self.coordinator.data or []
        return len(notifications)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return total count and recent notification titles."""
        notifications = self.coordinator.data or []
        return {
            "recent": [
                {
                    "title": n.title,
                    "module": n.module,
                    "event_type": n.event_type,
                    "related_child_name": n.related_child_name,
                    "created_at": n.created_at,
                }
                for n in notifications[:5]
            ],
        }


class AulaChildNotificationsSensor(
    AulaEntity[AulaNotificationsCoordinator], SensorEntity
):
    """Sensor showing unread notification count for a specific child."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "child_unread_notifications"

    def __init__(
        self,
        coordinator: AulaNotificationsCoordinator,
        child: Child,
    ) -> None:
        """Initialize the child notifications sensor."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{child.id}_unread_notifications"

    @property
    def _child_notifications(self) -> list:
        """Return notifications for this child."""
        notifications = self.coordinator.data or []
        return [n for n in notifications if n.institution_profile_id == self._child.id]

    @property
    def native_value(self) -> int:
        """Return the number of notifications for this child."""
        return len(self._child_notifications)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return by-type counts and recent notifications."""
        child_notifs = self._child_notifications
        if not child_notifs:
            return {}
        by_type: dict[str, int] = {}
        for n in child_notifs:
            key = n.event_type or "unknown"
            by_type[key] = by_type.get(key, 0) + 1
        return {
            "by_type": by_type,
            "recent": [
                {
                    "title": n.title,
                    "module": n.module,
                    "event_type": n.event_type,
                    "created_at": n.created_at,
                }
                for n in child_notifs[:5]
            ],
        }


class AulaLatestMessagesSensor(
    AulaAccountEntity[AulaMessagesCoordinator], SensorEntity
):
    """Sensor showing unread message count and the latest messages."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "latest_messages"

    def __init__(
        self,
        coordinator: AulaMessagesCoordinator,
        profile: Profile,
    ) -> None:
        """Initialize the latest messages sensor."""
        super().__init__(coordinator, profile)
        self._attr_unique_id = f"{profile.profile_id}_latest_messages"

    @property
    def _messages_data(self) -> MessagesData | None:
        """Return the coordinator's inbox data."""
        return self.coordinator.data

    @property
    def native_value(self) -> int:
        """Return the number of unread message threads."""
        data = self._messages_data
        if not data:
            return 0
        return data.unread_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the latest messages."""
        data = self._messages_data
        if not data or not data.messages:
            return {}
        return {
            "messages": [
                {
                    "thread_id": message.thread_id,
                    "subject": message.subject,
                    "sender": message.sender,
                    "date": message.date,
                    "unread": message.unread,
                    "preview": message.preview,
                    "has_attachments": message.has_attachments,
                }
                for message in data.messages
            ],
        }


class AulaLibraryLoansSensor(AulaEntity[AulaLibraryCoordinator], SensorEntity):
    """Sensor showing library loan count for a child."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_translation_key = "library_loans"

    def __init__(
        self,
        coordinator: AulaLibraryCoordinator,
        child: Child,
    ) -> None:
        """Initialize the library loans sensor."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{child.id}_library_loans"

    @property
    def _child_data(self) -> LibraryChildData | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._child.id)

    @property
    def native_value(self) -> int:
        """Return the number of active loans."""
        data = self._child_data
        if not data:
            return 0
        return len(data.loans) + len(data.longterm_loans)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return loan details."""
        data = self._child_data
        if not data:
            return {}
        return {
            "loans": [
                {
                    "title": loan.title,
                    "author": loan.author,
                    "due_date": loan.due_date,
                }
                for loan in itertools.islice(
                    itertools.chain(data.loans, data.longterm_loans),
                    MAX_ATTRIBUTE_ITEMS,
                )
            ],
            "reservations_count": len(data.reservations),
        }


class AulaMUTasksSensor(AulaEntity[AulaMUTasksCoordinator], SensorEntity):
    """Sensor showing Min Uddannelse task count for a child."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "mu_tasks"

    def __init__(
        self,
        coordinator: AulaMUTasksCoordinator,
        child: Child,
    ) -> None:
        """Initialize the MU tasks sensor."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{child.id}_mu_tasks"

    @property
    def _tasks(self) -> list:
        if not self.coordinator.data:
            return []
        return self.coordinator.data.get(self._child.id, [])

    @property
    def native_value(self) -> int:
        """Return the number of incomplete tasks."""
        return sum(1 for t in self._tasks if not t.is_completed)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return task details."""
        tasks = self._tasks
        if not tasks:
            return {}
        return {
            "tasks": [
                {
                    "title": t.title,
                    "due_date": str(t.due_date) if t.due_date else None,
                    "subject": t.classes[0].name if t.classes else None,
                    "is_completed": t.is_completed,
                }
                for t in tasks[:MAX_ATTRIBUTE_ITEMS]
            ],
        }


class AulaMUWeeklyNotesSensor(AulaEntity[AulaMUUgeplanCoordinator], SensorEntity):
    """Sensor showing Min Uddannelse weekly note count for a child."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_translation_key = "mu_weekly_notes"

    def __init__(
        self,
        coordinator: AulaMUUgeplanCoordinator,
        child: Child,
    ) -> None:
        """Initialize the MU weekly notes sensor."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{child.id}_mu_weekly_notes"

    @property
    def _letters(self) -> list[MUWeeklyLetter]:
        if not self.coordinator.data:
            return []
        return self.coordinator.data.current.get(self._child.id, [])

    @property
    def _next_week_letters(self) -> list[MUWeeklyLetter]:
        if not self.coordinator.data:
            return []
        return self.coordinator.data.next_week.get(self._child.id, [])

    @property
    def native_value(self) -> int:
        """Return the number of weekly notes."""
        return len(self._letters)

    @staticmethod
    def _format_letters(letters: list[MUWeeklyLetter]) -> list[str]:
        return [letter.content_html for letter in letters[:MAX_ATTRIBUTE_ITEMS]]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return weekly note details for current and next week."""
        letters = self._letters
        next_week_letters = self._next_week_letters
        if not letters and not next_week_letters:
            return {}
        attrs: dict[str, Any] = {}
        if letters:
            attrs["notes"] = self._format_letters(letters)
        if next_week_letters:
            attrs["next_week_notes"] = self._format_letters(next_week_letters)
        return attrs


class AulaEasyIQWeekplanSensor(AulaEntity[AulaEasyIQCoordinator], SensorEntity):
    """Sensor showing EasyIQ weekplan appointment count for a child."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "easyiq_weekplan"

    def __init__(
        self,
        coordinator: AulaEasyIQCoordinator,
        child: Child,
    ) -> None:
        """Initialize the EasyIQ weekplan sensor."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{child.id}_easyiq_weekplan"

    @property
    def _child_data(self) -> EasyIQChildData | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._child.id)

    @property
    def native_value(self) -> int:
        """Return the number of appointments."""
        data = self._child_data
        if not data:
            return 0
        return len(data.weekplan)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return appointment details."""
        data = self._child_data
        if not data:
            return {}
        attrs: dict[str, Any] = {}
        if data.weekplan:
            attrs["appointments"] = [
                {
                    "title": a.title,
                    "start": a.start,
                    "end": a.end,
                    # EasyIQ's class or team for the lesson, e.g. "6A". Empty
                    # for sources that do not carry one.
                    "class_name": a.activities,
                    # The body of the entry, as the HTML EasyIQ authored, the
                    # same form the Min Uddannelse notes are published in. For
                    # a notice this is the whole point of the row: `title` is
                    # only its first heading, so without this the text is lost.
                    "description": a.description,
                    # True for "Vigtig information" and other rows EasyIQ files
                    # under no subject. They carry their own `start`, so the day
                    # a notice belongs to survives instead of being flattened to
                    # the top of the week.
                    "is_notice": a.is_notice,
                }
                for a in data.weekplan[:MAX_ATTRIBUTE_ITEMS]
            ]
        # The week's general text ("Generelt om ugen"), as the HTML the
        # teacher authored. Omitted when the class has none this week, so a
        # template can default on it the way the Meebook ones do.
        if data.week_text:
            attrs["week_text"] = data.week_text
        return attrs


class AulaEasyIQHomeworkSensor(AulaEntity[AulaEasyIQCoordinator], SensorEntity):
    """Sensor showing EasyIQ homework count for a child."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "easyiq_homework"

    def __init__(
        self,
        coordinator: AulaEasyIQCoordinator,
        child: Child,
    ) -> None:
        """Initialize the EasyIQ homework sensor."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{child.id}_easyiq_homework"

    @property
    def _child_data(self) -> EasyIQChildData | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._child.id)

    @property
    def native_value(self) -> int:
        """Return the number of incomplete homework items."""
        data = self._child_data
        if not data:
            return 0
        return sum(1 for h in data.homework if not h.is_completed)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return homework details."""
        data = self._child_data
        if not data or not data.homework:
            return {}
        return {
            "homework": [
                {
                    "title": h.title,
                    "subject": h.subject,
                    "due_date": h.due_date,
                    "is_completed": h.is_completed,
                    # The class or team the assignment was set for, e.g. "6A".
                    "class_name": h.activities,
                }
                for h in data.homework[:MAX_ATTRIBUTE_ITEMS]
            ],
        }


class AulaMeebookWeekplanSensor(AulaEntity[AulaMeebookCoordinator], SensorEntity):
    """Sensor showing Meebook weekplan task count for a child."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "meebook_weekplan"

    def __init__(
        self,
        coordinator: AulaMeebookCoordinator,
        child: Child,
    ) -> None:
        """Initialize the Meebook weekplan sensor."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{child.id}_meebook_weekplan"

    @property
    def _tasks(self) -> list[MeebookTask]:
        if not self.coordinator.data:
            return []
        return self.coordinator.data.current.get(self._child.id, [])

    @property
    def _next_week_tasks(self) -> list[MeebookTask]:
        if not self.coordinator.data or self.coordinator.data.next_week is None:
            return []
        return self.coordinator.data.next_week.get(self._child.id, [])

    @property
    def native_value(self) -> int:
        """Return the number of tasks this week."""
        return len(self._tasks)

    @staticmethod
    def _format_tasks(tasks: list[MeebookTask]) -> list[dict[str, Any]]:
        """Format Meebook tasks for state attributes."""
        return [
            {
                "title": task.title,
                "type": task.type,
                "content": task.content,
            }
            for task in tasks[:MAX_ATTRIBUTE_ITEMS]
        ]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return task details for current and next week."""
        tasks = self._tasks
        next_week_tasks = self._next_week_tasks
        data = self.coordinator.data
        attrs: dict[str, Any] = {
            "next_week_available": data is not None and data.next_week is not None,
        }
        if tasks:
            attrs["tasks"] = self._format_tasks(tasks)
        if next_week_tasks:
            attrs["next_week_tasks"] = self._format_tasks(next_week_tasks)
        return attrs


class AulaHuskelistenSensor(AulaEntity[AulaHuskelistenCoordinator], SensorEntity):
    """Sensor showing Huskelisten reminder count for a child."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "huskelisten_reminders"

    def __init__(
        self,
        coordinator: AulaHuskelistenCoordinator,
        child: Child,
    ) -> None:
        """Initialize the Huskelisten sensor."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{child.id}_huskelisten_reminders"

    @property
    def _child_data(self) -> HuskelistenChildData | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._child.id)

    @property
    def native_value(self) -> int:
        """Return the total number of reminders."""
        data = self._child_data
        if not data:
            return 0
        return len(data.team_reminders) + len(data.assignment_reminders)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return reminder details."""
        data = self._child_data
        if not data:
            return {}
        team_items = (
            {
                "text": r.reminder_text,
                "due_date": r.due_date,
                "subject": r.subject_name,
                "team": r.team_name,
            }
            for r in data.team_reminders
        )
        assignment_items = (
            {
                "text": r.assignment_text,
                "due_date": r.due_date,
                "team": ", ".join(r.team_names) if r.team_names else None,
            }
            for r in data.assignment_reminders
        )
        return {
            "reminders": list(
                itertools.islice(
                    itertools.chain(team_items, assignment_items), MAX_ATTRIBUTE_ITEMS
                )
            )
        }

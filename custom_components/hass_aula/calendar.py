"""Calendar platform for the Aula integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aula import CalendarEvent as AulaCalendarEvent
from aula import HttpRequestError
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.util import dt as dt_util

from .const import PARALLEL_UPDATES as PARALLEL_UPDATES  # noqa: PLC0414
from .coordinator import AulaCalendarCoordinator
from .entity import AulaEntity

if TYPE_CHECKING:
    from datetime import datetime

    from aula import Child
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .data import AulaConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: AulaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Aula calendar entities."""
    coordinator = entry.runtime_data.calendar_coordinator
    profile = entry.runtime_data.profile

    async_add_entities(
        AulaCalendarEntity(coordinator=coordinator, child=child)
        for child in profile.children
    )


def _names(names: list[str], fallback: str | None) -> list[str]:
    """Return the full name list, falling back to the single-name field."""
    if names:
        return names
    return [fallback] if fallback else []


def _convert_event(event: AulaCalendarEvent) -> CalendarEvent:
    """Convert an Aula calendar event to a HA calendar event."""
    description_parts: list[str] = []
    # A lesson often has more than one adult attached; aula merges the rows
    # Aula sends per adult and lists them all here, so name every one of them
    # rather than only whoever happened to come first.
    teachers = _names(event.teacher_names, event.teacher_name)
    if teachers:
        label = "Teachers" if len(teachers) > 1 else "Teacher"
        description_parts.append(f"{label}: {', '.join(teachers)}")
    if event.has_substitute:
        substitutes = _names(event.substitute_names, event.substitute_name)
        if substitutes:
            label = "Substitutes" if len(substitutes) > 1 else "Substitute"
            description_parts.append(f"{label}: {', '.join(substitutes)}")
    if event.location:
        description_parts.append(f"Location: {event.location}")

    return CalendarEvent(
        summary=event.title,
        start=event.start_datetime,
        end=event.end_datetime,
        description="\n".join(description_parts) if description_parts else None,
        location=event.location,
    )


class AulaCalendarEntity(AulaEntity[AulaCalendarCoordinator], CalendarEntity):
    """Representation of an Aula school calendar."""

    _attr_translation_key = "school_calendar"

    def __init__(
        self,
        coordinator: AulaCalendarCoordinator,
        child: Child,
    ) -> None:
        """Initialize the calendar entity."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{child.id}_school_calendar"

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        events = self.coordinator.data.get(self._child.id, [])
        if not events:
            return None
        now = dt_util.now()
        upcoming = [e for e in events if e.end_datetime > now]
        if not upcoming:
            return None
        upcoming.sort(key=lambda e: e.start_datetime)
        return _convert_event(upcoming[0])

    async def async_get_events(
        self,
        hass: HomeAssistant,  # noqa: ARG002
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a date range."""
        try:
            calendars = await self.coordinator.client.get_calendar_events_by_child(
                [self._child.id], start_date, end_date
            )
        except HttpRequestError:
            return []

        return [_convert_event(event) for event in calendars.get(self._child.id, [])]

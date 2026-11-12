"""Custom types for the Aula integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from aula import AulaApiClient, Profile
    from aula.models import Appointment, EasyIQHomework, LibraryLoan
    from aula.models.meebook_weekplan import MeebookTask
    from aula.models.momo_huskeliste import AssignmentReminder, TeamReminder
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

    from .coordinator import (
        AulaCalendarCoordinator,
        AulaEasyIQCoordinator,
        AulaHuskelistenCoordinator,
        AulaLibraryCoordinator,
        AulaMeebookCoordinator,
        AulaMessagesCoordinator,
        AulaMUTasksCoordinator,
        AulaMUUgeplanCoordinator,
        AulaNotificationsCoordinator,
        AulaPresenceCoordinator,
    )
    from .token_manager import AulaTokenManager

type AulaConfigEntry = ConfigEntry[AulaRuntimeData]


@dataclass
class WidgetContext:
    """Context needed by widget API calls."""

    child_filter: list[str]
    institution_filter: list[str]
    session_uuid: str


@dataclass
class LibraryChildData:
    """Library data for a single child."""

    loans: list[LibraryLoan] = field(default_factory=list)
    longterm_loans: list[LibraryLoan] = field(default_factory=list)
    reservations: list[dict] = field(default_factory=list)


@dataclass
class EasyIQChildData:
    """EasyIQ data for a single child."""

    weekplan: list[Appointment] = field(default_factory=list)
    homework: list[EasyIQHomework] = field(default_factory=list)
    # The week's general text ("Generelt om ugen"), from the portal's
    # WeekPlan controller. Empty when the class has none this week.
    week_text: str = ""


@dataclass
class MeebookWeekplanData:
    """Meebook tasks by child; None means next week could not be fetched."""

    current: dict[int, list[MeebookTask]]
    next_week: dict[int, list[MeebookTask]] | None


@dataclass
class HuskelistenChildData:
    """Huskelisten data for a single child."""

    team_reminders: list[TeamReminder] = field(default_factory=list)
    assignment_reminders: list[AssignmentReminder] = field(default_factory=list)


@dataclass
class MessagePreview:
    """A single message shown by the latest-messages sensor."""

    thread_id: str
    subject: str
    sender: str | None
    date: str | None
    unread: bool
    preview: str
    #: Whether the newest message in the thread carries anything attached.
    #: False when the thread's messages could not be fetched, since an
    #: unreadable thread is not evidence of an attachment.
    has_attachments: bool = False


@dataclass
class MessagesData:
    """Inbox data for the active profile."""

    unread_count: int = 0
    messages: list[MessagePreview] = field(default_factory=list)


@dataclass
class AulaRuntimeData:
    """Runtime data for the Aula integration."""

    client: AulaApiClient
    token_manager: AulaTokenManager
    profile: Profile
    presence_coordinator: AulaPresenceCoordinator
    calendar_coordinator: AulaCalendarCoordinator
    notifications_coordinator: AulaNotificationsCoordinator
    messages_coordinator: AulaMessagesCoordinator
    library_coordinator: AulaLibraryCoordinator | None = None
    mu_tasks_coordinator: AulaMUTasksCoordinator | None = None
    mu_ugeplan_coordinator: AulaMUUgeplanCoordinator | None = None
    easyiq_coordinator: AulaEasyIQCoordinator | None = None
    meebook_coordinator: AulaMeebookCoordinator | None = None
    huskelisten_coordinator: AulaHuskelistenCoordinator | None = None

    @property
    def all_coordinators(self) -> Iterator[DataUpdateCoordinator]:
        """Yield all active coordinators."""
        for coord in (
            self.presence_coordinator,
            self.calendar_coordinator,
            self.notifications_coordinator,
            self.messages_coordinator,
            self.library_coordinator,
            self.mu_tasks_coordinator,
            self.mu_ugeplan_coordinator,
            self.easyiq_coordinator,
            self.meebook_coordinator,
            self.huskelisten_coordinator,
        ):
            if coord is not None:
                yield coord

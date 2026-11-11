"""DataUpdateCoordinators for the Aula integration."""

from __future__ import annotations

import asyncio
import functools
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, cast

from aula import (
    AulaAuthenticationError,
    AulaRejectedError,
    CalendarEvent,
    DailyOverview,
    HttpRequestError,
)
from aula.models import Message, MessageThread, MUTask, MUWeeklyPerson, Notification
from aula.widgets import EasyIQChildNotInPortal, EasyIQWrongChildSession
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    AULA_AUTHORIZATION_DENIED,
    CALENDAR_POLL_INTERVAL,
    DOMAIN,
    EASYIQ_POLL_INTERVAL,
    EVENT_NOTIFICATION,
    HUSKELISTEN_POLL_INTERVAL,
    LIBRARY_POLL_INTERVAL,
    LOGGER,
    MAX_MESSAGE_ITEMS,
    MAX_PREVIEW_CHARS,
    MEEBOOK_POLL_INTERVAL,
    MESSAGES_POLL_INTERVAL,
    MU_TASKS_POLL_INTERVAL,
    MU_UGEPLAN_POLL_INTERVAL,
    NOTIFICATIONS_POLL_INTERVAL,
    PRESENCE_POLL_INTERVAL,
    TRANSIENT_FAILURE_TOLERANCE,
    WIDGET_BIBLIOTEKET,
    WIDGET_EASYIQ_WEEKPLAN,
)
from .data import (
    EasyIQChildData,
    HuskelistenChildData,
    LibraryChildData,
    MeebookWeekplanData,
    MessagePreview,
    MessagesData,
    WidgetContext,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine

    from aula import AulaApiClient, Child, Profile
    from aula.models.meebook_weekplan import MeebookTask
    from aula.models.mu_weekly_letter import MUWeeklyLetter
    from aula.models.presence_template import PresenceWeekTemplate
    from homeassistant.core import HomeAssistant

    from .data import AulaConfigEntry
    from .token_manager import AulaTokenManager


@asynccontextmanager
async def _aula_api_errors(
    token_manager: AulaTokenManager,
    client: AulaApiClient,
) -> AsyncIterator[None]:
    """
    Translate Aula API errors to Home Assistant exceptions.

    ``client`` is the client the wrapped requests run on, so the session is
    only rebuilt while that client is still the current one.
    """
    try:
        yield
    except AulaAuthenticationError as err:
        try:
            await token_manager.async_refresh_and_rebuild_client(client)
            msg = "Session refreshed, retrying"
            raise UpdateFailed(msg) from err
        except AulaAuthenticationError:
            pass
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed",
        ) from err
    except HttpRequestError as err:
        # Besides its connection, server and rate-limit subclasses, aula raises
        # AulaRejectedError when Aula answers with an error code in the body,
        # often with HTTP 200.
        msg = f"Error communicating with Aula API: {err}"
        if isinstance(err, AulaRejectedError) and err.code == AULA_AUTHORIZATION_DENIED:
            msg = await _async_rebuild_after_rejection(token_manager, client, msg)
        raise UpdateFailed(msg) from err


async def _async_rebuild_after_rejection(
    token_manager: AulaTokenManager, client: AulaApiClient, msg: str
) -> str:
    """Rebuild a session Aula refused, returning the message to fail the poll with."""
    try:
        if await token_manager.async_rebuild_after_rejection(client):
            return f"{msg}; built a new session, retrying"
    except AulaAuthenticationError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed",
        ) from err
    except HttpRequestError as err:
        return f"{msg}; building a new session failed: {err}"
    return msg


class _TransientFailureTolerance:
    """Mixin holding the consecutive transient failure counter."""

    _transient_failures: int = 0


def _tolerate_transient_failures[DataT](
    func: Callable[[Any], Coroutine[Any, Any, DataT]],
) -> Callable[[Any], Coroutine[Any, Any, DataT]]:
    """Keep the previous data for up to TRANSIENT_FAILURE_TOLERANCE failed polls."""

    @functools.wraps(func)
    async def _wrapper(self: Any) -> DataT:
        try:
            data = await func(self)
        except UpdateFailed as err:
            # Only a success resets the count, so a long outage stays unavailable.
            self._transient_failures += 1
            if (
                self.data is None
                or self._transient_failures > TRANSIENT_FAILURE_TOLERANCE
            ):
                raise
            LOGGER.debug(
                "Transient failure %s/%s fetching %s data, keeping previous data: %s",
                self._transient_failures,
                TRANSIENT_FAILURE_TOLERANCE,
                self.name,
                err,
            )
            return cast("DataT", self.data)
        self._transient_failures = 0
        return data

    return _wrapper


def _get_child_widget_id(child: Child) -> str:
    """Get the widget user ID for a child from its raw data."""
    # TODO(aula-package): Child does not expose userId as a public field.  # noqa: TD003, FIX002, E501
    # Add Child.user_id to the aula package, then replace this _raw access.
    raw = child._raw  # noqa: SLF001
    if raw:
        return str(raw["userId"])
    return str(child.id)


def _get_child_institution_code(child: Child) -> str:
    """Get the institution code for a child from its raw data."""
    # TODO(aula-package): Child does not expose institutionCode as a public field.  # noqa: TD003, FIX002, E501
    # Add Child.institution_code to the aula package, then replace this _raw access.
    raw = child._raw  # noqa: SLF001
    if raw:
        return raw.get("institutionProfile", {}).get("institutionCode", "")
    return ""


class _PresenceChildData:
    """Presence data for a single child (overview + today's template)."""

    __slots__ = ("overview", "self_decider_end", "self_decider_start")

    def __init__(
        self,
        overview: DailyOverview | None,
        self_decider_start: str | None = None,
        self_decider_end: str | None = None,
    ) -> None:
        self.overview = overview
        self.self_decider_start = self_decider_start
        self.self_decider_end = self_decider_end


class AulaPresenceCoordinator(
    _TransientFailureTolerance,
    DataUpdateCoordinator[dict[int, _PresenceChildData]],
):
    """Coordinator for fetching presence data for all children."""

    config_entry: AulaConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: AulaApiClient,
        profile: Profile,
        token_manager: AulaTokenManager,
    ) -> None:
        """Initialize the presence coordinator."""
        super().__init__(
            hass,
            logger=LOGGER,
            name="Aula Presence",
            update_interval=timedelta(seconds=PRESENCE_POLL_INTERVAL),
        )
        self.client = client
        self.profile = profile
        self.token_manager = token_manager

    @_tolerate_transient_failures
    async def _async_update_data(self) -> dict[int, _PresenceChildData]:
        """Fetch presence data and today's templates for all children."""
        child_ids = [child.id for child in self.profile.children]
        today = dt_util.now().date()

        async with _aula_api_errors(self.token_manager, self.client):
            overview_results, templates = await asyncio.gather(
                asyncio.gather(
                    *(self.client.get_daily_overview(cid) for cid in child_ids)
                ),
                self.client.get_presence_templates(
                    institution_profile_ids=child_ids,
                    from_date=today,
                    to_date=today,
                ),
            )

        self_decider_map = _extract_self_decider_times(templates, today)

        return {
            child.id: _PresenceChildData(
                overview=overview,
                self_decider_start=self_decider_map.get(child.id, (None, None))[0],
                self_decider_end=self_decider_map.get(child.id, (None, None))[1],
            )
            for child, overview in zip(
                self.profile.children, overview_results, strict=False
            )
        }


def _extract_self_decider_times(
    templates: list[PresenceWeekTemplate],
    today: date,
) -> dict[int, tuple[str | None, str | None]]:
    """Extract self-decider start/end times from today's templates."""
    result: dict[int, tuple[str | None, str | None]] = {}
    today_iso = today.isoformat()
    for week_tmpl in templates:
        ip = week_tmpl.institution_profile
        if not ip or ip.id is None:
            continue
        for day in week_tmpl.day_templates:
            if day.by_date != today_iso:
                continue
            sta = day.spare_time_activity
            if sta:
                result[ip.id] = (sta.start_time, sta.end_time)
    return result


class AulaCalendarCoordinator(
    _TransientFailureTolerance,
    DataUpdateCoordinator[dict[int, list[CalendarEvent]]],
):
    """Coordinator for fetching calendar events for all children."""

    config_entry: AulaConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: AulaApiClient,
        profile: Profile,
        token_manager: AulaTokenManager,
    ) -> None:
        """Initialize the calendar coordinator."""
        super().__init__(
            hass,
            logger=LOGGER,
            name="Aula Calendar",
            update_interval=timedelta(seconds=CALENDAR_POLL_INTERVAL),
        )
        self.client = client
        self.profile = profile
        self.token_manager = token_manager

    @_tolerate_transient_failures
    async def _async_update_data(self) -> dict[int, list[CalendarEvent]]:
        """Fetch calendar events for all children."""
        async with _aula_api_errors(self.token_manager, self.client):
            now = dt_util.now()
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return await self.client.get_calendar_events_by_child(
                [child.id for child in self.profile.children],
                start,
                start + timedelta(days=30),
            )


class AulaNotificationsCoordinator(
    _TransientFailureTolerance,
    DataUpdateCoordinator[list[Notification]],
):
    """Coordinator for fetching notifications for the active profile."""

    config_entry: AulaConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: AulaApiClient,
        token_manager: AulaTokenManager,
    ) -> None:
        """Initialize the notifications coordinator."""
        super().__init__(
            hass,
            logger=LOGGER,
            name="Aula Notifications",
            update_interval=timedelta(seconds=NOTIFICATIONS_POLL_INTERVAL),
        )
        self.client = client
        self.token_manager = token_manager
        self._known_ids: set[str] | None = None

    @_tolerate_transient_failures
    async def _async_update_data(self) -> list[Notification]:
        """Fetch notifications for the active profile."""
        async with _aula_api_errors(self.token_manager, self.client):
            notifications = await self.client.get_notifications_for_active_profile(
                limit=50
            )

        new_ids = {n.id for n in notifications}
        if self._known_ids is None:
            # First fetch — populate without firing events
            self._known_ids = new_ids
        else:
            for n in notifications:
                if n.id not in self._known_ids:
                    self.hass.bus.async_fire(
                        EVENT_NOTIFICATION,
                        {
                            "notification_id": n.id,
                            "title": n.title,
                            "module": n.module,
                            "event_type": n.event_type,
                            "related_child_name": n.related_child_name,
                            "created_at": n.created_at,
                        },
                    )
            self._known_ids = new_ids

        return notifications


def _message_preview(
    thread: MessageThread,
    messages: list[Message] | BaseException,
    unread_ids: set[str],
) -> MessagePreview:
    """Shape a thread and its newest message into a MessagePreview."""
    # TODO(aula-package): MessageThread does not expose its timestamp as a  # noqa: TD003, FIX002, E501
    # public field. Add it to the aula package, then replace this _raw access.
    thread_raw = thread._raw or {}  # noqa: SLF001
    sender: str | None = None
    sent_at: str | None = None
    preview = ""
    has_attachments = False

    if isinstance(messages, BaseException):
        LOGGER.warning(
            "Could not fetch messages for thread %s: %s", thread.thread_id, messages
        )
    elif messages:
        message = messages[0]
        sender = message.sender_name
        if message.send_datetime is not None:
            sent_at = message.send_datetime.isoformat()
        preview = message.content[:MAX_PREVIEW_CHARS]
        has_attachments = message.has_attachments

    return MessagePreview(
        thread_id=thread.thread_id,
        subject=thread.subject,
        sender=sender,
        date=sent_at or thread_raw.get("lastUpdatedDate"),
        unread=thread.thread_id in unread_ids,
        preview=preview,
        has_attachments=has_attachments,
    )


class AulaMessagesCoordinator(
    _TransientFailureTolerance,
    DataUpdateCoordinator[MessagesData],
):
    """Coordinator for fetching the latest message threads for the active profile."""

    config_entry: AulaConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: AulaApiClient,
        token_manager: AulaTokenManager,
    ) -> None:
        """Initialize the messages coordinator."""
        super().__init__(
            hass,
            logger=LOGGER,
            name="Aula Messages",
            update_interval=timedelta(seconds=MESSAGES_POLL_INTERVAL),
        )
        self.client = client
        self.token_manager = token_manager

    @_tolerate_transient_failures
    async def _async_update_data(self) -> MessagesData:
        """Fetch the latest threads plus the newest message in each."""
        async with _aula_api_errors(self.token_manager, self.client):
            threads = await self.client.get_message_threads()
            unread_threads = await self.client.get_message_threads(filter_on="unread")
            latest = threads[:MAX_MESSAGE_ITEMS]
            # A single unreadable thread must not fail the whole update. An auth
            # problem would already have surfaced on the two calls above.
            thread_messages = await asyncio.gather(
                *(
                    self.client.get_messages_for_thread(thread.thread_id, limit=1)
                    for thread in latest
                ),
                return_exceptions=True,
            )

        unread_ids = {thread.thread_id for thread in unread_threads}
        return MessagesData(
            unread_count=len(unread_threads),
            messages=[
                _message_preview(thread, messages, unread_ids)
                for thread, messages in zip(latest, thread_messages, strict=True)
            ],
        )


class _AulaWidgetCoordinator[T](_TransientFailureTolerance, DataUpdateCoordinator[T]):
    """Shared base for all widget coordinators."""

    config_entry: AulaConfigEntry

    def __init__(  # noqa: PLR0913
        self,
        hass: HomeAssistant,
        client: AulaApiClient,
        profile: Profile,
        widget_context: WidgetContext,
        token_manager: AulaTokenManager,
        *,
        name: str,
        update_interval: timedelta,
    ) -> None:
        """Initialize the widget coordinator."""
        super().__init__(
            hass,
            logger=LOGGER,
            name=name,
            update_interval=update_interval,
        )
        self.client = client
        self.profile = profile
        self.widget_context = widget_context
        self.token_manager = token_manager
        # Pre-build name lookup for child matching
        self._child_by_name: dict[str, Child] = {
            child.name: child for child in profile.children
        }

    def _match_child(self, name: str) -> Child | None:
        """Match a name string to a child, with partial-match fallback."""
        child = self._child_by_name.get(name)
        if child:
            return child
        # Fallback: partial match
        for child_name, child in self._child_by_name.items():
            if child_name in name or name in child_name:
                return child
        return None


class AulaLibraryCoordinator(
    _AulaWidgetCoordinator[dict[int, LibraryChildData]],
):
    """Coordinator for fetching library loan data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AulaApiClient,
        profile: Profile,
        widget_context: WidgetContext,
        token_manager: AulaTokenManager,
    ) -> None:
        """Initialize the library coordinator."""
        super().__init__(
            hass,
            client,
            profile,
            widget_context,
            token_manager,
            name="Aula Library",
            update_interval=timedelta(seconds=LIBRARY_POLL_INTERVAL),
        )

    @_tolerate_transient_failures
    async def _async_update_data(self) -> dict[int, LibraryChildData]:
        """Fetch library status and distribute to children."""
        async with _aula_api_errors(self.token_manager, self.client):
            status = await self.client.widgets.get_library_status(
                widget_id=WIDGET_BIBLIOTEKET,
                children=self.widget_context.child_filter,
                institutions=self.widget_context.institution_filter,
                session_uuid=self.widget_context.session_uuid,
            )

        result: dict[int, LibraryChildData] = {
            child.id: LibraryChildData() for child in self.profile.children
        }

        for loan in status.loans:
            child = self._match_child(loan.patron_display_name)
            if child and child.id in result:
                result[child.id].loans.append(loan)

        for loan in status.longterm_loans:
            child = self._match_child(loan.patron_display_name)
            if child and child.id in result:
                result[child.id].longterm_loans.append(loan)

        # Reservations don't have patron info, assign to all children
        for child_data in result.values():
            child_data.reservations = status.reservations

        return result


class AulaMUTasksCoordinator(
    _AulaWidgetCoordinator[dict[int, list[MUTask]]],
):
    """Coordinator for fetching Min Uddannelse tasks."""

    def __init__(  # noqa: PLR0913
        self,
        hass: HomeAssistant,
        client: AulaApiClient,
        profile: Profile,
        widget_context: WidgetContext,
        token_manager: AulaTokenManager,
        widget_id: str,
    ) -> None:
        """
        Initialize the MU tasks coordinator.

        ``widget_id`` is the widget whose token mints access to the opgaveliste
        endpoint; which one the account has is resolved when the coordinators
        are created.
        """
        self.widget_id = widget_id
        super().__init__(
            hass,
            client,
            profile,
            widget_context,
            token_manager,
            name="Aula MU Tasks",
            update_interval=timedelta(seconds=MU_TASKS_POLL_INTERVAL),
        )

    @_tolerate_transient_failures
    async def _async_update_data(self) -> dict[int, list[MUTask]]:
        """Fetch MU tasks and distribute to children."""
        week = dt_util.now().strftime("%G-W%V")
        async with _aula_api_errors(self.token_manager, self.client):
            tasks = await self.client.widgets.get_mu_tasks(
                widget_id=self.widget_id,
                child_filter=self.widget_context.child_filter,
                institution_filter=self.widget_context.institution_filter,
                week=week,
                session_uuid=self.widget_context.session_uuid,
            )

        result: dict[int, list[MUTask]] = {
            child.id: [] for child in self.profile.children
        }

        for task in tasks:
            child = self._match_child(task.student_name)
            if child and child.id in result:
                result[child.id].append(task)

        return result


class _MUUgeplanData:
    """Data container for MU weekly notes (current + next week)."""

    __slots__ = ("current", "next_week")

    def __init__(
        self,
        current: dict[int, list[MUWeeklyLetter]],
        next_week: dict[int, list[MUWeeklyLetter]],
    ) -> None:
        self.current = current
        self.next_week = next_week


class AulaMUUgeplanCoordinator(
    _AulaWidgetCoordinator[_MUUgeplanData],
):
    """Coordinator for fetching Min Uddannelse weekly notes (ugenoter)."""

    def __init__(  # noqa: PLR0913
        self,
        hass: HomeAssistant,
        client: AulaApiClient,
        profile: Profile,
        widget_context: WidgetContext,
        token_manager: AulaTokenManager,
        widget_id: str,
    ) -> None:
        """
        Initialize the MU ugeplan coordinator.

        ``widget_id`` is the widget whose token mints access to the ugebrev
        endpoint, resolved like the MU tasks coordinator's.
        """
        self.widget_id = widget_id
        super().__init__(
            hass,
            client,
            profile,
            widget_context,
            token_manager,
            name="Aula MU Ugeplan",
            update_interval=timedelta(seconds=MU_UGEPLAN_POLL_INTERVAL),
        )

    async def _fetch_week(self, week: str) -> dict[int, list[MUWeeklyLetter]]:
        """Fetch MU weekly notes for a single week and distribute to children."""
        persons: list[MUWeeklyPerson] = await self.client.widgets.get_ugeplan(
            widget_id=self.widget_id,
            child_filter=self.widget_context.child_filter,
            institution_filter=self.widget_context.institution_filter,
            week=week,
            session_uuid=self.widget_context.session_uuid,
        )

        result: dict[int, list[MUWeeklyLetter]] = {
            child.id: [] for child in self.profile.children
        }

        for person in persons:
            child = self._match_child(person.name)
            if child and child.id in result:
                for institution in person.institutions:
                    result[child.id].extend(institution.letters)

        return result

    @_tolerate_transient_failures
    async def _async_update_data(self) -> _MUUgeplanData:
        """Fetch MU weekly notes for current and next week."""
        now = dt_util.now()
        current_week = now.strftime("%G-W%V")
        next_week = (now + timedelta(weeks=1)).strftime("%G-W%V")

        async with _aula_api_errors(self.token_manager, self.client):
            current = await self._fetch_week(current_week)
            next_week_data = await self._fetch_week(next_week)

        return _MUUgeplanData(current=current, next_week=next_week_data)


class AulaEasyIQCoordinator(
    _AulaWidgetCoordinator[dict[int, EasyIQChildData]],
):
    """Coordinator for fetching EasyIQ weekplan and homework."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AulaApiClient,
        profile: Profile,
        widget_context: WidgetContext,
        token_manager: AulaTokenManager,
    ) -> None:
        """Initialize the EasyIQ coordinator."""
        super().__init__(
            hass,
            client,
            profile,
            widget_context,
            token_manager,
            name="Aula EasyIQ",
            update_interval=timedelta(seconds=EASYIQ_POLL_INTERVAL),
        )

    @_tolerate_transient_failures
    async def _async_update_data(self) -> dict[int, EasyIQChildData]:
        """Fetch EasyIQ weekplan and homework per child."""
        week = dt_util.now().strftime("%G-W%V")

        async def _fetch_child(child: Child) -> tuple[int, EasyIQChildData]:
            child_id_str = _get_child_widget_id(child)
            inst_code = _get_child_institution_code(child)
            if not inst_code and self.widget_context.institution_filter:
                inst_code = self.widget_context.institution_filter[0]
            inst_filter = [inst_code]

            # EasyIQ serves both views from its school portal, which needs the
            # child's institution profile ID alongside their UniLogin, plus
            # every child's UniLogin as the portal's child filter and every
            # institution the guardian has, which is what the portal session is
            # established under. Without the latter a child at a second school
            # is not found (aula 1.8.0).
            try:
                weekplan, homework = await asyncio.gather(
                    self.client.widgets.get_easyiq_weekplan(
                        week=week,
                        session_uuid=self.widget_context.session_uuid,
                        institution_filter=inst_filter,
                        child_id=child_id_str,
                        widget_id=WIDGET_EASYIQ_WEEKPLAN,
                        child_profile_id=str(child.id),
                        all_child_user_ids=self.widget_context.child_filter,
                        all_institution_filter=self.widget_context.institution_filter,
                    ),
                    self.client.widgets.get_easyiq_homework(
                        week=week,
                        session_uuid=self.widget_context.session_uuid,
                        institution_filter=inst_filter,
                        child_id=child_id_str,
                        child_profile_id=str(child.id),
                        all_child_user_ids=self.widget_context.child_filter,
                        all_institution_filter=self.widget_context.institution_filter,
                    ),
                )
            except EasyIQChildNotInPortal:
                # The child's institution is not on EasyIQ at all — daycare,
                # typically. An absence, not a failure, and permanent as far as
                # polling is concerned, so keep the other children's data and
                # leave this one's sensors empty.
                LOGGER.debug("EasyIQ has no record of child %s", child.id)
                return child.id, EasyIQChildData()
            return child.id, EasyIQChildData(weekplan=weekplan, homework=homework)

        async with _aula_api_errors(self.token_manager, self.client):
            try:
                results = await asyncio.gather(
                    *(_fetch_child(child) for child in self.profile.children)
                )
            except EasyIQWrongChildSession as err:
                # The portal answered for a different child than we switched to,
                # so every row in this pass is suspect. Fail the update rather
                # than publish one child's week under another's name.
                msg = f"EasyIQ returned another child's data: {err}"
                raise UpdateFailed(msg) from err
            except RuntimeError as err:
                # With several children, aula refuses to read EasyIQ when the
                # portal does not say which child is which, rather than guess
                # and risk the same mix-up (aula 1.13.0).
                msg = f"EasyIQ could not tell the children apart: {err}"
                raise UpdateFailed(msg) from err

        return dict(results)


class AulaMeebookCoordinator(
    _AulaWidgetCoordinator[MeebookWeekplanData],
):
    """Coordinator for fetching Meebook weekplan data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AulaApiClient,
        profile: Profile,
        widget_context: WidgetContext,
        token_manager: AulaTokenManager,
    ) -> None:
        """Initialize the Meebook coordinator."""
        super().__init__(
            hass,
            client,
            profile,
            widget_context,
            token_manager,
            name="Aula Meebook",
            update_interval=timedelta(seconds=MEEBOOK_POLL_INTERVAL),
        )

    async def _fetch_week(self, week: str) -> dict[int, list[MeebookTask]]:
        """Fetch one Meebook weekplan and distribute tasks to children."""
        student_plans = await self.client.widgets.get_meebook_weekplan(
            child_filter=self.widget_context.child_filter,
            institution_filter=self.widget_context.institution_filter,
            week=week,
            session_uuid=self.widget_context.session_uuid,
        )

        result: dict[int, list[MeebookTask]] = {
            child.id: [] for child in self.profile.children
        }

        for plan in student_plans:
            child = self._match_child(plan.name)
            if child and child.id in result:
                for day_plan in plan.week_plan:
                    result[child.id].extend(day_plan.tasks)

        return result

    @_tolerate_transient_failures
    async def _async_update_data(self) -> MeebookWeekplanData:
        """Fetch Meebook tasks for current and next week."""
        now = dt_util.now()
        current_week = now.strftime("%G-W%V")
        next_week = (now + timedelta(weeks=1)).strftime("%G-W%V")

        async with _aula_api_errors(self.token_manager, self.client):
            current = await self._fetch_week(current_week)
            try:
                next_week_data = await self._fetch_week(next_week)
            except AulaAuthenticationError:
                raise
            except HttpRequestError:
                # Optional future data must not hide the current week's tasks.
                # Authentication errors still reach the outer error translator.
                LOGGER.warning("Could not fetch next week's Meebook tasks")
                next_week_data = None

        return MeebookWeekplanData(current=current, next_week=next_week_data)


class AulaHuskelistenCoordinator(
    _AulaWidgetCoordinator[dict[int, HuskelistenChildData]],
):
    """Coordinator for fetching Huskelisten reminders."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AulaApiClient,
        profile: Profile,
        widget_context: WidgetContext,
        token_manager: AulaTokenManager,
    ) -> None:
        """Initialize the Huskelisten coordinator."""
        super().__init__(
            hass,
            client,
            profile,
            widget_context,
            token_manager,
            name="Aula Huskelisten",
            update_interval=timedelta(seconds=HUSKELISTEN_POLL_INTERVAL),
        )

    @_tolerate_transient_failures
    async def _async_update_data(self) -> dict[int, HuskelistenChildData]:
        """Fetch Huskelisten reminders and distribute to children."""
        now = dt_util.now()
        from_date = now.strftime("%Y-%m-%d")
        due_no_later_than = (now + timedelta(days=30)).strftime("%Y-%m-%d")

        async with _aula_api_errors(self.token_manager, self.client):
            user_reminders_list = await self.client.widgets.get_momo_reminders(
                children=self.widget_context.child_filter,
                institutions=self.widget_context.institution_filter,
                session_uuid=self.widget_context.session_uuid,
                from_date=from_date,
                due_no_later_than=due_no_later_than,
            )

        result: dict[int, HuskelistenChildData] = {
            child.id: HuskelistenChildData() for child in self.profile.children
        }

        for user_reminders in user_reminders_list:
            child = self._match_child(user_reminders.user_name)
            if child and child.id in result:
                result[child.id].team_reminders.extend(user_reminders.team_reminders)
                result[child.id].assignment_reminders.extend(
                    user_reminders.assignment_reminders
                )

        return result

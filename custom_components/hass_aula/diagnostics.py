"""Diagnostics support for the Aula integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import AulaConfigEntry

REDACTED = "**REDACTED**"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,  # noqa: ARG001
    entry: AulaConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime_data = entry.runtime_data
    children = runtime_data.profile.children

    # Aula ids identify the account, so children are named by position instead.
    labels = {
        child.id: f"child_{position}"
        for position, child in enumerate(children, start=1)
    }

    def label(child_id: int) -> str:
        return labels.get(child_id, REDACTED)

    children_data = [
        {
            "id": label(child.id),
            "name": REDACTED,
            "institution_name": REDACTED,
        }
        for child in children
    ]

    presence_data: dict[str, Any] = {}
    for child_id, child_data in runtime_data.presence_coordinator.data.items():
        overview = child_data.overview if child_data else None
        if overview is None:
            presence_data[label(child_id)] = None
        else:
            presence_data[label(child_id)] = {
                "status": overview.status.name if overview.status else None,
                "location": overview.location.name if overview.location else None,
                "check_in_time": str(overview.check_in_time)
                if overview.check_in_time
                else None,
                "check_out_time": str(overview.check_out_time)
                if overview.check_out_time
                else None,
            }

    calendar_data: dict[str, int] = {}
    for child_id, events in runtime_data.calendar_coordinator.data.items():
        calendar_data[label(child_id)] = len(events)

    # Counts only — message subjects, senders and previews must not leak here.
    messages_data = runtime_data.messages_coordinator.data

    result: dict[str, Any] = {
        "profile": {
            "profile_id": REDACTED,
            "display_name": REDACTED,
            "children_count": len(children),
            "children": children_data,
        },
        "presence": presence_data,
        "calendar_event_counts": calendar_data,
        "messages": {
            "unread_count": messages_data.unread_count if messages_data else 0,
            "listed_count": len(messages_data.messages) if messages_data else 0,
        },
    }

    # Widget data summaries
    widgets: dict[str, Any] = {}

    if runtime_data.library_coordinator and runtime_data.library_coordinator.data:
        widgets["library"] = {
            label(child_id): len(data.loans) + len(data.longterm_loans)
            for child_id, data in runtime_data.library_coordinator.data.items()
        }

    if runtime_data.mu_tasks_coordinator and runtime_data.mu_tasks_coordinator.data:
        widgets["mu_tasks"] = {
            label(child_id): len(tasks)
            for child_id, tasks in runtime_data.mu_tasks_coordinator.data.items()
        }

    if runtime_data.mu_ugeplan_coordinator and runtime_data.mu_ugeplan_coordinator.data:
        ugeplan_data = runtime_data.mu_ugeplan_coordinator.data
        widgets["mu_ugeplan"] = {
            label(child_id): len(letters)
            for child_id, letters in ugeplan_data.current.items()
        }

    if runtime_data.easyiq_coordinator and runtime_data.easyiq_coordinator.data:
        widgets["easyiq"] = {
            label(child_id): {
                "weekplan": len(data.weekplan),
                "homework": len(data.homework),
            }
            for child_id, data in runtime_data.easyiq_coordinator.data.items()
        }

    if runtime_data.meebook_coordinator and runtime_data.meebook_coordinator.data:
        meebook_data = runtime_data.meebook_coordinator.data
        widgets["meebook"] = {
            label(child_id): {
                "current_week": len(tasks),
                "next_week": (
                    len(meebook_data.next_week.get(child_id, []))
                    if meebook_data.next_week is not None
                    else None
                ),
            }
            for child_id, tasks in meebook_data.current.items()
        }

    if (
        runtime_data.huskelisten_coordinator
        and runtime_data.huskelisten_coordinator.data
    ):
        widgets["huskelisten"] = {
            label(child_id): len(data.team_reminders) + len(data.assignment_reminders)
            for child_id, data in runtime_data.huskelisten_coordinator.data.items()
        }

    if widgets:
        result["widgets"] = widgets

    return result

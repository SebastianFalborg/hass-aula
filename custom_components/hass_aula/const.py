"""Constants for the Aula integration."""

from __future__ import annotations

from logging import Logger, getLogger

from aula import ActivityType
from aula.const import (
    MIN_UDDANNELSE_TASK_WIDGETS,
    MIN_UDDANNELSE_UGEPLAN_WIDGETS,
    WIDGET_BIBLIOTEKET,
    WIDGET_EASYIQ_HOMEWORK,
    WIDGET_EASYIQ_WEEKPLAN,
    WIDGET_HUSKELISTEN,
    WIDGET_MEEBOOK,
    WIDGET_MIN_UDDANNELSE_SSO,
    WIDGET_MIN_UDDANNELSE_TASKS,
    WIDGET_MIN_UDDANNELSE_UGEPLAN,
)
from homeassistant.const import Platform

LOGGER: Logger = getLogger(__package__)

DOMAIN = "hass_aula"

EVENT_NOTIFICATION = "hass_aula_notification"

CONF_AUTH_METHOD = "auth_method"
CONF_MITID_PASSWORD = "mitid_password"  # noqa: S105
CONF_MITID_USERNAME = "mitid_username"
CONF_TOKEN_CODE = "token_code"  # noqa: S105
CONF_TOKEN_DATA = "token_data"  # noqa: S105
CONF_WIDGETS = "widgets"

# Config entry schema version. Minor 2 replaced the combined EasyIQ widget ID
# with the weekly plan and homework IDs; see LEGACY_WIDGET_EASYIQ.
CONFIG_ENTRY_VERSION = 1
CONFIG_ENTRY_MINOR_VERSION = 2

# MitID authenticators this integration can drive. "app" approves the login in
# the MitID app; "token" reads a one-time code off a MitID kodeviser (code
# display), which users without a smartphone rely on.
AUTH_METHOD_APP = "app"
AUTH_METHOD_TOKEN = "token"  # noqa: S105
AUTH_METHODS = [AUTH_METHOD_APP, AUTH_METHOD_TOKEN]
TOKEN_CODE_LENGTH = 6

SERVICE_UPDATE_PRESENCE = "update_presence"
SERVICE_GET_THREAD_MESSAGES = "get_thread_messages"
SERVICE_MARK_THREAD_READ = "mark_thread_read"

ATTR_ACTIVITY_TYPE = "activity_type"
ATTR_COMMENT = "comment"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_DATE = "date"
ATTR_ENTRY_TIME = "entry_time"
ATTR_EXIT_TIME = "exit_time"
ATTR_EXIT_WITH = "exit_with"
ATTR_EXPIRES_AT = "expires_at"
ATTR_LIMIT = "limit"
ATTR_REPEAT = "repeat"
ATTR_THREAD_ID = "thread_id"

# Aula's own message list pages at 10; 50 is a generous ceiling for one thread.
MAX_THREAD_MESSAGES = 50
DEFAULT_THREAD_MESSAGES = 5

ACTIVITY_TYPE_PICKED_UP_BY = "picked_up_by"

# Maps the action's option slugs to the aula package's ActivityType members.
# Whether a type needs exit_with comes from ActivityType.requires_exit_with.
ACTIVITY_TYPES: dict[str, ActivityType] = {
    ACTIVITY_TYPE_PICKED_UP_BY: ActivityType.PICKED_UP_BY,
    "self_decider": ActivityType.SELF_DECIDER,
    "send_home": ActivityType.SEND_HOME,
    "go_home_with": ActivityType.GO_HOME_WITH,
    "drop_off_time": ActivityType.DROP_OFF_TIME,
}

REPEAT_NEVER = "never"

# Maps the action's snake_case options to the aula package's repeat_pattern values.
REPEAT_PATTERNS: dict[str, str] = {
    REPEAT_NEVER: "Never",
    "weekly": "Weekly",
    "every_2_weeks": "Every2Weeks",
}

PRESENCE_POLL_INTERVAL = 300  # 5 minutes
NOTIFICATIONS_POLL_INTERVAL = 300  # 5 minutes
CALENDAR_POLL_INTERVAL = 3600  # 60 minutes
MESSAGES_POLL_INTERVAL = 1800  # 30 minutes

# Widget poll intervals (seconds)
LIBRARY_POLL_INTERVAL = 3600  # 60 minutes
MU_TASKS_POLL_INTERVAL = 1800  # 30 minutes
MU_UGEPLAN_POLL_INTERVAL = 1800  # 30 minutes
EASYIQ_POLL_INTERVAL = 1800  # 30 minutes
MEEBOOK_POLL_INTERVAL = 3600  # 60 minutes
HUSKELISTEN_POLL_INTERVAL = 1800  # 30 minutes

TRANSIENT_FAILURE_TOLERANCE = 2  # failed polls in a row that keep the last data

# Aula's status code for a request it refuses as unauthorized. A session Aula
# accepted until then is rebuilt, at most once per cooldown (seconds), so a
# refusal that a new session does not fix is not rebuilt on every poll.
AULA_AUTHORIZATION_DENIED = 10
REJECTION_REBUILD_COOLDOWN = 1800  # 30 minutes

# Latest-messages sensor shaping
MAX_MESSAGE_ITEMS = 5
MAX_PREVIEW_CHARS = 200

# aula <= 1.5.0 carried a single combined EasyIQ widget under this ID, which
# 1.6.0 dropped: Aula itself lists the weekly plan (0128) and homework (0142)
# as separate widgets. Entries stored before then are migrated onto the two
# real IDs, so this exists only for that migration.
LEGACY_WIDGET_EASYIQ = "0001"

# Widgets whose token is accepted by the MinUddannelse opgaveliste endpoint,
# preferred first. Re-exported from the aula package so the fallback order and
# the set of widgets we offer stay in step.
MU_TASK_WIDGETS: tuple[str, ...] = MIN_UDDANNELSE_TASK_WIDGETS

# Likewise for the weekly letters (ugenoter): a school without the Ugenoter
# widget can still have them, fetched with an SSO widget token.
MU_UGEPLAN_WIDGETS: tuple[str, ...] = MIN_UDDANNELSE_UGEPLAN_WIDGETS

# Some Aula accounts advertise Meebook through the alternate "Meebook overblik"
# widget (0119) instead of the legacy weekplan widget (0004). The Meebook
# weekplan endpoint still accepts a token minted for 0004, so 0119 is a
# discovery/enablement alias only; the aula package deliberately keeps using
# WIDGET_MEEBOOK (0004) when it calls the Meebook API.
WIDGET_MEEBOOK_OVERVIEW = "0119"
MEEBOOK_PROVIDER_WIDGETS: tuple[str, ...] = (
    WIDGET_MEEBOOK,
    WIDGET_MEEBOOK_OVERVIEW,
)

SUPPORTED_WIDGETS: frozenset[str] = frozenset(
    {
        WIDGET_BIBLIOTEKET,
        WIDGET_EASYIQ_HOMEWORK,
        WIDGET_EASYIQ_WEEKPLAN,
        WIDGET_HUSKELISTEN,
        *MEEBOOK_PROVIDER_WIDGETS,
        WIDGET_MIN_UDDANNELSE_SSO,
        WIDGET_MIN_UDDANNELSE_TASKS,
        WIDGET_MIN_UDDANNELSE_UGEPLAN,
    }
)

PARALLEL_UPDATES = 1

PLATFORMS: list[Platform] = [
    Platform.CALENDAR,
    Platform.SENSOR,
]

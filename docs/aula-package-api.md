# Aula Python Package API Reference

> **Package:** `aula==1.17.0`
> **Source:** `../aula` (relative to this repo)
> **Last updated:** 2026-11-11

---

## Table of Contents

- [AulaApiClient](#aulaapiclient)
- [AulaWidgetsClient](#aulawidgetsclient)
- [Data Models](#data-models)
- [Enums](#enums)
- [Exceptions](#exceptions)
- [Constants](#constants)
- [HTTP Layer](#http-layer)
- [Authentication](#authentication)
- [Token Storage](#token-storage)
- [Common Patterns](#common-patterns)

---

## AulaApiClient

**Module:** `aula.api_client`

Async client for Aula API endpoints. Transport-agnostic: accepts any `HttpClient` implementation. Authentication uses `access_token` as a query parameter during `init()` to establish a server-side session, then relies on session cookies for all subsequent requests.

### Constructor

```python
AulaApiClient(
    http_client: HttpClient,
    access_token: str | None = None,
    csrf_token: str | None = None,
    on_token_refresh: Callable[[], Awaitable[str | None]] | None = None,
) -> None
```

### Session Management

| Method | Signature | Description |
|--------|-----------|-------------|
| `init` | `async init() -> None` | Discover current API version and establish guardian role |
| `is_logged_in` | `async is_logged_in() -> bool` | Check if session is still authenticated |
| `keep_alive` | `async keep_alive() -> bool` | Extend backend session to prevent timeouts |
| `close` | `async close() -> None` | Close the HTTP client |

Supports `async with` context manager.

### Profile & Context

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_profile` | `async get_profile() -> Profile` | Fetch authenticated user's profile with children, including extended-access ("udvidet adgang") children from `getProfileContext` |
| `get_profile_context` | `async get_profile_context() -> dict[str, Any]` | Fetch profile context for current guardian session |
| `get_profile_master_data` | `async get_profile_master_data(institution_profile_id: int) -> ProfileMasterData \| None` | Fetch extended profile master data (email, phone, address) |

### Widgets

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_widgets` | `async get_widgets() -> list[WidgetConfiguration]` | Return widget configurations available for the current user |

### Daily Overview & Presence

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_daily_overview` | `async get_daily_overview(child_id: int) -> DailyOverview \| None` | Fetch daily overview for a specific child |
| `get_presence_templates` | `async get_presence_templates(institution_profile_ids: list[int], from_date: date, to_date: date) -> list[PresenceWeekTemplate]` | Fetch presence week templates for given profiles and date range |
| `update_presence_template` | `async update_presence_template(institution_profile_id: int, by_date: date, *, entry_time: str, exit_time: str, activity_type: int = 0, exit_with: str \| None = None, comment: str \| None = None, template_id: int \| None = None, repeat_pattern: str = "Never", expires_at: str \| None = None) -> bool` | Create or update presence template (planned entry/exit times); returns True on success |
| `get_pickup_responsibles` | `async get_pickup_responsibles(child_ids: list[int]) -> list[ChildPickupResponsibles]` | Fetch pickup responsibles (family members + saved suggestions) for children |
| `get_presence_registrations` | `async get_presence_registrations(institution_profile_ids: list[int], from_date: date, to_date: date) -> list[PresenceRegistration]` | Fetch presence registrations for given profiles and date range (employee-only) |
| `get_presence_registration_detail` | `async get_presence_registration_detail(registration_id: int) -> PresenceRegistrationDetail \| None` | Fetch detail for a single presence registration (employee-only) |
| `get_presence_states` | `async get_presence_states(institution_profile_ids: list[int] \| None = None) -> list[ChildPresenceState]` | Fetch current presence states for children |
| `get_presence_configuration` | `async get_presence_configuration(child_ids: list[int]) -> list[PresenceConfiguration]` | Fetch presence configuration (pickup rules, etc.) by child IDs |
| `get_activity_overview` | `async get_activity_overview(institution_profile_ids: list[int], week: int, year: int) -> PresenceWeekOverview \| None` | Fetch activity/week overview for presence (employee-only) |
| `get_vacation_registrations` | `async get_vacation_registrations(child_ids: list[int]) -> list[VacationRegistration]` | Fetch vacation registrations for the given children (`Child.id`; a guardian's own or a child's user profile ID is rejected) |
| `update_presence_status` | `async update_presence_status(institution_profile_ids: list[int], status: PresenceState \| int) -> bool` | Set today's presence status, e.g. report a child sick; returns True if Aula accepted |

`update_presence_status` is the endpoint behind the portal's sick button —
reporting a child ill and taking the report back are the same call with a
different status. It always applies to **today**; Aula has no future-dated sick
report, so use `update_presence_template` or a vacation registration for a
planned absence. Taking a report back means sending `PresenceState.NOT_PRESENT`
(what the guardian dashboard sends) or `PresenceState.PRESENT` (what the
presence page sends) — pick whichever matches the child's real situation. An
institution can withhold this from guardians; `get_presence_configuration`
reports that up front via `PresenceConfiguration.can_edit(PresenceModule.REPORT_SICK)`.

### Notifications

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_notifications_for_active_profile` | `async get_notifications_for_active_profile(*, children_ids: list[int] \| None = None, institution_codes: list[str] \| None = None, offset: int = 0, limit: int = 50, module: str \| None = None) -> list[Notification]` | Fetch notifications for active profile |
| `get_notification_settings` | `async get_notification_settings() -> list[NotificationSetting]` | Fetch notification settings for active profile |

### Messaging

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_message_threads` | `async get_message_threads(filter_on: str \| None = None) -> list[MessageThread]` | Fetch first page of message threads, sorted by date descending |
| `get_messages_for_thread` | `async get_messages_for_thread(thread_id: str, limit: int = 5) -> list[Message]` | Fetch latest messages for a specific thread |
| `get_message_folders` | `async get_message_folders(include_deleted: bool = False) -> list[MessageFolder]` | Fetch message folders |
| `get_common_inboxes` | `async get_common_inboxes(institution_profile_ids: list[int] \| None = None) -> list[dict]` | Fetch common inboxes |
| `get_threads_in_bundle` | `async get_threads_in_bundle(bundle_id: int) -> list[MessageThread]` | Fetch threads in a bundle |
| `get_message_info` | `async get_message_info(thread_id: str, message_id: str) -> dict \| None` | Fetch lightweight message info |
| `get_auto_reply` | `async get_auto_reply() -> AutoReply \| None` | Fetch current auto-reply configuration |
| `mark_thread_read` | `async mark_thread_read(thread_id: str) -> bool` | Move the thread's read marker to its newest message, then confirm it with Aula; `False` if the thread holds no markable message |
| `search_messages` | `async search_messages(institution_profile_ids: list[int], institution_codes: list[str], *, text: str = "", from_date: date \| None = None, to_date: date \| None = None, has_attachments: bool \| None = None, limit: int = 100) -> list[Message]` | Search messages with server-side filtering and automatic pagination; logs a warning when the read is incomplete |
| `search_messages_result` | same parameters as `search_messages` `-> PaginationResult[Message]` | Search with completeness metadata; hits repeated across pages are kept once |
| `get_all_message_threads` | `async get_all_message_threads(cutoff_date: date) -> list[dict]` | Paginate threads until older than cutoff_date; warns when incomplete |
| `get_all_message_threads_result` | `async get_all_message_threads_result(cutoff_date: date) -> PaginationResult[dict]` | As above, with completeness metadata |
| `get_all_messages_for_thread` | `async get_all_messages_for_thread(thread_id: str) -> list[dict]` | Paginate all messages for a thread; warns when incomplete |
| `get_all_messages_for_thread_result` | `async get_all_messages_for_thread_result(thread_id: str) -> PaginationResult[dict]` | As above, with completeness metadata |

**`mark_thread_read` (1.12.0)** only handles threads in the guardian's own
mailbox: a thread whose mailbox is not shown to be theirs (common or OTP inbox)
raises `ValueError` before anything is written. Aula rejecting the call, or not
confirming the new marker, raises `HttpRequestError`. A thread that opens with
non-message events (recipients added or removed) is paged through, 20 at a time,
up to `_MAX_THREAD_PAGES` (50); past that it raises `ThreadScanLimitError`
(`aula.api_client`). A message arriving while the thread is marked may stay
unread.

`search_messages` profile IDs must be children only — including a parent can
make Aula reject the request.

### Calendar

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_calendar_events` | `async get_calendar_events(institution_profile_ids: list[int], start: datetime, end: datetime) -> list[CalendarEvent]` | Fetch events for inclusive whole days (time parts ignored); `ValueError` if start date is after end date (1.13.0). Co-taught lesson rows are merged |
| `get_calendar_events_by_child` | `async get_calendar_events_by_child(child_ids: list[int], start: datetime, end: datetime) -> dict[int, list[CalendarEvent]]` | One request for every child; an event shared by several children is listed under each. Booked parent meetings show at their booked slot (one extra request per child, only when the range has a meeting; a non-auth failure keeps the calendar row). Timezone-aware bounds, else `ValueError` (1.17.0) |
| `get_meeting_bookings` | `async get_meeting_bookings(child_id: int, start: datetime, end: datetime) -> list[MeetingBooking]` | A child's booked parent meetings overlapping `[start, end)`, with the booked slot's real times (1.13.0) |
| `get_calendar_event` | `async get_calendar_event(event_id: int, occurrence_datetime: str \| None = None) -> dict \| None` | Fetch a single calendar event by ID |
| `get_important_dates` | `async get_important_dates(limit: int = 10, include_today: bool = True) -> list[dict]` | Fetch upcoming important dates |
| `get_birthday_events` | `async get_birthday_events(institution_codes: list[str], start: str, end: str) -> list[dict]` | Fetch birthday events for institutions |
| `get_birthday_events_for_group` | `async get_birthday_events_for_group(group_id: int, start: str, end: str) -> list[dict]` | Fetch birthday events for a group |
| `get_event_types` | `async get_event_types(institution_codes: list[str] \| None = None) -> list[dict]` | Fetch event types |
| `get_daily_aggregated_events` | `async get_daily_aggregated_events(institution_profile_ids: list[int], start: str, end: str) -> list[dict]` | Fetch daily aggregated events |
| `get_events_for_institutions` | `async get_events_for_institutions(institution_codes: list[str], start: str, end: str) -> list[dict]` | Fetch events for institutions |
| `get_daily_event_count_for_group` | `async get_daily_event_count_for_group(group_id: int, start: str, end: str) -> list[dict]` | Fetch event count per day for a group |
| `get_events_by_group` | `async get_events_by_group(group_id: int, start: str, end: str) -> list[dict]` | Fetch events by group ID |

### Groups

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_groups` | `async get_groups(institution_codes: list[str], child_institution_profile_ids: list[int]) -> list[Group]` | Fetch groups for given institution codes and child profile IDs |
| `get_group` | `async get_group(group_id: int) -> Group \| None` | Fetch a single group by ID |
| `get_group_members` | `async get_group_members(group_id: int, portal_roles: list[str] \| None = None) -> list[GroupMember]` | Fetch members of a group |
| `search_groups` | `async search_groups(text: str, limit: int = 100) -> list[Group]` | Search for groups by name (`search.findGroups`) |

### Posts

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_posts` | `async get_posts(institution_profile_ids: list[int], page: int = 1, limit: int = 10) -> list[Post]` | Fetch posts from Aula; `page` is 1-based and sent as item offset `(page - 1) * limit` |
| `get_post` | `async get_post(post_id: int) -> Post \| None` | Fetch a single post by ID |
| `get_comments` | `async get_comments(parent_type: str, parent_id: int, limit: int = 100) -> list[Comment]` | Fetch comments for a given parent (e.g. post) |

### Consent & Documents

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_consent_responses` | `async get_consent_responses(institution_profile_ids: list[int]) -> list[ConsentResponse]` | Fetch consent responses for given institution profile IDs |
| `get_secure_documents` | `async get_secure_documents(institution_profile_ids: list[int], page_size: int = 20) -> list[SecureDocument]` | Fetch every secure document shared with the user, paging through all; pass the user's own institution profile IDs (a child's ID gets 403) |
| `get_common_files` | `async get_common_files(institution_codes: list[str], page_size: int = 20) -> list[CommonFile]` | Fetch every common file the given institutions share, paging through all; a guardian passes their children's institution codes |

### Search

| Method | Signature | Description |
|--------|-----------|-------------|
| `find_recipients` | `async find_recipients(text: str, limit: int = 100, doc_types: str \| None = None, portal_roles: list[str] \| None = None) -> list[dict]` | Find message recipients |
| `find_profiles_and_groups` | `async find_profiles_and_groups(text: str, limit: int = 100) -> dict` | Find profiles and groups |
| `search` | `async search(text: str, doc_type: str \| None = None, limit: int = 20, offset: int = 0) -> dict` | Global search |

### Contacts

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_contact_list` | `async get_contact_list(group_id: int, page: int \| None = None, order: str \| None = None) -> list[dict]` | Fetch contact list for a group |
| `get_contact_parents` | `async get_contact_parents(page: int \| None = None, order: str \| None = None) -> list[dict]` | Fetch other parents |

### Gallery

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_gallery_albums` | `async get_gallery_albums(institution_profile_ids: list[int], limit: int = 1000, *, index: int = 0, sort_on: str = "createdAt", order_direction: str = "desc", filter_by: str = "all") -> list[dict]` | Fetch gallery albums as raw dicts |
| `get_album_pictures` | `async get_album_pictures(institution_profile_ids: list[int], album_id: int, limit: int = 1000) -> list[dict]` | Fetch pictures for a specific album as raw dicts |
| `get_media_by_id` | `async get_media_by_id(media_id: int) -> dict \| None` | Fetch a single media item by ID |
| `get_media_by_profile` | `async get_media_by_profile(institution_profile_id: int, limit: int = 100) -> list[dict]` | Fetch media tagged with a profile |

### File Downloads

| Method | Signature | Description |
|--------|-----------|-------------|
| `download_file` | `async download_file(url: str) -> bytes` | Download a file as raw bytes |

### Deprecated Widget Methods

These delegate to `self.widgets.*` and will be removed in a future version:

| Method | Delegates to |
|--------|-------------|
| `get_mu_tasks(...)` | `self.widgets.get_mu_tasks` |
| `get_ugeplan(...)` | `self.widgets.get_ugeplan` |
| `get_easyiq_weekplan(...)` | `self.widgets.get_easyiq_weekplan` |
| `get_meebook_weekplan(...)` | `self.widgets.get_meebook_weekplan` |
| `get_momo_courses(...)` | `self.widgets.get_momo_courses` |
| `get_library_status(...)` | `self.widgets.get_library_status` |

### Attributes

| Attribute | Type | Notes |
|-----------|------|-------|
| `api_url` | `str` | Base API URL with version (e.g. `https://www.aula.dk/api/v25`) |
| `widgets` | `AulaWidgetsClient` | Widget-specific API client |

---

## AulaWidgetsClient

**Module:** `aula.widgets.client`

Widget provider API client for third-party Aula integrations. Constructed internally by `AulaApiClient`.

```python
AulaWidgetsClient(api_client: _WidgetRequestClient) -> None
```

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_mu_tasks` | `async get_mu_tasks(widget_id: str, child_filter: list[str], institution_filter: list[str], week: str, session_uuid: str) -> list[MUTask]` | Fetch Min Uddannelse tasks for a given week |
| `get_ugeplan` | `async get_ugeplan(widget_id: str, child_filter: list[str], institution_filter: list[str], week: str, session_uuid: str) -> list[MUWeeklyPerson]` | Fetch Min Uddannelse weekly plans (ugebreve) |
| `get_easyiq_weekplan` | `async get_easyiq_weekplan(week: str, session_uuid: str, institution_filter: list[str], child_id: str, widget_id: str = WIDGET_EASYIQ_WEEKPLAN, *, child_profile_id: str \| None = None, all_child_user_ids: list[str] \| None = None, all_institution_filter: list[str] \| None = None) -> list[Appointment]` | Fetch EasyIQ weekly plan appointments, falling back to the school portal. Raises `EasyIQChildNotInPortal` |
| `get_easyiq_homework` | `async get_easyiq_homework(week: str, session_uuid: str, institution_filter: list[str], child_id: str, *, child_profile_id: str, all_child_user_ids: list[str] \| None = None, all_institution_filter: list[str] \| None = None) -> list[EasyIQHomework]` | Fetch EasyIQ homework assignments from the school portal. Raises `EasyIQChildNotInPortal` |
| `get_easyiq_calendar_events` | `async get_easyiq_calendar_events(*, week: str, institution_filter: list[str], child_profile_id: str, child_user_id: str, all_child_user_ids: list[str], guardian_login: str, widget_id: str = WIDGET_EASYIQ_WEEKPLAN, all_institution_filter: list[str] \| None = None) -> list[EasyIQCalendarEvent]` | Read one week of raw EasyIQ weekly-plan rows |
| `get_easyiq_homework_events` | `async get_easyiq_homework_events(*, week: str, institution_filter: list[str], child_profile_id: str, child_user_id: str, all_child_user_ids: list[str], guardian_login: str, widget_id: str = WIDGET_EASYIQ_HOMEWORK, all_institution_filter: list[str] \| None = None) -> list[EasyIQCalendarEvent]` | Read one week of raw EasyIQ homework rows |
| `ensure_easyiq_session` | `async ensure_easyiq_session(institution_filter: list[str], guardian_login: str, child_user_ids: list[str]) -> None` | Bootstrap the EasyIQ portal session and learn its child IDs (best-effort, idempotent, safe to await concurrently) |
| `authenticate_easyiq_session` | `async authenticate_easyiq_session(institution_filter: list[str], guardian_login: str, child_user_ids: list[str], child_user_id: str = "", token: str \| None = None, widget_id: str = WIDGET_EASYIQ_HOMEWORK) -> dict[str, Any]` | `POST /Aula/AuthenticateAulaUser`, returning its body key-folded to lowercase |
| `switch_easyiq_child` | `async switch_easyiq_child(child_easyiq_id: str, institution_filter: list[str], guardian_login: str, child_user_ids: list[str], child_user_id: str = "", token: str \| None = None) -> None` | `POST /Aula/SwitchChild`, the portal's own child-selection call. Takes EasyIQ's `Id`, not a UniLogin |
| `confirm_easyiq_session_child` | `async confirm_easyiq_session_child(expected_child_login: str, institution_filter: list[str], guardian_login: str, child_user_ids: list[str], child_user_id: str, token: str \| None = None) -> str` | Check the session really is on the child asked for. Raises `EasyIQWrongChildSession` |
| `resolve_easyiq_child_id` | `resolve_easyiq_child_id(child_user_id: str) -> str \| None` | EasyIQ's own ID for a child, once the session has been made |
| `resolve_easyiq_child_login` | `resolve_easyiq_child_login(child_user_id: str) -> str \| None` | EasyIQ's own `Login` string for a child, once resolved |
| `easyiq_headers` | `easyiq_headers(token: str, institution_filter: list[str], guardian_login: str, child_user_ids: list[str], child_user_id: str = "") -> dict[str, str]` | Headers the EasyIQ portal expects from its embedded widgets |
| `easyiq_identifier_variants` | `easyiq_identifier_variants(child_profile_id: str, child_user_id: str, guardian_login: str, easyiq_child_id: str \| None = None) -> list[tuple[str, str]]` | `(loginId, child header)` pairs to try, best guess first |
| `get_meebook_weekplan` | `async get_meebook_weekplan(child_filter: list[str], institution_filter: list[str], week: str, session_uuid: str) -> list[MeebookStudentPlan]` | Fetch Meebook weekly plan |
| `get_docendo_weekplan` | `async get_docendo_weekplan(week: str) -> list[DocendoWeekPlan]` | Fetch Docendo weekly plans (widget `0057`, 1.14.0), one per class for all children. See [Docendo weekplans](#docendo-weekplans) |
| `get_momo_courses` | `async get_momo_courses(children: list[str], institutions: list[str], session_uuid: str) -> list[MomoUserCourses]` | Fetch MoMo courses (widget v1.3) |
| `get_momo_reminders` | `async get_momo_reminders(children: list[str], institutions: list[str], session_uuid: str, from_date: str, due_no_later_than: str) -> list[UserReminders]` | Fetch MoMo reminders (widget v1.10) |
| `get_library_status` | `async get_library_status(widget_id: str, children: list[str], institutions: list[str], session_uuid: str) -> LibraryStatus` | Fetch library status from Cicero (widget v1.6) |

### EasyIQ and the school portal

EasyIQ no longer serves homework or weekly plans from the Aula REST API —
`/api/aula/homeworkinfo` was removed upstream and 404s. Both now come from the
EasyIQ school portal (`EASYIQ_PORTAL`), which needs its own session and its own
child identifiers:

- `ensure_easyiq_session` POSTs to `/Aula/AuthenticateAulaUser` for the session
  cookies, then reads `/Aula/GetChildren` for EasyIQ's own per-child `Id` and
  `Login`, and keeps the parent `loginId` the portal answers with. It runs at
  most once per client and is called automatically by the fetch methods.
- The portal identifies a child by their **institution profile ID**
  (`child_profile_id`, i.e. `Child.id`) alongside their **UniLogin**
  (`child_id` / `child_user_id`, i.e. `Child.user_id`).
- `all_child_user_ids` is every child's UniLogin, sent as the `x-childfilter`
  header. Omitting it makes the portal answer 200 with nothing. Build it with
  `easyiq_child_user_ids(profile_context)` from `aula.widgets` (public in 1.17.0).
- `all_institution_filter` is every institution the **guardian** has, as opposed
  to `institution_filter`, which is the one institution being read. The
  bootstrap runs under `all_institution_filter or institution_filter`, and its
  child list is cached for the life of the client — so passing only one child's
  institution lets the first read decide which children are ever resolvable,
  and a child at a second school then looks like a child EasyIQ does not know.
  **New in 1.8.0.**
- Weekly plans and homework live on **separate controllers**; the calendar one
  never returns homework rows.
- When the bootstrap fails, `easyiq_identifier_variants` falls back to trying
  the Aula-derived identifier combinations in turn. When it succeeds, the
  protocol-correct pair (parent `loginId`, the child's real `Login`) is tried
  first.

`get_easyiq_weekplan` still tries the old `weekplaninfo` API first and only
falls back to the portal when that fails or returns nothing — and it can only
fall back if `child_profile_id` was supplied.

#### One child per read (1.8.0)

The portal session carries **one active child at a time**, so reading a week is
three calls, not one, and they are held together under a per-client lock:

1. `switch_easyiq_child` — `POST /Aula/SwitchChild?loginId=<EasyIQ Id>`.
2. `confirm_easyiq_session_child` — re-POSTs `AuthenticateAulaUser` and compares
   the `child` it echoes against the child asked for, casefolded. A mismatch
   raises `EasyIQWrongChildSession` rather than returning a sibling's week; an
   absent or empty `child` is logged and accepted.
3. The read itself, on the switched-to child.

A child missing from a known `GetChildren` list is not read at all: it raises
`EasyIQChildNotInPortal`, which means their institution is not on EasyIQ (a
daycare, typically) and so they have no week plan. Callers should treat it as an
absence for that child, not as a failed update for all of them.

When the `GetChildren` bootstrap failed, so no children are known, only a
single-child account falls back to guessing identifiers. With more than one
child in `all_child_user_ids`, the read raises a plain `RuntimeError`
("EasyIQ's portal did not identify the children; …") rather than risk returning
another child's rows (1.13.0).

---

## Data Models

**Module:** `aula.models`

All models inherit from `AulaDataClass` (provides `__iter__` for serialization). Every model has an optional `_raw: dict | None` field (excluded from repr) that stores the original API response dict. Most models have a `from_dict(data: dict) -> Self` class method.

### Profile

```python
@dataclass
class Profile(AulaDataClass):
    profile_id: int
    display_name: str
    children: list[Child] = []
    institution_profile_ids: list[int] = []
```

### Child

```python
@dataclass
class Child(AulaDataClass):
    id: int               # Institution profile ID — used for API calls
    profile_id: int       # User's profile ID — displayed to users
    name: str
    institution_name: str
    profile_picture: str
    user_id: str | None = None           # UniLogin (1.17.0)
    institution_code: str | None = None  # 1.17.0
```

### ProfileMasterData

```python
@dataclass
class ProfileMasterData(AulaDataClass):
    institution_profile_id: int
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone_number: str = ""
    mobile_phone: str = ""
    address: str = ""
    postal_code: str = ""
    city: str = ""
    municipality: str = ""
    portal_role: str = ""
```

### DailyOverview

```python
@dataclass
class DailyOverview(AulaDataClass):
    id: int | None = None
    institution_profile: InstitutionProfile | None = None
    main_group: MainGroup | None = None
    status: PresenceState | None = None
    location: PresenceLocation | None = None   # object since 1.7.0, was str
    sleep_intervals: list[SleepInterval] = []     # SleepInterval = dict[str, str]
    check_in_time: str | None = None
    check_out_time: str | None = None
    entry_time: str | None = None
    exit_time: str | None = None
    exit_with: str | None = None
    comment: str | None = None
```

### PresenceLocation

Where a child physically is. **New in 1.7.0** — `DailyOverview.location` was a
plain `str` before, so anything publishing it directly (a Home Assistant state
attribute, a JSON dump) needs `.name` now.

```python
@dataclass
class PresenceLocation(AulaDataClass):
    id: int | None = None
    name: str = ""
    description: str = ""
    symbol: str = ""
```

Aula sends this as an object; the live payload carries more keys than the four
the official client reads, and the rest stay in `_raw`. Use
`PresenceLocation.parse(value)` rather than `from_dict` when the value may be
absent — it returns `None` for `null` and accepts a bare string as the name.

### InstitutionProfile

```python
@dataclass
class InstitutionProfile(AulaDataClass):
    profile_id: int | None = None      # Matches Child.profile_id
    id: int | None = None              # Matches Child.id
    institution_code: str | None = None
    institution_name: str | None = None
    role: str | None = None
    name: str | None = None
    profile_picture: ProfilePicture | None = None
    short_name: str | None = None
    institution_role: str | None = None
    metadata: str | None = None
```

### MainGroup

```python
@dataclass
class MainGroup(AulaDataClass):
    id: int | None = None
    name: str | None = None
    short_name: str | None = None
    institution_code: str | None = None
    institution_name: str | None = None
    uni_group_type: str | None = None
```

### CalendarEvent

```python
@dataclass
class CalendarEvent(AulaDataClass):
    id: int
    title: str
    start_datetime: datetime
    end_datetime: datetime
    teacher_name: str | None
    has_substitute: bool
    substitute_name: str | None
    location: str | None
    belongs_to: int | None                                      # first of belongs_to_profiles
    teacher_names: list[str] = field(default_factory=list)      # 1.11.0
    substitute_names: list[str] = field(default_factory=list)   # 1.11.0
    belongs_to_profiles: list[int] = field(default_factory=list)  # 1.17.0
    event_type: str | None = None   # "lesson", "event", "school_home_meeting", ... (1.17.0)
```

When one request covers several children, Aula returns an event they share
(twins' lesson, a school event for siblings) once and names all of them in
`belongs_to_profiles`. Filing events by `belongs_to` alone leaves it off the
other children's calendars; `get_calendar_events_by_child()` does the filing.
Built without `belongs_to_profiles`, it is filled from `belongs_to`.

Aula returns one `lesson` row per adult on a lesson. `get_calendar_events()`
folds rows with the same title, timeslot, location and children into one event via
`merge_duplicate_lessons(events)` (exported from `aula.models`), collecting every
adult into `teacher_names` / `substitute_names`. `teacher_name` /
`substitute_name` still name the first.

### MeetingBooking

Returned by `get_meeting_bookings()` (1.13.0). A parent meeting's calendar row
spans the whole booking period; this is the slot actually booked for the child.
Unbooked invitations and other children's answers are left out.

```python
@dataclass
class MeetingBooking(AulaDataClass):
    meeting_id: int
    child_id: int              # institution profile ID (Child.id)
    title: str                 # "Samtale" when the row has none
    meeting_type: str          # "school_home_meeting" or "parental_meeting"
    start_datetime: datetime   # always offset-aware
    end_datetime: datetime
    location: str | None = None
```

`get_meeting_bookings()` needs timezone-aware bounds with `end > start`
(`ValueError` otherwise), reads in chunks of at most 49 days, and raises
`HttpRequestError` rather than returning a partial list when a chunk fails.

`booking.as_calendar_event()` (1.17.0) returns the booked slot as a
`CalendarEvent` belonging to that child, with `event_type` set to the meeting type.

### PaginationResult

**Module:** `aula.models.pagination` (1.13.0)

```python
TerminationReason = Literal["exhausted", "cutoff", "max_pages", "no_progress", "inconsistent_total"]

@dataclass
class PaginationResult[T]:
    items: list[T]            # first-seen order, duplicates dropped
    complete: bool            # True only for "exhausted" or "cutoff"
    termination_reason: TerminationReason
```

### Message

```python
@dataclass
class Message(AulaDataClass):
    id: str
    content_html: str
    attachments: list[Attachment] = field(default_factory=list)
    sender_name: str | None = field(default=None, kw_only=True)                 # 1.12.0
    send_datetime: datetime | None = field(default=None, kw_only=True)          # 1.12.0
    # Properties:
    # content: str           — plain text stripped from HTML
    # content_markdown: str  — HTML converted to Markdown
    # has_attachments: bool  — whether anything is attached
    # Classmethod:
    # from_dict(data) -> Message
```

`from_dict` reads the body from `text.html`, falling back to a bare `text`
string on older messages. Both `messaging.getMessagesForThread` and
`search.findMessage` parse through it, so a search filtered on attachments
returns them. **`attachments` is new in 1.9.0.**

`sender_name` comes from `sender.fullName` and `send_datetime` from
`sendDateTime` (parsed with `parse_api_datetime`, so `None` when unreadable).
`from_search_hit(hit)` builds a `Message` from a `search.findMessage` hit,
taking the sender from a `"Name: "` prefix on the body when the hit has no
sender field.

### MessageThread

```python
@dataclass
class MessageThread(AulaDataClass):
    thread_id: str
    subject: str
```

### MessageFolder

```python
@dataclass
class MessageFolder(AulaDataClass):
    id: int
    name: str
```

### AutoReply

```python
@dataclass
class AutoReply(AulaDataClass):
    is_enabled: bool = False
    message: str = ""
    start_date: str | None = None
    end_date: str | None = None
```

### Notification

```python
@dataclass
class Notification(AulaDataClass):
    id: str
    title: str
    module: str | None = None
    event_type: str | None = None
    notification_type: str | None = None
    institution_code: str | None = None
    created_at: str | None = None
    expires_at: str | None = None
    related_child_name: str | None = None
    post_id: int | None = None
    album_id: int | None = None
    media_id: int | None = None
    institution_profile_id: int | None = None
```

### NotificationSetting

```python
@dataclass
class NotificationSetting(AulaDataClass):
    module: str = ""
    is_enabled: bool = False
    push_enabled: bool = False
    email_enabled: bool = False
```

### Post

```python
@dataclass
class Post(AulaDataClass):
    id: int
    title: str
    content_html: str
    timestamp: datetime | None
    owner: ProfileReference
    allow_comments: bool
    shared_with_groups: list[dict]
    publish_at: datetime | None
    is_published: bool
    expire_at: datetime | None
    is_expired: bool
    is_important: bool
    important_from: datetime | None
    important_to: datetime | None
    attachments: list[Attachment]   # list[dict] before 1.9.0
    comment_count: int
    can_current_user_delete: bool
    can_current_user_comment: bool
    edited_at: datetime | None = None
    # Properties:
    # content: str          — plain text stripped from HTML
    # content_markdown: str — HTML converted to Markdown
```

### Attachment

**New in 1.9.0.** One envelope with exactly one of four content variants, so a
caller can ask what an attachment is called and where its bytes are without
knowing whether it arrived as an upload, a gallery item, a cloud-drive link or a
secure document. Carried by both `Post.attachments` and `Message.attachments`.

```python
@dataclass
class Attachment(AulaDataClass):
    id: int | None = None
    name: str = ""
    status: str = ""
    created: datetime | None = None
    file: AttachmentFile | None = None
    media: AttachmentMedia | None = None
    link: AttachmentLink | None = None
    document: AttachmentDocument | None = None
    creator: InstitutionProfile | None = None
    # Property:
    # url: str | None — file.url, else link.url, else None (secure documents)
    # Classmethod:
    # from_dict(data) -> Attachment

@dataclass
class AttachmentFile(AulaDataClass):
    id: int | None = None
    name: str = ""
    url: str | None = None
    created: datetime | None = None
    scanning_status: str = ""

@dataclass
class AttachmentMedia(AulaDataClass):
    title: str = ""
    description: str = ""
    media_type: str = ""
    thumbnail_url: str | None = None

@dataclass
class AttachmentLink(AulaDataClass):
    service: str = ""
    name: str = ""
    url: str | None = None

@dataclass
class AttachmentDocument(AulaDataClass):
    id: int | None = None
    title: str = ""
    document_type: str = ""
    can_access: bool = False
    is_deleted: bool = False
```

A media item's inner file is hoisted onto `Attachment.file`, so `url` answers
for uploads and gallery items alike. `name` falls back to the file's name, then
the link's, then the document's title.

`aula.models.attachment.parse_attachments(raw_attachments: Any) -> list[Attachment]`
reads an API `attachments` list and skips anything unreadable, logging a warning
per skipped item. It is not exported from `aula.models`.

Being `AulaDataClass` instances, these are **not** JSON-serializable as they
stand, and `dict(attachment)` alone is not enough either — it leaves `created`
as a `datetime` and the variants as dataclasses. Use `aula.utils.json.to_json`,
or pick out the fields wanted, before putting any of this in a Home Assistant
state attribute or service response.

### Comment

```python
@dataclass
class Comment(AulaDataClass):
    id: int
    content_html: str
    creator_name: str
    creator_institution_profile_id: int | None = None
    created_at: str = ""
    # Properties:
    # content: str          — plain text stripped from HTML
```

### ConsentResponse

```python
@dataclass
class ConsentResponse(AulaDataClass):
    id: int
    consent_id: int
    title: str = ""
    description: str = ""
    status: str = ""
    responded_at: str | None = None
    institution_code: str = ""
```

### SecureDocument

```python
@dataclass
class SecureDocument(AulaDataClass):
    id: int
    title: str = ""
    document_type: str = ""
    description: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    owner_name: str = ""       # from `creator`, falling back to `owner`
    institution_code: str = ""
    is_read: bool = False
```

### CommonFile

```python
@dataclass
class CommonFile(AulaDataClass):
    id: int
    title: str = ""
    created_at: str | None = None
    institution_code: str = ""
    institution_name: str = ""
    file_name: str = ""
    file_url: str = ""
    is_data_policy: bool = False
```

### VacationRegistration

```python
@dataclass
class VacationRegistration(AulaDataClass):
    id: int                              # vacationRegistrationId
    child_id: int = 0
    child_name: str = ""
    title: str = ""
    start_date: str | None = None
    end_date: str | None = None
    response_id: int = 0
    response_deadline: str | None = None
    note_to_guardian: str = ""
    is_editable: bool = False
    is_missing_answer: bool = False
    is_presence_times_required: bool = False
```

Aula returns these grouped by child from
`presence.getVacationRegistrationsByChildren`; each row is flattened so the
child it belongs to travels with the registration. `from_dict` therefore takes
a second argument: `from_dict(data: dict, child: dict | None = None)`.

### ProfileReference

```python
@dataclass
class ProfileReference(AulaDataClass):
    id: int
    profile_id: int
    first_name: str
    last_name: str
    full_name: str
    short_name: str
    role: str
    institution_name: str
    profile_picture: dict | None = None
```

### Group

```python
@dataclass
class Group(AulaDataClass):
    id: int            # always coerced to int
    name: str
    group_type: str = ""
    institution_code: str = ""
    description: str = ""
```

### GroupMember

```python
@dataclass
class GroupMember(AulaDataClass):
    institution_profile_id: int
    name: str
    portal_role: str = ""
```

### WidgetConfiguration

```python
@dataclass
class WidgetConfiguration(AulaDataClass):
    widget_id: str
    name: str
    widget_supplier: str
    widget_type: str
    placement: str
    is_secure: bool
    can_access_on_mobile: bool
    aggregated_display_mode: str
```

### Appointment (EasyIQ)

```python
@dataclass
class Appointment(AulaDataClass):
    appointment_id: str
    title: str
    start: str = ""
    end: str = ""
    description: str = ""
    activities: str = ""      # EasyIQ ActivitiesDisplay: class or team, e.g. "6A"
    item_type: int | None = None
    owner_name: str = field(default="", kw_only=True)
    is_all_day: bool = field(default=False, kw_only=True)
    is_notice: bool = field(default=False, kw_only=True)
```

`activities` is empty for sources that do not carry a class or team.
`is_all_day` and `is_notice` accept only `true`/`1`/`yes` (any case) as true.

### EasyIQHomework

```python
@dataclass
class EasyIQHomework(AulaDataClass):
    id: str
    title: str
    description: str = ""
    due_date: str = ""
    subject: str = ""
    activities: str = ""      # class or team the assignment was set for
    is_completed: bool = False
```

Besides `from_dict`, it has `from_calendar_event(event: EasyIQCalendarEvent) -> EasyIQHomework`,
used for portal rows. The portal carries no completion flag, so rows built that
way always have `is_completed=False`.

### EasyIQCalendarEvent

One raw row from an EasyIQ portal week controller. A single request returns the
whole week for a child — lessons, calendar entries and homework interleaved,
told apart by `item_type`.

```python
@dataclass
class EasyIQCalendarEvent(AulaDataClass):
    item_type: int | None = None
    event_id: str = ""
    start: str = ""           # normalised to ISO 8601
    end: str = ""             # normalised to ISO 8601
    courses: str = ""
    activities: str = ""
    description: str = ""
    owner_name: str = field(default="", kw_only=True)    # OwnerName or Teacher
    is_all_day: bool = field(default=False, kw_only=True)
    is_notice: bool = field(default=False, kw_only=True)  # row has no course
    event_title: str = field(default="", kw_only=True)   # explicit Title/Name

    @property
    def title(self) -> str:   # event_title, courses, activities, or the
                              # description's first heading/line; else empty
```

A row without a course is a notice, and notices are always all-day.
`StartDate`/`EndDate` are accepted as start/end keys alongside the ISO ones.

`from_dict` matches keys **case-insensitively**: the calendar controller answers
in camelCase (`itemType`) and the homework controller in PascalCase (`ItemType`).
Text fields are HTML-unescaped, and timestamps are normalised to ISO 8601 —
a row can carry `StartTimeISO` but leave `EndTimeISO` null, so the two ends of
one event otherwise arrive in different formats. Unparsable values pass through
untouched rather than being dropped.

### MUTask

```python
@dataclass
class MUTask(AulaDataClass):
    id: str
    title: str
    task_type: str
    due_date: datetime | None
    weekday: str
    week_number: int
    is_completed: bool
    student_name: str
    unilogin: str
    url: str                                   # SSO entry point, not navigable
    deep_link: str | None = None               # the real MinUddannelse page URL
    classes: list[MUTaskClass] = []
    course: MUTaskCourse | None = None
    student_count: int | None = None
    completed_count: int | None = None
    placement: str | None = None
    placement_time: str | None = None
```

### MUTaskClass

```python
@dataclass
class MUTaskClass(AulaDataClass):
    id: int
    name: str
    subject_id: int
    subject_name: str
```

### MUTaskCourse

```python
@dataclass
class MUTaskCourse(AulaDataClass):
    id: str
    name: str
    icon: str
    yearly_plan_id: str
    color: str | None
    url: str | None
```

### MUWeeklyPerson / MUWeeklyInstitution / MUWeeklyLetter

```python
@dataclass
class MUWeeklyPerson(AulaDataClass):
    name: str
    id: int
    unilogin: str
    institutions: list[MUWeeklyInstitution] = []

@dataclass
class MUWeeklyInstitution(AulaDataClass):
    name: str
    code: int
    letters: list[MUWeeklyLetter] = []

@dataclass
class MUWeeklyLetter(AulaDataClass):
    group_id: int
    group_name: str
    content_html: str
    week_number: int
    sort_order: int
```

### MeebookStudentPlan / MeebookDayPlan / MeebookTask

```python
@dataclass
class MeebookStudentPlan(AulaDataClass):
    name: str
    unilogin: str
    week_plan: list[MeebookDayPlan] = []

@dataclass
class MeebookDayPlan(AulaDataClass):
    date: str
    tasks: list[MeebookTask] = []

@dataclass
class MeebookTask(AulaDataClass):
    id: int
    type: str
    title: str
    content: str
    pill: str
    link_text: str
```

### DocendoWeekPlan / DocendoLesson

Added in 1.14.0. Times are UTC; Docendo sometimes omits the offset, and those values are read as UTC.

```python
@dataclass
class DocendoWeekPlan(AulaDataClass):
    name: str                         # The class, e.g. "4A"
    note: str
    lessons: list[DocendoLesson] = [] # Sorted by start_time, missing times last

    def matches_class(self, class_name: str | None) -> bool: ...
        # Ignores case, spaces and punctuation: "4.A" and "4 a" match "4A"

@dataclass
class DocendoLesson(AulaDataClass):
    title: str
    start_time: datetime | None
    end_time: datetime | None
    description: str
    learning_goal: str
    notes_for_students: str

    has_content: bool                 # Property: False for breaks and empty lessons
```

### MomoUserCourses / MomoCourse

```python
@dataclass
class MomoUserCourses(AulaDataClass):
    user_id: str
    name: str
    courses: list[MomoCourse] = []

@dataclass
class MomoCourse(AulaDataClass):
    id: str
    title: str
    institution_id: str
    image: str | None
```

### UserReminders / TeamReminder / AssignmentReminder

```python
@dataclass
class UserReminders(AulaDataClass):
    user_id: int
    user_name: str
    team_reminders: list[TeamReminder] = []
    assignment_reminders: list[AssignmentReminder] = []

@dataclass
class TeamReminder(AulaDataClass):
    id: int
    institution_name: str
    institution_id: int
    due_date: str
    team_id: int
    team_name: str
    reminder_text: str
    created_by: str
    last_edit_by: str
    subject_name: str

@dataclass
class AssignmentReminder(AulaDataClass):
    id: int
    institution_name: str
    institution_id: int
    due_date: str
    course_id: int
    team_names: list[str]
    team_ids: list[int]
    assignment_id: int
    assignment_text: str
```

### LibraryStatus / LibraryLoan

```python
@dataclass
class LibraryStatus(AulaDataClass):
    loans: list[LibraryLoan] = []
    longterm_loans: list[LibraryLoan] = []
    reservations: list[dict] = []
    branch_ids: list[str] = []

@dataclass
class LibraryLoan(AulaDataClass):
    id: int
    title: str
    author: str
    patron_display_name: str
    due_date: str
    number_of_loans: int
    cover_image_url: str = ""
```

### Presence Templates

```python
@dataclass
class PresenceWeekTemplate(AulaDataClass):
    institution_profile: InstitutionProfile | None = None
    day_templates: list[DayTemplate] = []

@dataclass
class DayTemplate(AulaDataClass):
    id: int | None = None
    day_of_week: int | None = None
    by_date: str | None = None
    repeat_pattern: str | None = None
    repeat_from_date: str | None = None
    repeat_to_date: str | None = None
    is_on_vacation: bool = False
    activity_type: int | None = None
    entry_time: str | None = None
    exit_time: str | None = None
    exit_with: str | None = None
    comment: str | None = None
    spare_time_activity: SpareTimeActivity | None = None

@dataclass
class SpareTimeActivity(AulaDataClass):
    start_time: str | None = None
    end_time: str | None = None
    comment: str | None = None
```

### Presence Registration Models

```python
@dataclass
class PresenceRegistration(AulaDataClass):
    id: int | None = None
    institution_profile_id: int | None = None
    status: PresenceState | None = None
    date: str | None = None
    entry_time: str | None = None
    exit_time: str | None = None
    check_in_time: str | None = None
    check_out_time: str | None = None

@dataclass
class PresenceRegistrationDetail(AulaDataClass):
    id: int | None = None
    child_name: str | None = None
    institution_profile_id: int | None = None
    status: PresenceState | None = None
    date: str | None = None
    entry_time: str | None = None
    exit_time: str | None = None
    check_in_time: str | None = None
    check_out_time: str | None = None
    exit_with: str | None = None
    comment: str | None = None

@dataclass
class ChildPresenceState(AulaDataClass):
    institution_profile_id: int | None = None
    name: str | None = None                    # From uniStudent.name in API response
    status: PresenceState | None = None        # Parsed from "state" field in API

@dataclass
class PresenceConfiguration(AulaDataClass):
    child_id: int | None = None                # From uniStudentId in API response
    institution_code: str | None = None
    institution_name: str | None = None
    pickup: bool | None = None
    go_home_with: bool | None = None
    self_decider: bool | None = None

@dataclass
class PresenceWeekOverview(AulaDataClass):
    days: list[PresenceDay] = []

@dataclass
class PresenceDay(AulaDataClass):
    date: str | None = None
    activities: list[PresenceActivity] = []

@dataclass
class PresenceActivity(AulaDataClass):
    title: str | None = None
    start_time: str | None = None
    end_time: str | None = None
```

### ProfilePicture

```python
@dataclass
class ProfilePicture(AulaDataClass):
    url: str | None = None
```

### ChildPickupResponsibles / PickupPerson

```python
@dataclass
class PickupPerson(AulaDataClass):
    name: str = ""
    relation: str | None = None
    institution_profile_id: int | None = None
    suggestion_id: int | None = None

@dataclass
class ChildPickupResponsibles(AulaDataClass):
    uni_student_id: int = 0
    persons: list[PickupPerson] = []
```

---

## Enums

### PresenceState

**Module:** `aula.models.presence`

| Value | Int | English | Danish |
|-------|-----|---------|--------|
| `NOT_PRESENT` | 0 | Not Present | Ikke kommet |
| `SICK` | 1 | Sick | Syg |
| `REPORTED_ABSENT` | 2 | Reported Absent | Ferie/fri |
| `PRESENT` | 3 | Present | Til stede |
| `FIELDTRIP` | 4 | Field Trip | På tur |
| `SLEEPING` | 5 | Sleeping | Sover |
| `SPARE_TIME_ACTIVITY` | 6 | Spare Time Activity | Til aktivitet |
| `PHYSICAL_PLACEMENT` | 7 | Physical Placement | Fysisk placering |
| `CHECKED_OUT` | 8 | Checked Out | Gået |

**Properties:** `display_name: str`, `danish_name: str`
**Class method:** `get_display_name(value: int) -> str`

### ActivityType

**Module:** `aula.models.presence` (also exported from `aula`)

How a child leaves at the end of the day. Accepted by `update_presence_template`.

| Value | Int | English | Danish |
|-------|-----|---------|--------|
| `PICKED_UP_BY` | 0 | Collected By | Hentes af |
| `SELF_DECIDER` | 1 | Self Decider | Selvbestemmer |
| `SEND_HOME` | 2 | Sent Home | Sendes hjem |
| `GO_HOME_WITH` | 3 | Goes Home With | Går hjem med |
| `DROP_OFF_TIME` | 4 | Drop-off Time | Afleveringstid |

**Properties:** `display_name: str`, `danish_name: str`, `requires_exit_with: bool`
**Class method:** `get_display_name(value: int) -> str`

`requires_exit_with` is `True` for `PICKED_UP_BY` and `GO_HOME_WITH`; both need a
name in `exit_with`, including the relation as Aula shows it (`"Nick Nissen (Far)"`).

### PresenceModule

**New in 1.7.0.** A Komme/gå feature an institution can switch on or off per
child. Pair with `PresenceConfiguration.can_edit(module)` to find out whether a
call will be accepted before making it.

```python
PICKUP_TIMES = "pickup_times"              VACATION = "vacation"
DROP_OFF_TIME = "drop_off_time"            FIELD_TRIP = "field_trip"
DAILY_MESSAGE = "daily_message"            SPARE_TIME_ACTIVITY = "spare_time_activity"
REPORT_SICK = "report_sick"                LOCATION = "location"
SLEEP = "sleep"                            PICKUP_TYPE = "pickup_type"
```

### PresenceModulePermission

**New in 1.7.0.** What the signed-in role may do with a `PresenceModule`.

```python
DEACTIVATED = "deactivated"
READABLE = "readable"
EDITABLE = "editable"
```

### PresenceDashboard

**New in 1.7.0.** Which dashboard a set of module permissions applies to.

```python
GUARDIAN = "guardian_dashboard"
EMPLOYEE = "employee_dashboard"
CHECK_IN = "check_in_dashboard"
```

---

## Exceptions

### HTTP Exceptions (`aula.http`)

```
HttpRequestError                 — Base; any non-2xx response
├── AulaRejectedError            — Body status.code != 0 (1.17.0)
├── AulaAuthenticationError      — 401/403
│   ├── AulaSessionExpiredError  — Session expired (sub-code 23; 13 before 1.17.0)
│   ├── AulaStepUpRequiredError  — Elevated auth required (sub-code 8)
│   ├── AulaUserDeactivatedError — User account deactivated (sub-code 7)
│   └── AulaInvalidTokenError    — Invalid access token (sub-code 9)
├── AulaRateLimitError           — 429
├── AulaServerError              — 5xx
├── AulaNotFoundError            — 404
└── AulaConnectionError          — Network errors (status_code=0)
```

All store `status_code: int` as an attribute.

**Error envelopes (1.13.0):** when an Aula API response is 2xx but its body
carries a non-zero `status.code` (and no sub-code mapped to an auth error), the
client raises instead of returning an empty result. Since 1.17.0 that is
`AulaRejectedError`, a subclass of `HttpRequestError`, with `code` (Aula's
status code; 10 is authorization denied), `sub_code: int | None` and
`api_method: str | None`. `status_code` stays the HTTP status, often 200. The
message reads `Aula rejected <method> (status code 10, sub-code 33, HTTP 403)`;
before 1.17.0 it was the base `HttpRequestError` with only `(status code 10)`.

### Auth Exceptions (`aula.auth.exceptions`)

```
MitIDAuthError                   — Base for MitID auth failures
├── MitIDError                   — MitID protocol errors
│   ├── TokenInvalidError        — TOTP code rejected
│   └── PasswordInvalidError     — MitID password rejected
├── NetworkError                 — Network failures during auth
├── SAMLError                    — SAML protocol errors
│   └── SecurityCheckError       — STIL's bot-defence gate blocked the login
└── OAuthError                   — OAuth flow failures
```

`SecurityCheckError` is **new in 1.10.0**: the login was diverted to
`security-check.stil.dk`, which needs JavaScript and so cannot be answered by
this client. Its message names the likely cause (a non-Danish IP address).
`authenticate()` catches it and re-raises `RuntimeError(str(err))` **without**
the `"MitID authentication failed: "` prefix the other MitID errors get, so
callers reading `__cause__` see `SecurityCheckError` there.

### Widget Exceptions (`aula.widgets`)

**New in 1.8.0.** Both subclass `Exception` directly, so neither is caught by
`except HttpRequestError` or by an `AulaConnectionError`-style handler.

```
EasyIQChildNotInPortal   — EasyIQ's portal has no identity for this child, so
                           they have no week plan (daycare, typically). Raised
                           by get_easyiq_weekplan / get_easyiq_homework and
                           their *_events counterparts. An absence, not a fault.
EasyIQWrongChildSession  — The portal session is on a different child than the
                           one asked for; the read that followed would return
                           someone else's week. Raised by
                           confirm_easyiq_session_child.
```

---

## Constants

**Module:** `aula.const`

### API URLs

```python
API_URL = "https://www.aula.dk/api/v"
API_VERSION = "25"   # 1.14.0; aula.dk answers 410 Gone for v24
MIN_UDDANNELSE_API = "https://api.minuddannelse.net/aula"
SYSTEMATIC_API = "https://systematic-momo.dk/api/aula"
EASYIQ_API = "https://api.easyiqcloud.dk/api/aula"
MEEBOOK_API = "https://app.meebook.com/aulaapi"
CICERO_API = "https://surf.cicero-suite.com/portal-api/rest/aula"
DOCENDO_API = "https://app.docendo.dk/aula/v2"   # 1.14.0; unofficial, what Docendo's own widget calls

# EasyIQ school portal — homework and weekly plans come from here, not from
# the Aula REST API. The two data types live on separate controllers.
EASYIQ_PORTAL = "https://skoleportal.easyiqcloud.dk"
EASYIQ_CALENDAR_PATH = "/Calendar/CalendarGetWeekplanEvents"
EASYIQ_HOMEWORK_PATH = "/AulaHuskeliste/GetWeekplanEvents"
EASYIQ_CHILDREN_PATH = "/Aula/GetChildren"
EASYIQ_AUTHENTICATE_PATH = "/Aula/AuthenticateAulaUser"
EASYIQ_SWITCHCHILD_PATH = "/Aula/SwitchChild"   # 1.8.0; takes EasyIQ's own Id
```

### Widget IDs

`WIDGET_EASYIQ = "0001"`, the combined EasyIQ ID, was **removed in 1.6.0** —
Aula lists the weekly plan and homework as separate widgets. The ID is back as
`WIDGET_EASYIQ_LEGACY` (1.13.0), listed in `EASYIQ_WEEKPLAN_WIDGETS` as a
weekly-plan token fallback; only the CLI picks from that tuple.

```python
WIDGET_EASYIQ_WEEKPLAN = "0128"
WIDGET_EASYIQ_LEGACY = "0001"
WIDGET_EASYIQ_HOMEWORK = "0142"

# EasyIQ weekplan-capable widgets, in preference order.
EASYIQ_WEEKPLAN_WIDGETS = (WIDGET_EASYIQ_WEEKPLAN, WIDGET_EASYIQ_LEGACY, WIDGET_EASYIQ_HOMEWORK)
WIDGET_BIBLIOTEKET = "0019"
WIDGET_MIN_UDDANNELSE_UGEPLAN = "0029"
WIDGET_MIN_UDDANNELSE_TASKS = "0030"
WIDGET_MIN_UDDANNELSE_SSO = "0023"

# Widgets that can mint a token for MinUddannelse's opgaveliste, in preference
# order. Not every school lists 0030, and one that has only the SSO widget still
# has opgaver — a 0023 token is accepted by the same endpoint, same parameters.
MIN_UDDANNELSE_TASK_WIDGETS = (WIDGET_MIN_UDDANNELSE_TASKS, WIDGET_MIN_UDDANNELSE_SSO)

# Likewise for weekly letters (/ugebrev): the SSO widget mints a working token
# at schools without the Ugenoter widget (1.13.0).
MIN_UDDANNELSE_UGEPLAN_WIDGETS = (WIDGET_MIN_UDDANNELSE_UGEPLAN, WIDGET_MIN_UDDANNELSE_SSO)
WIDGET_MEEBOOK = "0004"
WIDGET_HUSKELISTEN = "0062"
WIDGET_DOCENDO = "0057"   # 1.14.0
```

### Auth URLs

```python
AUTH_BASE_URL = "https://login.aula.dk"
OAUTH_AUTHORIZE_PATH = "/simplesaml/module.php/oidc/authorize.php"
OAUTH_TOKEN_PATH = "/simplesaml/module.php/oidc/token.php"
APP_REDIRECT_URI = "https://app-private.aula.dk"
OAUTH_CLIENT_ID = "_99949a54b8b65423862aac1bf629599ed64231607a"  # Level 3 = full MitID
OAUTH_SCOPE = "aula-sensitive"
```

### CSRF

```python
CSRF_TOKEN_COOKIE = "Csrfp-Token"      # Cookie name (PascalCase)
CSRF_TOKEN_HEADER = "csrfp-token"      # Header name (lowercase)
```

### EasyIQ item types

Exported from `aula.models`. EasyIQ tags every portal row with an `itemType`;
its own widget source names them: 1 OpgaveFraForløb, 2 LektieFraForløb, 3 Event,
4 Lektie, 5 Plan, 6 Holiday, 7 TimeTableEvent, 8 VigtigInformation, 9 Ugeplan,
10 ClassroomStart, 11 ArbejdeFraForløb.

```python
WEEKPLAN_ITEM_TYPES = (8, 9)
HOMEWORK_ITEM_TYPES = (1, 2, 3, 4, 8)
```

Homework includes work set as part of a course, not only a bare `Lektie`. The
two overlap on 8 because both views show important notices.

### Other

```python
DOMAIN = "aula"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ..."
BROKER_URL = "https://broker.unilogin.dk"
MITID_BASE_URL = "https://nemlog-in.mitid.dk"

# 1.10.0. STIL's bot-defence gate. Landing here means the login was diverted,
# not that it failed; the page needs JavaScript, so it can only be reported.
STIL_SECURITY_CHECK_HOST = "security-check.stil.dk"
```

---

## HTTP Layer

**Module:** `aula.http` (protocol), `aula.http_httpx` (implementation)

### HttpClient Protocol

```python
@runtime_checkable
class HttpClient(Protocol):
    async def request(
        self, method: str, url: str, *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> HttpResponse: ...

    async def download_bytes(self, url: str) -> bytes: ...
    def get_cookie(self, name: str) -> str | None: ...
    async def close(self) -> None: ...
```

### HttpResponse

```python
@dataclass
class HttpResponse:
    status_code: int
    data: Any = None                    # Pre-parsed JSON
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any: ...          # Returns self.data (sync)
    def raise_for_status(self) -> None: ...  # Maps status codes to exceptions
```

### HttpxHttpClient

```python
class HttpxHttpClient:
    def __init__(
        self,
        cookies: dict[str, str] | None = None,
        httpx_client: httpx.AsyncClient | None = None,
    ) -> None: ...
```

- `follow_redirects=True`
- Timeout: 30s connect, 60s read (120s read for downloads)
- Sets `User-Agent` from `const.USER_AGENT`
- If `httpx_client` is provided, caller retains ownership and must close it

---

## Authentication

**Module:** `aula.auth.mitid_client` (low-level), `aula.auth_flow` (high-level)

### High-Level Functions

#### authenticate()

```python
async def authenticate(
    mitid_username: str,
    token_storage: TokenStorage | None = None,
    on_qr_codes: Callable | None = None,
    on_login_required: Callable | None = None,
    httpx_client: httpx.AsyncClient | None = None,
    force_login: bool = False,
    on_identity_selected: Callable | None = None,
    auth_method: str = "app",            # "app" or "token"
    on_token_digits: Callable | None = None,
    on_password: Callable | None = None,
    on_otp_code: Callable[[str], None] | None = None,
    on_qr_done: Callable[[], None] | None = None,
) -> dict[str, Any]
```

Handles cached tokens, refresh, and fresh MitID login. Returns token data dict. Applies a 60-second proactive expiry buffer (`_TOKEN_EXPIRY_BUFFER_SECS`) to prevent mid-request failures.

Callbacks:

| Callback | Fires when |
|----------|------------|
| `on_qr_codes(qr1, qr2)` | MitID rotates the two halves of the channel-binding code. Since 1.10.0 **unchanged codes are not resent**, so this fires on rotation rather than once per poll |
| `on_qr_done()` | The app has read the codes. **New in 1.10.0.** Fires at most once, and never in the OTP or kodeviser flows. `qr1`/`qr2` are already `None` by then, so consumers should only use it to take the codes off the screen |
| `on_otp_code(code)` | MitID asked for a typed code instead of a QR scan |
| `on_token_digits()` | Async; must return the 6 digits from a MitID code display |
| `on_password()` | Async; must return the MitID password |
| `on_identity_selected(names)` | Async; must return the index of the identity to log in as |
| `on_login_required()` | Cached tokens are unusable and a fresh login is starting |

#### create_client()

```python
async def create_client(
    token_data: dict[str, Any],
    http_client: HttpClient | None = None,
    *,
    token_storage: TokenStorage | None = None,
) -> AulaApiClient
```

Creates a ready-to-use `AulaApiClient` from stored credentials. Calls `init()` internally. When a `refresh_token` is present in `token_data`, builds an `on_token_refresh` callback using `_refresh_token_via_oidc()` for automatic 401 retry. With `token_storage`, that automatic refresh merges the rotated credentials into `token_data` and saves the whole blob before retrying; without it, rotated tokens live only in memory.

#### authenticate_and_create_client()

```python
async def authenticate_and_create_client(
    mitid_username: str,
    token_storage: TokenStorage,
    ...  # same params as authenticate()
) -> AulaApiClient
```

Convenience wrapper combining `authenticate()` + `create_client()`. Not in the
top-level `__all__` — import it from `aula.auth_flow`. Unlike `authenticate()`
it takes no `force_login`; it sets it itself when retrying after an
`AulaAuthenticationError`.

### MitIDAuthClient

```python
class MitIDAuthClient:
    def __init__(
        self,
        mitid_username: str,
        timeout: int = 30,
        on_qr_codes: Callable | None = None,
        on_qr_done: Callable[[], None] | None = None,
        httpx_client: httpx.AsyncClient | None = None,
        on_identity_selected: Callable | None = None,
        auth_method: str = "app",
        on_token_digits: Callable | None = None,
        on_password: Callable | None = None,
        on_otp_code: Callable[[str], None] | None = None,
    ) -> None: ...

    async def authenticate(self) -> dict[str, Any]:
        """7-step OAuth + SAML + MitID flow. Returns {"success": True, "tokens": {...}}"""

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh using stored refresh_token. Returns updated token dict."""
```

`refresh_access_token` keeps the old `refresh_token` in the returned dict when
the token endpoint does not rotate it (1.13.0).

**Properties:** `access_token`, `refresh_token`, `tokens`, `is_authenticated`, `cookies`, `mitid_client`

Supports `async with` context manager.

### Token Structure

```python
{
    "access_token": "...",
    "refresh_token": "...",
    "expires_in": 3600,
    "expires_at": 1709487234.5,   # Unix timestamp
    "token_type": "Bearer",
}
```

### Authentication Flow Steps

1. Start OAuth flow (PKCE parameters)
2. Follow redirect to MitID
3. MitID authentication (app QR/OTP or hardware token + password)
4. Complete MitID flow → SAML response
5. SAML broker processing. Since 1.17.0 the UniLogin `post-broker-login` form's
   hidden role field `selected-aktoer` is posted as `KONTAKT` (guardian), so
   users with several roles (a parent with rights at a school) are not refused
   with status 400; a confirmation page is submitted; and the `SAMLError` says
   when the identity is linked to a private organisation, or quotes the page's
   message otherwise
6. Complete Aula login
7. Exchange OAuth code for tokens

### Session Lifecycle

1. `access_token` passed as query param during `AulaApiClient.init()`
2. Server sets session cookies (including `Csrfp-Token`)
3. `access_token` is cleared after init
4. All subsequent requests use session cookies only
5. `csrfp-token` header is added to POST requests automatically

---

## Token Storage

**Module:** `aula.token_storage`

### TokenStorage (ABC)

```python
class TokenStorage(ABC):
    async def load(self) -> dict[str, Any] | None: ...
    async def save(self, data: dict[str, Any]) -> None: ...
```

### FileTokenStorage

```python
class FileTokenStorage(TokenStorage):
    def __init__(self, path: str | Path) -> None: ...
    async def clear(self) -> bool: ...   # 1.10.0; True if a file was removed
```

`clear()` is what `aula logout` calls. It is defined on `FileTokenStorage`
only, not on the `TokenStorage` ABC, so code holding a `TokenStorage`-typed
reference cannot rely on it. Writes go through `mkstemp` + `os.replace` and are
chmod'ed `0o600` off Windows.

Persisted data format:

```python
{
    "timestamp": 1709487234.5,
    "created_at": "2024-03-03 10:00:34",
    "username": "mitid_username",
    "tokens": { ... },
    "cookies": {
        "Csrfp-Token": "...",
        # other session cookies
    }
}
```

---

## Common Patterns

### child.id vs child.profile_id

- `Child.id` = Institution profile ID. **Use this for API calls** (e.g. `get_daily_overview(child_id=child.id)`)
- `Child.profile_id` = User's profile ID. Displayed to users, matches `InstitutionProfile.profile_id`
- When mapping `DailyOverview.institution_profile` to a `Child`, match on the `id` field

### Widget Token Flow

1. Call `get_widgets()` to discover available widgets and their IDs
2. Internally, `_get_bearer_token(widget_id)` fetches a per-widget bearer token
3. Widget requests use this bearer token in the `Authorization` header
4. Each widget provider has its own API base URL (see Constants)

### Widget Method Parameters

Most widget methods share a common parameter pattern:

- `widget_id: str` — The widget ID constant (e.g. `WIDGET_MIN_UDDANNELSE_TASKS`)
- `child_filter: list[str]` — List of child IDs (as strings)
- `institution_filter: list[str]` — List of institution codes (as strings)
- `week: str` — ISO week string (e.g. `"2024-W10"`)
- `session_uuid: str` — Unique session identifier

`WidgetContext.from_children(children, profile_context)` from `aula.widgets`
(1.17.0) builds `child_filter` (each child's `user_id`), `institution_filter`
(their `institution_code`s, deduplicated) and `session_uuid` (the profile
context's `data.userId`). Pass a subset of children to scope a call. It raises
`ValueError` when no child has a UniLogin or the context names no guardian.

EasyIQ's portal methods need more than this — see
[EasyIQ and the school portal](#easyiq-and-the-school-portal). In particular
`session_uuid` doubles as the portal's `guardian_login`, which is the guardian's
UniLogin: `(await client.get_profile_context())["data"]["userId"]`.

### Docendo weekplans

`get_docendo_weekplan(week)` takes only the week. Docendo does not filter by
child: one call returns a plan per class for all of the guardian's children.
Pair a plan with a child by the child's class name, which Aula sends as
`institutionProfile.metadata`:

```python
from aula.utils.mapping import get_in

plans = await client.widgets.get_docendo_weekplan("2026-W45")
class_name = get_in(child._raw or {}, "institutionProfile.metadata", default=None)
child_plans = [plan for plan in plans if plan.matches_class(class_name)]
```

`DailyOverview.institution_profile.metadata` holds the same value. The class
name can be missing or spelled differently from Docendo's, so the CLI
(`aula docendo:ugeplan`) shows every plan to a guardian with only one child
when none match.

### Reading nested API values

Aula sends an explicit `null` for objects it leaves empty, so `data.get("x", {}).get("y")`
raises on a present-but-null `x`. Use `get_in` instead:

```python
from aula.utils.mapping import get_in

get_in(child._raw, "institutionProfile.institutionCode", default="")
# Since 1.17.0 this particular value is Child.institution_code.
```

A missing key, a null value, and an unexpected shape all yield `default`.

### Reading API timestamps

`aula.utils.dates.parse_api_datetime` is the shared reader behind the post,
message and attachment models (**new in 1.9.0**):

```python
from aula.utils.dates import parse_api_datetime

def parse_api_datetime(value: Any) -> datetime | None
```

Anything falsy, non-`str`, or unparsable yields `None` rather than raising, so
raw dict values can go straight in.

### CLI JSON Output

All CLI commands support `--output json` (or `AULA_OUTPUT=json` env var) to emit machine-readable JSON instead of human-readable text. When active, each command serializes its result via `to_json()` (handles `datetime`, `enum`, and `AulaDataClass` instances) and prints a single JSON document to stdout.

```bash
aula --output json profile
aula --output json overview
aula --output json messages --search "homework"
```

**Module:** `aula.utils.json`

```python
def to_json(data: Any) -> str:
    """Serialize data to JSON with datetime/enum/AulaDataClass support."""
```

**Module:** `aula.utils.output`

```python
def output_json(ctx: click.Context, data: Any) -> bool:
    """If --output json is active, emit JSON and return True."""
```

### API Version Handling

- Current default: `API_VERSION = "25"`
- `_request_with_version_retry()` automatically bumps the version on 410 Gone
- `_set_correct_api_version()` discovers the correct version during `init()`

### Package Exports

All public types are available from the top-level `aula` package:

```python
from aula import (
    AulaApiClient, AulaWidgetsClient,
    authenticate, create_client,
    HttpClient, HttpResponse, HttpxHttpClient,
    HttpRequestError, AulaAuthenticationError, AulaConnectionError,
    AulaNotFoundError, AulaRateLimitError, AulaServerError,
    AulaRejectedError,                    # 1.17.0
    TokenStorage, FileTokenStorage,
    Profile, Child, DailyOverview, Message, MessageThread,
    CalendarEvent, WidgetConfiguration,
    Attachment, AttachmentFile, AttachmentMedia,
    AttachmentLink, AttachmentDocument,   # 1.9.0
    ActivityType, PresenceState, __version__,
)
```

The EasyIQ exceptions and the widget helpers live with the widget client:

```python
from aula.widgets import EasyIQChildNotInPortal, EasyIQWrongChildSession
from aula.widgets import WidgetContext, easyiq_child_user_ids   # 1.17.0
```

Auth exceptions are not re-exported either:

```python
from aula.auth.exceptions import MitIDAuthError, SecurityCheckError
```

Additional models must be imported from `aula.models`:

```python
from aula.models import (
    Appointment, AutoReply, Comment, CommonFile, ConsentResponse,
    EasyIQHomework, Group, GroupMember,
    LibraryLoan, LibraryStatus, MeebookStudentPlan,
    DocendoWeekPlan, DocendoLesson,
    MessageFolder, MomoUserCourses, NotificationSetting,
    UserReminders, MUTask, MUWeeklyPerson, Notification, Post,
    ProfileMasterData, SecureDocument, VacationRegistration,
    ChildPickupResponsibles, PickupPerson,
    PresenceWeekTemplate, DayTemplate, SpareTimeActivity,
    PresenceRegistration, PresenceRegistrationDetail,
    ChildPresenceState, PresenceConfiguration,
    PresenceWeekOverview, PresenceDay, PresenceActivity,
    MeetingBooking, merge_duplicate_lessons,
)
from aula.models.pagination import PaginationResult
from aula.api_client import ThreadScanLimitError
```

New exception subclasses (importable from `aula.http`):

```python
from aula.http import (
    AulaSessionExpiredError, AulaStepUpRequiredError,
    AulaUserDeactivatedError, AulaInvalidTokenError,
)
```

Enums:

```python
from aula.models.presence import PresenceState
```

Constants:

```python
from aula.const import (
    WIDGET_EASYIQ_WEEKPLAN, WIDGET_EASYIQ_HOMEWORK, WIDGET_BIBLIOTEKET,
    WIDGET_MIN_UDDANNELSE_TASKS, WIDGET_MEEBOOK, WIDGET_HUSKELISTEN,
    WIDGET_DOCENDO, ...
)
```

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
scripts/test                          # run all tests (auto-creates .venv if needed)
scripts/test tests/test_sensor.py     # run a single test file
scripts/test tests/test_sensor.py::test_presence_sensor_native_value  # single test
scripts/lint                          # ruff format + ruff check --fix
python3 scripts/check_translations    # verify translations match strings.json
scripts/develop                       # run HA locally with the integration loaded
scripts/release <version> [--dry-run] # bump version, tag, create GitHub release
prek run --all-files                  # run all pre-commit hooks manually
```

## Aula Package API Reference

When trying to understand the `aula` PyPI package, consult **`docs/aula-package-api.md`** — it documents every public method, data model, enum, exception, and constant in the package. It states the version it was generated from in its header; if that trails the pin in `manifest.json`, regenerate it with the `update-aula-api-docs` skill rather than trusting it.

## Architecture

**Integration domain:** `hass_aula` | **Manifest:** `custom_components/hass_aula/manifest.json`

### Entry point (`__init__.py`)

`async_setup_entry` creates `AulaTokenManager` → builds `HttpxHttpClient` → calls `aula.create_client()` → fetches `Profile` → instantiates all coordinators → runs first refresh via `asyncio.gather` → stores everything in `entry.runtime_data` as `AulaRuntimeData` → forwards to platforms (SENSOR, CALENDAR).

### Config flow (`config_flow.py`)

Steps: `user` → `mitid_auth` (background auth task) → `mitid_qr` (animated QR SVG served via temporary HTTP endpoint `AulaQRView`) → `select_widgets` → CREATE_ENTRY. Also supports `reauth` and `reconfigure` flows (silent token refresh when possible).

### Coordinators (`coordinator.py`)

All extend `DataUpdateCoordinator`. Error handling centralized in `_aula_api_errors` context manager (maps Aula exceptions → HA exceptions, auto-refreshes tokens on auth errors). Every `_async_update_data` is wrapped in `@_tolerate_transient_failures`, which keeps the previous data for up to `TRANSIENT_FAILURE_TOLERANCE` consecutive `UpdateFailed`s; a new coordinator needs the decorator and the `_TransientFailureTolerance` mixin, which `_AulaWidgetCoordinator` already includes. Widget coordinators extend `_AulaWidgetCoordinator` which adds name-based child matching.

| Coordinator | Poll interval |
|---|---|
| `AulaPresenceCoordinator` | 5 min |
| `AulaNotificationsCoordinator` | 5 min |
| `AulaMessagesCoordinator` | 30 min |
| `AulaCalendarCoordinator` | 60 min |
| `AulaLibraryCoordinator` | 60 min |
| `AulaMeebookCoordinator` | 60 min |
| `AulaMUTasksCoordinator` | 30 min |
| `AulaEasyIQCoordinator` | 30 min |
| `AulaHuskelistenCoordinator` | 30 min |

### Entities

- `AulaEntity(CoordinatorEntity)` — base for per-child entities, device = `(DOMAIN, str(child.id))`
- `AulaAccountEntity(CoordinatorEntity)` — base for profile-level entities, device = `(DOMAIN, f"profile_{profile.profile_id}")`
- Unique ID pattern: `{child_id}_{entity_key}`

### Token manager (`token_manager.py`)

Uses `asyncio.Lock` to prevent concurrent refreshes. `async_refresh_and_rebuild_client()` updates all coordinator client references and closes the old client.

### Data (`data.py`)

`AulaRuntimeData` dataclass holds all coordinators, client, token manager, and profile. `AulaConfigEntry = ConfigEntry[AulaRuntimeData]`.

## Test Patterns

- **Framework:** `pytest` + `pytest-homeassistant` (published from home-assistant/core `packages/`), `asyncio_mode = auto`. Custom integrations are enabled by default, so there is no `enable_custom_integrations` fixture
- **Fixtures:** `conftest.py` provides factory functions (`mock_child`, `mock_profile`, `mock_daily_overview`, etc.) returning `MagicMock` objects spec'd against real aula model classes
- **Client mock:** `mock_aula_client` fixture patches `custom_components.hass_aula.create_client` globally
- **Entry helpers:** `make_config_entry()` / `make_widget_config_entry(widgets)` for creating `MockConfigEntry` with default Aula data
- **Integration setup tests:** `await hass.config_entries.async_setup(entry.entry_id)` then `await hass.async_block_till_done()`
- **Coordinator tests:** directly instantiate coordinators, call `await coordinator.async_refresh()`, assert on `coordinator.data`

## Project Conventions

- Python 3.14, ruff with `select = ["ALL"]`, strict mypy
- Translations source of truth: `strings.json` — run `check_translations` to verify `translations/*.json` stay in sync
- Pre-commit via [prek](https://prek.j178.dev) (`prek.toml`): ruff, codespell, yamllint, check-translations, pytest

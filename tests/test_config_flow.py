"""Tests for Aula config flow."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from aula import WidgetConfiguration
from aula.auth.exceptions import PasswordInvalidError, TokenInvalidError
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.hass_aula.config_flow import _selectable_widgets
from custom_components.hass_aula.const import (
    AUTH_METHOD_APP,
    AUTH_METHOD_TOKEN,
    CONF_AUTH_METHOD,
    CONF_IDENTITY,
    CONF_MITID_PASSWORD,
    CONF_MITID_USERNAME,
    CONF_TOKEN_CODE,
    CONF_TOKEN_DATA,
    CONF_WIDGETS,
    DOMAIN,
    SUPPORTED_WIDGETS,
    WIDGET_MEEBOOK,
    WIDGET_MEEBOOK_OVERVIEW,
)

from .conftest import MOCK_TOKEN_DATA, MOCK_USERNAME, make_config_entry


def test_meebook_overview_widget_is_supported() -> None:
    """Test Meebook overblik is offered as a supported data provider."""
    assert WIDGET_MEEBOOK_OVERVIEW in SUPPORTED_WIDGETS


def test_selectable_widgets_offers_iframe_typed_secure_widgets() -> None:
    """
    The EasyIQ weekplan is typed 'iframe' but secure; the dialog must offer it.

    The filter used to check ``widget_type == "secure"``, which dropped every
    secure widget the portal renders another way — the EasyIQ weekplan among
    them, leaving EasyIQ schools nothing to select.
    """
    iframe_weekplan = WidgetConfiguration(
        widget_id="0128",
        name="EasyIQ Ugeplan",
        widget_supplier="EasyIQ",
        widget_type="iframe",
        placement="fullWidth",
        is_secure=True,
        can_access_on_mobile=True,
        aggregated_display_mode="Shown",
    )
    unsecured = replace(iframe_weekplan, is_secure=False)

    assert _selectable_widgets([iframe_weekplan, unsecured]) == [iframe_weekplan]


def _widget(
    widget_id: str, name: str, widget_type: str = "secure"
) -> WidgetConfiguration:
    """Build a widget as returned by the Aula widget discovery endpoint."""
    return WidgetConfiguration(
        widget_id=widget_id,
        name=name,
        widget_supplier="Meebook",
        widget_type=widget_type,
        placement="fullWidth",
        is_secure=widget_type == "secure",
        can_access_on_mobile=True,
        aggregated_display_mode="",
    )


def _widget_options(result: Any) -> dict[str, str]:
    """Return the select_widgets options as {widget_id: label}."""
    for key, validator in result["data_schema"].schema.items():
        if key == CONF_WIDGETS:
            return {o["value"]: o["label"] for o in validator.config["options"]}
    msg = "no widget selector in the select_widgets form"
    raise AssertionError(msg)


# Patch target for widget fetching (avoids network calls in tests)
_FETCH_WIDGETS = (
    "custom_components.hass_aula.config_flow.AulaFlowHandler._async_fetch_widgets"
)


async def _advance_to_select_widgets(hass: HomeAssistant, flow_id: str) -> None:
    """
    Drive the flow from SHOW_PROGRESS (if any) to the select_widgets FORM.

    With an eager mock, auth may complete synchronously and we go straight to
    FORM.  With a slower mock we get SHOW_PROGRESS first.  This helper handles
    both so individual tests stay focused on what they're actually testing.
    """
    # Let any in-flight tasks run (needed when auth is truly async)
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_configure(flow_id)

    # If we're still in progress, let tasks run and poll once more
    if result["type"] is FlowResultType.SHOW_PROGRESS:
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(flow_id)

    return result


async def test_user_flow_selects_discovered_meebook_overview_widget(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test a discovered Meebook overblik widget is supported and persisted."""
    client = AsyncMock()
    client.get_widgets.return_value = [
        _widget(WIDGET_MEEBOOK_OVERVIEW, "Meebook overblik"),
        _widget(WIDGET_MEEBOOK, "Meebook ugeplan"),
        _widget("8888", "Some other provider"),
        _widget("9999", "Insecure widget", widget_type="insecure"),
    ]

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    with (
        patch(
            "custom_components.hass_aula.config_flow.authenticate",
            return_value=MOCK_TOKEN_DATA,
        ),
        patch(
            "custom_components.hass_aula.config_flow.create_client",
            return_value=client,
        ),
        patch(
            "custom_components.hass_aula.config_flow.HttpxHttpClient",
            return_value=AsyncMock(),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_MITID_USERNAME: MOCK_USERNAME},
        )
        if result["type"] is FlowResultType.SHOW_PROGRESS:
            result = await _advance_to_select_widgets(hass, result["flow_id"])

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "select_widgets"

        options = _widget_options(result)
        assert options[WIDGET_MEEBOOK_OVERVIEW] == "Meebook overblik"
        assert "not supported" not in options[WIDGET_MEEBOOK_OVERVIEW]
        assert "not supported" in options["8888"]
        assert "9999" not in options

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_WIDGETS: [WIDGET_MEEBOOK_OVERVIEW]},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_WIDGETS] == [WIDGET_MEEBOOK_OVERVIEW]


async def test_user_flow_success(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test successful user config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with (
        patch(
            "custom_components.hass_aula.config_flow.authenticate",
            return_value=MOCK_TOKEN_DATA,
        ),
        patch(_FETCH_WIDGETS, return_value=[]),
    ):
        # Submit username
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_MITID_USERNAME: MOCK_USERNAME},
        )

        # Advance through any progress steps to select_widgets
        if result["type"] is FlowResultType.SHOW_PROGRESS:
            result = await _advance_to_select_widgets(hass, result["flow_id"])

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "select_widgets"

        # Submit widget selection → CREATE_ENTRY
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_WIDGETS: []},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == MOCK_USERNAME
    assert result["data"][CONF_MITID_USERNAME] == MOCK_USERNAME
    assert result["data"][CONF_TOKEN_DATA] == MOCK_TOKEN_DATA


async def test_user_flow_duplicate(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test user flow aborts for duplicate entry."""
    with (
        patch(
            "custom_components.hass_aula.config_flow.authenticate",
            return_value=MOCK_TOKEN_DATA,
        ),
        patch(_FETCH_WIDGETS, return_value=[]),
    ):
        # Complete first install
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_MITID_USERNAME: MOCK_USERNAME},
        )
        if result["type"] is FlowResultType.SHOW_PROGRESS:
            result = await _advance_to_select_widgets(hass, result["flow_id"])
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "select_widgets"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_WIDGETS: []}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY

    # Try to add the same account again
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_MITID_USERNAME: MOCK_USERNAME},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_auth_failure(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test user flow handles auth failure."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    with patch(
        "custom_components.hass_aula.config_flow.authenticate",
        side_effect=RuntimeError("MitID authentication failed"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_MITID_USERNAME: MOCK_USERNAME},
        )

        # May get SHOW_PROGRESS or ABORT depending on task timing
        if result["type"] is FlowResultType.SHOW_PROGRESS:
            await hass.async_block_till_done()
            result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "auth_failed"


async def test_reauth_flow(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test reauth flow."""
    entry = make_config_entry()
    entry.add_to_hass(hass)

    await entry.start_reauth_flow(hass)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    flow_id = flows[0]["flow_id"]

    result = await hass.config_entries.flow.async_configure(flow_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch(
        "custom_components.hass_aula.config_flow.authenticate",
        return_value=MOCK_TOKEN_DATA,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )

        if result["type"] is FlowResultType.SHOW_PROGRESS:
            await hass.async_block_till_done()
            result = await hass.config_entries.flow.async_configure(flow_id)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"


_MOCK_REFRESH = (
    "custom_components.hass_aula.config_flow.AulaFlowHandler._async_refresh_token"
)


async def test_reconfigure_flow_token_valid(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test reconfigure skips MitID auth when refresh token is valid."""
    entry = make_config_entry()
    entry.add_to_hass(hass)

    refreshed_token_data = {**MOCK_TOKEN_DATA, "timestamp": 1700099999.0}

    with (
        patch(_MOCK_REFRESH, return_value=refreshed_token_data),
        patch(
            _FETCH_WIDGETS,
            return_value=[SimpleNamespace(widget_id="test-widget", name="Test")],
        ),
    ):
        result = await entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_widgets"

    with patch(
        "custom_components.hass_aula.config_flow.AulaFlowHandler.async_update_reload_and_abort",
        return_value={"type": FlowResultType.ABORT, "reason": "reconfigure_successful"},
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_WIDGETS: []},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_flow_token_expired(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test reconfigure falls back to MitID auth when refresh fails."""
    entry = make_config_entry()
    entry.add_to_hass(hass)

    with patch(_MOCK_REFRESH, side_effect=RuntimeError("Token expired")):
        result = await entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    flow_id = result["flow_id"]

    with (
        patch(
            "custom_components.hass_aula.config_flow.authenticate",
            return_value=MOCK_TOKEN_DATA,
        ),
        patch(_FETCH_WIDGETS, return_value=[]),
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={CONF_MITID_USERNAME: "new_user"},
        )

        if result["type"] is FlowResultType.SHOW_PROGRESS:
            await hass.async_block_till_done()
            result = await hass.config_entries.flow.async_configure(flow_id)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "select_widgets"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_WIDGETS: []},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


def _wrapped_mitid_error(cause: Exception) -> RuntimeError:
    """Build the RuntimeError aula.authenticate raises for a MitID failure."""
    err = RuntimeError(f"MitID authentication failed: {cause}")
    err.__cause__ = cause
    return err


async def test_token_flow_success(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test signing in with a MitID code display instead of the app."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_MITID_USERNAME: MOCK_USERNAME,
            CONF_AUTH_METHOD: AUTH_METHOD_TOKEN,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "mitid_token"

    # Read the credentials the way the library does, while auth is running —
    # the flow wipes them as soon as it succeeds.
    seen: dict[str, str] = {}

    async def fake_authenticate(**kwargs: Any) -> dict[str, Any]:
        seen["auth_method"] = kwargs["auth_method"]
        seen["code"] = await kwargs["on_token_digits"]()
        seen["password"] = await kwargs["on_password"]()
        return MOCK_TOKEN_DATA

    with (
        patch(
            "custom_components.hass_aula.config_flow.authenticate",
            side_effect=fake_authenticate,
        ),
        patch(_FETCH_WIDGETS, return_value=[]),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_MITID_PASSWORD: "hunter2",
                CONF_TOKEN_CODE: "123456",
            },
        )
        if result["type"] is FlowResultType.SHOW_PROGRESS:
            result = await _advance_to_select_widgets(hass, result["flow_id"])

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "select_widgets"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_WIDGETS: []},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_AUTH_METHOD] == AUTH_METHOD_TOKEN
    # The password and code are single-use, so they must not reach the entry.
    assert CONF_MITID_PASSWORD not in result["data"]
    assert CONF_TOKEN_CODE not in result["data"]

    assert seen == {
        "auth_method": AUTH_METHOD_TOKEN,
        "code": "123456",
        "password": "hunter2",
    }


async def test_app_flow_records_auth_method(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test the app method is the default and is stored on the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )

    with (
        patch(
            "custom_components.hass_aula.config_flow.authenticate",
            return_value=MOCK_TOKEN_DATA,
        ) as mock_auth,
        patch(_FETCH_WIDGETS, return_value=[]),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_MITID_USERNAME: MOCK_USERNAME},
        )
        if result["type"] is FlowResultType.SHOW_PROGRESS:
            result = await _advance_to_select_widgets(hass, result["flow_id"])
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_WIDGETS: []},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_AUTH_METHOD] == AUTH_METHOD_APP
    assert mock_auth.await_args.kwargs["auth_method"] == AUTH_METHOD_APP


@pytest.mark.parametrize("code", ["12345", "1234567", "12345a", "      "])
async def test_token_flow_rejects_malformed_code(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    code: str,
) -> None:
    """Test a code that is not 6 digits is caught before calling MitID."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_MITID_USERNAME: MOCK_USERNAME,
            CONF_AUTH_METHOD: AUTH_METHOD_TOKEN,
        },
    )

    with patch(
        "custom_components.hass_aula.config_flow.authenticate",
    ) as mock_auth:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_MITID_PASSWORD: "hunter2", CONF_TOKEN_CODE: code},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "mitid_token"
    assert result["errors"] == {CONF_TOKEN_CODE: "invalid_token_code"}
    mock_auth.assert_not_awaited()


@pytest.mark.parametrize(
    ("cause", "expected_error"),
    [
        (TokenInvalidError("rejected"), "invalid_token_code"),
        (PasswordInvalidError("rejected"), "invalid_password"),
        (RuntimeError("something else"), "auth_failed"),
    ],
)
async def test_token_flow_rejected_credentials_returns_to_form(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    cause: Exception,
    expected_error: str,
) -> None:
    """Test a rejected code or password is retryable instead of a dead end."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_MITID_USERNAME: MOCK_USERNAME,
            CONF_AUTH_METHOD: AUTH_METHOD_TOKEN,
        },
    )
    flow_id = result["flow_id"]

    with patch(
        "custom_components.hass_aula.config_flow.authenticate",
        side_effect=_wrapped_mitid_error(cause),
    ) as mock_auth:
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={CONF_MITID_PASSWORD: "hunter2", CONF_TOKEN_CODE: "123456"},
        )
        if result["type"] is FlowResultType.SHOW_PROGRESS:
            await hass.async_block_till_done()
            result = await hass.config_entries.flow.async_configure(flow_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "mitid_token"
    assert result["errors"] == {"base": expected_error}
    # The rejected code must not be replayed into MitID on the way back.
    assert mock_auth.await_count == 1

    # The retry must run a fresh auth attempt rather than reusing the dead task.
    with (
        patch(
            "custom_components.hass_aula.config_flow.authenticate",
            return_value=MOCK_TOKEN_DATA,
        ),
        patch(_FETCH_WIDGETS, return_value=[]),
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={CONF_MITID_PASSWORD: "hunter2", CONF_TOKEN_CODE: "654321"},
        )
        if result["type"] is FlowResultType.SHOW_PROGRESS:
            result = await _advance_to_select_widgets(hass, flow_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_widgets"


async def test_app_flow_shows_otp_code_when_qr_is_not_offered(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test the typed-code channel shows the code instead of spinning on a QR."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )

    release = asyncio.Event()

    async def fake_authenticate(**kwargs: Any) -> dict[str, Any]:
        # MitID picks the typed-code channel: on_otp_code fires, on_qr_codes never does.
        kwargs["on_otp_code"]("482913")
        await release.wait()
        return MOCK_TOKEN_DATA

    with (
        patch(
            "custom_components.hass_aula.config_flow.authenticate",
            side_effect=fake_authenticate,
        ),
        patch(_FETCH_WIDGETS, return_value=[]),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_MITID_USERNAME: MOCK_USERNAME},
        )
        flow_id = result["flow_id"]
        if result["type"] is FlowResultType.SHOW_PROGRESS:
            await hass.async_block_till_done()
            result = await hass.config_entries.flow.async_configure(flow_id)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "mitid_otp"
        assert result["description_placeholders"] == {"otp_code": "482913"}

        # Approving in the app finishes the auth; Submit then completes the flow.
        release.set()
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(flow_id, user_input={})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_widgets"


async def test_reauth_reuses_stored_token_method(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test reauth asks for a new code when the account uses a code display."""
    entry = make_config_entry(
        data={
            CONF_MITID_USERNAME: MOCK_USERNAME,
            CONF_AUTH_METHOD: AUTH_METHOD_TOKEN,
            CONF_TOKEN_DATA: MOCK_TOKEN_DATA,
        },
    )
    entry.add_to_hass(hass)

    await entry.start_reauth_flow(hass)
    await hass.async_block_till_done()
    flow_id = hass.config_entries.flow.async_progress()[0]["flow_id"]

    result = await hass.config_entries.flow.async_configure(flow_id)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(flow_id, user_input={})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "mitid_token"

    with patch(
        "custom_components.hass_aula.config_flow.authenticate",
        return_value=MOCK_TOKEN_DATA,
    ) as mock_auth:
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={CONF_MITID_PASSWORD: "hunter2", CONF_TOKEN_CODE: "123456"},
        )
        if result["type"] is FlowResultType.SHOW_PROGRESS:
            await hass.async_block_till_done()
            result = await hass.config_entries.flow.async_configure(flow_id)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_auth.await_args.kwargs["auth_method"] == AUTH_METHOD_TOKEN
    assert entry.data[CONF_AUTH_METHOD] == AUTH_METHOD_TOKEN


# What MitID offers a person with both a private and a business identity, in the
# "name (detail)" form aula hands to on_identity_selected.
_IDENTITIES = ["Mette Hansen (Privat)", "Mette Hansen (Firma ApS)"]

_QR_SVG = "custom_components.hass_aula.config_flow.generate_animated_qr_svg"


def _identity_options(result: Any) -> dict[str, str]:
    """Return the mitid_identity options as {value: label}."""
    for key, validator in result["data_schema"].schema.items():
        if key == CONF_IDENTITY:
            return {o["value"]: o["label"] for o in validator.config["options"]}
    msg = "no identity selector in the mitid_identity form"
    raise AssertionError(msg)


async def _wait_for_step(hass: HomeAssistant, flow_id: str, step_id: str) -> None:
    """
    Let the flow react to its progress task while the login is still running.

    async_block_till_done would wait for the login itself, which is paused on
    the identity choice, so step the loop instead.
    """
    for _ in range(20):
        if hass.config_entries.flow.async_get(flow_id)["step_id"] == step_id:
            return
        await asyncio.sleep(0)
    msg = f"flow never reached {step_id}"
    raise AssertionError(msg)


async def test_app_flow_asks_which_mitid_identity_to_use(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test a MitID with several identities logs in with the one the user picks."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    approved = asyncio.Event()
    asked = asyncio.Event()
    chosen: list[int] = []

    async def fake_authenticate(**kwargs: Any) -> dict[str, Any]:
        kwargs["on_qr_codes"](None, None)
        await approved.wait()
        asked.set()
        chosen.append(await kwargs["on_identity_selected"](_IDENTITIES))
        return MOCK_TOKEN_DATA

    with (
        patch(
            "custom_components.hass_aula.config_flow.authenticate",
            side_effect=fake_authenticate,
        ),
        patch(_QR_SVG, return_value="<svg/>"),
        patch(_FETCH_WIDGETS, return_value=[]),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_MITID_USERNAME: MOCK_USERNAME},
        )
        flow_id = result["flow_id"]
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "mitid_qr"

        # Approving in the app takes MitID to its identity picker.
        approved.set()
        await asked.wait()

        # Submit on the QR step, as the user does after approving.
        result = await hass.config_entries.flow.async_configure(flow_id, user_input={})
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "mitid_identity"
        assert _identity_options(result) == {
            "0": "Mette Hansen (Privat)",
            "1": "Mette Hansen (Firma ApS)",
        }

        # The login resumes with the choice and shows progress until it is done.
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_IDENTITY: "1"}
        )
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(flow_id)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "select_widgets"

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_WIDGETS: []}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert chosen == [1]


async def test_token_flow_asks_which_mitid_identity_to_use(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test the code display spinner gives way to the identity picker."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_MITID_USERNAME: MOCK_USERNAME,
            CONF_AUTH_METHOD: AUTH_METHOD_TOKEN,
        },
    )
    flow_id = result["flow_id"]

    mitid_answered = asyncio.Event()
    asked = asyncio.Event()
    chosen: list[int] = []

    async def fake_authenticate(**kwargs: Any) -> dict[str, Any]:
        await mitid_answered.wait()
        asked.set()
        chosen.append(await kwargs["on_identity_selected"](_IDENTITIES))
        return MOCK_TOKEN_DATA

    with (
        patch(
            "custom_components.hass_aula.config_flow.authenticate",
            side_effect=fake_authenticate,
        ),
        patch(_FETCH_WIDGETS, return_value=[]),
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={CONF_MITID_PASSWORD: "hunter2", CONF_TOKEN_CODE: "123456"},
        )
        assert result["type"] is FlowResultType.SHOW_PROGRESS

        mitid_answered.set()
        await asked.wait()
        await _wait_for_step(hass, flow_id, "mitid_identity")

        result = await hass.config_entries.flow.async_configure(flow_id)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "mitid_identity"

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_IDENTITY: "1"}
        )
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(flow_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_widgets"
    assert chosen == [1]


async def test_token_flow_finishes_after_the_spinner(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test a code display login still running when the spinner shows completes."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_MITID_USERNAME: MOCK_USERNAME,
            CONF_AUTH_METHOD: AUTH_METHOD_TOKEN,
        },
    )
    flow_id = result["flow_id"]

    mitid_answered = asyncio.Event()

    async def fake_authenticate(**_kwargs: Any) -> dict[str, Any]:
        await mitid_answered.wait()
        return MOCK_TOKEN_DATA

    with (
        patch(
            "custom_components.hass_aula.config_flow.authenticate",
            side_effect=fake_authenticate,
        ),
        patch(_FETCH_WIDGETS, return_value=[]),
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={CONF_MITID_PASSWORD: "hunter2", CONF_TOKEN_CODE: "123456"},
        )
        assert result["type"] is FlowResultType.SHOW_PROGRESS

        # SHOW_PROGRESS may only become SHOW_PROGRESS or SHOW_PROGRESS_DONE, so
        # going straight to the widget form raised a ValueError here.
        mitid_answered.set()
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(flow_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_widgets"


async def test_closing_the_flow_at_the_identity_step_stops_the_login(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test a login waiting on the identity choice is cancelled with the flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    cancelled = asyncio.Event()

    async def fake_authenticate(**kwargs: Any) -> dict[str, Any]:
        kwargs["on_qr_codes"](None, None)
        try:
            await kwargs["on_identity_selected"](_IDENTITIES)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return MOCK_TOKEN_DATA

    with (
        patch(
            "custom_components.hass_aula.config_flow.authenticate",
            side_effect=fake_authenticate,
        ),
        patch(_QR_SVG, return_value="<svg/>"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_MITID_USERNAME: MOCK_USERNAME},
        )
        assert result["step_id"] == "mitid_identity"

        hass.config_entries.flow.async_abort(result["flow_id"])
        await hass.async_block_till_done()

    assert cancelled.is_set()

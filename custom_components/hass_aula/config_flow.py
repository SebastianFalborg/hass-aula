"""Config flow for the Aula integration."""

from __future__ import annotations

import asyncio
import ssl
import time
from typing import TYPE_CHECKING, Any

import httpx
import voluptuous as vol
from aula import WidgetConfiguration, authenticate, create_client
from aula.auth.exceptions import PasswordInvalidError, TokenInvalidError
from aula.auth.mitid_client import MitIDAuthClient
from aula.http_httpx import HttpxHttpClient
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.helpers import selector
from slugify import slugify

from .const import (
    AUTH_METHOD_APP,
    AUTH_METHOD_TOKEN,
    AUTH_METHODS,
    CONF_AUTH_METHOD,
    CONF_IDENTITY,
    CONF_MITID_PASSWORD,
    CONF_MITID_USERNAME,
    CONF_TOKEN_CODE,
    CONF_TOKEN_DATA,
    CONF_WIDGETS,
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    LOGGER,
    SUPPORTED_WIDGETS,
    TOKEN_CODE_LENGTH,
)
from .qr_view import AulaQRView, generate_animated_qr_svg

if TYPE_CHECKING:
    import qrcode


def _selectable_widgets(
    widgets: list[WidgetConfiguration],
) -> list[WidgetConfiguration]:
    """
    Return the widgets the data-provider dialog may offer.

    The portal's widget list mixes in widgets the guardian can see in the app
    but this integration cannot serve, so the dialog marks those "(not
    supported)" instead of hiding them. What the portal itself marks secure
    decides what is offered as supported: the EasyIQ weekplan is typed
    "iframe" but secure, and filtering on the type string instead dropped it
    from every EasyIQ school's dialog.
    """
    return [w for w in widgets if w.is_secure]


def _auth_method_selector() -> selector.SelectSelector:
    """Selector for the MitID authenticator to use."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=AUTH_METHODS,
            translation_key=CONF_AUTH_METHOD,
            mode=selector.SelectSelectorMode.LIST,
        ),
    )


def _token_error_code(err: BaseException | None) -> str:
    """
    Map a failed kodeviser login to a form error key.

    ``aula.authenticate`` wraps MitID failures in a RuntimeError, so the
    specific cause is read off ``__cause__``.
    """
    cause = err.__cause__ if err is not None else None
    if isinstance(cause, TokenInvalidError):
        return "invalid_token_code"
    if isinstance(cause, PasswordInvalidError):
        return "invalid_password"
    return "auth_failed"


class AulaFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Aula."""

    VERSION = CONFIG_ENTRY_VERSION
    MINOR_VERSION = CONFIG_ENTRY_MINOR_VERSION

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._mitid_username: str = ""
        self._token_data: dict[str, Any] | None = None
        self._auth_task: asyncio.Task[dict[str, Any]] | None = None
        self._qr_ready_task: asyncio.Task[None] | None = None
        self._qr_ready_event: asyncio.Event | None = None
        self._qr_svg: str | None = None
        self._httpx_client: httpx.AsyncClient | None = None
        self._qr_view: AulaQRView | None = None
        self._existing_entry: ConfigEntry | None = None
        self._is_reconfigure: bool = False
        self._available_widgets: list[WidgetConfiguration] = []
        self._auth_method: str = AUTH_METHOD_APP
        # Kodeviser credentials. Held in memory for the duration of the flow
        # only — never written to the config entry.
        self._mitid_password: str = ""
        self._token_code: str = ""
        self._token_error: str | None = None
        self._otp_code: str | None = None
        # MitID identity picker. The request resolves when MitID asks which
        # identity to use; the login then waits on the choice.
        self._identity_request: asyncio.Future[None] | None = None
        self._identity_choice: asyncio.Future[int] | None = None
        self._identities: list[str] = []

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the user step - enter MitID username."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._mitid_username = user_input[CONF_MITID_USERNAME]
            self._auth_method = user_input.get(CONF_AUTH_METHOD, AUTH_METHOD_APP)
            await self.async_set_unique_id(slugify(self._mitid_username))
            self._abort_if_unique_id_configured()
            return await self._async_start_auth()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MITID_USERNAME): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Required(
                        CONF_AUTH_METHOD, default=AUTH_METHOD_APP
                    ): _auth_method_selector(),
                },
            ),
            errors=errors,
        )

    async def _async_start_auth(self) -> ConfigFlowResult:
        """Route to the step that collects what the chosen authenticator needs."""
        if self._auth_method == AUTH_METHOD_TOKEN:
            return await self.async_step_mitid_token()
        return await self.async_step_mitid_auth()

    async def async_step_mitid_token(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """
        Collect the MitID password and kodeviser code before authenticating.

        The code is one-time and short-lived, so it is collected immediately
        before the auth run rather than stored.
        """
        errors: dict[str, str] = {}
        if self._token_error:
            errors["base"] = self._token_error
            self._token_error = None
            # Reached from mitid_auth via progress_done. The flow manager replays
            # the input that started the failed attempt, so drop it — resubmitting
            # a rejected code would loop straight back into MitID.
            user_input = None

        if user_input is not None:
            password = user_input[CONF_MITID_PASSWORD]
            code = user_input[CONF_TOKEN_CODE].strip()
            if not code.isdigit() or len(code) != TOKEN_CODE_LENGTH:
                errors[CONF_TOKEN_CODE] = "invalid_token_code"
            else:
                self._mitid_password = password
                self._token_code = code
                return await self.async_step_mitid_auth()

        return self.async_show_form(
            step_id="mitid_token",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MITID_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        ),
                    ),
                    vol.Required(CONF_TOKEN_CODE): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                },
            ),
            description_placeholders={CONF_MITID_USERNAME: self._mitid_username},
            errors=errors,
        )

    async def async_step_mitid_auth(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Handle MitID authentication, showing a QR code for the app method."""
        uses_qr = self._auth_method != AUTH_METHOD_TOKEN
        if not self._auth_task:
            LOGGER.debug(
                "Starting MitID auth flow for %s using %s",
                self._mitid_username,
                self._auth_method,
            )
            if uses_qr:
                self._qr_ready_event = asyncio.Event()
                self._qr_ready_task = self.hass.async_create_task(
                    self._wait_for_qr_ready(),
                    "hass_aula_qr_ready",
                )
            # Build the SSL context in an executor to avoid blocking the event
            # loop with ssl.SSLContext.load_verify_locations.
            ssl_context = await self.hass.async_add_executor_job(
                ssl.create_default_context,
            )
            self._httpx_client = httpx.AsyncClient(
                verify=ssl_context,
                follow_redirects=False,
                timeout=30,
            )
            # Register the view BEFORE creating the auth task.
            # The task starts eagerly, so on_qr_codes fires synchronously during
            # task creation — _qr_view must already exist at that point.
            if uses_qr:
                self._register_qr_view()
                LOGGER.debug("QR view registered at /api/hass_aula/qr/%s", self.flow_id)
            self._identity_request = self.hass.loop.create_future()
            self._auth_task = self.hass.async_create_task(
                self._async_authenticate(),
                "hass_aula_mitid_auth",
            )
            LOGGER.debug(
                "Auth task created. qr_svg set=%s, "
                "qr_view has svg=%s, qr_ready_event set=%s",
                self._qr_svg is not None,
                self._qr_view is not None and self._qr_view._svg is not None,  # noqa: SLF001
                self._qr_ready_event is not None and self._qr_ready_event.is_set(),
            )

        # This step may be showing progress, and SHOW_PROGRESS can only become
        # SHOW_PROGRESS or SHOW_PROGRESS_DONE, so hand over via progress_done.
        if self._pending_identity_choice():
            return self.async_show_progress_done(next_step_id="mitid_identity")

        if self._auth_task.done():
            return self.async_show_progress_done(next_step_id="mitid_auth_done")

        if not uses_qr:
            # Kodeviser: nothing to display, just wait for the handshake. Wait on
            # the identity question too, or a login paused on it spins forever.
            return self.async_show_progress(
                step_id="mitid_auth",
                progress_action="authenticating_token",
                progress_task=self.hass.async_create_task(
                    self._wait_for_auth_or_identity_request(),
                    "hass_aula_mitid_wait",
                ),
            )

        # MitID asked for a typed code instead of a QR scan. Nothing will ever be
        # drawn for this user, so show the code rather than spinning forever.
        if self._otp_code:
            LOGGER.debug("OTP code requested, transitioning to OTP form step")
            return self.async_show_progress_done(next_step_id="mitid_otp")

        # QR is ready — transition out of progress via progress_done, then show QR form.
        # SHOW_PROGRESS can only transition to SHOW_PROGRESS or SHOW_PROGRESS_DONE;
        # jumping directly to SHOW_FORM raises a ValueError.
        if self._qr_svg:
            LOGGER.debug("QR ready, transitioning to QR form step via progress_done")
            return self.async_show_progress_done(next_step_id="mitid_qr")

        # QR not yet generated — show spinner while waiting.
        progress_task = (
            self._qr_ready_task
            if self._qr_ready_task and not self._qr_ready_task.done()
            else self._auth_task
        )
        LOGGER.debug(
            "Showing progress spinner, progress_task=%s",
            "qr_ready" if progress_task is self._qr_ready_task else "auth",
        )
        return self.async_show_progress(
            step_id="mitid_auth",
            progress_action="authenticating",
            progress_task=progress_task,
        )

    async def _async_auth_task_finished(
        self,
        task: asyncio.Task[dict[str, Any]],
        *,
        uses_qr: bool,
    ) -> ConfigFlowResult:
        """Turn a completed auth attempt into the next flow step."""
        self._unregister_qr_view()
        if err := task.exception():
            LOGGER.error("MitID authentication failed: %s", err)
            if uses_qr:
                return self.async_abort(reason="auth_failed")
            # A mistyped code or password is worth a retry rather than a dead
            # end. SHOW_PROGRESS cannot become SHOW_FORM directly, so hand
            # control back via progress_done.
            self._token_error = _token_error_code(err)
            self._reset_auth_task()
            return self.async_show_progress_done(next_step_id="mitid_token")

        self._token_data = task.result()
        return await self._async_auth_complete()

    async def async_step_mitid_auth_done(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Handle completion of MitID auth progress."""
        LOGGER.debug(
            "mitid_auth_done called: auth_task done=%s, qr_svg set=%s",
            self._auth_task.done() if self._auth_task else "no task",
            self._qr_svg is not None,
        )
        # The QR-ready task finished but auth is still running.
        # SHOW_PROGRESS does not render description_placeholders in the frontend,
        # so switch to a FORM step which does render its description markdown.
        if self._auth_task and not self._auth_task.done():
            if self._otp_code:
                return await self.async_step_mitid_otp()
            return await self.async_step_mitid_qr()

        if self._auth_task is None:
            self._unregister_qr_view()
            return await self._async_auth_complete()

        return await self._async_auth_task_finished(
            self._auth_task, uses_qr=self._auth_method != AUTH_METHOD_TOKEN
        )

    async def async_step_mitid_qr(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Show QR code step; FORM renders markdown images, PROGRESS does not."""
        if user_input is not None:
            # User clicked Submit after approving on their phone.
            if self._pending_identity_choice():
                return await self.async_step_mitid_identity()
            if self._auth_task and self._auth_task.done():
                self._unregister_qr_view()
                if self._auth_task.exception():
                    LOGGER.error(
                        "MitID authentication failed: %s", self._auth_task.exception()
                    )
                    return self.async_abort(reason="auth_failed")
                self._token_data = self._auth_task.result()
                return await self._async_auth_complete()
            # Auth not finished yet — re-show with the latest QR (on_qr_codes
            # keeps updating the view in the background).
            LOGGER.debug("Submit pressed but auth not done yet, re-showing QR form")

        LOGGER.debug(
            "Showing QR form: qr_url=/api/hass_aula/qr/%s, auth_done=%s",
            self.flow_id,
            self._auth_task.done() if self._auth_task else "no task",
        )
        return self.async_show_form(
            step_id="mitid_qr",
            data_schema=vol.Schema({}),
            description_placeholders={"qr_url": f"/api/hass_aula/qr/{self.flow_id}"},
        )

    async def async_step_mitid_otp(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Show the code MitID wants typed into the app instead of a QR scan."""
        if user_input is not None and self._pending_identity_choice():
            return await self.async_step_mitid_identity()
        if user_input is not None and self._auth_task and self._auth_task.done():
            self._unregister_qr_view()
            if self._auth_task.exception():
                LOGGER.error(
                    "MitID authentication failed: %s", self._auth_task.exception()
                )
                return self.async_abort(reason="auth_failed")
            self._token_data = self._auth_task.result()
            return await self._async_auth_complete()

        return self.async_show_form(
            step_id="mitid_otp",
            data_schema=vol.Schema({}),
            description_placeholders={"otp_code": self._otp_code or ""},
        )

    async def async_step_mitid_identity(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Ask which identity to log in with when MitID offers more than one."""
        task = self._auth_task
        choice = self._pending_identity_choice()
        if task is None or choice is None:
            # Back from the progress shown after the choice.
            if task and not task.done():
                return self._async_show_identity_progress(task)
            return self.async_show_progress_done(next_step_id="mitid_auth_done")

        # The flow manager replays the input of the step that led here, so
        # only treat it as a choice when it carries one.
        if user_input is not None and CONF_IDENTITY in user_input:
            choice.set_result(int(user_input[CONF_IDENTITY]))
            return self._async_show_identity_progress(task)

        return self.async_show_form(
            step_id="mitid_identity",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IDENTITY): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=str(index), label=identity
                                )
                                for index, identity in enumerate(self._identities)
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                        ),
                    ),
                },
            ),
        )

    def _async_show_identity_progress(
        self, task: asyncio.Task[dict[str, Any]]
    ) -> ConfigFlowResult:
        """Show progress while the login carries on with the chosen identity."""
        return self.async_show_progress(
            step_id="mitid_identity",
            progress_action="logging_in",
            progress_task=task,
        )

    async def async_step_select_widgets(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Let the user choose which widgets to enable."""
        if not self._available_widgets:
            self._available_widgets = await self._async_fetch_widgets()

        if user_input is not None:
            data = {
                CONF_MITID_USERNAME: self._mitid_username,
                CONF_AUTH_METHOD: self._auth_method,
                CONF_TOKEN_DATA: self._token_data,
                CONF_WIDGETS: user_input.get(CONF_WIDGETS, []),
            }
            if self._existing_entry:
                return self.async_update_reload_and_abort(
                    self._existing_entry, data=data
                )
            return self.async_create_entry(
                title=self._mitid_username,
                data=data,
            )

        default_widgets = (
            list(self._existing_entry.data.get(CONF_WIDGETS, []))
            if self._existing_entry
            else []
        )
        supported: list[selector.SelectOptionDict] = []
        unsupported: list[selector.SelectOptionDict] = []
        for w in self._available_widgets:
            if w.widget_id in SUPPORTED_WIDGETS:
                supported.append(
                    selector.SelectOptionDict(value=w.widget_id, label=w.name)
                )
            else:
                unsupported.append(
                    selector.SelectOptionDict(
                        value=w.widget_id,
                        label=f"{w.name} (not supported)",
                    )
                )
        options = [*supported, *unsupported]
        valid_values = {opt["value"] for opt in options}
        default_widgets = [w for w in default_widgets if w in valid_values]
        return self.async_show_form(
            step_id="select_widgets",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_WIDGETS, default=default_widgets
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            multiple=True,
                        ),
                    ),
                },
            ),
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> ConfigFlowResult:
        """Handle reauth when token expires."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="unknown")
        self._existing_entry = entry
        self._mitid_username = entry_data[CONF_MITID_USERNAME]
        self._auth_method = entry_data.get(CONF_AUTH_METHOD, AUTH_METHOD_APP)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle reauth confirmation - starts MitID auth."""
        if user_input is not None:
            return await self._async_start_auth()

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={
                CONF_MITID_USERNAME: self._mitid_username,
            },
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle reconfiguration - allow changing MitID username."""
        errors: dict[str, str] = {}

        reconfigure_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        if reconfigure_entry is None:
            return self.async_abort(reason="unknown")
        self._existing_entry = reconfigure_entry
        self._is_reconfigure = True

        if user_input is not None:
            self._mitid_username = user_input[CONF_MITID_USERNAME]
            self._auth_method = user_input.get(CONF_AUTH_METHOD, AUTH_METHOD_APP)
            return await self._async_start_auth()

        self._mitid_username = (
            reconfigure_entry.data.get(CONF_MITID_USERNAME, "")
            if reconfigure_entry
            else ""
        )
        self._auth_method = reconfigure_entry.data.get(
            CONF_AUTH_METHOD, AUTH_METHOD_APP
        )

        # Try refreshing the existing token to skip MitID auth
        if reconfigure_entry:
            token_data = reconfigure_entry.data.get(CONF_TOKEN_DATA, {})
            refresh_token = token_data.get("tokens", {}).get("refresh_token")
            if refresh_token:
                try:
                    self._token_data = await self._async_refresh_token(
                        token_data, refresh_token
                    )
                    return await self.async_step_select_widgets()
                except Exception:  # noqa: BLE001
                    LOGGER.debug(
                        "Token refresh failed during reconfigure, "
                        "falling back to MitID auth"
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MITID_USERNAME,
                        default=self._mitid_username,
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Required(
                        CONF_AUTH_METHOD,
                        default=self._auth_method,
                    ): _auth_method_selector(),
                },
            ),
            errors=errors,
        )

    async def _async_auth_complete(self) -> ConfigFlowResult:
        """Route to widget selection or skip for reauth."""
        # The kodeviser credentials are single-use; drop them once they worked.
        self._mitid_password = ""
        self._token_code = ""
        if self._existing_entry and not self._is_reconfigure:
            return self.async_update_reload_and_abort(
                self._existing_entry,
                data={
                    CONF_MITID_USERNAME: self._mitid_username,
                    CONF_AUTH_METHOD: self._auth_method,
                    CONF_TOKEN_DATA: self._token_data,
                    CONF_WIDGETS: self._existing_entry.data.get(CONF_WIDGETS, []),
                },
            )
        return await self.async_step_select_widgets()

    async def _async_fetch_widgets(self) -> list[WidgetConfiguration]:
        """Create a temporary client to fetch available widgets."""
        if self._token_data is None:
            return []
        cookies = self._token_data.get("cookies", {})
        http_client = await self.hass.async_add_executor_job(HttpxHttpClient, cookies)
        try:
            client = await create_client(self._token_data, http_client=http_client)
            widgets = _selectable_widgets(await client.get_widgets())
        except Exception:  # noqa: BLE001
            LOGGER.exception("Failed to fetch widgets")
            return []
        else:
            LOGGER.debug("Fetched %d secure widgets", len(widgets))
            return widgets
        finally:
            await http_client.close()

    async def _async_refresh_token(
        self, token_data: dict[str, Any], refresh_token: str
    ) -> dict[str, Any]:
        """Attempt to refresh the access token using the stored refresh token."""
        ssl_context = await self.hass.async_add_executor_job(
            ssl.create_default_context,
        )
        httpx_client = httpx.AsyncClient(
            verify=ssl_context, follow_redirects=False, timeout=30
        )
        try:
            auth_client = MitIDAuthClient(mitid_username="", httpx_client=httpx_client)
            new_tokens = await auth_client.refresh_access_token(refresh_token)
        finally:
            await httpx_client.aclose()

        return {
            "timestamp": time.time(),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "username": token_data.get("username", ""),
            "tokens": new_tokens,
            "cookies": token_data.get("cookies", {}),
        }

    async def _async_authenticate(self) -> dict[str, Any]:
        """Run MitID authentication in background."""

        def on_qr_codes(qr1: qrcode.QRCode[Any], qr2: qrcode.QRCode[Any]) -> None:
            LOGGER.debug(
                "on_qr_codes called: qr1=%s, qr2=%s, _qr_view=%s",
                type(qr1).__name__,
                type(qr2).__name__,
                "set" if self._qr_view else "None",
            )
            self._qr_svg = generate_animated_qr_svg(qr1, qr2)
            LOGGER.debug("QR SVG generated (%d bytes)", len(self._qr_svg))
            if self._qr_view:
                self._qr_view.update_svg(self._qr_svg)
                LOGGER.debug("QR SVG written to view")
            else:
                LOGGER.warning(
                    "on_qr_codes fired but _qr_view is None — SVG not served"
                )
            if self._qr_ready_event:
                self._qr_ready_event.set()
                LOGGER.debug("QR ready event set")

        def on_otp_code(code: str) -> None:
            # MitID chose the typed-code channel, so on_qr_codes will never fire.
            # Release the same wait the QR path uses, or the flow spins forever.
            LOGGER.debug("OTP code received from MitID")
            self._otp_code = code
            if self._qr_ready_event:
                self._qr_ready_event.set()

        async def on_identity_selected(identities: list[str]) -> int:
            # MitID offers more than one identity, e.g. private and business.
            # Wait for the user to pick one rather than guessing.
            LOGGER.debug("MitID offers %d identities, asking which", len(identities))
            self._identities = identities
            choice: asyncio.Future[int] = self.hass.loop.create_future()
            self._identity_choice = choice
            if self._identity_request and not self._identity_request.done():
                self._identity_request.set_result(None)
            return await choice

        async def on_token_digits() -> str:
            return self._token_code

        async def on_password() -> str:
            return self._mitid_password

        LOGGER.debug(
            "Calling aula.authenticate for %s using %s",
            self._mitid_username,
            self._auth_method,
        )
        try:
            result = await authenticate(
                mitid_username=self._mitid_username,
                on_qr_codes=on_qr_codes,
                httpx_client=self._httpx_client,
                auth_method=self._auth_method,
                on_token_digits=on_token_digits,
                on_password=on_password,
                on_otp_code=on_otp_code,
                on_identity_selected=on_identity_selected,
            )
        finally:
            if self._httpx_client:
                await self._httpx_client.aclose()
        LOGGER.debug("aula.authenticate returned successfully")
        return result

    async def _wait_for_qr_ready(self) -> None:
        """Wait until QR codes have been generated."""
        if self._qr_ready_event:
            await self._qr_ready_event.wait()

    async def _wait_for_auth_or_identity_request(self) -> None:
        """Wait until the login finishes or MitID asks which identity to use."""
        if self._auth_task is None or self._identity_request is None:
            return
        await asyncio.wait(
            (self._auth_task, self._identity_request),
            return_when=asyncio.FIRST_COMPLETED,
        )

    def _pending_identity_choice(self) -> asyncio.Future[int] | None:
        """Return the identity choice the login is waiting on, if any."""
        choice = self._identity_choice
        if choice is None or choice.done():
            return None
        return choice

    def _reset_auth_task(self) -> None:
        """Drop a finished auth attempt so the next one starts clean."""
        self._auth_task = None
        self._qr_ready_task = None
        self._qr_ready_event = None
        self._qr_svg = None
        self._httpx_client = None
        self._token_code = ""
        self._otp_code = None
        self._identity_request = None
        self._identity_choice = None
        self._identities = []

    def _register_qr_view(self) -> None:
        """Register a temporary HTTP view for serving the QR code SVG."""
        self._qr_view = AulaQRView(self.flow_id)
        self.hass.http.register_view(self._qr_view)

    def _unregister_qr_view(self) -> None:
        """Unregister the QR code HTTP view."""
        self._qr_view = None

    def async_abort(self, *, reason: str, **kwargs: Any) -> ConfigFlowResult:
        """Handle flow abort - clean up resources."""
        self._unregister_qr_view()
        return super().async_abort(reason=reason, **kwargs)

    def async_remove(self) -> None:
        """Stop a login still running when the flow is closed."""
        # A login paused on the identity choice would otherwise wait forever.
        if self._auth_task and not self._auth_task.done():
            self._auth_task.cancel()

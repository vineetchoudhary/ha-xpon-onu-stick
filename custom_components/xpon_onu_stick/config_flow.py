"""UI setup, authentication, connection changes, and polling options."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from yarl import URL

from .api import OnuAuthError, OnuConnectionError, OnuParseError, OnuSessionBusy, normalize_host
from .client import (
    async_create_ssh_client,
    async_forget_onu_client,
    async_get_onu_client,
    async_remember_onu_client,
)
from .const import (
    CONF_CONNECTION_TYPE,
    CONF_LOGOUT_AFTER_POLL,
    CONF_SSH_FINGERPRINT,
    CONF_SSH_KEY_FILE,
    CONNECTION_BOA,
    CONNECTION_ODI_SSH,
    DEFAULT_LOGOUT_AFTER_POLL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SSH_PORT,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .devices.odi_oss.ssh import (
    OnuHostKeyError,
    OnuKeyFileError,
    normalize_fingerprint,
    normalize_ssh_host,
)
from .health import LIMIT_DEFAULTS, MEASUREMENT_UNITS, validate_limits


def _connection_schema(defaults: dict[str, Any], *, include_host: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if include_host:
        host_field = vol.Required(CONF_HOST)
        if CONF_HOST in defaults:
            host_field = vol.Required(CONF_HOST, default=defaults[CONF_HOST])
        fields[host_field] = str
    fields[vol.Optional(CONF_USERNAME, default=defaults.get(CONF_USERNAME, ""))] = str
    fields[vol.Optional(CONF_PASSWORD, default="")] = TextSelector(
        TextSelectorConfig(type=TextSelectorType.PASSWORD)
    )
    return vol.Schema(fields)


def _ssh_schema(defaults: dict[str, Any], *, reauth: bool) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(CONF_SSH_KEY_FILE, default=defaults.get(CONF_SSH_KEY_FILE, "")): str,
    }
    if not reauth:
        fields = {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED)): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_SSH_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            **fields,
            vol.Required(CONF_SSH_FINGERPRINT, default=defaults.get(CONF_SSH_FINGERPRINT, "")): str,
        }
    return vol.Schema(fields)


class OnuConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a device after verifying a read-only status poll."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OnuOptionsFlow:
        return OnuOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_menu(step_id="user", menu_options=["boa", "ssh"])
        if user_input.get(CONF_CONNECTION_TYPE) == CONNECTION_ODI_SSH:
            return await self.async_step_ssh(user_input)
        return await self.async_step_boa(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_menu(step_id="reconfigure", menu_options=["boa", "ssh"])
        entry = self._get_reconfigure_entry()
        if user_input.get(CONF_CONNECTION_TYPE, entry.data.get(CONF_CONNECTION_TYPE)) == (
            CONNECTION_ODI_SSH
        ):
            return await self.async_step_ssh(user_input)
        return await self.async_step_boa(user_input)

    async def async_step_boa(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_connection_step("boa", user_input)

    async def async_step_ssh(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry() if self.source == "reconfigure" else None
        return await self._async_ssh_step(user_input, entry=entry, reauth=False)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        if entry_data.get(CONF_CONNECTION_TYPE) == CONNECTION_ODI_SSH:
            return await self.async_step_ssh_reauth()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_connection_step("reauth_confirm", user_input)

    async def async_step_ssh_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_ssh_step(user_input, entry=self._get_reauth_entry(), reauth=True)

    async def _async_ssh_step(
        self, user_input: dict[str, Any] | None, *, entry: ConfigEntry | None, reauth: bool
    ) -> ConfigFlowResult:
        defaults = dict(entry.data) if entry else {}
        old_is_ssh = defaults.get(CONF_CONNECTION_TYPE) == CONNECTION_ODI_SSH
        if entry and not old_is_ssh:
            defaults[CONF_HOST] = URL(defaults[CONF_HOST]).host
        errors: dict[str, str] = {}
        if user_input is not None:
            if reauth:
                defaults[CONF_SSH_KEY_FILE] = user_input.get(CONF_SSH_KEY_FILE, "")
            else:
                defaults.update(user_input)
            data = {
                CONF_CONNECTION_TYPE: CONNECTION_ODI_SSH,
                CONF_HOST: defaults.get(CONF_HOST, ""),
                CONF_PORT: defaults.get(CONF_PORT, DEFAULT_SSH_PORT),
                CONF_SSH_KEY_FILE: defaults.get(CONF_SSH_KEY_FILE, "").strip(),
                CONF_SSH_FINGERPRINT: defaults.get(CONF_SSH_FINGERPRINT, ""),
            }
            try:
                data[CONF_HOST] = normalize_ssh_host(data[CONF_HOST])
            except ValueError:
                errors[CONF_HOST] = "invalid_ssh_host"
            if type(data[CONF_PORT]) is not int or not 1 <= data[CONF_PORT] <= 65535:
                errors[CONF_PORT] = "invalid_ssh_port"
            try:
                data[CONF_SSH_FINGERPRINT] = normalize_fingerprint(data[CONF_SSH_FINGERPRINT])
            except ValueError:
                errors[CONF_SSH_FINGERPRINT] = "invalid_ssh_fingerprint"
            if not errors:
                client = async_create_ssh_client(self.hass, data)
                try:
                    try:
                        status = await client.async_get_status()
                    finally:
                        await client.async_close()
                    await self.async_set_unique_id(status.mac_address)
                    if entry:
                        self._abort_if_unique_id_mismatch()
                        if not old_is_ssh:
                            async_forget_onu_client(self.hass, entry.data[CONF_HOST])
                        return self.async_update_reload_and_abort(entry, data=data)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title=status.name, data=data)
                except OnuKeyFileError:
                    errors[CONF_SSH_KEY_FILE] = "invalid_ssh_key_file"
                except OnuHostKeyError:
                    errors["base"] = "ssh_host_key_mismatch"
                except OnuAuthError:
                    errors["base"] = "ssh_key_rejected"
                except OnuConnectionError:
                    errors["base"] = "cannot_connect_ssh"
                except OnuParseError:
                    errors["base"] = "unsupported_ssh_device"
        return self.async_show_form(
            step_id="ssh_reauth" if reauth else "ssh",
            data_schema=_ssh_schema(defaults, reauth=reauth),
            errors=errors,
        )

    async def _async_connection_step(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        entry = None
        if self.source == "reconfigure":
            entry = self._get_reconfigure_entry()
        elif step_id == "reauth_confirm":
            entry = self._get_reauth_entry()
        defaults = dict(entry.data) if entry else {}
        old_is_ssh = defaults.get(CONF_CONNECTION_TYPE) == CONNECTION_ODI_SSH
        if old_is_ssh:
            defaults[CONF_HOST] = (
                URL.build(scheme="http", host=defaults[CONF_HOST]).origin().human_repr()
            )
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {
                CONF_HOST: user_input.get(CONF_HOST, defaults.get(CONF_HOST, "")),
                CONF_USERNAME: user_input.get(CONF_USERNAME, "").strip(),
                CONF_PASSWORD: user_input.get(CONF_PASSWORD, ""),
            }
            defaults.update(data)
            try:
                data[CONF_HOST] = normalize_host(data[CONF_HOST])
                if data[CONF_PASSWORD] and not data[CONF_USERNAME]:
                    errors[CONF_USERNAME] = "username_required"
                else:
                    client = async_get_onu_client(
                        self.hass,
                        data[CONF_HOST],
                        data[CONF_USERNAME],
                        data[CONF_PASSWORD],
                    )
                    status = await client.async_get_status(logout_after_poll=False)
                    await self.async_set_unique_id(status.mac_address)
                    if entry:
                        self._abort_if_unique_id_mismatch()
                        async_remember_onu_client(self.hass, client)
                        if (
                            not old_is_ssh
                            and normalize_host(entry.data[CONF_HOST]) != data[CONF_HOST]
                        ):
                            async_forget_onu_client(self.hass, entry.data[CONF_HOST])
                        return self.async_update_reload_and_abort(entry, data=data)
                    self._abort_if_unique_id_configured()
                    async_remember_onu_client(self.hass, client)
                    return self.async_create_entry(
                        title=status.name,
                        data=data,
                    )
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
            except OnuAuthError:
                errors["base"] = "invalid_auth"
            except OnuSessionBusy:
                errors["base"] = "session_busy"
            except OnuConnectionError:
                errors["base"] = "cannot_connect"
            except OnuParseError:
                errors["base"] = "unsupported_device"

        return self.async_show_form(
            step_id=step_id,
            data_schema=_connection_schema(defaults, include_host=step_id != "reauth_confirm"),
            errors=errors,
        )


class OnuOptionsFlow(OptionsFlowWithReload):
    """Change polling, advisory status limits, and session behavior."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options = ["polling", "status_limits"]
        if self.config_entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_BOA) == CONNECTION_BOA:
            options.append("session")
        return self.async_show_menu(step_id="init", menu_options=options)

    async def async_step_session(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="", data={**self.config_entry.options, **user_input}
            )
        return self.async_show_form(
            step_id="session",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOGOUT_AFTER_POLL,
                        default=self.config_entry.options.get(
                            CONF_LOGOUT_AFTER_POLL, DEFAULT_LOGOUT_AFTER_POLL
                        ),
                    ): BooleanSelector(),
                }
            ),
        )

    async def async_step_polling(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="", data={**self.config_entry.options, **user_input}
            )
        return self.async_show_form(
            step_id="polling",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                    ),
                }
            ),
        )

    async def async_step_status_limits(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        defaults = {**LIMIT_DEFAULTS, **self.config_entry.options}
        errors: dict[str, str] = {}
        if user_input is not None:
            # Omitted optional bias limits clear a previously configured range.
            limits = {**LIMIT_DEFAULTS, **user_input}
            errors = validate_limits(limits)
            if not errors:
                return self.async_create_entry(
                    title="", data={**self.config_entry.options, **limits}
                )
            defaults.update(limits)
        fields: dict[Any, Any] = {}
        for key, default in LIMIT_DEFAULTS.items():
            measurement = key.rsplit("_", 1)[0]
            unit = (
                "dB"
                if key == "rx_power_warning_margin"
                else MEASUREMENT_UNITS.get(measurement, "°C")
            )
            if default is None:
                marker = vol.Optional(key)
                if defaults[key] is not None:
                    marker = vol.Optional(key, description={"suggested_value": defaults[key]})
                validator = vol.Any(
                    None,
                    NumberSelector(
                        NumberSelectorConfig(
                            mode=NumberSelectorMode.BOX, step="any", unit_of_measurement=unit
                        )
                    ),
                )
            else:
                marker = vol.Required(key, default=defaults[key])
                validator = NumberSelector(
                    NumberSelectorConfig(
                        mode=NumberSelectorMode.BOX, step="any", unit_of_measurement=unit
                    )
                )
            fields[marker] = validator
        return self.async_show_form(
            step_id="status_limits", data_schema=vol.Schema(fields), errors=errors
        )

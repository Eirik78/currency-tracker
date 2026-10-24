"""Config and options flow for Currency Tracker."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import RatesUnavailable, async_fetch_rates
from .const import (
    CONF_AMOUNT,
    CONF_FIRST_HOUR,
    CONF_FROM,
    CONF_LAST_HOUR,
    CONF_MARKUP,
    CONF_TO,
    CURRENCIES,
    DEFAULT_AMOUNT,
    DEFAULT_FIRST_HOUR,
    DEFAULT_FROM,
    DEFAULT_LAST_HOUR,
    DEFAULT_MARKUP,
    DEFAULT_TO,
    DOMAIN,
)

_CURRENCY = SelectSelector(
    SelectSelectorConfig(
        options=[SelectOptionDict(value=c, label=f"{c} – {n}") for c, n in CURRENCIES.items()],
        mode=SelectSelectorMode.DROPDOWN,
    )
)
_HOUR = NumberSelector(NumberSelectorConfig(min=0, max=23, step=1, mode=NumberSelectorMode.BOX))

SETTINGS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_AMOUNT, default=DEFAULT_AMOUNT): NumberSelector(
            NumberSelectorConfig(min=0.01, step="any", mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_MARKUP, default=DEFAULT_MARKUP): NumberSelector(
            NumberSelectorConfig(
                min=0, max=100, step=0.01, unit_of_measurement="%", mode=NumberSelectorMode.BOX
            )
        ),
        vol.Required(CONF_FIRST_HOUR, default=DEFAULT_FIRST_HOUR): _HOUR,
        vol.Required(CONF_LAST_HOUR, default=DEFAULT_LAST_HOUR): _HOUR,
    }
)
USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_FROM, default=DEFAULT_FROM): _CURRENCY,
        vol.Required(CONF_TO, default=DEFAULT_TO): _CURRENCY,
    }
).extend(SETTINGS_SCHEMA.schema)


def _settings(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_AMOUNT: float(user_input[CONF_AMOUNT]),
        CONF_MARKUP: float(user_input[CONF_MARKUP]),
        CONF_FIRST_HOUR: int(user_input[CONF_FIRST_HOUR]),
        CONF_LAST_HOUR: int(user_input[CONF_LAST_HOUR]),
    }


def _hours_error(user_input: dict[str, Any]) -> dict[str, str]:
    if int(user_input[CONF_LAST_HOUR]) < int(user_input[CONF_FIRST_HOUR]):
        return {CONF_LAST_HOUR: "last_before_first"}
    return {}


class CurrencyTrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """One entry per currency pair."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            from_cur, to_cur = user_input[CONF_FROM], user_input[CONF_TO]
            errors = _hours_error(user_input)
            if from_cur == to_cur:
                errors[CONF_TO] = "same_currency"
            if not errors:
                await self.async_set_unique_id(f"{from_cur}_{to_cur}")
                self._abort_if_unique_id_configured()
                try:
                    table = await async_fetch_rates(async_get_clientsession(self.hass), from_cur)
                except RatesUnavailable:
                    errors["base"] = "cannot_connect"
                else:
                    if to_cur not in table.rates:
                        errors[CONF_TO] = "unsupported_pair"
                    else:
                        return self.async_create_entry(
                            title=f"{from_cur} → {to_cur}",
                            data={CONF_FROM: from_cur, CONF_TO: to_cur},
                            options=_settings(user_input),
                        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> CurrencyTrackerOptionsFlow:
        return CurrencyTrackerOptionsFlow()


class CurrencyTrackerOptionsFlow(OptionsFlow):
    """Amount, markup and update hours. The pair itself is fixed per entry."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _hours_error(user_input)
            if not errors:
                # keep anything else stored in options; the update listener applies it
                return self.async_create_entry(data={**self.config_entry.options, **_settings(user_input)})
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                SETTINGS_SCHEMA, user_input or self.config_entry.options
            ),
            errors=errors,
        )

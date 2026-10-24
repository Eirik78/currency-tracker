"""Coordinator holding the latest rate table for one conversion."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RateCache, RatesUnavailable, RateTable
from .const import (
    CONF_AMOUNT,
    CONF_FIRST_HOUR,
    CONF_FROM,
    CONF_HISTORY_YEARS,
    CONF_LAST_HOUR,
    CONF_MARKUP,
    CONF_TO,
    DEFAULT_AMOUNT,
    DEFAULT_FIRST_HOUR,
    DEFAULT_HISTORY_YEARS,
    DEFAULT_LAST_HOUR,
    DEFAULT_MARKUP,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

type CurrencyConfigEntry = ConfigEntry[CurrencyCoordinator]


@dataclass(frozen=True)
class Settings:
    """User-adjustable values, read from the entry's options."""

    amount: float
    markup: float
    first_hour: int
    last_hour: int
    history_years: int

    @classmethod
    def from_entry(cls, entry: ConfigEntry) -> Settings:
        o = entry.options
        return cls(
            float(o.get(CONF_AMOUNT, DEFAULT_AMOUNT)),
            float(o.get(CONF_MARKUP, DEFAULT_MARKUP)),
            int(o.get(CONF_FIRST_HOUR, DEFAULT_FIRST_HOUR)),
            int(o.get(CONF_LAST_HOUR, DEFAULT_LAST_HOUR)),
            int(o.get(CONF_HISTORY_YEARS, DEFAULT_HISTORY_YEARS)),
        )

    @property
    def factor(self) -> float:
        """Multiplier from market rate to the shown converted value."""
        return self.amount * (1 + self.markup / 100)


class CurrencyCoordinator(DataUpdateCoordinator[RateTable]):
    """Holds the rate table; amount and markup are applied when entities read it."""

    config_entry: CurrencyConfigEntry

    def __init__(self, hass: HomeAssistant, entry: CurrencyConfigEntry, cache: RateCache) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=None,
            always_update=False,
        )
        self.from_cur: str = entry.data[CONF_FROM]
        self.to_cur: str = entry.data[CONF_TO]
        self.settings = Settings.from_entry(entry)
        self._cache = cache
        self._force = False

    async def async_force_refresh(self) -> None:
        """Fetch new rates now, bypassing the shared cache."""
        self._force = True
        try:
            await self.async_refresh()
        finally:
            self._force = False

    async def _async_update_data(self) -> RateTable:
        try:
            table = await self._cache.async_get(self.from_cur, force=self._force)
        except RatesUnavailable as err:
            raise UpdateFailed(str(err)) from err
        if self.to_cur not in table.rates:
            raise UpdateFailed(f"{table.source} has no rate for {self.to_cur}")
        return table

    @property
    def market_rate(self) -> float | None:
        """1 from_cur in to_cur, without markup."""
        return self.data.rates.get(self.to_cur) if self.data else None

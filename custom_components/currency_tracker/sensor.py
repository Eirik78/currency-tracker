"""Market rate and converted value sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import RestoreSensor, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import AVERAGE_DAYS
from .coordinator import CurrencyConfigEntry, CurrencyCoordinator
from .entity import CurrencyEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CurrencyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors for one conversion."""
    coordinator = entry.runtime_data
    async_add_entities(
        [MarketRateSensor(coordinator), ConvertedSensor(coordinator)]
        + [AverageSensor(coordinator, days) for days in AVERAGE_DAYS]
    )


class _RateSensor(CurrencyEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: CurrencyCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._attr_native_unit_of_measurement = coordinator.to_cur


class MarketRateSensor(_RateSensor):
    """1 unit of the From currency in the To currency, without markup."""

    _attr_suggested_display_precision = 4

    def __init__(self, coordinator: CurrencyCoordinator) -> None:
        super().__init__(coordinator, "market_rate")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.market_rate


class ConvertedSensor(_RateSensor):
    """Amount × market rate × (1 + markup %). Recomputed at once on changes."""

    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: CurrencyCoordinator) -> None:
        super().__init__(coordinator, "converted")

    @property
    def native_value(self) -> float | None:
        rate = self.coordinator.market_rate
        return None if rate is None else rate * self.coordinator.settings.factor

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.coordinator
        rate = c.market_rate
        return {
            "amount": c.settings.amount,
            "markup_percent": c.settings.markup,
            "market_rate": rate,
            "rate_with_markup": None if rate is None else rate * (1 + c.settings.markup / 100),
            "rates_published": c.data.updated.isoformat() if c.data and c.data.updated else None,
            "source": c.data.source if c.data else None,
        }


class AverageSensor(_RateSensor, RestoreSensor):
    """Average of Converted's daily means; restored on restart, updated hourly."""

    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: CurrencyCoordinator, days: int) -> None:
        super().__init__(coordinator, f"average_{days}")
        self._days = days

    @property
    def native_value(self) -> float | None:
        return self.coordinator.averages.get(self._days)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        averages = self.coordinator.averages
        if averages.get(self._days) is None and (last := await self.async_get_last_sensor_data()):
            if isinstance(last.native_value, (int, float)):
                averages[self._days] = float(last.native_value)

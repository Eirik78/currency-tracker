"""Amount and markup: change them and the converted value updates at once."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_AMOUNT, CONF_MARKUP
from .coordinator import CurrencyConfigEntry, CurrencyCoordinator
from .entity import CurrencyEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CurrencyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the adjustable numbers for one conversion."""
    coordinator = entry.runtime_data
    async_add_entities([AmountNumber(coordinator), MarkupNumber(coordinator)])


class _OptionNumber(CurrencyEntity, NumberEntity):
    """Stored in the entry's options, so it survives restarts."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _option: str

    async def async_set_native_value(self, value: float) -> None:
        entry = self.coordinator.config_entry
        # the entry's update listener applies it to the sensors immediately
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, self._option: value}
        )


class AmountNumber(_OptionNumber):
    """Amount of the From currency to convert."""

    _option = CONF_AMOUNT
    _attr_native_min_value = 0.01
    _attr_native_max_value = 1_000_000_000
    _attr_native_step = 0.01

    def __init__(self, coordinator: CurrencyCoordinator) -> None:
        super().__init__(coordinator, "amount")
        self._attr_native_unit_of_measurement = coordinator.from_cur

    @property
    def native_value(self) -> float:
        return self.coordinator.settings.amount


class MarkupNumber(_OptionNumber):
    """Percentage added on top of the market rate."""

    _option = CONF_MARKUP
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 0.01
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: CurrencyCoordinator) -> None:
        super().__init__(coordinator, "markup")

    @property
    def native_value(self) -> float:
        return self.coordinator.settings.markup

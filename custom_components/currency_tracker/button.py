"""Update now button."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import CurrencyConfigEntry, CurrencyCoordinator
from .entity import CurrencyEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CurrencyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Update now button."""
    async_add_entities([UpdateNowButton(entry.runtime_data)])


class UpdateNowButton(CurrencyEntity, ButtonEntity):
    """Fetch new rates outside the schedule."""

    def __init__(self, coordinator: CurrencyCoordinator) -> None:
        super().__init__(coordinator, "update_now")

    async def async_press(self) -> None:
        await self.coordinator.async_force_refresh()

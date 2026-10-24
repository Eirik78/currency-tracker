"""Base entity for Currency Tracker."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import CurrencyCoordinator


class CurrencyEntity(CoordinatorEntity[CurrencyCoordinator]):
    """One device per conversion; entity names come from translations."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: CurrencyCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"{coordinator.from_cur} {coordinator.to_cur}",
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Currency Tracker",
            model=f"{coordinator.from_cur} → {coordinator.to_cur}",
        )

    @property
    def available(self) -> bool:
        """Keep the last rates on a failed fetch; they change only about daily."""
        return self.coordinator.data is not None

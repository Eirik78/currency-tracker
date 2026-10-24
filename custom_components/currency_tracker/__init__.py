"""Currency Tracker: live exchange rates with markup and Norges Bank history."""

from __future__ import annotations

from datetime import datetime

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change

from . import history
from .api import RateCache
from .const import DOMAIN
from .coordinator import CurrencyConfigEntry, CurrencyCoordinator, Settings

PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: CurrencyConfigEntry) -> bool:
    """Set up one conversion."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = RateCache(async_get_clientsession(hass))
    coordinator = CurrencyCoordinator(hass, entry, hass.data[DOMAIN])
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # fetch at minute 0 of every hour from first_hour to last_hour (HA's local time)
    s = coordinator.settings

    async def _scheduled(_now: datetime) -> None:
        await coordinator.async_refresh()

    entry.async_on_unload(
        async_track_time_change(
            hass, _scheduled, hour=list(range(s.first_hour, s.last_hour + 1)), minute=0, second=0
        )
    )
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # no-op once the configured years are imported
    entry.async_create_background_task(
        hass, history.async_import_history(hass, entry), f"{DOMAIN} history import"
    )
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: CurrencyConfigEntry) -> None:
    """Apply changed amount/markup at once; reload only for a new schedule."""
    coordinator = entry.runtime_data
    old, new = coordinator.settings, Settings.from_entry(entry)
    if old == new:
        return  # e.g. only entry.data changed (history flag)
    # not tied to the entry: these must survive the reload below
    if old.factor != new.factor:
        hass.async_create_background_task(
            history.async_rewrite_today(hass, entry), f"{DOMAIN} rewrite today"
        )
    if new.history_years > old.history_years:
        hass.async_create_background_task(
            history.async_import_history(hass, entry), f"{DOMAIN} history import"
        )
    if (old.first_hour, old.last_hour) != (new.first_hour, new.last_hour):
        hass.config_entries.async_schedule_reload(entry.entry_id)
        return
    coordinator.settings = new
    coordinator.async_update_listeners()


async def async_unload_entry(hass: HomeAssistant, entry: CurrencyConfigEntry) -> bool:
    """Unload a conversion."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

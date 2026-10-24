"""Long-term statistics: Norges Bank backfill and today's markup rewrite."""

from __future__ import annotations

from bisect import bisect_right
from datetime import UTC, date, datetime, time, timedelta, tzinfo
import logging

import aiohttp

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import async_fetch_history
from .const import CONF_FROM, CONF_TO, DATA_HISTORY_IMPORTED, DOMAIN, HISTORY_DAYS
from .coordinator import CurrencyConfigEntry, Settings

_LOGGER = logging.getLogger(__name__)


def _entity_ids(hass: HomeAssistant, entry: CurrencyConfigEntry) -> tuple[str | None, str | None]:
    reg = er.async_get(hass)
    return (
        reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_market_rate"),
        reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_converted"),
    )


def _metadata(entity_id: str, unit: str) -> dict:
    return {
        "source": "recorder",
        "statistic_id": entity_id,
        "name": None,
        "unit_of_measurement": unit,
        "unit_class": None,
        "mean_type": StatisticMeanType.ARITHMETIC,
        "has_sum": False,
    }


def _row(start: datetime, value: float) -> dict:
    return {"start": start, "mean": value, "min": value, "max": value}


def hourly_rates(
    daily: dict[date, float], first_day: date, cutoff: datetime, tz: tzinfo
) -> list[tuple[datetime, float]]:
    """Hourly rows up to cutoff; each hour uses the latest rate on or before its local date."""
    days = sorted(daily)
    out: list[tuple[datetime, float]] = []
    hour = datetime.combine(first_day, time(), tz).astimezone(UTC)
    while hour < cutoff:
        i = bisect_right(days, hour.astimezone(tz).date()) - 1
        if i >= 0:
            out.append((hour, daily[days[i]]))
        hour += timedelta(hours=1)
    return out


async def async_import_history(hass: HomeAssistant, entry: CurrencyConfigEntry) -> None:
    """Import two years of Norges Bank rates, up to when the entry was created."""
    if "recorder" not in hass.config.components:
        return
    rate_id, conv_id = _entity_ids(hass, entry)
    if not rate_id or not conv_id:
        return
    from_cur, to_cur = entry.data[CONF_FROM], entry.data[CONF_TO]

    # the recorder's own statistics start here
    cutoff = entry.created_at.replace(minute=0, second=0, microsecond=0)
    last_day = dt_util.as_local(cutoff).date()
    first_day = last_day - timedelta(days=HISTORY_DAYS)
    try:
        # a week extra so a weekend at the start has a rate to carry
        daily = await async_fetch_history(
            async_get_clientsession(hass), from_cur, to_cur, first_day - timedelta(days=7), last_day
        )
    except (aiohttp.ClientError, TimeoutError, KeyError, ValueError) as err:
        _LOGGER.warning("Norges Bank history for %s→%s not imported, will retry at next start: %s",
                        from_cur, to_cur, err)
        return

    if daily:
        factor = Settings.from_entry(entry).factor
        hourly = hourly_rates(daily, first_day, cutoff, dt_util.get_default_time_zone())
        async_import_statistics(
            hass, _metadata(rate_id, to_cur), [_row(h, v) for h, v in hourly]
        )
        async_import_statistics(
            hass, _metadata(conv_id, to_cur), [_row(h, v * factor) for h, v in hourly]
        )
        _LOGGER.info("Imported %d hours of Norges Bank history for %s→%s",
                     len(hourly), from_cur, to_cur)
    else:
        _LOGGER.info("Norges Bank publishes no rates for %s→%s; no history imported",
                     from_cur, to_cur)

    hass.config_entries.async_update_entry(entry, data={**entry.data, DATA_HISTORY_IMPORTED: True})


async def async_rewrite_today(hass: HomeAssistant, entry: CurrencyConfigEntry) -> None:
    """Recompute today's converted statistics with the current amount and markup."""
    if "recorder" not in hass.config.components:
        return
    rate_id, conv_id = _entity_ids(hass, entry)
    if not rate_id or not conv_id:
        return
    start = dt_util.start_of_local_day()
    end = dt_util.now().replace(minute=0, second=0, microsecond=0)  # completed hours only
    if end <= start:
        return
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, start, end, {rate_id}, "hour", None, {"mean", "min", "max"}
    )
    factor = Settings.from_entry(entry).factor
    rows = [
        {"start": dt_util.utc_from_timestamp(r["start"])}
        | {k: (r.get(k) or r["mean"]) * factor for k in ("mean", "min", "max")}
        for r in stats.get(rate_id, [])
        if r.get("mean") is not None
    ]
    if rows:
        async_import_statistics(hass, _metadata(conv_id, entry.data[CONF_TO]), rows)

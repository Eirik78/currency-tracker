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
from .const import (
    AVERAGE_DAYS,
    CONF_FROM,
    CONF_TO,
    DATA_HISTORY_FROM,
    DATA_HISTORY_IMPORTED,
    DOMAIN,
)
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


def _years_back(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February
        return day.replace(year=day.year - years, day=28)


def import_range(
    created: datetime, years: int, data: dict, tz: tzinfo
) -> tuple[date, datetime] | None:
    """(first day, end) still to import, or None when nothing is missing.

    The recorder's own statistics start when the entry was created; after an
    earlier import, the end is the first day already imported.
    """
    created = created.replace(minute=0, second=0, microsecond=0)
    last_day = created.astimezone(tz).date()
    first_day = _years_back(last_day, years)
    if value := data.get(DATA_HISTORY_FROM):
        done: date | None = date.fromisoformat(value)
    elif data.get(DATA_HISTORY_IMPORTED):  # imported by 1.0.0
        done = last_day - timedelta(days=730)
    else:
        done = None
    if done is not None and first_day >= done:
        return None
    end = created if done is None else datetime.combine(done, time(), tz).astimezone(UTC)
    return first_day, end


async def async_import_history(hass: HomeAssistant, entry: CurrencyConfigEntry) -> bool:
    """Import Norges Bank rates back to the configured number of years.

    Only days not imported before are added, so existing days keep their values.
    Returns True when statistics were added (and written to the database).
    """
    if "recorder" not in hass.config.components:
        return False
    rate_id, conv_id = _entity_ids(hass, entry)
    if not rate_id or not conv_id:
        return False
    from_cur, to_cur = entry.data[CONF_FROM], entry.data[CONF_TO]
    settings = Settings.from_entry(entry)
    tz = dt_util.get_default_time_zone()

    if not (todo := import_range(entry.created_at, settings.history_years, entry.data, tz)):
        return False
    first_day, cutoff = todo
    try:
        # a week extra so a weekend at the start has a rate to carry
        daily = await async_fetch_history(
            async_get_clientsession(hass), from_cur, to_cur,
            first_day - timedelta(days=7), cutoff.astimezone(tz).date(),
        )
    except (aiohttp.ClientError, TimeoutError, KeyError, ValueError) as err:
        _LOGGER.warning("Norges Bank history for %s→%s not imported, will retry at next start: %s",
                        from_cur, to_cur, err)
        return False

    if daily:
        hourly = hourly_rates(daily, first_day, cutoff, tz)
        async_import_statistics(
            hass, _metadata(rate_id, to_cur), [_row(h, v) for h, v in hourly]
        )
        async_import_statistics(
            hass, _metadata(conv_id, to_cur), [_row(h, v * settings.factor) for h, v in hourly]
        )
        _LOGGER.info("Imported Norges Bank history for %s→%s from %s", from_cur, to_cur, first_day)
        await get_instance(hass).async_block_till_done()  # written before averages read it
    else:
        _LOGGER.info("Norges Bank publishes no rates for %s→%s; no history imported",
                     from_cur, to_cur)

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, DATA_HISTORY_FROM: first_day.isoformat()}
    )
    return bool(daily)


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


def daily_average(rows: list, since: float) -> float | None:
    """Average of the daily means that start at or after since (timestamp)."""
    means = [r["mean"] for r in rows if r["start"] >= since and r.get("mean") is not None]
    return sum(means) / len(means) if means else None


async def async_update_averages(hass: HomeAssistant, entry: CurrencyConfigEntry) -> None:
    """Update the 30 and 365 day averages of Converted from long-term statistics."""
    if "recorder" not in hass.config.components:
        return
    _, conv_id = _entity_ids(hass, entry)
    if not conv_id:
        return
    now = dt_util.utcnow()
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass, now - timedelta(days=max(AVERAGE_DAYS)), None, {conv_id}, "day", None, {"mean"},
    )
    rows = stats.get(conv_id, [])
    coordinator = entry.runtime_data
    for days in AVERAGE_DAYS:
        coordinator.averages[days] = daily_average(rows, (now - timedelta(days=days)).timestamp())
    coordinator.async_update_listeners()


async def async_load(hass: HomeAssistant, entry: CurrencyConfigEntry) -> None:
    """Import missing history, then calculate averages that are new or have no value."""
    imported = await async_import_history(hass, entry)
    averages = entry.runtime_data.averages
    if imported or any(averages.get(days) is None for days in AVERAGE_DAYS):
        await async_update_averages(hass, entry)

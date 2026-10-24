"""Exchange rate sources: live rates and Norges Bank history."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime
import logging
import time

import aiohttp

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=20)
CACHE_SECONDS = 300  # entries on the same base currency share one fetch


class RatesUnavailable(Exception):
    """Raised when no source could deliver rates."""


@dataclass(frozen=True)
class RateTable:
    """All rates for one base currency (1 base = rates[code] code)."""

    base: str
    rates: dict[str, float]
    updated: datetime | None  # when the source last changed its rates
    source: str


async def _er_api(session: aiohttp.ClientSession, base: str) -> RateTable:
    async with session.get(
        f"https://open.er-api.com/v6/latest/{base}", timeout=TIMEOUT
    ) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    if data.get("result") != "success" or not data.get("rates"):
        raise RatesUnavailable(f"open.er-api: {data.get('error-type', 'no rates')}")
    ts = data.get("time_last_update_unix")
    return RateTable(
        base,
        {k.upper(): float(v) for k, v in data["rates"].items()},
        datetime.fromtimestamp(ts, UTC) if ts else None,
        "open.er-api.com",
    )


async def _currency_api(session: aiohttp.ClientSession, base: str, url: str) -> RateTable:
    b = base.lower()
    async with session.get(url.format(base=b), timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    rates = data.get(b)
    if not rates:
        raise RatesUnavailable("currency-api: no rates")
    updated = None
    if data.get("date"):
        updated = datetime.fromisoformat(data["date"]).replace(tzinfo=UTC)
    return RateTable(
        base,
        {k.upper(): float(v) for k, v in rates.items() if isinstance(v, (int, float))},
        updated,
        "currency-api (fawazahmed0)",
    )


_FALLBACKS = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{base}.json",
    "https://latest.currency-api.pages.dev/v1/currencies/{base}.json",
)


async def async_fetch_rates(session: aiohttp.ClientSession, base: str) -> RateTable:
    """Fetch live rates for base, trying open.er-api first, then the fallbacks."""
    try:
        return await _er_api(session, base)
    except (aiohttp.ClientError, TimeoutError, ValueError, RatesUnavailable) as err:
        _LOGGER.debug("open.er-api failed for %s: %s", base, err)
    for url in _FALLBACKS:
        try:
            return await _currency_api(session, base, url)
        except (aiohttp.ClientError, TimeoutError, ValueError, RatesUnavailable) as err:
            _LOGGER.debug("Fallback %s failed for %s: %s", url, base, err)
    raise RatesUnavailable(f"No source could deliver rates for {base}")


class RateCache:
    """Shared, short-lived cache so several conversions on one base fetch once."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._tables: dict[str, tuple[float, RateTable]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def async_get(self, base: str, force: bool = False) -> RateTable:
        async with self._locks.setdefault(base, asyncio.Lock()):
            cached = self._tables.get(base)
            if cached and not force and time.monotonic() - cached[0] < CACHE_SECONDS:
                return cached[1]
            table = await async_fetch_rates(self._session, base)
            self._tables[base] = (time.monotonic(), table)
            return table


# ── Norges Bank history ────────────────────────────────────────────────────────
NB_URL = "https://data.norges-bank.no/api/data/EXR/B.{codes}.NOK.SP"


async def async_fetch_history(
    session: aiohttp.ClientSession, from_cur: str, to_cur: str, start: date, end: date
) -> dict[date, float]:
    """Daily from→to rates (business days), crossed via NOK; {} if not published."""
    codes = sorted({c for c in (from_cur, to_cur) if c != "NOK"})
    if not codes:
        return {}
    async with session.get(
        NB_URL.format(codes="+".join(codes)),
        params={
            "format": "sdmx-json",
            "startPeriod": start.isoformat(),
            "endPeriod": end.isoformat(),
            "locale": "en",
        },
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        if resp.status == 404:  # no series for this currency
            return {}
        resp.raise_for_status()
        payload = await resp.json(content_type=None)

    nok_per = _parse_sdmx(payload)  # {code: {date: NOK per 1 unit}}
    nok_per["NOK"] = None  # marker: always 1
    if any(c not in nok_per for c in (from_cur, to_cur)):
        return {}

    def val(code: str, day: date) -> float | None:
        return 1.0 if code == "NOK" else nok_per[code].get(day)

    days = set().union(*(nok_per[c] for c in codes))
    out: dict[date, float] = {}
    for day in sorted(days):
        f, t = val(from_cur, day), val(to_cur, day)
        if f is not None and t:
            out[day] = f / t
    return out


def _parse_sdmx(payload: dict) -> dict[str, dict[date, float]]:
    data = payload["data"]
    structure = data["structure"]
    series_dims = structure["dimensions"]["series"]
    base_pos = next(i for i, d in enumerate(series_dims) if d["id"] == "BASE_CUR")
    base_ids = [v["id"] for v in series_dims[base_pos]["values"]]
    periods = [v["id"] for v in structure["dimensions"]["observation"][0]["values"]]
    attrs = structure["attributes"]["series"]
    mult_pos = next((i for i, a in enumerate(attrs) if a["id"] == "UNIT_MULT"), None)

    result: dict[str, dict[date, float]] = {}
    for key, series in data["dataSets"][0]["series"].items():
        code = base_ids[int(key.split(":")[base_pos])]
        mult = 0
        if mult_pos is not None:
            idx = series["attributes"][mult_pos]
            if idx is not None:
                mult = int(attrs[mult_pos]["values"][idx]["id"])
        scale = 10**mult  # e.g. SEK and JPY are quoted per 100
        result[code] = {
            date.fromisoformat(periods[int(i)]): float(obs[0]) / scale
            for i, obs in series["observations"].items()
            if obs and obs[0] not in (None, "", "NaN")
        }
    return result

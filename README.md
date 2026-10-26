# Currency Tracker

Home Assistant integration for live exchange rates with adjustable amount and markup,
plus two years of history from Norges Bank.

## Entities (per currency pair)

- **Converted** – amount × market rate × (1 + markup %)
- **Market rate** – rate without markup
- **Average 30 days**, **Average 365 days** – average of Converted's daily values
- **Amount**, **Markup** – changes apply immediately, no new fetch needed
- **Update now** – fetch rates outside the schedule

Add one entry per pair. Amount, markup and update hours can be changed under **Configure**.

## Updates

At startup and every hour from 10:00 to 18:00 (adjustable, Home Assistant's time zone).
Averages update at :15 in the same hours.
Source: [open.er-api.com](https://www.exchangerate-api.com), with
[currency-api](https://github.com/fawazahmed0/exchange-api) as fallback.

## History

After setup, daily rates from [Norges Bank](https://www.norges-bank.no/en/topics/Statistics/open-data/)
are imported into long-term statistics for both sensors: 2 years by default, up to 25
(**History (years)** under Configure). Raising it imports only the missing older years;
their Converted values use the current amount and markup. Weekends carry the previous
business day's rate. Pairs without NOK are calculated through NOK; currencies Norges
Bank doesn't publish get no history.

Changing amount or markup recalculates today's statistics; older days are kept.

The full history shows in a **Statistics graph** card. The History page only uses it for
periods older than 10 days.

## Install

**HACS:** HACS → ⋮ → Custom repositories → add `https://github.com/Eirik78/currency-tracker`
as type *Integration* → install → restart Home Assistant.

**Manual:** copy `custom_components/currency_tracker` to `config/custom_components/` and restart.

Then: Settings → Devices & services → Add integration → **Currency Tracker**.

## Attribution

Rates by [Exchange Rate API](https://www.exchangerate-api.com). History: Norges Bank (NLOD 2.0).

## Releasing

Bump `version` in `manifest.json` and add a matching `## x.y.z` section to `CHANGELOG.md`.
On push, a GitHub release is created and HACS offers it as an update with those notes.

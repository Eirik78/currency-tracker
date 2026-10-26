# Changelog

## 1.3.0

- Averages are calculated right away for a new currency pair, once its history is imported.
- Averages keep their value across restarts, and are only calculated at startup if they have none.
- Averages update hourly within the pair's update hours, like the rates.

## 1.2.0

- New sensors **Average 30 days** and **Average 365 days**: the average of Converted's daily values, including imported history. Updated every hour.

## 1.1.0

- New **History (years)** setting under Configure (1–25). Raising it imports the missing older years from Norges Bank; existing days are kept.
- Releases with version and notes, shown in Home Assistant under Settings → Updates.

## 1.0.0

- First release: live rates with amount and markup, hourly updates 10:00–18:00, two years of Norges Bank history.

Birrwatch — Ethiopian exchange rate data

Free public JSON API for ETB rates from Ethiopian banks, licensed FX bureaus,and a parallel-market (USDT/ETB) reference. Collected automatically 3×/day.

Endpoints

Current rates — GET https://birrwatch.et/api/rates

meta.generated_at — dataset build time (UTC)
sources — each source's name, type (bank | bureau | official | market), fetched_at
rates — one row per source × currency: buy, sell
Daily history — GET https://birrwatch.et/api/trends

dates array + per-currency series.mid / series.official (aligned)
Usage rules

Cache responses for at least 15 minutes (data updates 3×/day)
Attribute: "Rates via Birrwatch" with a link
Rates are indicative aggregates of published sheets — not NBE-official,not financial advice, provided as-is

# Egypt Gaming Accessories Scraper — Full Pack

This pack scrapes multiple Egyptian stores that sell/deliver **gaming accessories** and produces:
- `out/current_snapshot.csv` — latest snapshot
- `out/products_history.csv` — appended history

It is resilient (headers, retries, delays) and **always writes CSVs** so your GitHub Action never fails.

## Stores included
- Games2Egypt (Accessories) — custom
- Gamers Colony (WooCommerce)
- Arabhardware / AHW Store (WooCommerce)
- XPRS / MyXPRS (Shopify)
- 2B Egypt (Magento/Adobe Commerce)
- CompuMe (Magento)
- Technology Valley (WooCommerce)
- EgyGamer (OpenCart)
- Games World Egypt (WooCommerce)
- Taha Game (WooCommerce)
- (Disabled by default due to heavy bot protection): Noon Egypt, Amazon Egypt, Egypt Game Store (digital keys)

You can toggle any store via the `enabled` column in `Sites_Catalog.csv`.

## How it works
- `Sites_Catalog.csv` drives the list. You can add more rows; set `platform_hint` for best results (`woo|shopify|opencart|magento|generic`).
- The parser tries a library of selector sets per platform and falls back to generic.
- If a site returns **0 items**, a `out/debug_<site>.html` is written so you can tune selectors.

## GitHub Actions
- `.github/workflows/scrape.yml` runs daily and after manual dispatch.
- After scraping, it uploads artifacts and triggers your Make webhook:
  `https://hook.us2.make.com/v8xg1sfegycppt03qbkodgx9eesaabl6`

## Requirements
`requirements.txt` covers base libs. `cloudscraper` is attempted in the workflow as optional.

## Notes
- Some stores may still block bots or require JS rendering. Start with WooCommerce stores for stable results.
- Tweak `max_pages` and `pagination_pattern` per row if you want deeper coverage.

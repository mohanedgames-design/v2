# Scraper + Make Webhook Fix Pack

## What's Included
1. scrape.py - Updated scraper with headers, cloudscraper, delays, and retry logic.
2. requirements.txt - Dependencies list.
3. .github/workflows/scrape.yml - Fixed indentation, added webhook POST.
4. Sites_Catalog.csv - Starter catalog for sites.
5. README.md - This file.

## Instructions
1. Replace existing files in your repo with these.
2. Commit and push.
3. In your Make scenario:
   - Ensure the **Webhook** module is the first trigger.
   - Turn the scenario **ON**.
4. Copy the webhook URL into `scrape.yml`.
5. Next GitHub run will POST to Make, triggering automation.


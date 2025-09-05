#!/usr/bin/env python3
import os, re, sys, time
import urllib.parse as up
from datetime import datetime, timezone
import requests
import pandas as pd
from bs4 import BeautifulSoup

SITES_CSV = os.environ.get("SITES_CSV_PATH", "Sites_Catalog.csv")
OUT_DIR = os.environ.get("OUT_DIR", "out")
HISTORY_CSV = os.path.join(OUT_DIR, "products_history.csv")
SNAPSHOT_CSV = os.path.join(OUT_DIR, "current_snapshot.csv")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}

def abs_url(base, url):
    try:
        return up.urljoin(base, url)
    except Exception:
        return url

def clean_text(s):
    return re.sub(r"\s+", " ", (s or "").strip())

def parse_price(raw, currency_hint="EGP|ج.م|LE|جنيه"):
    if raw is None:
        return None, None, ""
    raw_text = clean_text(raw)
    currency_match = re.search(currency_hint, raw_text, flags=re.I)
    currency = currency_match.group(0) if currency_match else ""
    num_match = re.search(r"(\d[\d,.\s]*)", raw_text)
    val = None
    if num_match:
        num = num_match.group(1).replace(",", "").replace(" ", "")
        try:
            val = float(num)
        except:
            pass
    return val, currency, raw_text

def pick_attr(el, selector, base_url, explicit_attr=None):
    # CSS select; supports '@href' to read attribute
    if not selector:
        return None
    attr = explicit_attr
    sel = selector
    if "@href" in selector:
        sel, attr = selector.split("@", 1)
    target = el.select_one(sel) if el else None
    if not target:
        return None
    if attr:
        if attr == "href":
            return abs_url(base_url, target.get(attr))
        return target.get(attr)
    return target.get_text()

def http_get(url, headers, retries=3, backoff=2):
    for i in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=45)
            if r.status_code == 200 and r.text:
                return r
            else:
                print(f"[WARN] GET {url} -> status={r.status_code}", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] GET {url} failed attempt {i+1}: {e}", file=sys.stderr)
        time.sleep(backoff * (i+1))
    return None

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    sites = pd.read_csv(SITES_CSV)
    history_rows = []

    for _, row in sites.iterrows():
        site_name = str(row.get("site_name", ""))
        url = str(row.get("url", ""))
        list_selector = str(row.get("list_selector", ""))
        name_selector = str(row.get("name_selector", ""))
        price_selector = str(row.get("price_selector", ""))
        status_selector = str(row.get("status_selector", ""))
        soldout_regex = str(row.get("status_soldout_text", "out of stock|sold out|غير متوفر|نفد|غير متاح"))
        price_attribute = str(row.get("price_attribute", ""))
        currency_hint = str(row.get("currency_hint", "EGP|ج.م|LE|جنيه"))
        sku_selector = str(row.get("sku_selector", ""))
        product_url_selector = str(row.get("product_url_selector", "a@href"))

        print(f"[INFO] Scraping {site_name} - {url}")
        resp = http_get(url, HEADERS, retries=3, backoff=2)
        if not resp:
            print(f"[ERROR] Skipping {site_name} (no response)", file=sys.stderr)
            continue

        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select(list_selector) if list_selector else []
        if not cards:
            safe = re.sub(r"\W+", "_", site_name)[:30]
            with open(os.path.join(OUT_DIR, f"debug_{safe}.html"), "w", encoding="utf-8") as f:
                f.write(resp.text)
            print(f"[WARN] No cards matched for {site_name}. Debug HTML saved.", file=sys.stderr)

        ts = datetime.now(timezone.utc).isoformat()
        for card in cards:
            name = clean_text(pick_attr(card, name_selector, url))
            raw_price = pick_attr(card, price_selector, url, price_attribute if price_attribute else None)
            status_text = clean_text(pick_attr(card, status_selector, url))
            sku = clean_text(pick_attr(card, sku_selector, url)) if sku_selector else ""
            product_url = pick_attr(card, product_url_selector, url) or ""

            status = "Unknown"
            if re.search(soldout_regex, status_text or "", flags=re.I):
                status = "Sold Out"
            elif raw_price and len(clean_text(raw_price)) > 0:
                status = "Available"

            price_value, currency, raw_price_text = parse_price(raw_price, currency_hint)

            history_rows.append({
                "timestamp_iso": ts,
                "site_name": site_name,
                "product_name": name,
                "sku": sku,
                "product_url": product_url,
                "status": status,
                "price_value": price_value,
                "currency": currency,
                "raw_price_text": raw_price_text,
                "source_url": url,
                "notes": ""
            })
        time.sleep(1.0)

    if history_rows:
        hist_df = pd.DataFrame(history_rows)
        if os.path.exists(HISTORY_CSV):
            hist_df.to_csv(HISTORY_CSV, mode="a", header=False, index=False, encoding="utf-8-sig")
        else:
            hist_df.to_csv(HISTORY_CSV, index=False, encoding="utf-8-sig")

        hist_all = pd.read_csv(HISTORY_CSV)
        hist_all["key"] = hist_all["site_name"].astype(str) + "|" + hist_all["product_url"].astype(str)
        latest_idx = hist_all.groupby("key")["timestamp_iso"].idxmax()
        snap = hist_all.loc[latest_idx].drop(columns=["key"]).sort_values(["site_name","product_name"])
        snap.to_csv(SNAPSHOT_CSV, index=False, encoding="utf-8-sig")
        print(f"[INFO] Wrote {len(hist_df)} rows; snapshot has {len(snap)} products.")
    else:
        print("[INFO] No rows scraped.")
        with open(SNAPSHOT_CSV, "w", encoding="utf-8") as f:
            f.write("timestamp_iso,site_name,product_name,sku,product_url,status,price_value,currency,raw_price_text,source_url,notes\n")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import os, time, re, sys
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
from bs4 import BeautifulSoup

# Prefer cloudscraper; fall back to requests if import fails
try:
    import cloudscraper
    _scraper = cloudscraper.create_scraper(browser={'browser':'chrome','platform':'windows','mobile':False})
    def http_get(url, headers, timeout=45):
        return _scraper.get(url, headers=headers, timeout=timeout)
except Exception:
    import requests
    def http_get(url, headers, timeout=45):
        return requests.get(url, headers=headers, timeout=timeout)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SITES = [
    # You can add more category URLs here
    ("Jumia Egypt", "https://www.jumia.com.eg/gaming-pc-accessories/", "article.prd", "h3.name", ".prc", "a.core"),
    ("Gamers Colony", "https://gamerscolony.net/product-category/accessories/", "ul.products li.product", ".woocommerce-loop-product__title", ".woocommerce-Price-amount", "a.woocommerce-LoopProduct-link"),
]

OUT_DIR = Path("out")
HISTORY_CSV = OUT_DIR / "products_history.csv"
SNAPSHOT_CSV = OUT_DIR / "current_snapshot.csv"
OUT_DIR.mkdir(exist_ok=True)

def clean(s): return re.sub(r"\s+", " ", (s or "").strip())

def get_html(url, retries=4, backoff=2.0):
    for i in range(retries):
        try:
            r = http_get(url, HEADERS, timeout=45)
            code = getattr(r, "status_code", 0)
            if code == 200 and getattr(r, "text", ""):
                return r.text
            print(f"[WARN] GET {url} -> status={code}", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] GET {url} failed attempt {i+1}: {e}", file=sys.stderr)
        time.sleep(backoff * (i+1))
    return None

def parse_price(text):
    if not text: return None, "", ""
    raw = clean(text)
    m = re.search(r"(\d[\d,.\s]*)", raw)
    val = None
    if m:
        num = m.group(1).replace(",", "").replace(" ", "")
        try: val = float(num)
        except: pass
    cur = ""
    mc = re.search(r"(EGP|ج\.م|LE|جنيه)", raw, re.I)
    if mc: cur = mc.group(1)
    return val, cur, raw

def scrape_once(name, url, list_sel, name_sel, price_sel, link_sel):
    html = get_html(url)
    if not html:
        print(f"[ERROR] {name}: no response for {url}", file=sys.stderr)
        return []

    soup = BeautifulSoup(html, "lxml")
    cards = soup.select(list_sel) or []
    if not cards:
        # Save debug HTML so you can inspect selectors from the artifact
        dbg = OUT_DIR / f"debug_{re.sub(r'\\W+','_',name)[:30]}.html"
        dbg.write_text(html, encoding="utf-8")
        print(f"[WARN] {name}: no products matched. Debug saved -> {dbg}", file=sys.stderr)

    rows = []
    ts = datetime.now(timezone.utc).isoformat()
    for el in cards:
        pname = clean(el.select_one(name_sel).get_text() if el.select_one(name_sel) else "")
        link_el = el.select_one(link_sel)
        plink = link_el.get("href") if link_el else ""
        price_el = el.select_one(price_sel)
        price_val, currency, raw_price = parse_price(price_el.get_text() if price_el else "")
        status = "Available" if price_val is not None else "Unknown"

        rows.append({
            "timestamp_iso": ts,
            "site_name": name,
            "product_name": pname,
            "sku": "",
            "product_url": plink,
            "status": status,
            "price_value": price_val,
            "currency": currency,
            "raw_price_text": raw_price,
            "source_url": url,
            "notes": ""
        })
    # politeness
    time.sleep(1.2)
    return rows

def main():
    all_rows = []
    for tup in SITES:
        all_rows.extend(scrape_once(*tup))

    # Always write CSVs so the workflow can continue
    if all_rows:
        df = pd.DataFrame(all_rows)
        # history (append)
        if HISTORY_CSV.exists():
            df.to_csv(HISTORY_CSV, mode="a", header=False, index=False, encoding="utf-8-sig")
        else:
            df.to_csv(HISTORY_CSV, index=False, encoding="utf-8-sig")
        # snapshot (latest by site+url)
        hist_all = pd.read_csv(HISTORY_CSV)
        hist_all["key"] = hist_all["site_name"].astype(str) + "|" + hist_all["product_url"].astype(str)
        latest_idx = hist_all.groupby("key")["timestamp_iso"].idxmax()
        snap = hist_all.loc[latest_idx].drop(columns=["key"]).sort_values(["site_name","product_name"])
        snap.to_csv(SNAPSHOT_CSV, index=False, encoding="utf-8-sig")
        print(f"[INFO] Wrote {len(df)} new rows; snapshot has {len(snap)} products.")
    else:
        # write empty scaffold so later steps don’t fail
        hdr = "timestamp_iso,site_name,product_name,sku,product_url,status,price_value,currency,raw_price_text,source_url,notes\n"
        SNAPSHOT_CSV.write_text(hdr, encoding="utf-8")
        HISTORY_CSV.write_text(hdr, encoding="utf-8")
        print("[INFO] No rows scraped; wrote empty CSVs.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Never crash the job; write empty CSVs and exit 0
        hdr = "timestamp_iso,site_name,product_name,sku,product_url,status,price_value,currency,raw_price_text,source_url,notes\n"
        OUT_DIR.mkdir(exist_ok=True)
        SNAPSHOT_CSV.write_text(hdr, encoding="utf-8")
        HISTORY_CSV.write_text(hdr, encoding="utf-8")
        print(f"[WARN] scrape.py swallowed exception: {e}", file=sys.stderr)
        sys.exit(0)

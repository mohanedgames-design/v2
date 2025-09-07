#!/usr/bin/env python3
import os, re, time, random, sys, csv
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
from bs4 import BeautifulSoup

# ----- HTTP layer: try cloudscraper if available, else requests -----
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]
def _headers():
    return {
        "User-Agent": random.choice(UA_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Cache-Control": "no-cache",
    }

def _get_http_client():
    try:
        import cloudscraper  # optional
        s = cloudscraper.create_scraper(browser={'browser':'chrome','platform':'windows','mobile':False})
        return lambda url, timeout=45: s.get(url, headers=_headers(), timeout=timeout)
    except Exception:
        import requests
        s = requests.Session()
        return lambda url, timeout=45: s.get(url, headers=_headers(), timeout=timeout)
HTTP_GET = _get_http_client()

def fetch(url, retries=4, backoff=2.0):
    for i in range(retries):
        try:
            r = HTTP_GET(url, timeout=60)
            code = getattr(r, "status_code", 0)
            if code == 200 and getattr(r, "text", ""):
                return r.text
            print(f"[WARN] GET {url} -> status={code}", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] GET {url} failed ({i+1}/{retries}): {e}", file=sys.stderr)
        time.sleep(backoff * (i+1))
    return None

# ----- Parsing helpers -----
def clean(s):
    return re.sub(r"\s+", " ", (s or "").strip())

def parse_price(text):
    if not text: 
        return None, "", ""
    raw = clean(text)
    m = re.search(r"(\d[\d,\.\s]*)", raw)
    val = None
    if m:
        num = m.group(1).replace(",", "").replace(" ", "")
        try:
            val = float(num)
        except Exception:
            val = None
    cur = ""
    mc = re.search(r"(EGP|ج\.م|LE|جنيه|E\s*G\s*P)", raw, re.I)
    if mc: cur = mc.group(1)
    return val, cur, raw

# A library of common platform selector sets (tried in order).
SELECTOR_SETS = {
    "woo": {
        "list": ["ul.products li.product", "li.product", ".products .product"],
        "name": [".woocommerce-loop-product__title", ".product-title", "h2, h3"],
        "price": [".woocommerce-Price-amount", ".price .amount", ".price"],
        "link": ["a.woocommerce-LoopProduct-link", "a.woocommerce-LoopProduct__link", "a"]
    },
    "shopify": {
        "list": [".product-grid .grid__item", ".collection .grid__item", ".product-card"],
        "name": [".card__heading", ".product-card__title", "a.full-unstyled-link"],
        "price": [".price__current", ".price-item--regular", ".price"],
        "link": ["a.full-unstyled-link", "a.card__link", "a"]
    },
    "opencart": {
        "list": [".product-layout", ".product-thumb", ".product-grid .product-layout"],
        "name": [".caption a", "h4 a", ".product-thumb .caption a"],
        "price": [".price-new", ".price", ".price-tax"],
        "link": [".image a", "h4 a", "a"]
    },
    "magento": {
        "list": [".product-item", ".products-grid .product-item"],
        "name": [".product-item-name a", "a.product-item-link"],
        "price": [".price", ".price-wrapper"],
        "link": ["a.product-item-link", ".product-item-name a", "a"]
    },
    "generic": {
        "list": ["article", ".card", "div[class*=product]", "li[class*=product]"],
        "name": ["h3 a", "h2 a", ".title a", ".name", ".title", "a[title]"],
        "price": [".price", ".amount", ".prc", ".current-price", ".product-price"],
        "link": ["a", "h3 a", "h2 a"]
    }
}

def try_select(soup, selectors):
    for sel in selectors:
        els = soup.select(sel)
        if els:
            return els, sel
    return [], None

def extract_products(html, platform_hint=""):
    soup = BeautifulSoup(html, "lxml")
    rows = []
    # Decide selector order
    order = []
    if platform_hint and platform_hint in SELECTOR_SETS:
        order.append(platform_hint)
    order += ["woo", "shopify", "opencart", "magento", "generic"]
    # choose items list
    items = []
    platform_used = "none"
    for key in order:
        items, used = try_select(soup, SELECTOR_SETS[key]["list"])
        if items:
            platform_used = key
            break

    for el in items:
        # Name
        name = ""
        for sel in SELECTOR_SETS.get(platform_used, SELECTOR_SETS["generic"])["name"]:
            n = el.select_one(sel) or soup.select_one(sel)  # fallback
            if n and clean(n.get_text()):
                name = clean(n.get_text())
                break
        # Link
        link = ""
        for sel in SELECTOR_SETS.get(platform_used, SELECTOR_SETS["generic"])["link"]:
            a = el.select_one(sel) or soup.select_one(sel)
            if a and a.get("href"):
                link = a.get("href")
                break
        # Price
        price_val, currency, raw_price = None, "", ""
        for sel in SELECTOR_SETS.get(platform_used, SELECTOR_SETS["generic"])["price"]:
            p = el.select_one(sel) or soup.select_one(sel)
            if p and clean(p.get_text()):
                price_val, currency, raw_price = parse_price(p.get_text())
                break

        if name or link:
            rows.append((name, link, price_val, currency, raw_price, platform_used))

    return rows, platform_used

def main():
    OUT = Path("out"); OUT.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    # Read sites list
    catalog = Path("Sites_Catalog.csv")
    if not catalog.exists():
        print("[ERROR] Sites_Catalog.csv not found.", file=sys.stderr)
        sys.exit(0)

    sites = []
    with catalog.open("r", encoding="utf-8-sig") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            if r.get("enabled","true").strip().lower() in ("true","1","yes","y"):
                sites.append(r)

    all_rows = []
    for s in sites:
        name = s["site_name"]
        url = s["category_url"]
        platform = s.get("platform_hint","").strip().lower()
        max_pages = int(s.get("max_pages","1") or "1")
        page_pattern = s.get("pagination_pattern","").strip()

        for page in range(1, max_pages+1):
            page_url = url
            if page_pattern:
                page_url = page_pattern.replace("{page}", str(page)).replace("{base}", url)
            html = fetch(page_url)
            if not html:
                safe = re.sub(r"\W+", "_", name)[:30]
                Path(OUT / f"debug_{safe}.html").write_text(f"<!-- no html for {page_url} -->", encoding="utf-8")
                continue
            items, used = extract_products(html, platform_hint=platform)
            if not items and page == 1:
                safe = re.sub(r"\W+", "_", name)[:30]
                Path(OUT / f"debug_{safe}.html").write_text(html, encoding="utf-8")
                print(f"[WARN] {name}: 0 matches using platform '{platform or 'auto'}' — saved debug file.", file=sys.stderr)
            for (pname,plink,pval,cur,raw,used_plat) in items:
                status = "Available" if pval is not None else "Unknown"
                all_rows.append({
                    "timestamp_iso": ts,
                    "site_name": name,
                    "product_name": pname,
                    "sku": "",
                    "product_url": plink,
                    "status": status,
                    "price_value": pval,
                    "currency": cur,
                    "raw_price_text": raw,
                    "source_url": page_url,
                    "notes": used_plat
                })
            time.sleep(random.uniform(1.0, 2.0))

    # Write outputs (always)
    hdr = ["timestamp_iso","site_name","product_name","sku","product_url","status","price_value","currency","raw_price_text","source_url","notes"]
    snapshot = Path("out/current_snapshot.csv")
    history = Path("out/products_history.csv")

    if all_rows:
        df = pd.DataFrame(all_rows)
        if history.exists():
            df.to_csv(history, mode="a", header=False, index=False, encoding="utf-8-sig")
        else:
            df.to_csv(history, index=False, encoding="utf-8-sig")

        hist_all = pd.read_csv(history)
        hist_all["key"] = hist_all["site_name"].astype(str) + "|" + hist_all["product_url"].astype(str)
        latest_idx = hist_all.groupby("key")["timestamp_iso"].idxmax()
        snap = hist_all.loc[latest_idx].drop(columns=["key"]).sort_values(["site_name","product_name"])
        snap.to_csv(snapshot, index=False, encoding="utf-8-sig")
        print(f"[INFO] snapshot rows: {len(snap)} / appended: {len(df)}")
    else:
        with snapshot.open("w", encoding="utf-8-sig") as f:
            f.write(",".join(hdr) + "\n")
        with history.open("w", encoding="utf-8-sig") as f:
            f.write(",".join(hdr) + "\n")
        print("[INFO] No rows scraped; wrote empty CSVs.")

if __name__ == "__main__":
    main()

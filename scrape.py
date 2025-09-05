#!/usr/bin/env python3
import os, re, sys, time, random
import urllib.parse as up
from datetime import datetime, timezone
import requests
import pandas as pd
from bs4 import BeautifulSoup

SITES_CSV = os.environ.get("SITES_CSV_PATH", "Sites_Catalog.csv")
OUT_DIR = os.environ.get("OUT_DIR", "out")
HISTORY_CSV = os.path.join(OUT_DIR, "products_history.csv")
SNAPSHOT_CSV = os.path.join(OUT_DIR, "current_snapshot.csv")

DESKTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
MOBILE_UA  = "Mozilla/5.0 (Linux; Android 12; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Mobile Safari/537.36"

BASE_HEADERS = {
    "User-Agent": DESKTOP_UA,
    "Accept-Language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "DNT": "1",
}

DEFAULT_LIST_SELECTORS = [
    "ul.products li.product",      # WooCommerce
    "li.product",                  # WooCommerce generic
    "article.prd",                 # Jumia
    ".product-layout",             # OpenCart
    ".product-thumb",              # OpenCart
    ".product-card",               # Generic theme
    ".product-item",               # Generic theme
    "li.product-item"              # Magento-ish
]

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

def jitter_sleep(ms):
    time.sleep(ms/1000.0 + random.uniform(0.2, 0.8))

def http_get(session, url, headers, retries=4, backoff=2, mobile_fallback=True):
    # try desktop first, optionally mobile if no good
    last = None
    for attempt in range(retries):
        try:
            h = headers.copy()
            if attempt >= 2 and mobile_fallback:
                h["User-Agent"] = MOBILE_UA
            r = session.get(url, headers=h, timeout=45)
            if r.status_code == 200 and r.text:
                # simple bot page detection
                bot_signals = ["Just a moment", "cf-browser-verification", "captcha", "Access Denied"]
                if any(sig.lower() in r.text.lower() for sig in bot_signals):
                    print(f"[WARN] Bot wall detected @ {url} (attempt {attempt+1})", file=sys.stderr)
                else:
                    return r
            else:
                print(f"[WARN] GET {url} -> status={r.status_code}", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] GET {url} failed attempt {attempt+1}: {e}", file=sys.stderr)
        time.sleep(backoff * (attempt+1))
    return last

def get_cards(soup, list_selector, url, site_name):
    cards = []
    if list_selector:
        try:
            cards = soup.select(list_selector)
            print(f"[DEBUG] {site_name}: primary '{list_selector}' -> {len(cards)}")
        except Exception as e:
            print(f"[WARN] {site_name}: invalid selector '{list_selector}': {e}", file=sys.stderr)
    if not cards:
        for sel in DEFAULT_LIST_SELECTORS:
            try:
                cards = soup.select(sel)
            except Exception:
                cards = []
            if cards:
                print(f"[DEBUG] {site_name}: fallback '{sel}' -> {len(cards)}")
                break
    return cards

def iterate_pages(url, paging_mode, page_param, start_page, max_pages, next_selector, session, headers, site_name, sleep_ms, mobile_fallback):
    urls = []
    if paging_mode == "param":
        sp = int(start_page or 1)
        mx = int(max_pages or 1)
        for p in range(sp, sp+mx):
            parsed = up.urlparse(url)
            q = dict(up.parse_qsl(parsed.query))
            q[page_param or "page"] = str(p)
            new_q = up.urlencode(q)
            page_url = up.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_q, parsed.fragment))
            urls.append(page_url)
    elif paging_mode == "link":
        # follow "next" link up to max_pages
        visited = set()
        cur = url
        mx = int(max_pages or 1)
        for _ in range(mx):
            if cur in visited: break
            visited.add(cur)
            urls.append(cur)
            r = http_get(session, cur, headers, mobile_fallback=mobile_fallback)
            if not r: break
            soup = BeautifulSoup(r.text, "lxml")
            nxt = soup.select_one(next_selector or "a.next, a[rel=next], .next.page-numbers")
            if not nxt or not nxt.get("href"):
                break
            cur = abs_url(cur, nxt.get("href"))
            jitter_sleep(sleep_ms or 1200)
    else:
        urls = [url]
    return urls

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    df = pd.read_csv(SITES_CSV)
    history_rows = []

    session = requests.Session()

    for _, row in df.iterrows():
        site_name = str(row.get("site_name", ""))
        base_url = str(row.get("url", ""))
        list_selector = str(row.get("list_selector", ""))
        name_selector = str(row.get("name_selector", ""))
        price_selector = str(row.get("price_selector", ""))
        status_selector = str(row.get("status_selector", ""))
        soldout_regex = str(row.get("status_soldout_text", "out of stock|sold out|غير متوفر|نفد|غير متاح"))
        price_attribute = str(row.get("price_attribute", ""))
        currency_hint = str(row.get("currency_hint", "EGP|ج.م|LE|جنيه"))
        sku_selector = str(row.get("sku_selector", ""))
        product_url_selector = str(row.get("product_url_selector", "a@href"))
        paging_mode = str(row.get("paging_mode", "")).strip().lower() or "none"
        page_param = str(row.get("page_param", "page"))
        start_page = int(row.get("start_page", 1)) if not pd.isna(row.get("start_page", 1)) else 1
        max_pages = int(row.get("max_pages", 1)) if not pd.isna(row.get("max_pages", 1)) else 1
        next_selector = str(row.get("next_page_selector", ""))
        sleep_ms = int(row.get("sleep_ms", 1200)) if not pd.isna(row.get("sleep_ms", 1200)) else 1200
        mobile_fallback = str(row.get("mobile_ua_fallback", "true")).lower() != "false"

        page_urls = iterate_pages(base_url, paging_mode, page_param, start_page, max_pages,
                                  next_selector, session, BASE_HEADERS, site_name, sleep_ms, mobile_fallback)
        print(f"[INFO] {site_name}: scanning {len(page_urls)} page(s)")

        for page_url in page_urls:
            r = http_get(session, page_url, BASE_HEADERS, mobile_fallback=mobile_fallback)
            if not r:
                print(f"[ERROR] {site_name}: no response for {page_url}", file=sys.stderr)
                continue
            soup = BeautifulSoup(r.text, "lxml")
            cards = get_cards(soup, list_selector, page_url, site_name)

            if not cards:
                # Save debug HTML for this page
                safe = re.sub(r"\W+", "_", f"{site_name}_p")[:40]
                with open(os.path.join(OUT_DIR, f"debug_{safe}.html"), "w", encoding="utf-8") as f:
                    f.write(r.text)
                print(f"[WARN] {site_name}: no product cards found on {page_url}", file=sys.stderr)

            ts = datetime.now(timezone.utc).isoformat()
            for card in cards:
                name = clean_text(pick_attr(card, name_selector, page_url)) if name_selector else ""
                if not name:
                    # generic fallbacks
                    name = clean_text(pick_attr(card, ".woocommerce-loop-product__title", page_url)) or \
                           clean_text(pick_attr(card, "h3.name", page_url)) or \
                           clean_text(pick_attr(card, "h2,h3,.product-title,.caption a", page_url))

                raw_price = pick_attr(card, price_selector, page_url, price_attribute if price_attribute else None) if price_selector else None
                if not raw_price:
                    raw_price = pick_attr(card, ".woocommerce-Price-amount", page_url) or \
                                pick_attr(card, ".prc,.price,.amount", page_url)

                status_text = clean_text(pick_attr(card, status_selector, page_url)) if status_selector else ""
                if not status_text:
                    status_text = clean_text(pick_attr(card, ".stock,.availability,.-unavailable,.oos,.badge,.stock-status", page_url)) or ""

                sku = clean_text(pick_attr(card, sku_selector, page_url)) if sku_selector else ""
                product_url = pick_attr(card, product_url_selector, page_url) or ""
                if not product_url:
                    a = card.select_one("a[href]")
                    if a and a.get("href"):
                        product_url = abs_url(page_url, a.get("href"))

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
                    "source_url": page_url,
                    "notes": ""
                })
            jitter_sleep(sleep_ms)

    # write history & snapshot
    os.makedirs(OUT_DIR, exist_ok=True)
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

import cloudscraper
import time
from bs4 import BeautifulSoup
import pandas as pd

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def fetch(url, retries=3, delay=2):
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
    for attempt in range(retries):
        try:
            resp = scraper.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            print(f"[WARN] {url} failed: {e}")
        time.sleep(delay)
    print(f"[ERROR] No response from {url}")
    return None

def scrape():
    # Minimal placeholder logic; user to adjust selectors
    urls = [
        "https://www.jumia.com.eg/gaming-pc-accessories/",
        "https://gamerscolony.net/product-category/accessories/"
    ]
    data = []
    for url in urls:
        html = fetch(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        for item in soup.select("a.core"):
            name = item.get_text(strip=True)
            link = item.get("href")
            data.append({"product_name": name, "product_url": link, "source_url": url})
        time.sleep(1.5)

    df = pd.DataFrame(data)
    out_dir = Path("out")
    out_dir.mkdir(exist_ok=True)
    snapshot_file = out_dir / "current_snapshot.csv"
    df.to_csv(snapshot_file, index=False)
    print(f"[INFO] Wrote {snapshot_file}")

if __name__ == "__main__":
    scrape()

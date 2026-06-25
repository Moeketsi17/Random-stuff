import os
import re
import time
import json
import csv
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime

BASE_URL = "https://www.grainsa.co.za"
START_PATH = "/news-headlines/press-releases"

# YEARS YOU WANT TO SCRAPE
YEARS = ["2025", "2026"]

def fetch(url):
    print("Fetching:", url)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.text

def slugify(text):
    text = re.sub(r'%[0-9A-Fa-f]{2}', '-', text)
    return re.sub(r'[^0-9a-zA-Z\-]+', '-', text).strip('-').lower()

def format_date(date_str):
    """Try to parse various date formats"""
    date_formats = [
        "%d %B %Y",      # 15 January 2025
        "%B %d, %Y",     # January 15, 2025
        "%d/%m/%Y",      # 15/01/2025
        "%Y-%m-%d",      # 2025-01-15
        "%d %b %Y",      # 15 Jan 2025
    ]
    
    for fmt in date_formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except:
            continue
    
    return date_str

# OUTPUT FILES
OUT_JSON = "grainsa_press_releases_2025_2026.json"
OUT_CSV = "grainsa_press_releases_2025_2026.csv"
IMAGES_DIR = "grainsa_press_releases_images"

os.makedirs(IMAGES_DIR, exist_ok=True)

print("=" * 80)
print(f"🔍 SCRAPING GRAINSA PRESS RELEASES FOR {', '.join(YEARS)}")
print("=" * 80)

html = fetch(urljoin(BASE_URL, START_PATH))
soup = BeautifulSoup(html, "html.parser")

all_articles = []
all_links = []


# FIND PRESS RELEASES FOR TARGET YEARS
# Method 1: Look for year-based sections (if they exist as collapsible panels)
for year in YEARS:
    # Try looking for collapse sections by year
    for i in range(1, 13):  # Try 12 possible panels per year
        panel_ids = [
            f"collapse{year}",
            f"collapse-{year}",
            f"year-{year}",
            f"year{year}",
        ]
        
        for panel_id in panel_ids:
            year_div = soup.select_one(f"#{panel_id}")
            if year_div:
                print(f"📌 Found year section: {year}")
                
                for a in year_div.select("a"):
                    href = a.get("href")
                    if href:
                        full = urljoin(BASE_URL, href)
                        if full not in all_links:
                            all_links.append(full)
                break

# Method 2: Look for all links on the page and filter by year
if not all_links:
    print(f"📌 No collapsible sections found, scanning all links...")
    
    for a in soup.select("a"):
        href = a.get("href")
        text = a.get_text(strip=True)
        
        if href:
            # Check if link or text contains year reference
            if any(year in href or year in text for year in YEARS):
                full = urljoin(BASE_URL, href)
                if full not in all_links and "press-releases" in full:
                    all_links.append(full)

# Method 3: Look for article containers and extract dates from them
if not all_links:
    print(f"📌 Trying to find article containers...")
    
    # Common patterns for article containers
    selectors = [
        "article",
        ".article",
        ".post",
        ".press-release",
        "[data-type='press-release']",
        ".news-item",
        ".item",
    ]
    
    for selector in selectors:
        for article in soup.select(selector):
            # Look for links within the article
            link = article.select_one("a")
            if link and link.get("href"):
                href = link.get("href")
                full = urljoin(BASE_URL, href)
                
                # Check date
                text = article.get_text()
                if any(year in text or year in full for year in YEARS):
                    if full not in all_links:
                        all_links.append(full)

print(f"\n📎 Total press release links found for {', '.join(YEARS)}: {len(all_links)}\n")

if not all_links:
    print("⚠️  No links found. The page structure may be different.")
    print("Displaying page structure for debugging...")
    
    # Show what we found
    print("\nArticles/Posts found:")
    for selector in ["article", ".article", ".post", ".press-release", ".news-item"]:
        items = soup.select(selector)
        if items:
            print(f"  - {selector}: {len(items)} items")



# SCRAPE EACH ARTICLE
for i, url in enumerate(all_links, 1):
    try:
        print(f"\n[{i}/{len(all_links)}] ➡ Scraping: {url}")

        html = fetch(url)
        soup_article = BeautifulSoup(html, "html.parser")

        # Title
        title_tag = soup_article.select_one("h1, h2")
        title = title_tag.get_text(strip=True) if title_tag else "Untitled"

        # Main content - try various selectors
        content_div = (
            soup_article.select_one(".article-details") or
            soup_article.select_one(".post-content") or
            soup_article.select_one("article") or
            soup_article.select_one(".content") or
            soup_article.body
        )

        if not content_div:
            content_div = soup_article.body

        # Remove unwanted elements
        for bad in content_div.select("ul.share, .share-box, .social-share, nav, .navigation, script, style"):
            bad.decompose()

        # Extract date
        date_str = "Unknown"
        
        # Try common date patterns
        date_patterns = [
            soup_article.select_one("time"),
            soup_article.select_one(".date"),
            soup_article.select_one("[data-date]"),
            soup_article.select_one(".published-date"),
        ]
        
        for date_elem in date_patterns:
            if date_elem:
                date_text = date_elem.get_text(strip=True)
                if date_text:
                    date_str = date_text
                    break
        
        # If no date found, try to extract from text
        if date_str == "Unknown":
            for year in YEARS:
                pattern = rf"\d{{1,2}}\s*(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*{year}"
                match = re.search(pattern, content_div.get_text(), re.IGNORECASE)
                if match:
                    date_str = match.group()
                    break

        formatted_date = format_date(date_str)

        # -----------------------------
        # IMAGE PROCESSING
        # -----------------------------
        img_urls = []

        for img in content_div.select("img"):
            src = img.get("src") or img.get("data-src")
            if not src:
                continue

            # FULL URL for downloading
            full_img = urljoin(BASE_URL, src)

            # RELATIVE URL for saving
            relative_img = urlparse(full_img).path

            # Add relative path to JSON/CSV
            img_urls.append(relative_img)

            # Update HTML to use relative path
            img["src"] = relative_img

            # Download image locally
            fname = slugify(os.path.basename(urlparse(src).path))
            if not fname:
                fname = slugify(relative_img.split('/')[-1]) or "image"
            
            local_path = os.path.join(IMAGES_DIR, fname)

            if not os.path.exists(local_path):
                try:
                    print(f"   Downloading image: {full_img}")
                    img_data = requests.get(full_img, timeout=20).content
                    with open(local_path, "wb") as f:
                        f.write(img_data)
                except Exception as e:
                    print(f"   ❌ Failed to download: {full_img} - {e}")

        # Normalize headings
        for tag in content_div.find_all(["h2", "h3"]):
            tag.name = "h4"

        content_html = str(content_div)
        content_text = content_div.get_text(" ", strip=True)

        # Save article
        all_articles.append({
            "title": title,
            "url": url,
            "date": formatted_date,
            "content_text": content_text[:500] + "..." if len(content_text) > 500 else content_text,
            "content_html": content_html,
            "images": img_urls,
        })

        print(f"   ✅ Scraped: {title} ({formatted_date})")

    except Exception as e:
        print(f"❌ Error scraping {url}: {e}")

    time.sleep(1)  # Be respectful with requests

# -----------------------------------------------------------
# SAVE JSON + CSV
# -----------------------------------------------------------

print("\n" + "=" * 80)
print(f"💾 Saving {len(all_articles)} articles to JSON + CSV...\n")

# JSON file
with open(OUT_JSON, "w", encoding="utf8") as f:
    json.dump(all_articles, f, indent=2, ensure_ascii=False)
    print(f"✅ JSON saved → {OUT_JSON}")

# CSV file
with open(OUT_CSV, "w", encoding="utf8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["title", "url", "date", "content_text", "images"])
    writer.writeheader()
    for a in all_articles:
        writer.writerow({
            "title": a["title"],
            "url": a["url"],
            "date": a["date"],
            "content_text": a["content_text"],
            "images": " | ".join(a["images"]) if a["images"] else "",
        })
    print(f"✅ CSV saved → {OUT_CSV}")

print(f"✅ Images saved → {IMAGES_DIR}/")
print("\n🎉 SCRAPING COMPLETE!")
print(f"📊 Total articles scraped: {len(all_articles)}")

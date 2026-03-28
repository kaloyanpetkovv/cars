#!/usr/bin/env python3
import json
import re
import time
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from bs4 import BeautifulSoup
import requests

# ============================================================
TELEGRAM_BOT_TOKEN = "8634258923:AAEd_BZcTIxKPTQuzJ9hG9bFh0w2d2M_tWk"
TELEGRAM_CHAT_ID   = "-5276167808"
OPENLANE_USERNAME  = "kapitolia"
OPENLANE_PASSWORD  = "Samsung@1"
CHECK_INTERVAL_SECONDS = 60
SEEN_IDS_FILE = "seen_listings.json"

OPENLANE_SEARCH_URL = "https://www.openlane.eu/bg/findcar?fuelTypes=100004&auctionTypes=2"
# ============================================================


def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.ok:
            print("Telegram: izprateno!")
        else:
            print(f"Telegram greshka: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Telegram greshka: {e}")


def init_driver_and_login():
    print("Startiram Edge za login...")
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    driver = webdriver.Edge(options=options)
    wait = WebDriverWait(driver, 30)

    driver.get("https://www.openlane.eu/bg/home")
    time.sleep(4)

    # Cookie banner
    try:
        btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(text(),'Приемане на всички') or contains(text(),'Accept all') or contains(text(),'accept')]")
        ))
        btn.click()
        print("Cookie baner zatvoren.")
        time.sleep(2)
    except:
        print("Nyama cookie baner.")

    # Login button
    try:
        vhod = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//a[normalize-space()='Вход'] | //button[normalize-space()='Вход'] | //a[contains(@href,'login')] | //button[contains(text(),'Login')]")
        ))
        vhod.click()
        print("Vhod buton natisnat.")
        time.sleep(3)
    except Exception as e:
        print(f"Ne moga da natisna Vhod: {e}")

    # Username
    username_field = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//input[@type='text' or @type='email' or @name='username' or @name='email' or @id='username' or @id='email']")
    ))
    username_field.clear()
    username_field.send_keys(OPENLANE_USERNAME)
    print(f"Username popolnen: {OPENLANE_USERNAME}")
    time.sleep(1)
    username_field.send_keys(Keys.RETURN)
    print("Enter sled username.")
    time.sleep(3)

    # Password
    pass_field = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//input[@type='password']")
    ))
    pass_field.clear()
    pass_field.send_keys(OPENLANE_PASSWORD)
    print("Parola popolnena.")
    time.sleep(1)
    pass_field.send_keys(Keys.RETURN)
    print("Enter sled parola.")

    try:
        WebDriverWait(driver, 20).until(
            lambda d: "login" not in d.current_url and d.current_url != "https://www.openlane.eu/bg/home"
            or "home" in d.current_url
        )
    except:
        pass
    time.sleep(4)

    print(f"Lognat! URL: {driver.current_url}")
    return driver


def parse_cards_from_html(soup) -> list:
    """
    Primary extraction using confirmed selector: section.rc-CarCardDesktop
    Verified from page_debug.html - 20 cards found with this selector.
    Page is server-side rendered, no __NEXT_DATA__ or XHR needed.
    """
    cards = soup.select("section.rc-CarCardDesktop")
    print(f"HTML cards (rc-CarCardDesktop): {len(cards)}")

    listings = []
    for card in cards:
        title_link = card.select_one("h3.title > a")
        if not title_link:
            continue

        href = title_link.get("href", "")
        match = re.search(r'auctionId=(\d+)', href)
        listing_id = match.group(1) if match else ""
        if not listing_id:
            continue

        link = "https://www.openlane.eu" + href

        # Title from span.strong inside the link
        title_span = title_link.select_one("span.strong")
        if title_span:
            title = title_span.get_text(strip=True)
        else:
            title = title_link.get_text(strip=True).split(" - ")[0].strip()

        # Mileage is in the full title text: "Make Model ... - 140.998 km"
        full_text = title_link.get_text(strip=True)
        km_match = re.search(r'[\d\.\s]+\s*km', full_text, re.IGNORECASE)
        km = km_match.group(0).strip() if km_match else ""

        # Price and registration date from auction-details grid
        price = "N/A"
        year = ""
        details = card.select_one("div.auction-details")
        if details:
            rows = details.select("div.columns")
            for row in rows:
                price_spans = row.select("span.strong")
                if price_spans:
                    price = price_spans[0].get_text(strip=True)
                    break
            for row in rows:
                data_spans = row.select("span.data")
                if data_spans:
                    year = data_spans[0].get_text(strip=True)
                    break

        listings.append({
            "id": listing_id,
            "title": title,
            "price": price,
            "year": year,
            "km": km,
            "link": link,
        })

    return listings


def extract_vehicles_from_next_data(data) -> list:
    """Fallback: recursively search for vehicle lists in __NEXT_DATA__."""
    vehicles = []
    visited = set()

    def looks_like_vehicle(obj):
        if not isinstance(obj, dict):
            return False
        return bool({"make", "vehicleId", "lotId", "uuid", "vin", "auctionId"} & set(obj.keys()))

    def search(obj, depth=0):
        if depth > 12:
            return
        obj_id = id(obj)
        if obj_id in visited:
            return
        visited.add(obj_id)
        if isinstance(obj, list):
            if obj and looks_like_vehicle(obj[0]):
                vehicles.extend(obj)
                return
            for item in obj:
                search(item, depth + 1)
        elif isinstance(obj, dict):
            for key in ("vehicles", "items", "results", "lots", "auctions", "listings", "data", "cars"):
                val = obj.get(key)
                if isinstance(val, list) and val and looks_like_vehicle(val[0]):
                    vehicles.extend(val)
                    return
            for v in obj.values():
                search(v, depth + 1)

    search(data)
    return vehicles


def fetch_listings_selenium(driver):
    try:
        driver.get(OPENLANE_SEARCH_URL)
        print("Stranicata se zarejda...")

        # Wait for car cards to appear
        try:
            WebDriverWait(driver, 25).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "section.rc-CarCardDesktop"))
            )
        except:
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "main"))
                )
            except:
                pass
            time.sleep(3)

        # Select "Първо най-новите" (Newest first)
        try:
            sort_select = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".sort-selector select"))
            )
            Select(sort_select).select_by_value("BatchStartDateForSorting|ascending")
            print("Sort: Purvo naj-novite.")
            time.sleep(3)
        except Exception as e:
            print(f"Sort ne e prilojen: {e}")

        # Save debug file
        with open("page_debug.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("Debug HTML zapisano v page_debug.html")

        soup = BeautifulSoup(driver.page_source, "html.parser")

        # -- Attempt 1: section.rc-CarCardDesktop (confirmed working) --
        listings = parse_cards_from_html(soup)
        if listings:
            return listings

        # -- Attempt 2: __NEXT_DATA__ fallback --
        script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if script_tag:
            try:
                data = json.loads(script_tag.string)
                vehicles = extract_vehicles_from_next_data(data)
                print(f"__NEXT_DATA__: {len(vehicles)} vehicles.")
                for item in vehicles:
                    listing_id = str(
                        item.get("auctionId") or item.get("id") or item.get("uuid") or
                        item.get("vehicleId") or item.get("lotId") or ""
                    )
                    make  = item.get("make") or ""
                    model = item.get("model") or ""
                    title = item.get("title") or f"{make} {model}".strip() or "Unknown"
                    price = (
                        item.get("price") or item.get("buyNowPrice") or
                        item.get("currentBid") or item.get("startingPrice") or "N/A"
                    )
                    year  = item.get("year") or item.get("firstRegistrationYear") or ""
                    km    = item.get("mileage") or item.get("km") or item.get("kilometers") or ""
                    link  = item.get("url") or item.get("detailUrl") or item.get("href") or ""
                    if link and not link.startswith("http"):
                        link = "https://www.openlane.eu" + link
                    if not link:
                        link = OPENLANE_SEARCH_URL
                    if listing_id:
                        listings.append({
                            "id": listing_id, "title": title,
                            "price": price, "year": year,
                            "km": km, "link": link
                        })
                if listings:
                    return listings
            except Exception as e:
                print(f"__NEXT_DATA__ parse greshka: {e}")

        if not listings:
            print("VNIMANIE: 0 obyavi namereni! Proveri page_debug.html.")

        return listings

    except Exception as e:
        print(f"[Greshka pri fetch] {e}")
        import traceback
        traceback.print_exc()
        return []


def load_seen_ids():
    if os.path.exists(SEEN_IDS_FILE):
        with open(SEEN_IDS_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_ids(ids: set):
    with open(SEEN_IDS_FILE, "w") as f:
        json.dump(list(ids), f)


def format_message(listing: dict) -> str:
    parts = [
        "⚡ <b>Nova elektricheska obyava v OpenLane!</b>",
        "",
        f"🚗 <b>{listing['title']}</b>"
    ]
    if listing.get("year"):
        parts.append(f"📅 Registratsiya: {listing['year']}")
    if listing.get("km"):
        parts.append(f"🛣 Probeg: {listing['km']}")
    if listing.get("price") and listing["price"] != "N/A":
        parts.append(f"💶 Cena: {listing['price']}")
    parts.append(f"🔗 <a href=\"{listing['link']}\">Viz obyavata</a>")
    return "\n".join(parts)


def main():
    print("=" * 50)
    print("OpenLane Telegram Notifier startiran")
    print(f"Proverka na vseki {CHECK_INTERVAL_SECONDS} sekundi")
    print("=" * 50)

    driver = init_driver_and_login()
    if not driver:
        print("Login ne uspya!")
        return

    send_telegram("✅ <b>OpenLane Notifier startiran!</b>\n\nLoginal sum se uspeshno!")

    seen_ids = load_seen_ids()
    first_run = len(seen_ids) == 0

    while True:
        now = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{now}] Proveryavam za novi obyavi...")

        listings = fetch_listings_selenium(driver)
        print(f"[{now}] Namereni {len(listings)} obyavi.")

        new_listings = [l for l in listings if l["id"] not in seen_ids]

        if first_run:
            for l in listings:
                seen_ids.add(l["id"])
            save_seen_ids(seen_ids)
            print(f"[{now}] Parvo startivane - zapazeni {len(seen_ids)} obyavi.")
            first_run = False
            if len(seen_ids) == 0:
                print("[!] VNIMANIE: Ne sa namereni obyavi pri purvo startivane!")
                print("[!] Proveri page_debug.html.")
        else:
            if new_listings:
                print(f"[{now}] {len(new_listings)} novi obyavi!")
                for listing in new_listings:
                    send_telegram(format_message(listing))
                    seen_ids.add(listing["id"])
                    time.sleep(1)
                save_seen_ids(seen_ids)
            else:
                print(f"[{now}] Nyama novi obyavi.")

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

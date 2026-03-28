#!/usr/bin/env python3
import json
import time
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
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
    # Enable performance logging to capture network/API requests
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

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


def looks_like_vehicle(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    vehicle_keys = {"make", "vehicleId", "lotId", "uuid", "vin", "auctionId", "listingId"}
    return bool(vehicle_keys & set(obj.keys()))


def extract_vehicles_from_next_data(data) -> list:
    """Recursively search for vehicle lists in any data structure."""
    vehicles = []
    visited = set()

    def search(obj, depth=0):
        if depth > 15:
            return
        obj_id = id(obj)
        if obj_id in visited:
            return
        visited.add(obj_id)

        if isinstance(obj, list):
            if len(obj) > 0 and looks_like_vehicle(obj[0]):
                vehicles.extend(obj)
                return
            for item in obj:
                search(item, depth + 1)
        elif isinstance(obj, dict):
            # Check high-priority container keys first
            for key in ("vehicles", "items", "results", "lots", "auctions", "listings", "data", "cars", "content"):
                val = obj.get(key)
                if isinstance(val, list) and len(val) > 0 and looks_like_vehicle(val[0]):
                    vehicles.extend(val)
                    return
            for v in obj.values():
                search(v, depth + 1)

    search(data)
    return vehicles


def get_vehicles_from_network_log(driver) -> list:
    """
    Intercepts network responses via Chrome performance log (CDP).
    Captures actual API calls that return vehicle/auction data.
    """
    vehicles = []
    try:
        logs = driver.get_log("performance")
    except Exception as e:
        print(f"Performance log ne e nalichen: {e}")
        return []

    for entry in logs:
        try:
            msg = json.loads(entry["message"])["message"]
            if msg.get("method") != "Network.responseReceived":
                continue

            params = msg.get("params", {})
            url = params.get("response", {}).get("url", "")
            mime = params.get("response", {}).get("mimeType", "")

            # Only look at JSON responses for vehicle/search related endpoints
            if "json" not in mime:
                continue
            if not any(kw in url.lower() for kw in [
                "vehicle", "car", "search", "findcar", "auction", "lot", "listing", "inventory"
            ]):
                continue

            request_id = params.get("requestId")
            if not request_id:
                continue

            try:
                response = driver.execute_cdp_cmd(
                    "Network.getResponseBody", {"requestId": request_id}
                )
                body = response.get("body", "")
                if not body:
                    continue
                data = json.loads(body)
                found = extract_vehicles_from_next_data(data)
                if found:
                    print(f"Network API [{url}]: {len(found)} vehicles namereni.")
                    vehicles.extend(found)
            except Exception:
                pass
        except Exception:
            pass

    return vehicles


def parse_vehicle_item(item: dict, base_url: str) -> dict | None:
    listing_id = str(
        item.get("id") or item.get("uuid") or
        item.get("vehicleId") or item.get("lotId") or
        item.get("auctionId") or item.get("listingId") or ""
    )
    if not listing_id:
        return None

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
        link = base_url

    return {"id": listing_id, "title": title, "price": price, "year": year, "km": km, "link": link}


def fetch_listings_selenium(driver):
    try:
        driver.get(OPENLANE_SEARCH_URL)
        print("Stranicata se zarejda...")

        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "main"))
            )
        except:
            pass

        # Scroll to trigger lazy-loaded content
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(2)

        # Save debug file for troubleshooting
        with open("page_debug.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("Debug HTML zapisano v page_debug.html")

        listings = []

        # ── Attempt 1: Network API interception (most reliable) ──
        vehicles = get_vehicles_from_network_log(driver)
        if vehicles:
            for item in vehicles:
                entry = parse_vehicle_item(item, OPENLANE_SEARCH_URL)
                if entry:
                    listings.append(entry)
            if listings:
                print(f"Network log: {len(listings)} obyavi namereni.")
                return listings

        # ── Attempt 2: __NEXT_DATA__ script tag ──
        soup = BeautifulSoup(driver.page_source, "html.parser")
        script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if script_tag:
            try:
                data = json.loads(script_tag.string)
                vehicles = extract_vehicles_from_next_data(data)
                print(f"__NEXT_DATA__: {len(vehicles)} vehicles.")
                for item in vehicles:
                    entry = parse_vehicle_item(item, OPENLANE_SEARCH_URL)
                    if entry:
                        listings.append(entry)
                if listings:
                    return listings
            except Exception as e:
                print(f"__NEXT_DATA__ parse greshka: {e}")

        # ── Attempt 3: JavaScript window state ──
        js_scripts = [
            "return JSON.stringify(window.__NEXT_DATA__ || null);",
            "return JSON.stringify(window.__REDUX_STATE__ || window.__INITIAL_STATE__ || null);",
            "return JSON.stringify(window.searchResults || window.vehicleResults || null);",
        ]
        for script in js_scripts:
            try:
                result = driver.execute_script(script)
                if result and result != "null":
                    data = json.loads(result)
                    if data:
                        vehicles = extract_vehicles_from_next_data(data)
                        if vehicles:
                            print(f"JS injection: {len(vehicles)} vehicles namereni.")
                            for item in vehicles:
                                entry = parse_vehicle_item(item, OPENLANE_SEARCH_URL)
                                if entry:
                                    listings.append(entry)
                            if listings:
                                return listings
            except:
                pass

        # ── Attempt 4: HTML card selectors (expanded list) ──
        selectors = [
            "[data-vehicle-id]",
            "[data-listing-id]",
            "[data-lot-id]",
            "[data-testid*='vehicle']",
            "[data-testid*='car']",
            "[data-testid*='listing']",
            "[data-testid*='result']",
            ".vehicle-card",
            ".car-card",
            ".listing-card",
            ".search-result-item",
            "[class*='VehicleCard']",
            "[class*='vehicleCard']",
            "[class*='CarCard']",
            "[class*='carCard']",
            "[class*='ListingCard']",
            "[class*='listingCard']",
            "[class*='ResultCard']",
            "[class*='resultCard']",
            "[class*='SearchResult']",
            "[class*='AuctionCard']",
            "[class*='auctionCard']",
            "article[class*='card']",
            "article[class*='Card']",
            "li[class*='vehicle']",
            "li[class*='car']",
            "div[class*='vehicle-item']",
            "div[class*='auction-item']",
        ]

        cards = []
        for sel in selectors:
            found = soup.select(sel)
            if found:
                print(f"Selektor '{sel}': {len(found)} cards.")
                cards = found
                break

        print(f"HTML cards obshto: {len(cards)}")

        for card in cards:
            listing_id = (
                card.get("data-vehicle-id") or card.get("data-listing-id") or
                card.get("data-id") or card.get("data-lot-id") or ""
            )
            title_el = card.select_one(
                "h2, h3, h4, [class*='title'], [class*='Title'], [class*='name'], [class*='Name']"
            )
            title = title_el.get_text(strip=True) if title_el else "Unknown"
            price_el = card.select_one("[class*='price'], [class*='Price'], [class*='bid'], [class*='Bid']")
            price = price_el.get_text(strip=True) if price_el else "N/A"
            link_el = card.select_one("a[href]")
            link = (
                ("https://www.openlane.eu" + link_el["href"])
                if link_el and link_el.get("href")
                else OPENLANE_SEARCH_URL
            )
            if not listing_id:
                listing_id = link.split("/")[-1].split("?")[0] if link != OPENLANE_SEARCH_URL else ""
            if listing_id:
                listings.append({
                    "id": str(listing_id), "title": title,
                    "price": price, "year": "", "km": "", "link": link
                })

        if not listings:
            print("VNIMANIE: 0 obyavi namereni! Proveri page_debug.html za HTML strukturata.")

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
        parts.append(f"📅 Godina: {listing['year']}")
    if listing.get("km"):
        parts.append(f"🛣 Probeg: {listing['km']} km")
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
                print("[!] Proveri page_debug.html za da vidish HTML strukturata.")
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

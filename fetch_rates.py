import json
import re
import time
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Use cloudscraper to prevent Cloudflare blocks if installed
try:
    import cloudscraper
    session = cloudscraper.create_scraper()
except ImportError:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    })


def extract_js_array(html_text: str, var_name: str):
    """
    Extracts JSON arrays defined as JavaScript variables from page scripts.
    e.g.: const fullPriceData = [...]; or let fullPriceData = [...];
    """
    pattern = r"(?:const|let|var)\s+" + re.escape(var_name) + r"\s*=\s*(\[\s*\{.*?\}\]\s*);"
    match = re.search(pattern, html_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception as e:
            print(f"Error parsing JSON for {var_name}: {e}")
    return []


def generate_usd_chart(aed_irr_data, aed_usd_data, output_file="usd_chart.png", days_limit=180):
    """
    Aligns AED/IRR and AED/USD by day, calculates USD/Toman, and draws the chart.
    """
    if not aed_irr_data:
        print("No historical AED/IRR data found.")
        return

    # Build a lookup dictionary for AED to USD rates: {YYYY-MM-DD: aed_usd_rate}
    usd_rate_by_date = {}
    for item in aed_usd_data:
        d = datetime.fromtimestamp(item["timestamp"]).strftime("%Y-%m-%d")
        usd_rate_by_date[d] = item["rate"]

    chart_dates = []
    usd_toman_prices = []

    # Calculate USD/Toman for each point
    for item in aed_irr_data:
        ts = item["timestamp"]
        dt = datetime.fromtimestamp(ts)
        d_str = dt.strftime("%Y-%m-%d")

        aed_irr = item["price"]
        aed_toman = aed_irr / 10.0  # 1 Toman = 10 IRR

        # Get AED -> USD rate for this day; default to standard peg 1 / 3.6725 (~0.27229)
        aed_usd = usd_rate_by_date.get(d_str, 0.272257)

        if aed_usd > 0:
            usd_toman = int(round(aed_toman / aed_usd))
            chart_dates.append(dt)
            usd_toman_prices.append(usd_toman)

    if not chart_dates:
        print("Could not compute any USD/Toman historical points.")
        return

    # Keep the most recent N days for a clean, readable chart (e.g., last 6 months / 180 days)
    if days_limit and len(chart_dates) > days_limit:
        chart_dates = chart_dates[-days_limit:]
        usd_toman_prices = usd_toman_prices[-days_limit:]

    # Plot styling
    plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
    fig, ax = plt.subplots(figsize=(11, 5), dpi=150)

    # Plot line and fill area
    ax.plot(chart_dates, usd_toman_prices, color="#2563eb", linewidth=2.2, label="USD / Toman")
    ax.fill_between(chart_dates, usd_toman_prices, color="#3b82f6", alpha=0.15)

    # Annotate latest value
    latest_date = chart_dates[-1]
    latest_price = usd_toman_prices[-1]
    ax.plot(latest_date, latest_price, marker="o", markersize=6, color="#1d4ed8")
    ax.annotate(
        f"Latest: {latest_price:,} Toman",
        xy=(latest_date, latest_price),
        xytext=(-80, 15),
        textcoords="offset points",
        fontweight="bold",
        fontsize=9,
        color="#1e3a8a",
        bbox=dict(boxstyle="round,pad=0.4", fc="#dbeafe", ec="#3b82f6", lw=1),
        arrowprops=dict(arrowstyle="->", color="#3b82f6", lw=1)
    )

    # Axes formatting
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"{int(x):,}"))

    ax.set_title("USD to Toman Exchange Rate Trend (Calculated via Dubai AED)", fontsize=13, fontweight="bold", pad=15)
    ax.set_xlabel("Date", fontsize=10, labelpad=10)
    ax.set_ylabel("Price (Toman)", fontsize=10, labelpad=10)
    ax.grid(True, linestyle="--", alpha=0.5)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()
    print(f"Chart successfully saved to {output_file}")


def main():
    market_data = {
        "usd": "نامشخص",
        "oil": "نامشخص",
        "updated": "--:--"
    }

    print("Fetching page data from AlanChand...")
    resp_aed = session.get("https://alanchand.com/en/currencies-price/aed", timeout=15)
    resp_usd = session.get("https://alanchand.com/en/exchange-rates/aed-usd", timeout=15)

    aed_irr_history = []
    aed_usd_history = []

    if resp_aed.status_code == 200:
        aed_irr_history = extract_js_array(resp_aed.text, "fullPriceData")

    if resp_usd.status_code == 200:
        aed_usd_history = extract_js_array(resp_usd.text, "fullPriceData")

    # 1. Calculate live rate for market.json
    try:
        soup_usd = BeautifulSoup(resp_usd.text, "lxml")
        soup_aed = BeautifulSoup(resp_aed.text, "lxml")

        usd_input = soup_usd.find("input", id="inputCalcValue") or soup_usd.find("input", id="outputCalcValue")
        usd_rate = float(usd_input.get("data-rate")) if usd_input and usd_input.get("data-rate") else 0.2723

        aed_input = soup_aed.find("input", attrs={"data-curr": "tmn"})
        aed_price_raw = aed_input.get("data-price") or aed_input.get("value") if aed_input else None

        if aed_price_raw:
            aed_toman = float(str(aed_price_raw).replace(",", "").strip()) / 10.0
            live_usd_toman = int(round(aed_toman / usd_rate))
            market_data["usd"] = f"{live_usd_toman:,}"
    except Exception as e:
        print(f"Error computing live USD rate: {e}")

    # 2. Fetch live Oil price
    try:
        resp_oil = session.get("https://oilprice.com/oil-price-charts/46", timeout=15)
        if resp_oil.status_code == 200:
            soup_oil = BeautifulSoup(resp_oil.text, "lxml")
            oil_el = soup_oil.select_one(".last_price")
            if oil_el:
                market_data["oil"] = oil_el.get_text(strip=True)
    except Exception as e:
        print(f"Error fetching Oil price: {e}")

    market_data["updated"] = time.strftime("%H:%M")

    # 3. Save market.json
    with open("market.json", "w", encoding="utf-8") as f:
        json.dump(market_data, f, ensure_ascii=False, indent=2)
    print("market.json saved:", market_data)

    # 4. Generate USD/Toman chart from the extracted website chart arrays
    generate_usd_chart(aed_irr_history, aed_usd_history, output_file="usd_chart.png", days_limit=180)


if __name__ == "__main__":
    main()
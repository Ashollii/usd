import json
import os
import re
from datetime import datetime
import urllib.request
import requests
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager

# Ensure Tehran Timezone (UTC+3:30)
try:
    from zoneinfo import ZoneInfo
    TEHRAN_TZ = ZoneInfo("Asia/Tehran")
except Exception:
    from datetime import timezone, timedelta
    TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))


def get_tehran_now() -> datetime:
    """Returns the current datetime in Asia/Tehran timezone."""
    return datetime.now(TEHRAN_TZ)


# Bypass protection if available
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


def to_persian_digits(num_str: str) -> str:
    """Converts English digits in a string to Persian digits."""
    persian_digits = {
        "0": "۰", "1": "۱", "2": "۲", "3": "۳", "4": "۴",
        "5": "۵", "6": "۶", "7": "۷", "8": "۸", "9": "۹", ",": "،"
    }
    return "".join(persian_digits.get(char, char) for char in str(num_str))


def ensure_vazirmatn_font():
    """Downloads Vazirmatn font if not present and returns the font property."""
    font_path = "Vazirmatn-Bold.ttf"
    if not os.path.exists(font_path):
        url = "https://raw.githubusercontent.com/rastikerdar/vazirmatn/master/fonts/ttf/Vazirmatn-Bold.ttf"
        try:
            print("Downloading Vazirmatn font...")
            urllib.request.urlretrieve(url, font_path)
        except Exception as e:
            print(f"Failed to download Vazirmatn: {e}")
            return None

    if os.path.exists(font_path):
        font_manager.fontManager.addfont(font_path)
        return font_manager.FontProperties(fname=font_path)
    return None


def extract_js_array(html_text: str, var_name: str):
    """Extracts JSON array embedded in JavaScript script tags."""
    pattern = r"(?:const|let|var)\s+" + re.escape(var_name) + r"\s*=\s*(\[\s*\{.*?\}\]\s*);"
    match = re.search(pattern, html_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception as e:
            print(f"Error parsing JSON for {var_name}: {e}")
    return []


def update_history_api(aed_irr_history, aed_usd_history, live_usd_toman, api_dir="api"):
    """
    Maintains a persistent api/history.json file in Tehran timezone.
    """
    os.makedirs(api_dir, exist_ok=True)
    api_file = os.path.join(api_dir, "history.json")

    history_map = {}

    if os.path.exists(api_file):
        try:
            with open(api_file, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                for item in existing_data.get("history", []):
                    history_map[item["date"]] = item
        except Exception as e:
            print(f"Warning: could not read existing api/history.json: {e}")

    # Bootstrap if empty
    if not history_map and aed_irr_history:
        print("Bootstrapping historical database from website chart data...")
        usd_rate_by_date = {}
        for item in aed_usd_history:
            d = datetime.fromtimestamp(item["timestamp"], tz=TEHRAN_TZ).strftime("%Y-%m-%d")
            usd_rate_by_date[d] = item["rate"]

        for item in aed_irr_history:
            dt = datetime.fromtimestamp(item["timestamp"], tz=TEHRAN_TZ)
            d_str = dt.strftime("%Y-%m-%d")
            aed_toman = item["price"] / 10.0
            aed_usd = usd_rate_by_date.get(d_str, 0.272257)

            if aed_usd > 0:
                calc_usd_toman = int(round(aed_toman / aed_usd))
                history_map[d_str] = {
                    "timestamp": item["timestamp"],
                    "date": d_str,
                    "price_toman": calc_usd_toman,
                    "price_irr": calc_usd_toman * 10
                }

    now_tehran = get_tehran_now()
    today_str = now_tehran.strftime("%Y-%m-%d")
    current_ts = int(now_tehran.timestamp())

    if live_usd_toman is not None:
        history_map[today_str] = {
            "timestamp": current_ts,
            "date": today_str,
            "price_toman": live_usd_toman,
            "price_irr": live_usd_toman * 10
        }

    sorted_history = [history_map[k] for k in sorted(history_map.keys())]

    api_payload = {
        "symbol": "USD/TOMAN",
        "base_currency": "USD",
        "target_currency": "TOMAN",
        "timezone": "Asia/Tehran",
        "updated_at": now_tehran.strftime("%Y-%m-%d %H:%M:%S"),
        "total_records": len(sorted_history),
        "latest": sorted_history[-1] if sorted_history else None,
        "history": sorted_history
    }

    with open(api_file, "w", encoding="utf-8") as f:
        json.dump(api_payload, f, ensure_ascii=False, indent=2)

    print(f"API data saved to {api_file} ({len(sorted_history)} records).")
    return sorted_history


def generate_usd_chart(history_records, output_file="usd_chart.png", days_limit=180):
    if not history_records:
        print("No historical points available for chart.")
        return

    vazir_prop = ensure_vazirmatn_font()

    records = history_records[-days_limit:] if days_limit else history_records

    chart_dates = [datetime.strptime(item["date"], "%Y-%m-%d") for item in records]
    usd_toman_prices = [item["price_toman"] for item in records]

    plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
    fig, ax = plt.subplots(figsize=(11, 5), dpi=150)

    ax.plot(chart_dates, usd_toman_prices, color="#2563eb", linewidth=2.3)
    ax.fill_between(chart_dates, usd_toman_prices, color="#3b82f6", alpha=0.15)

    latest_date = chart_dates[-1]
    latest_price = usd_toman_prices[-1]
    formatted_price = to_persian_digits(f"{latest_price:,}")

    ax.plot(latest_date, latest_price, marker="o", markersize=6, color="#1d4ed8")
    ax.annotate(
        f"{formatted_price} تومان",
        xy=(latest_date, latest_price),
        xytext=(-95, 15),
        textcoords="offset points",
        fontproperties=vazir_prop,
        fontsize=10,
        color="#1e3a8a",
        bbox=dict(boxstyle="round,pad=0.4", fc="#dbeafe", ec="#3b82f6", lw=1),
        arrowprops=dict(arrowstyle="->", color="#3b82f6", lw=1)
    )

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y/%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: to_persian_digits(f"{int(x):,}")))

    if vazir_prop:
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            label.set_fontproperties(vazir_prop)

    ax.set_title("نمودار قیمت دلار به تومان (محاسبه از نرخ درهم امارات)", fontproperties=vazir_prop, fontsize=13, pad=15)
    ax.set_xlabel("تاریخ", fontproperties=vazir_prop, fontsize=10, labelpad=10)
    ax.set_ylabel("قیمت (تومان)", fontproperties=vazir_prop, fontsize=10, labelpad=10)
    ax.grid(True, linestyle="--", alpha=0.5)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()
    print(f"Chart saved to {output_file}")


def update_readme(market_data):
    """Generates a Persian README.md with explicit Tehran time."""
    usd_persian = to_persian_digits(market_data.get("usd", "نامشخص"))
    oil_persian = to_persian_digits(market_data.get("oil", "نامشخص"))
    updated_persian = to_persian_digits(market_data.get("updated", "--:--"))

    readme_content = f"""<div dir="rtl" align="center">

<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css">

<h1 style="font-family: 'Vazirmatn', sans-serif;">📈 آخرین قیمت دلار و نفت</h1>

<p style="font-family: 'Vazirmatn', sans-serif; font-size: 14px; color: #555;">
⏱ بروزرسانی خودکار هر ۳۰ دقیقه | آخرین بروزرسانی: <b>{updated_persian} (به وقت تهران)</b>
</p>

---

<table style="font-family: 'Vazirmatn', sans-serif; font-size: 16px; border-collapse: collapse;">
  <thead>
    <tr style="background-color: #f3f4f6;">
      <th style="padding: 12px 24px;">شاخص</th>
      <th style="padding: 12px 24px;">قیمت لحظه‌ای</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td style="padding: 12px 24px;">💵 <b>دلار آمریکا (آزاد)</b></td>
      <td style="padding: 12px 24px; color: #16a34a; font-weight: bold;">{usd_persian} تومان</td>
    </tr>
    <tr>
      <td style="padding: 12px 24px;">🛢️ <b>نفت خام اوپک / برنت</b></td>
      <td style="padding: 12px 24px; color: #2563eb; font-weight: bold;">{oil_persian} دلار</td>
    </tr>
  </tbody>
</table>

---

<h2 style="font-family: 'Vazirmatn', sans-serif; margin-top: 25px;">📊 روند ۶ ماهه قیمت دلار</h2>

<img src="usd_chart.png?raw=true" alt="نمودار قیمت دلار" width="95%" style="border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);" />

---

<h3 style="font-family: 'Vazirmatn', sans-serif; margin-top: 25px;">🌐 وب‌سرویس و API تاریخچه</h3>

<p style="font-family: 'Vazirmatn', sans-serif; font-size: 14px; color: #444;" dir="ltr">
JSON Endpoint: <code>api/history.json</code>
</p>

</div>
"""
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print("README.md updated.")


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

    # 1. Compute Live Rate
    live_usd_toman = None
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

    # 2. Live Oil Price
    try:
        resp_oil = session.get("https://oilprice.com/oil-price-charts/46", timeout=15)
        if resp_oil.status_code == 200:
            soup_oil = BeautifulSoup(resp_oil.text, "lxml")
            oil_el = soup_oil.select_one(".last_price")
            if oil_el:
                market_data["oil"] = oil_el.get_text(strip=True)
    except Exception as e:
        print(f"Error fetching Oil price: {e}")

    # Explicit Tehran Time
    now_tehran = get_tehran_now()
    market_data["updated"] = now_tehran.strftime("%H:%M")

    # 3. Save market.json
    with open("market.json", "w", encoding="utf-8") as f:
        json.dump(market_data, f, ensure_ascii=False, indent=2)

    # 4. Update History API
    history_records = update_history_api(aed_irr_history, aed_usd_history, live_usd_toman)

    # 5. Generate Chart
    generate_usd_chart(history_records, output_file="usd_chart.png", days_limit=180)

    # 6. Update README.md
    update_readme(market_data)


if __name__ == "__main__":
    main()

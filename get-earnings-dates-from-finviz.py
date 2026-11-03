import time
import sys
import requests
import os
import datetime
import json
import argparse
from html.parser import HTMLParser

#!/usr/bin/env python3
BASE_NEXTWEEK = "https://finviz.com/screener.ashx?v=161&f=cap_largeover,earningsdate_nextweek,sh_price_o50&o=earningsdate"
BASE_THISWEEK = "https://finviz.com/screener.ashx?v=161&f=cap_largeover,earningsdate_thisweek,sh_price_o50&o=earningsdate"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; script/1.0)"}
DEFAULT_COUNT = 20         # change as needed
DELAY_SECONDS = 0.1        # polite delay between requests


class ScreenerParser(HTMLParser):
    """Read stock rows from Finviz's server-rendered div grid."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self.div_depth = 0
        self.row_depth = None
        self.earnings_depth = None
        self.ticker = None
        self.earnings_parts = []

    def handle_starttag(self, tag, attrs):
        if tag != "div":
            return
        self.div_depth += 1
        attrs = dict(attrs)
        if attrs.get("role") == "row" and attrs.get("data-row-key"):
            self.row_depth = self.div_depth
            self.ticker = attrs["data-row-key"]
            self.earnings_parts = []
        elif self.row_depth is not None and attrs.get("data-column-id") == "earningsDate":
            self.earnings_depth = self.div_depth

    def handle_data(self, data):
        if self.earnings_depth is not None:
            self.earnings_parts.append(data)

    def handle_endtag(self, tag):
        if tag != "div":
            return
        if self.div_depth == self.earnings_depth:
            self.earnings_depth = None
        if self.div_depth == self.row_depth:
            earningsdate = " ".join("".join(self.earnings_parts).split())
            self.rows.append({
                "ticker": self.ticker,
                "scheduled_date": earningsdate or "N/A"
            })
            self.row_depth = None
            self.ticker = None
        self.div_depth -= 1


def parse_earnings(content: str):
    parser = ScreenerParser()
    parser.feed(content)
    parser.close()
    return parser.rows


def r_for_iteration(i: int):
    if i == 1:
        return None
    return 20 * i - 19


def fetch_and_save(i: int, base_url: str = BASE_NEXTWEEK):
    r = r_for_iteration(i)
    url = base_url if r is None else f"{base_url}&r={r}"
    print(f"[{i}] GET {url}")
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    filename = "finviz.html"
    # write as text using detected encoding
    resp.encoding = resp.encoding or "utf-8"
    with open(filename, "w", encoding="utf-8") as fh:
        fh.write(resp.text)
    print(f"[{i}] saved -> {filename}")

def read_weekly_options_from_csv(csv_path=os.path.join("docs", "data", "cboe_weekly_options.csv")):
    print(f"{datetime.datetime.now().strftime('%H:%M:%S')} - Fetching weekly options from CBOE.")
    # get CBOE weekly options first
    url = "https://www.cboe.com/available_weeklys/get_csv_download/"
    response = requests.get(url)
    if response.status_code == 200:
        with open(csv_path, "w") as f:
            f.write(response.text)
    
    weeklies = {}
    start_processing = False
    with open(csv_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not start_processing:
                if line == "Available Weeklys - Equity":
                    start_processing = True
                continue
            if line == "":
                continue
            parts = line.split(",",1)
            if len(parts) < 2:
                continue
            symbol = parts[0].strip().strip('"')
            stock_name = parts[1].strip().strip('"')
            weeklies[symbol] = stock_name
    
    print(f"{datetime.datetime.now().strftime('%H:%M:%S')} - Fetched {len(weeklies)} weekly options from CBOE.")
    return weeklies

def update_index_json(date_str: str, filename: str):
    index_path = os.path.join("docs", "data", "all-earnings-index.json")
    index_data = []
    
    # Read existing
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as fh:
                index_data = json.load(fh)
        except Exception as e:
            print(f"Error reading index json: {e}", file=sys.stderr)
    
    # Use a dictionary to ensure uniqueness by date. 
    # This automatically handles deduplication and overwrites.
    data_map = {item["date"]: item for item in index_data if "date" in item}
    
    # Add/Overwrite new entry
    data_map[date_str] = {"date": date_str, "filename": filename}
    
    # Convert back to list
    index_data = list(data_map.values())
    
    # Sort by date descending
    index_data.sort(key=lambda x: x["date"], reverse=True)
    
    try:
        with open(index_path, "w", encoding="utf-8") as fh:
            json.dump(index_data, fh, indent=2)
        print(f"Updated index with {date_str} -> {filename}")
    except Exception as e:
        print(f"Error writing index json: {e}", file=sys.stderr)

def week_start_date(today: datetime.date, this_week: bool = False):
    monday = today - datetime.timedelta(days=today.weekday())
    return monday if this_week else monday + datetime.timedelta(days=7)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Fetch weekly earnings dates from Finviz.")
    parser.add_argument("count", nargs="?", type=int, default=DEFAULT_COUNT,
                        help="maximum number of pages to fetch (default: %(default)s)")
    parser.add_argument("--this-week", action="store_true",
                        help="fetch this week's earnings instead of next week's")
    return parser.parse_args(argv)


def main(count: int, this_week: bool = False):
    base_url = BASE_THISWEEK if this_week else BASE_NEXTWEEK
    weeklies = read_weekly_options_from_csv()

    i = 1
    
    collected_earnings = []
    
    # Use the Monday of the same week as the selected Finviz filter.
    today = datetime.datetime.now().date()
    start_monday = week_start_date(today, this_week)
    date_str = start_monday.strftime("%Y-%m-%d")

    while i <= count:
        try:
            fetch_and_save(i, base_url)
        except Exception as e:
            print(f"[{i}] error: {e}", file=sys.stderr)
            i += 1
            time.sleep(DELAY_SECONDS)
            continue

        try:
            with open("finviz.html", "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
        except Exception as e:
            print(f"[{i}] read error: {e}", file=sys.stderr)
            i += 1
            time.sleep(DELAY_SECONDS)
            continue

        rows = parse_earnings(content)
        if not rows:
            print(f"[{i}] no stock rows found, stopping.")
            break

        valid_items_on_page = 0
        for row in rows:
            ticker = row["ticker"]
            if ticker not in weeklies:
                continue

            earningsdate = row["scheduled_date"]
            if earningsdate == "N/A":
                earningsdate_real_str = "N/A"
            else:
                date_part = earningsdate.split("/", 1)[0].strip()
                date_part = f"{date_part} {datetime.datetime.now().year}"
                try:
                    dt = datetime.datetime.strptime(date_part, "%b %d %Y")
                except ValueError:
                    try:
                        dt = datetime.datetime.strptime(date_part, "%B %d %Y")
                    except ValueError:
                        dt = None

                earningsdate_real_str = "N/A"
                if dt is not None:
                    if earningsdate.endswith("/b"):
                        dt -= datetime.timedelta(days=1)
                    earningsdate_real_obj = dt.date()
                    earningsdate_real_str = f"{earningsdate_real_obj} ({earningsdate_real_obj.strftime('%A')})"

            collected_earnings.append({
                "ticker": ticker,
                "scheduled_date": earningsdate,
                "open_trade_date": earningsdate_real_str
            })
            valid_items_on_page += 1

        print(f"[{i}] Processed page, found {valid_items_on_page} valid items.")

        if len(rows) < 20:
            break

        i += 1
        time.sleep(DELAY_SECONDS)

    # Save collected data
    filename = f"earnings-for-week-starting-{date_str}.json"
    file_path = os.path.join("docs", "data", filename)
    
    output_data = {
        "week_start": date_str,
        "data": collected_earnings
    }
    
    try:
        with open(file_path, "w", encoding="utf-8") as fh:
            json.dump(output_data, fh, indent=2)
        print(f"Saved {len(collected_earnings)} items to {filename}")
        
        update_index_json(date_str, filename)


        
    except Exception as e:
        print(f"Error saving data: {e}", file=sys.stderr)

    try:
        if os.path.exists("finviz.html"):
            os.remove("finviz.html")
            print("Removed finviz.html")
    except Exception as e:
        print(f"Error removing finviz.html: {e}", file=sys.stderr)

if __name__ == "__main__":
    args = parse_args()
    main(args.count, this_week=args.this_week)
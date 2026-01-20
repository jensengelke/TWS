import time
import sys
import requests
import re
import os
import datetime
import json

#!/usr/bin/env python3

BASE = "https://finviz.com/screener.ashx?v=161&f=cap_largeover,earningsdate_nextweek,sh_price_o50&o=earningsdate"
#BASE = "https://finviz.com/screener.ashx?v=161&f=cap_largeover,earningsdate_thisweek,sh_price_o50&o=earningsdate"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; script/1.0)"}
DEFAULT_COUNT = 20         # change as needed
DELAY_SECONDS = 0.1        # polite delay between requests


def r_for_iteration(i: int):
    if i == 1:
        return None
    return 20 * i - 19


def fetch_and_save(i: int):
    r = r_for_iteration(i)
    url = BASE if r is None else f"{BASE}&r={r}"
    print(f"[{i}] GET {url}")
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    filename = "finviz.html"
    # write as text using detected encoding
    resp.encoding = resp.encoding or "utf-8"
    with open(filename, "w", encoding=resp.encoding) as fh:
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

def main(count: int):
    weeklies = read_weekly_options_from_csv()

    i = 1
    marker = '<tr class="styled-row is-bordered is-rounded is-hoverable is-striped has-color-text" valign="top">'
    
    collected_earnings = []
    
    # Calculate target week start date (Monday)
    today = datetime.datetime.now().date()
    days_ahead = (0 - today.weekday()) % 7
    if days_ahead == 0:
         days_ahead += 7
    start_monday = today + datetime.timedelta(days=days_ahead)
    date_str = start_monday.strftime("%Y-%m-%d")

    while i <= count:
        try:
            fetch_and_save(i)
        except Exception as e:
            print(f"[{i}] error: {e}", file=sys.stderr)
            i += 1
            time.sleep(DELAY_SECONDS)
            continue

        try:
            with open(f"finviz.html", "r", errors="ignore") as fh:
                content = fh.read()
        except Exception as e:
            print(f"[{i}] read error: {e}", file=sys.stderr)
            i += 1
            time.sleep(DELAY_SECONDS)
            continue

        if marker in content:
            lines = content.splitlines()
            try:
                first_idx = next(j for j, line in enumerate(lines) if marker in line)
            except StopIteration:
                print(f"[{i}] marker not found in lines", file=sys.stderr)
            else:
                lines = lines[first_idx + 1 :]
                ticker_pattern = re.compile(r'.*class="tab-link">(.+?)</a>.*')
                earnings_pattern = re.compile(r'b=1" ">(... [0-9][0-9]/[a,b])')
                
                valid_items_on_page = 0
                for line in lines[:20]:
                    ticker_m = ticker_pattern.search(line)
                    earnings_m = earnings_pattern.search(line)
                    
                    if not ticker_m:
                        continue
                        
                    ticker = ticker_m.group(1)
                    if ticker not in weeklies:
                        continue
                    
                    earningsdate = earnings_m.group(1) if earnings_m else "N/A"
                    
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
                                try:
                                    dt -= datetime.timedelta(days=1)
                                except Exception:
                                    pass
                            earningsdate_real_obj = dt.date()
                            earningsdate_real_str = f"{earningsdate_real_obj} ({earningsdate_real_obj.strftime('%A')})"
                    
                    collected_earnings.append({
                        "ticker": ticker,
                        "scheduled_date": earningsdate,
                        "open_trade_date": earningsdate_real_str
                    })
                    valid_items_on_page += 1
                
                print(f"[{i}] Processed page, found {valid_items_on_page} valid items.")

        if marker not in content:
            print(f"[{i}] marker not found, stopping.")
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
    try:
        n = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_COUNT
    except ValueError:
        n = DEFAULT_COUNT
    main(n)
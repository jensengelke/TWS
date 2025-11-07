import time
import sys
import requests
import re
import os
import datetime
from shutil import copy2

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

def add_date_to_index(date_str: str):
    index_path = os.path.join("docs", "index.html")
    marker_html = "<!-- Additional data links can be added here -->"
    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()

        for idx, line in enumerate(lines):
            if marker_html in line:
                insert_idx = idx
                break
        else:
            insert_idx = None

        if insert_idx is not None:
            new_row = f"        <li><a href=\"data/earnings-for-week-starting-{date_str}.html\">Earnings for week starting {date_str}</a></li>\n"
            lines.insert(insert_idx + 1, new_row)
            with open(index_path, "w", encoding="utf-8") as fh:
                fh.writelines(lines)
            print(f"Added entry for week starting {date_str} to earnings index.")
        else:
            print("Index marker not found; could not add entry.")

    except Exception as e:
        print(f"Error updating earnings index: {e}", file=sys.stderr)

def main(count: int):
    weeklies = read_weekly_options_from_csv()

    i = 1
    marker = '<tr class="styled-row is-bordered is-rounded is-hoverable is-striped has-color-text" valign="top">'
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
                # delete all lines up to and including the marker line
                lines = lines[first_idx + 1 :]
                ticker_pattern = re.compile(r'.*class="tab-link">(.+?)</a>.*')
                earnings_pattern = re.compile(r'b=1" ">(... [0-9][0-9]/[a,b])')
                for line in lines[:20]:
                    ticker_m = ticker_pattern.search(line)
                    earnings_m = earnings_pattern.search(line)
                    ticker = ticker_m.group(1) if ticker_m else "N/A"
                    if not ticker in weeklies:
                        print(f"[{i}] skipping {ticker} as not in weekly options list.")
                        continue
                    earningsdate = earnings_m.group(1) if earnings_m else "N/A"
                    # convert "Oct 22/a" -> actual date in current year (earningsdate_real)
                    if earningsdate == "N/A":
                        earningsdate_real = "N/A"
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
                        if dt is not None:
                            if earningsdate.endswith("/b"):
                                try:
                                    dt -= datetime.timedelta(days=1)
                                except Exception:
                                    pass
                            earningsdate_real = dt.replace(year=datetime.datetime.now().year).date()
                        else:
                            earningsdate_real = "N/A"

                        # append weekday name in English in brackets
                        earningsdate_real = f"{earningsdate_real} ({earningsdate_real.strftime('%A')})"
                    try:
                        today = datetime.datetime.now().date()
                        days_ahead = (0 - today.weekday()) % 7
                        if days_ahead == 0:
                            days_ahead += 7
                        start_monday = today + datetime.timedelta(days=days_ahead)
                        date_str = start_monday.strftime("%Y-%m-%d")
                        p = os.path.join("docs", "data", f"earnings-for-week-starting-{date_str}.html")
                        if not os.path.exists(p):
                            template = os.path.join("docs", "data","earnings-template.html")
                            copy2(template, p)
                        marker_html = "<!-- Earnings data rows will be inserted here -->"
                        marker_date = "Earnings Dates - week starting REPLACE"
                        with open(p, "r", encoding="utf-8") as fh:
                            lines = fh.readlines()

                        for idx, line in enumerate(lines):
                            if marker_date in line:
                                date_idx = idx
                                print(f"found replace in line {date_idx}")
                                continue
                            if marker_html in line:
                                insert_idx = idx
                                break
                        else:
                            insert_idx = None
                            date_idx = None

                        if date_idx is not None:
                            print(f"replacing date in line {date_idx}")
                            lines[date_idx] = lines[date_idx].replace("REPLACE", date_str)
                        else:
                            print(f"[{i}] date marker not found")
                        
                        if insert_idx is not None:
                            new_row = f"<tr><td><a href=\"https://finviz.com/quote.ashx?t={ticker}\" target=\"_blank\">{ticker}</a></td><td>{earningsdate}</td><td>{earningsdate_real}</td></tr>\n"
                            lines.insert(insert_idx, new_row)
                            with open(p, "w", encoding="utf-8") as fh:
                                fh.writelines(lines)
                        
                    except Exception as e:
                        print(f"[{i}] write error: {e}", file=sys.stderr)

        if marker not in content:
            print(f"[{i}] marker not found, stopping.")
            break

        i += 1
        time.sleep(DELAY_SECONDS)

    add_date_to_index(date_str)
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
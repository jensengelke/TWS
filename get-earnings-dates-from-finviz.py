import time
import sys
import requests
import re
import os
from datetime import datetime
import datetime as _dt
from shutil import copy2

#!/usr/bin/env python3

BASE = "https://finviz.com/screener.ashx?v=161&f=cap_largeover,earningsdate_nextweek,sh_price_o50&o=earningsdate"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; script/1.0)"}
DEFAULT_COUNT = 10         # change as needed
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


def main(count: int):
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
                    earningsdate = earnings_m.group(1) if earnings_m else "N/A"
                    # convert "Oct 22/a" -> actual date in current year (earningsdate_real)
                    if earningsdate == "N/A":
                        earningsdate_real = "N/A"
                    else:
                        date_part = earningsdate.split("/", 1)[0].strip()
                        date_part = f"{date_part} {datetime.now().year}"
                        try:
                            dt = datetime.strptime(date_part, "%b %d %Y")
                        except ValueError:
                            try:
                                dt = datetime.strptime(date_part, "%B %d %Y")
                            except ValueError:
                                dt = None
                        if dt is not None:
                            if earningsdate.endswith("/b"):
                                try:
                                    dt -= _dt.timedelta(days=1)
                                except Exception:
                                    pass
                            earningsdate_real = dt.replace(year=datetime.now().year).date()
                        else:
                            earningsdate_real = "N/A"

                        # append weekday name in English in brackets
                        earningsdate_real = f"{earningsdate_real} ({earningsdate_real.strftime('%A')})"
                    try:
                        today = datetime.now().date()
                        days_ahead = (0 - today.weekday()) % 7
                        start_monday = today + _dt.timedelta(days=days_ahead)
                        date_str = start_monday.strftime("%Y-%m-%d")
                        p = os.path.join("pages", "data", f"earnings-for-week-starting-{date_str}.html")
                        if not os.path.exists(p):
                            template = os.path.join("pages", "data","earnings-template.html")
                            copy2(template, p)
                        marker_html = "<!-- Earnings data rows will be inserted here -->"
                        marker_date = "<h1>Earnings Dates - week starting (REPLACE)</h1>"
                        with open(p, "r", encoding="utf-8") as fh:
                            lines = fh.readlines()

                        for idx, line in enumerate(lines):
                            if marker_date in line:
                                lines[idx] = line.replace("REPLACE", date_str)
                                break
                            if marker_html in line:
                                insert_idx = idx
                                break
                        else:
                            insert_idx = None

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




if __name__ == "__main__":
    try:
        n = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_COUNT
    except ValueError:
        n = DEFAULT_COUNT
    main(n)
import argparse
import datetime
import json
import os
import pandas as pd
import requests
import sys
from enum import IntEnum

class Weekday(IntEnum):
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6

def get_apikey_from_config(config_file: str):
    
    with open(config_file, "r") as f:
        config = json.load(f)
    
    if not config:
        print(f"Create a configuration file at {config_file} with your Finnhub API key:")
        print('"apikey": "YOUR_API_KEY"}')
        sys.exit(1)

    apikey= config.get("apikey", "")
    if not apikey:
        print(f"API key not found in {config_file}. Please add your Finnhub API key.")
        sys.exit(1)
    
    print(f"{datetime.datetime.now().strftime("%H:%M:%S")} - Obtained API key from configuration file: {config_file}")
    return apikey

def get_earnings_dates( config_file: str, this_week=False, start_date: str = "", end_date: str = ""):
    print(f"{datetime.datetime.now().strftime("%H:%M:%S")} - Invoking Finnhub API to get earnings dates for next week...")
    url = f"https://finnhub.io/api/v1/calendar/earnings"
    
    if start_date == "" or start_date is None:
        # weekday is 0 for Monday, 1 for Tuesday, ..., 6 for Sunday
        today = datetime.date.today()
        monday = today - datetime.timedelta(days=today.weekday()) 
        if not this_week:
            monday = monday + datetime.timedelta(days=7)
        start_date = monday.strftime("%Y-%m-%d")
    if end_date == "" or end_date is None:        
        end_date = (datetime.datetime.strptime(start_date, "%Y-%m-%d").date() + datetime.timedelta(days=4)).strftime("%Y-%m-%d")
        
    params = {
        "from": start_date,
        "to": end_date
    }
    
    print(f"  > From {params['from']}, To {params['to']}")

    headers = { "X-Finnhub-Token": get_apikey_from_config(config_file=config_file) }
    response = requests.get(url=url, params=params, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        print(f"response:\n{response.text}")
        result = [  {"symbol": entry["symbol"], "date": str(entry["date"]), "hour": entry["hour"]} 
            for entry in data.get("earningsCalendar", [])]
        print(f"{datetime.datetime.now().strftime('%H:%M:%S')} - Response received with {len(result)} earnings dates.")
        return result
        
    else:
        return f"Error fetching data: {response.status_code}"
    

def get_weekly_options_from_cboe(csv_path="weekly_options.csv"):
    print(f"{datetime.datetime.now().strftime('%H:%M:%S')} - Fetching weekly options from CBOE...")

    url = "https://www.cboe.com/available_weeklys/get_csv_download/"    
    response = requests.get(url)
    if response.status_code == 200:
        with open(csv_path, "w") as f:
            f.write(response.text)
    
def read_weekly_options_from_csv(csv_path="weekly_options.csv"):
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

# Helper to write CSV in required format
def write_custom_csv(dataframe, filename):
    with open(filename, "w") as f:
        for _, row in dataframe.iterrows():
            f.write(f"DES,{row['symbol']},STK,SMART/AMEX,,,,\n")

def create_dataframe_from_earnings_with_weekly_options(earnings_dates, weeklies):
    rows = []
    for entry in earnings_dates:
        symbol = entry["symbol"]
        date = entry["date"]
        hour = entry["hour"]
        if symbol in weeklies:
            name = weeklies[symbol]
            # Calculate tradedate
            if hour.lower() == "amc":
                tradedate = date
            elif hour.lower() == "bmo":
                tradedate = (datetime.datetime.strptime(date, "%Y-%m-%d") - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                tradedate = date
            # Calculate weekday name
            weekday = datetime.datetime.strptime(tradedate, "%Y-%m-%d").strftime("%A")
            rows.append({
                "symbol": symbol,
                "name": name,
                "earningsdate": date,
                "earningshour": hour,
                "tradedate": tradedate,
                "weekday": weekday
            })
    print(f"number of rows: {len(rows)}")
    return pd.DataFrame(rows)

def main(args):
    if not args.skip_weekly_options:
        get_weekly_options_from_cboe()
    else:
        print(f"{datetime.datetime.now().strftime('%H:%M:%S')} - Skipping fetching weekly options from CBOE. Assuming 'weekly_options.csv' exists in the current directory.")

    weeklies = read_weekly_options_from_csv()
    earnings_dates = get_earnings_dates(this_week = args.this_week, start_date=args.start, end_date=args.end, config_file=args.config)
    
    df = create_dataframe_from_earnings_with_weekly_options(earnings_dates, weeklies)
    if (df.empty):
        print(f"{datetime.datetime.now().strftime('%H:%M:%S')} - No valid earnings data found.")
        return
    df = df.sort_values(by="tradedate", ascending=True)
    print(df.to_string(index=False, justify="left"))

    # Prepare output directory
    output_dir = args.output
    print(f"{datetime.datetime.now().strftime('%H:%M:%S')} - Creating earnings dates CSV files in {output_dir}...")

    # Write all rows to earnings.csv
    write_custom_csv(df, os.path.join(output_dir, "earnings.csv"))

    # Write one file per weekday
    for weekday in df["weekday"].unique():
        weekday_df = df[df["weekday"] == weekday]
        fname = f"earnings_{weekday.lower()}.csv"
        write_custom_csv(weekday_df, os.path.join(output_dir, fname))
    

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Get earnings dates and weekly options.")
    parser.add_argument("--config", type=str, default=".config/finnhub.json", help="Path to the Finnhub API key configuration file. Default is '.config/finnhub.json'.")
    parser.add_argument("--output", type=str, default="c:/jts", help="Output directory for the earnings dates CSV files. Default is 'c:/jts'.")
    parser.add_argument("--skip-weekly-options", action="store_true", help="Skip fetching weekly options from CBOE. The script assumes that a file weekly_options.csv exists in the current directory.", default=False)
    parser.add_argument("--this-week", action="store_true", help="Get this week's earnings.", default=False)
    parser.add_argument("--start", type=str, help="Start date for earnings dates in YYYY-MM-DD format. If not provided, the script will use the next Monday's date.", default=None)
    parser.add_argument("--end", type=str, help="End date for earnings dates in YYYY-MM-DD format. If not provided, the script will use the next Friday's date.", default=None)
    args = parser.parse_args()

    main(args)
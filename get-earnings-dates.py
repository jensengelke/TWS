import requests
import datetime
import json
import sys
import pandas as pd

def get_apikey_from_config():
    file = ".config/finnhub.json"
    with open(file, "r") as f:
        config = json.load(f)
    
    if not config:
        print(f"Create a configuration file at {file} with your Finnhub API key:")
        print('"apikey": "YOUR_API_KEY"}')
        sys.exit(1)

    apikey= config.get("apikey", "")
    if not apikey:
        print(f"API key not found in {file}. Please add your Finnhub API key.")
        sys.exit(1)
    
    return apikey

def get_earnings_dates():
    url = f"https://finnhub.io/api/v1/calendar/earnings"
    params = {
        "from": compute_next_weeks_monday(),  # Use the function to get next Monday's date
        "to": compute_next_weeks_friday()  # Use the function to get next Friday's date
    }

    headers = { "X-Finnhub-Token": get_apikey_from_config() }

    response = requests.get(url=url, params=params, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        result = [  {"symbol": entry["symbol"], "date": str(entry["date"]), "hour": entry["hour"]} 
            for entry in data.get("earningsCalendar", [])]
        return result
        
    else:
        return f"Error fetching data: {response.status_code}"
    

def get_weekly_options_from_cboe():
    csv_path = "weekly_options.csv"
    url = "https://www.cboe.com/available_weeklys/get_csv_download/"    
    response = requests.get(url)
    if response.status_code == 200:
        with open(f"weekly_options.csv", "w") as f:
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
            
    return weeklies

def compute_next_weeks_friday():
    today = datetime.date.today()
    # Friday is weekday 4 (Monday=0)
    days_until_friday = (4 - today.weekday() + 7) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    next_friday = today + datetime.timedelta(days=days_until_friday)
    return next_friday.strftime("%Y-%m-%d")

def compute_next_weeks_monday():
    today = datetime.date.today()
    # Monday is weekday 0 (Monday=0)
    days_until_monday = (0 - today.weekday() + 7) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    next_monday = today + datetime.timedelta(days=days_until_monday)
    return next_monday.strftime("%Y-%m-%d")

def main():
    weeklies = get_weekly_options_from_cboe()
    earnings_dates = get_earnings_dates()
    
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
            rows.append({
                "symbol": symbol,
                "name": name,
                "earningsdate": date,
                "earningshour": hour,
                "tradedate": tradedate
            })
    
    df = pd.DataFrame(rows)
    df = df.sort_values(by="tradedate", ascending=True)
    print(df.to_string(index=False, justify="left"))

if __name__ == "__main__":
    main()
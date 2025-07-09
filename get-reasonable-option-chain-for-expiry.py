from ibapi.client import *
from ibapi.wrapper import *
import threading
import time
import pandas as pd
import argparse


argparse = argparse.ArgumentParser(description="Get reasonable option chain for expiry")
argparse.add_argument("--contract", help="SPX and SPY are supported. Default is SPX", default="SPX")
argparse.add_argument("--min-dte", help="Minimum number of days AFTER a date in historic data to get an option chain", default=90)
argparse.add_argument("--max-dte", help="Maximum number of days AFTER a date in historic data to get an option chain", default=120)
args = argparse.parse_args()

mycontract = Contract()
if args.contract.upper() == "SPY":
    mycontract.symbol = "SPY"
    mycontract.secType = "STK"
    mycontract.exchange = "SMART"
    mycontract.currency = "USD"
else:
    print("Using default contract SPX")
    mycontract.symbol = "SPX"
    mycontract.secType = "IND"
    mycontract.exchange = "CBOE"
    mycontract.currency = "USD"

#format YYYYMMDD
#Get current date in format YYYYMMDD
current_date = pd.Timestamp.now().strftime('%Y%m%d')
min_date = pd.Timestamp.now() - pd.Timedelta(days=int(args.max_dte))
max_date = pd.Timestamp.now() - pd.Timedelta(days=int(args.min_dte))
print(f"Current date: {current_date}")
print(f"Min date: {min_date.strftime('%Y%m%d')}")
print(f"Max date: {max_date.strftime('%Y%m%d')}")

#Read historic data from CSV file
filename = f"historic-{mycontract.symbol.lower()}.csv"
try:
    data = pd.read_csv(filename)
    print(f"Read {len(data)} rows from {filename}")
except FileNotFoundError:
    print(f"File {filename} not found. Please run get-one-year-historic-data-5min.py first.")
    exit(1) 

#Find contract close values for dates between min_date and max_date
# Make sure your DataFrame's 'date' column is also in datetime format
data['date'] = pd.to_datetime(data['date'], format='%Y%m%d')

# Filter using datetime comparisons
mask = (data['date'] >= min_date) & (data['date'] <= max_date)
filtered_df = data[mask]

min_low = filtered_df['low'].min()
max_high = filtered_df['high'].max()

print("Minimum Low:", min_low)
print("Maximum High:", max_high)
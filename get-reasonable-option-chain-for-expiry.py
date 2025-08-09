# For SPX and SPY data in historic-<symbol>.csv get the ATM straddle option with 90-120 days to expiration
# Download historic data for that chain and save it to a CSV file

import argparse
import json
import logging
import os
import threading
import time
import pandas as pd
from ibapi.client import *
from ibapi.wrapper import *


args = {} # command line arguments
ibrequests_contractDetails = {} # keep track of requests for contract details
ibrequests_historicData = {} # keep track of requests for historic data
ibrequests_request_keys = {} # avoid duplicate requests
relevant_contracts = {} # keep track of relevant contracts
historic_data = {} # dict of dataframes for historic data (key is contract long name)
mycontract = None  # global variable for the contract we are interested in


# callback functions when IB returns data
class IBConnection(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)        

    def nextValidId(self, orderId: int):
        self.orderId = orderId
        
    def nextId(self):
        self.orderId += 1
        return self.orderId

    def error(self, reqId: int, errorCode: int, errorString: str, advancedOrderRejectJson=""):
        if reqId == -1:
            error_message = f"Connection setup: {errorString}"
        else:
            error_message = f"Error. Id: {reqId}, Code: {errorCode}, Msg: {errorString}"
        logging.info(error_message)
        # remove the entry from ibrequests_contractDetails where the key is reqId
        if reqId in ibrequests_contractDetails:
            del ibrequests_contractDetails[reqId]
        # remove the entry from ibrequests_historicData where the key is reqId
        if reqId in ibrequests_historicData and errorCode != 2176:            
            del ibrequests_historicData[reqId]

    def contractDetails(self, reqId: int, contractDetails):        
        if not contractDetails in relevant_contracts:
            relevant_contracts[reqId] = contractDetails
                
    def contractDetailsEnd(self, reqId: int):
        ibrequests_contractDetails.pop(reqId, None)  # Remove the request from the tracking dictionary
        contract_details = relevant_contracts.get(reqId)
        filename = get_filename_for_contract_details(contract_details.contract)
        # Save contract details to a JSON file
        try:
            if contract_details:
                with open(filename, 'w') as f:
                    json.dump(contract_details_to_dict(contract_details), f, indent=4)
        except Exception as e:
            logging.error(f"Error saving contract details to {filename}: {e}")
            exit(1)

    def historicalData(self, reqId: int, bar):
        split_date = bar.date.split('  ')
        row= {
            'date': split_date[0],  # Extract date part only
            'time': split_date[1],  # Extract time part only
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close
        }
        ibrequests_historicData[reqId]['data'].loc[len(ibrequests_historicData[reqId]['data'])] = row
        
    def historicalDataEnd(self, reqId: int, start: str, end: str):
        self.cancelHistoricalData(reqId)
        contract = ibrequests_historicData[reqId]['contract']
        filename=get_filename_for_historic_data(contract)
        ibrequests_historicData[reqId]['data'].to_csv(filename, index=False)
        ibrequests_historicData.pop(reqId, None)  # Remove the request from the tracking dictionary
        

def contract_details_to_dict(obj):
    if hasattr(obj, "__dict__"):
        result = {}
        for key, value in obj.__dict__.items():
            # Recursively convert nested objects
            result[key] = contract_details_to_dict(value)
        return result
    elif isinstance(obj, list):
        return [contract_details_to_dict(item) for item in obj]
    else:
        return obj

def get_filename_for_historic_data(contract):
    symbol = contract.localSymbol.replace(" ", "")  # Remove spaces from the symbol
    if not symbol or symbol == "":
        symbol = contract.symbol.replace(" ", "")  # Fallback to the symbol if localSymbol is empty
    return f"historic-data/historic-{symbol}.csv"

def get_filename_for_contract_details(contract):
    symbol = contract.localSymbol.replace(" ", "")  # Remove spaces from the symbol
    if not symbol or symbol == "":
        symbol = contract.symbol.replace(" ", "")  # Fallback to the symbol if localSymbol is empty
    return f"contract-details/contract-details-{symbol}.csv"


def find_atm_straddle_options(symbol, expiry, strike):
    if expiry < pd.Timestamp.now():
        logging.debug(f"Expiry {expiry} is in the past. Skipping.")
        return
    
    # skip saturday and sunday
    if expiry.weekday() >= 5:
        logging.debug(f"Expiry {expiry} is on a weekend. Skipping.")
        return  
    
    request_key = f"{symbol}-{expiry_date.strftime('%Y%m%d')}-{atm_strike}"
    if request_key in ibrequests_request_keys:
        logging.debug(f"Request for {symbol} with expiry {expiry} and strike {strike} already exists. Skipping.")
        return
    #invoke ibapi to find ATM straddle options for the given expiry and strike
    contract = Contract()
    contract.symbol = symbol
    contract.secType = "OPT"
    contract.exchange = "SMART"
    contract.currency = "USD"
    contract.lastTradeDateOrContractMonth = expiry.strftime('%Y%m%d')
    contract.strike = strike
    reqId = app.nextId()
    logging.debug(f"Requesting contract details for {contract} with reqId {reqId}")
    app.reqContractDetails(reqId, contract)
    ibrequests_contractDetails[reqId] = contract
    
def print_progress_bar(iteration, total, length=40):
    percent = f"{100 * (iteration / float(total)):.1f}"
    filled_length = int(length * iteration // total)
    bar = '█' * filled_length + '-' * (length - filled_length)
    sys.stdout.write(f"\rProgress: |{bar}| {percent}% Complete")
    sys.stdout.flush()
    if iteration == total:
        print()  # Move to next line when done

def connect():
    app.run()


def init():
    try:
        argparse.add_argument("--contract", help="SPX and SPY are supported. Default is SPX", default="SPX")
        argparse.add_argument("--min-dte", help="Minimum number of days AFTER a date in historic data to get an option chain", default=90, type=int)
        argparse.add_argument("--max-dte", help="Maximum number of days AFTER a date in historic data to get an option chain", default=120, type=int)
        argparse.add_argument("--skip-contract-details", help="Skip requesting contract details for the given symbol", action='store_true')
        argparse.add_argument("--skip-historic-data", help="Skip requesting historic data for the given symbol", action='store_true')
        argparse.add_argument("--bar-size", help="Bar size for historic data. Default is 5 mins", default="5 mins")
        args = argparse.parse_args()
    except Exception as e:
        print(f"Error parsing command line arguments: {e}")
        exit(1)
    
    app = IBConnection()
    print("Starting IB API Test Application...")
    #logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', filename='get-reasonable-option-chain-for-expiry.log', filemode='w')
    random_client_id = int(time.time()) % 1000  # Generate a random client ID
    app.connect("127.0.0.1", 7496, clientId=random_client_id)
    print("Connecting to TWS...")
    time.sleep(1)
    print("serverVersion:%s connectionTime:%s" % (app.serverVersion(), app.twsConnectionTime()))
    threading.Thread(target=app.run, daemon=True).start()
    app.orderId=0

    mycontract = Contract()
    if args.contract.upper() == "SPY":
        print("Using contract SPY")
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

    return args, app, mycontract

argparse = argparse.ArgumentParser(description="Get reasonable option chain for expiry")
args, app, mycontract = init()

# (1) request and store contract details for the given symbol
if not args.skip_contract_details:
    reqId = app.nextId()
    ibrequests_contractDetails[reqId] = mycontract
    app.reqContractDetails(reqId, mycontract)
    # remove from relevant_contracts if it exists
    if reqId in relevant_contracts:
        del relevant_contracts[reqId]

# (2) request historic data for the given symbol
underlying_historic_data_filename = get_filename_for_historic_data(mycontract)
if not args.skip_historic_data:
    # delete previous file if it exists
    max_wait_time = 90 # seconds
    try:
        os.remove(underlying_historic_data_filename)
    except FileNotFoundError:
        pass
    reqId = app.nextId()
    yesterday = (pd.Timestamp.now() - pd.Timedelta(days=1)).strftime('%Y%m%d')
    duration = f"{int(args.max_dte)} D"
    ibrequests_historicData[reqId] = { 'contract': mycontract, 'data': pd.DataFrame(columns=['date', 'time', 'open', 'high', 'low', 'close'])}
    print(f"Requesting historical data for {mycontract.symbol} from {yesterday} with duration {duration} and bar size {args.bar_size}")
    app.reqHistoricalData(reqId, contract=mycontract, endDateTime=f"{yesterday}-23:59:59",
                      durationStr=duration, barSizeSetting=args.bar_size, whatToShow="TRADES",useRTH=1, 
                      formatDate=1, keepUpToDate=False,chartOptions=[])
    
    print(f"Waiting for {underlying_historic_data_filename} to be created with historical data for {mycontract.symbol}... max wait time is {max_wait_time} seconds")
    while max_wait_time > 0 and (not os.path.exists(underlying_historic_data_filename)):
        max_wait_time -= 1
        print_progress_bar(iteration=max_wait_time, total=90)
        time.sleep(1)

# (3) determine unique dates in the historic data and find ATM straddle options for each date's latest close
# (3.1) Read historic data from CSV file
underlying_data_df = pd.read_csv(underlying_historic_data_filename)
if underlying_data_df.empty:
    print(f"No historic data found for {mycontract.symbol}. Please run get-one-year-historic-data-5min.py first.")
    exit(1)
else:
    print(f"Read {len(underlying_data_df)} rows from {underlying_historic_data_filename}")

# (3.2) Convert 'date' column to datetime format
underlying_data_df['date'] = pd.to_datetime(underlying_data_df['date'], format='%Y%m%d')

# (3.3) Filter data for the at most max_dte days
min_date = pd.Timestamp.now() - pd.Timedelta(days=args.max_dte)
underlying_data_df['date'] = pd.to_datetime(underlying_data_df['date'], format='%Y%m%d')
underlying_data_df = underlying_data_df[underlying_data_df['date'] >= min_date]
print(f"filter historic data to dates between {underlying_data_df['date'].min()} and {underlying_data_df['date'].max()}")

# (3.4) Iterate through unique dates from the filtered data
unique_dates = underlying_data_df['date'].unique()
for index, current_date in enumerate(unique_dates):
    rows_for_date = underlying_data_df[underlying_data_df['date'] == current_date]
    if not rows_for_date.empty:
        # Get the last row for this date
        last_row = rows_for_date.iloc[-1]
        current_close = last_row['close']
    else:
        current_close = None  # or handle as needed
        continue
    
    # Calculate the strike price for ATM options
    atm_strike = round(current_close / 5) * 5  # Round to nearest 5 for SPX/ES
    list_of_requests = {}
    for dte in range(int(args.min_dte), int(args.max_dte) + 1):
        expiry_date = current_date + pd.Timedelta(days=dte)
        #print(f"Processing row for {current_date.strftime('%Y-%m-%d')} with close {current_close}. Searching for ATM strike {atm_strike} for expiry {expiry_date.strftime('%Y-%m-%d')}")
        find_atm_straddle_options(mycontract.symbol, expiry_date, atm_strike)

total_requests = len(ibrequests_contractDetails)
print(f"Searching for contract details for {total_requests} contracts.")
while ibrequests_contractDetails:
    print_progress_bar(iteration=total_requests - len(ibrequests_contractDetails), total=total_requests)
    time.sleep(0.2)

# (4) Request historical data for each relevant contract found
for contract_details in relevant_contracts.values():
    reqId = app.nextId()
    ibrequests_historicData[reqId] = {'contract': contract_details.contract, 'data': pd.DataFrame(columns=['date', 'time', 'open', 'high', 'low', 'close'])}
    print(f"Requesting historical data for {contract_details.contract.localSymbol} with reqId {reqId}")
    yesterday = (pd.Timestamp.now() - pd.Timedelta(days=1)).strftime('%Y%m%d')
    duration = f"{int(args.max_dte)} D"
    app.reqHistoricalData(reqId, contract=contract_details.contract, endDateTime=f"{yesterday}-23:59:59", durationStr=duration,
                            barSizeSetting='5 mins', whatToShow='TRADES', useRTH=1, formatDate=1, keepUpToDate=False, chartOptions=[])

total_requests = len(ibrequests_historicData)
max_wait_time = 6000 # seconds
print(f"Waiting for historic data to be downloaded max wait time is {max_wait_time} seconds.\n\n")
while max_wait_time > 0 and ibrequests_historicData:
    max_wait_time -= 1
    print_progress_bar(iteration=(total_requests-len(ibrequests_historicData)), total=total_requests)
    time.sleep(1)

userinput = input("Press any other key to exit...")
app.disconnect()
exit(0) 

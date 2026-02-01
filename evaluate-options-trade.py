from typing import Callable
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract, ContractDetails
from ibapi.common import SetOfString, SetOfFloat, TickerId
from ibapi.ticktype import TickType, TickTypeEnum
from decimal import Decimal
import argparse
import logging
import threading
import time
import datetime
import sys
import pandas as pd
import json
import os

class PriceData:
    stock_fields = ["LAST", "ASK", "BID"] # valid for all sec types
    option_fields = ["LAST", "ASK", "BID", "DELTA", "GAMMA", "VEGA", "IV"] #  "OPTION_CALL_OPEN_INTEREST", "OPTION_PUT_OPEN_INTEREST"

    def __init__(self, security_type :str = "OPT"):
        self.security_type = security_type
        self.data = {}
        
    def to_str(self):
        return ", ".join(f"{k}={v}" for k, v in self.data.items() if v is not None)

    def update(self, value, field_name: str):
        self.data[field_name] = value

    def is_complete(self):
        complete : bool = True
        if self.security_type == "OPT":
            for f in self.option_fields:
                if f not in self.data or self.data[f] is None:
                    complete = False
                    break
        if self.security_type == "STK":
            for f in self.stock_fields:
                if f not in self.data or self.data[f] is None:
                    complete = False
                    break
        return complete
    
    def get(self, field_name: str):
        return self.data.get(field_name, None)

    def get_instrument_value(self):
        val = self.data.get("MARK_PRICE")
        if val is not None:
            return val
        bid = self.data.get("BID")
        ask = self.data.get("ASK")
        if bid is not None and ask is not None:
            return (bid + ask) / 2
        return None

class IncompleteDataError(Exception):
    """Raised when the expected move cannot be determined due to missing option data."""
    pass

class EarningsApp(EWrapper, EClient):
    requestId = 0
    def __init__(self):
        EClient.__init__(self, self)

    def nextId(self):
        self.requestId += 1
        logging.debug(f"Next request ID: {self.requestId}")
        return self.requestId

    def contractDetails(self, reqId: int, contractDetails):
        logging.debug(f"Contract details for reqId {reqId}: {contractDetails}")
        if reqId in ibrequests_contractDetails:
            type = ibrequests_contractDetails[reqId]["type"]
            logging.debug(f"Contract details for {ibrequests_contractDetails[reqId]}: ({type}) {contractDetails}")
            if type == "stock_contract":
                contract_details_data[contractDetails.contract.symbol] = contractDetails
                contract_data[contractDetails.contract.symbol] = contractDetails.contract
            if type == "option_chain":
                underlying = ibrequests_contractDetails[reqId]["underlying"]
                options_chain[underlying][contractDetails.contract.localSymbol] = contractDetails
                logging.debug(f"Option chain for reqId {reqId}: {contractDetails}") 
                
    def contractDetailsEnd(self, reqId: int):
        logging.debug(f"Contract details end for reqId: {reqId}")
        ibrequests_contractDetails.pop(reqId, None)
            
    # Called with option chain parameters in response to reqSecDefOptParams
    def securityDefinitionOptionParameter(
        self,
        reqId: int,
        exchange: str,
        underlyingConId: int,
        tradingClass: str,
        multiplier: str,
        expirations: SetOfString,
        strikes: SetOfFloat,
    ):
        logging.debug(f"Received option parameters for reqId {reqId}")
        print("Expirations:", expirations)
        print("Strikes:", strikes)

    # Called when market data price ticks are received.
    def tickPrice(self, reqId: TickerId, tickType: int, price: float, attrib):
        if not reqId in ibrequests_marketData:
            return
        else:
            contract: Contract = ibrequests_marketData[reqId]
            key = contract.localSymbol if contract.localSymbol else contract.symbol
            #print(f"{key} - tickPrice: {TickTypeEnum.toStr(tickType)}={price}")
            if not key in price_data:
                tick_price_data = PriceData(contract.secType)
            else:
                tick_price_data : PriceData = price_data[key]
                
            tick_price_data.update(price, TickTypeEnum.toStr(tickType))
            price_data[key] = tick_price_data
            if tick_price_data.is_complete():
                ibrequests_marketData.pop(reqId)
                self.cancelMktData(reqId)
    
    def tickSize(self, reqId: TickerId, tickType: TickType, size: Decimal):
        #print(f"tickSize: {TickTypeEnum.toStr(tickType)} ({tickType})={size}")
        if not reqId in ibrequests_marketData:
            return
        else:
            contract: Contract = ibrequests_marketData[reqId]
            key = contract.localSymbol if contract.localSymbol else contract.symbol
            #print(f"{key} -tickSize: {TickTypeEnum.toStr(tickType)}={size}")
            if not key in price_data:
                tick_price_data = PriceData(contract.secType)
            else:
                tick_price_data : PriceData = price_data[key]
                
            tick_price_data.update(size, TickTypeEnum.toStr(tickType))
            price_data[key] = tick_price_data
            if tick_price_data.is_complete():
                ibrequests_marketData.pop(reqId)
                self.cancelMktData(reqId)

    def tickGeneric(
        self,
        reqId: TickerId,
        tickType: TickType,
        value: float,
    ):
        pass
        #print(f"tickGeneric: {TickTypeEnum.toStr(tickType)} ({tickType})={value}")
    
    def tickOptionComputation(
        self,
        reqId: TickerId,
        tickType: TickType,
        tickAttrib: int,
        impliedVol: float,
        delta: float,
        optPrice: float,
        pvDividend: float,
        gamma: float,
        vega: float,
        theta: float,
        undPrice: float,
    ):
        #print(f"tickOptionComputation: {TickTypeEnum.toStr(tickType)} ({tickType}), Implied Volatility: {impliedVol}, Delta: {delta}, Price: {optPrice}, pvDividend={pvDividend}")
        if not reqId in ibrequests_marketData:
            return
        else:
            contract: Contract = ibrequests_marketData[reqId]
            key = contract.localSymbol if contract.localSymbol else contract.symbol
            #print(f"{key} - tickOptionComputation: {TickTypeEnum.toStr(tickType)}, Implied Volatility: {impliedVol}, Delta: {delta}, Price: {optPrice}, pvDividend={pvDividend}")
            if not key in price_data:
                tick_price_data = PriceData(contract.secType)
            else:
                tick_price_data : PriceData = price_data[key]
                
            tick_price_data.update(delta, "DELTA")
            tick_price_data.update(impliedVol, "IV")
            tick_price_data.update(gamma, "GAMMA")
            tick_price_data.update(vega, "VEGA")
            tick_price_data.update(theta, "THETA")
            price_data[key] = tick_price_data
            if tick_price_data.is_complete():
                ibrequests_marketData.pop(reqId)
                self.cancelMktData(reqId)

    # Error handling callback.
    def error(self, reqId: TickerId, errorTime: int, errorCode: int, errorString: str, advancedOrderRejectJson=""):
        error_message = f"Error. Id: {reqId}, Code: {errorCode}, Msg: {errorString}"
        if reqId == -1:
            logging.debug(f"Error: {error_message}")
        elif errorCode == 366:
            logging.debug(f"Error: {error_message} - No market data available outside trading hours.")
        else:
            print(error_message)

    def historicalData(self, reqId: int, bar):
        split_date = bar.date.split('  ')
        date = split_date[0]  # Extract date part only
        time = None if (len(split_date) < 2) else split_date[1]  # Extract time part only if available
        row = {
            'date': date,  # Extract date part only
            'time': time,  # Extract time part only
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close
        }
        contract = ibrequests_historicalData[reqId]
        key = contract.localSymbol if contract.localSymbol else contract.symbol
        data: pd.DataFrame 
        data = historic_data[key] if key in historic_data else pd.DataFrame(columns=['date', 'time', 'open', 'high', 'low', 'close'])
        data.loc[len(data)] = row
        historic_data[key] = data
        #print(f"Historical Data. ReqId: {reqId}, Date: {split_date[0]}, Time: {split_date[1]}, Open: {bar.open}, High: {bar.high}, Low: {bar.low}, Close: {bar.close}")
        
    def historicalDataEnd(self, reqId: int, start: str, end: str):
        self.cancelHistoricalData(reqId)
        ibrequests_historicalData.pop(reqId, None)
        

ibrequests_contractDetails = {} # keep track of requests for contract details
ibrequests_marketData = {} # keep track of requests for market data
ibrequests_historicalData = {} # keep track of requests for historical data
contract_data = {}
contract_details_data = {}
price_data = {}
historic_data = {} # dict of symbol, array of rows
options_chain = {}

def init():
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', filename='evaluate-options-trade.log', filemode='w')
    parser = argparse.ArgumentParser(description="Get option chain for a symbol and evaluate trade options.")
    parser.add_argument("--symbol", type=str, help="The stock symbol to evaluate options for.")
    parser.add_argument("--earnings-week", type=str, help="Path to the earnings week JSON file.", default=None)
    parser.add_argument("--paper", action="store_true", help="Connect to default port for paper trading")
    
    args = parser.parse_args()

    app = EarningsApp()
    logging.info("Starting IB API Test Application...")
    random_client_id = int(time.time()) % 1000  # Generate a random client ID
    #port : int = 4001
    port : int = 7496
    if args.paper:
        port = 7497
    
    print(f"Connecting to port={port}")
    app.connect("127.0.0.1", port, clientId=random_client_id)
    logging.info("Connecting to TWS...")
    time.sleep(1)
    logging.info("serverVersion:%s connectionTime:%s" % (app.serverVersion(), app.twsConnectionTime()))
    threading.Thread(target=app.run, daemon=True).start()
    return app, args

def print_progress_bar(iteration, total, length=40, type="progress"):
    percent = f"{100 * (iteration / float(total)):.1f}"
    filled_length = int(length * iteration // total)
    bar = '█' * filled_length + '-' * (length - filled_length)
    if type == "progress":
        sys.stdout.write(f"\rProgress: |{bar}| {percent}% Complete")
    else:
        sys.stdout.write(f"\rWaiting: |{bar}| {percent}% remaining")
    sys.stdout.flush()
    if iteration == total:
        print()  # Move to next line when done

def compute_next_friday():
    """Compute next Friday's date in YYYYMMDD format."""
    today = datetime.date.today()
    # Friday is weekday 4 (where Monday=0)
    days_ahead = 4 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    next_friday = today + datetime.timedelta(days=days_ahead)
    return next_friday.strftime("%Y%m%d")

def get_stock_contract(app: EarningsApp, symbol: str):
    stock_contract = Contract()
    stock_contract.symbol = symbol 
    stock_contract.secType = "STK"
    stock_contract.exchange = "SMART"
    stock_contract.currency = "USD"
    reqId = app.nextId()
    app.reqContractDetails(reqId, stock_contract)
    ibrequests_contractDetails[reqId] = {"type": "stock_contract"}
    print(f"Requesting stock details for {symbol}")
    wait(lambda: reqId not in ibrequests_contractDetails, wait_time=2, wait_step=0.1)
    stock_contract_details = contract_details_data.get(symbol, None)  
    if stock_contract_details == None:
        raise IncompleteDataError("No stock contract details available for {symbol}")
    print(f"Received stock contract details for candidate {symbol}: {stock_contract_details.contract.conId}")
    return stock_contract

def request_market_data(app: EarningsApp, contract: Contract):
    reqId = app.nextId()
    logging.debug(f"Requesting market data for {contract} with reqId {reqId}")
    app.reqMarketDataType(2)
    tick_types = "232"
    if contract.secType == "OPT":
        tick_types="100,101,232"
        #tick_types=""
    app.reqMktData(reqId, contract, tick_types, False, False, [])
    
    ibrequests_marketData[reqId] = contract
    return reqId

def wait(condition: Callable, wait_time=5, wait_step=0.5):
    """Wait for a specified time, printing progress."""
    total_steps = int(wait_time / wait_step)
    for step in range(total_steps):
        # if wait_time > 10:
        #     print_progress_bar(iteration=total_steps - step, total=total_steps, type="waiting")
        time.sleep(wait_step)
        if condition(): break
    # print()  # Move to next line after completion (only required when printing a progress bar)

def get_option_chain(app: EarningsApp, symbol: str):
    """Request option chain for the stock contract."""
    contract = Contract()
    contract.symbol = symbol
    contract.secType = "OPT"
    contract.exchange = "SMART"
    contract.currency = "USD"
    contract.lastTradeDateOrContractMonth = compute_next_friday() # TODO: consider this-week
    # contract.strike = strike # no strike to get all strikes
    # contract.right = "C" # no right to get all options
    reqId = app.nextId()
    logging.debug(f"Requesting contract details for {contract} with reqId {reqId}")
    options_chain[symbol] = {}
    app.reqContractDetails(reqId, contract)
    ibrequests_contractDetails[reqId] = { "type": "option_chain", "underlying": symbol }
    wait(lambda: reqId not in ibrequests_contractDetails, wait_time=5, wait_step=0.1)
    
    print(f"Option Chain for {symbol}: {len(options_chain[symbol])} options found.")
    
def terminate(app: EarningsApp, message: str):
    print(message)
    app.disconnect()

def is_good_stock(symbol: str):
    if price_data[symbol].get("LAST") != None and price_data[symbol].get("LAST") > -1 and price_data[symbol].get("LAST")  < 40 or \
       price_data[symbol].get("ASK") != None and price_data[symbol].get("ASK") > -1 and price_data[symbol].get("ASK")  < 40 or \
       price_data[symbol].get("BID") != None and price_data[symbol].get("BID") > -1 and price_data[symbol].get("BID")  < 40 or \
       price_data[symbol].get_instrument_value() < 40 :
          print(f"too cheap!")
          return False
    return True

def print_option_price(description: str, price_data: PriceData):
    print(f"{description}: strike={price_data.get('strike')}, IV={price_data.get('IV')}, call OI={price_data.get('OPTION_CALL_OPEN_INTEREST')}, put OI={price_data.get('OPTION_PUT_OPEN_INTEREST')}, theta={price_data.get('THETA')}, delta={price_data.get('DELTA')}, gamma={price_data.get('GAMMA')}, vega={price_data.get('VEGA')}, price={price_data.get_instrument_value()}")

def determine_expected_move(contract: Contract, app: EarningsApp):
    current_price = price_data[contract.symbol].get_instrument_value()
    
    if not options_chain.get(contract.symbol):
        raise IncompleteDataError(f"No options found for {contract.symbol}")

    # Convert options_chain to a DataFrame
    data = {}

    for key, contract_details in options_chain[contract.symbol].items():
        # Convert ContractDetails object to a dictionary of its attributes
        # You may want to filter or flatten nested objects as needed
        data[key] = contract_details.contract.__dict__
    
    options_df : pd.DataFrame = pd.DataFrame.from_dict(data, orient='index')
    # add a column to options_df for the distance from the current price
    options_df["distance_from_price"] = options_df["strike"] - current_price
    options_df["distance_from_price"] = options_df["distance_from_price"].abs()
    
    closest_options = options_df.nsmallest(6, 'distance_from_price').sort_values(by='strike')
    
    unique_strikes = closest_options['strike'].unique()
    atm_strike = unique_strikes[1]
    # find the atm call by filtering clostest options by strike=atm_strike and right=c
    atm_call_key = closest_options[(closest_options['strike'] == atm_strike) & (closest_options['right'] == 'C')].index[0]
    atm_call = options_chain[contract.symbol][atm_call_key].contract
    
    atm_put_key = closest_options[(closest_options['strike'] == atm_strike) & (closest_options['right'] == 'P')].index[0]
    atm_put = options_chain[contract.symbol][atm_put_key].contract

    #print("\n3 option strikes closest to current price:")
    #print(closest_options[['strike', 'distance_from_price', 'right']])

    strangle_put_key = closest_options[(closest_options['strike'] == unique_strikes[0]) & (closest_options['right'] == 'P')].index[0]
    strangle_put = options_chain[contract.symbol][strangle_put_key].contract
    strangle_call_key = closest_options[(closest_options['strike'] == unique_strikes[2]) & (closest_options['right'] == 'C')].index[0]
    strangle_call = options_chain[contract.symbol][strangle_call_key].contract

    req_ids= []
    req_ids.append(request_market_data(app, atm_call))
    req_ids.append(request_market_data(app, atm_put))
    req_ids.append(request_market_data(app, strangle_call))
    req_ids.append(request_market_data(app, strangle_put))
    wait(lambda: all(req_id not in ibrequests_marketData for req_id in req_ids), wait_time=30, wait_step=0.1)

    option_data_complete : bool = True
    if price_data[atm_call_key] is None or price_data[atm_call_key].is_complete() == False:
        print(f"Could not retrieve market data for ATM call {atm_call_key}.")
        option_data_complete = False
    else:
        print_option_price(description=f"ATM call {atm_call_key}", price_data=price_data[atm_call_key])
    if price_data[atm_put_key] is None or price_data[atm_put_key].is_complete() == False:
        print(f"Could not retrieve market data for ATM put {atm_put_key}.")
        option_data_complete = False
    else:
        print_option_price(description=f"ATM put {atm_put_key}", price_data=price_data[atm_put_key])
    if price_data[strangle_call_key] is None or price_data[strangle_call_key].is_complete() == False:
        print(f"Could not retrieve market data for Strangle call {strangle_call_key}.")
        option_data_complete = False
    else:
        print_option_price(description=f"Strangle call {strangle_call_key}", price_data=price_data[strangle_call_key])
    if price_data[strangle_put_key] is None or price_data[strangle_put_key].is_complete() == False:
        print(f"Could not retrieve market data for Strangle put {strangle_put_key}.")
        option_data_complete = False
    else:
        print_option_price(description=f"Strangle put {strangle_put_key}", price_data=price_data[strangle_put_key])
    
    if option_data_complete:
        expected_move = (price_data[atm_call_key].get_instrument_value() + price_data[atm_put_key].get_instrument_value() \
                     + price_data[strangle_call_key].get_instrument_value() + price_data[strangle_put_key].get_instrument_value()) / 2
    else:
        raise IncompleteDataError(f"Could not retrieve market data for all options. Expected move cannot be determined.") 
        
    return expected_move

def evalulate_stock_history(app: EarningsApp, contract: Contract):
    """Request historical data for the stock contract."""
    reqId = app.nextId()
    logging.debug(f"Requesting historical data for {contract}")
    yesterday = (pd.Timestamp.now() - pd.Timedelta(days=1)).strftime('%Y%m%d')
    app.reqHistoricalData(reqId, contract=contract, endDateTime=f"{yesterday}-23:59:59", 
                      durationStr="3 Y", barSizeSetting="1 day", whatToShow="TRADES",useRTH=1, 
                      formatDate=1, keepUpToDate=False,chartOptions=[])

    ibrequests_historicalData[reqId] = contract
    wait(lambda: reqId not in ibrequests_historicalData, wait_time=120, wait_step=0.1)
    stock_historic_data = historic_data[contract.symbol] 
    # add a column candle_length to stock_historic_data which is the difference between high and low
    stock_historic_data['candle_length'] = stock_historic_data['high'] - stock_historic_data['low']
    # add a column percent_move to stock_historic_data which is the percentage move from low to high
    stock_historic_data['percent_move'] = (stock_historic_data['candle_length'] / stock_historic_data['close']) * 100
    # print the 14 largetst percent moves
    print("\n14 largest percent moves in the last 3 years:")
    top_moves = stock_historic_data.nlargest(14, 'percent_move')[['date',  'open', 'high', 'low', 'close', 'candle_length', 'percent_move']]
    print(top_moves)
    # calculate the average percent move of the top 14 percent moves
    average_percent_move = stock_historic_data.nlargest(14, 'percent_move')['percent_move'].mean()
    
    # Convert DataFrame to list of dictionaries for JSON serialization
    top_moves_list = top_moves.to_dict(orient='records')
    
    return average_percent_move, top_moves_list
    
def get_contracts_from_earnings_file(app: EarningsApp, filename: str):
    symbols = []
    if filename == "" or filename is None:
        return symbols
    
    # Try to construct full path if only date or filename given, or check absolute
    if not os.path.exists(filename):
        # Allow passing just the date part or similar, try to find in docs/data
        potential_path = os.path.join("docs", "data", filename)
        if os.path.exists(potential_path):
             filename = potential_path
        else:
             print(f"File {filename} not found.")
             return symbols
             
    try:
        with open(filename, "r") as f:
            data = json.load(f)
            if "data" in data and isinstance(data["data"], list):
                for item in data["data"]:
                    symbol = item.get("ticker")
                    if symbol:
                        try:
                            symbols.append(get_stock_contract(app, symbol))
                        except IncompleteDataError as e:
                            print(f"Skipping {symbol}: {e}")
                            continue
            else:
                 print(f"Invalid format in {filename}: 'data' array missing.")
    except Exception as e:
        print(f"Error reading {filename}: {e}")        
        
    return symbols

def save_results_to_json(symbol: str, underlying_price_data: PriceData, expected_move: float, average_percent_move: float, lower_boundary: float, upper_boundary: float, historic_moves: list = None):
    directory = "docs/data"
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    filepath = os.path.join(directory, f"{symbol}.json")
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Underlying Prices
    underlying_prices = {
        "Bid": underlying_price_data.get("BID"),
        "Ask": underlying_price_data.get("ASK"),
        "get_instrument_value": underlying_price_data.get_instrument_value()
    }
    
    # Option Prices
    option_prices_list = []
    if symbol in options_chain:
        for local_symbol, details in options_chain[symbol].items():
            if local_symbol in price_data:
                p_data = price_data[local_symbol]
                
                # Check if strike is within boundaries
                strike = details.contract.strike
                # Calculate double expected move boundaries again for filtering (or pass them as args if preferred)
                # For simplicity, we just check if we have data. If we have data, it means it was requested.
                # The request logic in main() already filtered by boundaries.
                
                opt_entry = {
                    "contract_localSymbol": local_symbol,
                    "contract_strike": details.contract.strike,
                    "contract_right": details.contract.right,
                    "Bid": p_data.get("BID"),
                    "Ask": p_data.get("ASK"),
                    "IV": p_data.get("IV"),
                    "call_open_interest": p_data.get("OPTION_CALL_OPEN_INTEREST"),
                    "put_open_interest": p_data.get("OPTION_PUT_OPEN_INTEREST"),
                    "theta": p_data.get("THETA"),
                    "delta": p_data.get("DELTA"),
                    "gamma": p_data.get("GAMMA"),
                    "vega": p_data.get("VEGA"),
                    "price": p_data.get_instrument_value()
                }
                option_prices_list.append(opt_entry)
    
    recommendation = {
        "expected_move": expected_move,
        "average_percent_move": average_percent_move,
        "lower_boundary": lower_boundary,
        "upper_boundary": upper_boundary
    }
    
    new_entry = {
        "timestamp": timestamp,
        "underlying_prices": underlying_prices,
        "option_prices": option_prices_list,
        "recommendation": recommendation
    }
    
    data = {"prices": []}
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                content = f.read()
                if content:
                    data = json.loads(content)
        except json.JSONDecodeError:
            print(f"Error reading {filepath}, starting fresh.")
            
    if "prices" not in data:
        data["prices"] = []

    # Update or add the historic-move field
    if historic_moves is not None:
        data["historic_move"] = historic_moves
        
    data["prices"].append(new_entry)
    
    with open(filepath, "w") as f:
        json.dump(data, f, indent=4)
    print(f"Saved results to {filepath}")

def main():
    app,args = init()
    contracts : list[Contract] = []
    if args.symbol:
        stock_contract : Contract = None
        try:
            stock_contract = get_stock_contract(app, args.symbol)
        except IncompleteDataError as e:
            print(f"Failed to get contract information for {args.symbol}. Aborting")
        if stock_contract != None:
            contracts.append(stock_contract)
    elif args.earnings_week:
        earnings_file=f"docs/data/earnings-for-week-starting-{args.earnings_week}.json"
        print(f"{datetime.datetime.now().strftime('%H:%M:%S')} - Processing earnings week file: {earnings_file}")
        contracts = get_contracts_from_earnings_file(app, earnings_file)
    else:
         print("No symbol or earnings week file provided.")
    
    if len(contracts)>0:
        for contract in contracts:
            print(f"----------------------------------------------------------------------")
            print(f"Evaluating options for {contract.symbol}...")
            reqId = request_market_data(app=app, contract=contract)
            wait(lambda: reqId not in ibrequests_marketData, wait_time=5, wait_step=0.1)
            print(f"Market Data for {contract.symbol}: {price_data[contract.symbol].to_str()}")

            if not is_good_stock(contract.symbol):
                print(f"Stock does not meet criteria.")
                continue

            get_option_chain(app=app, symbol=contract.symbol)
            
            get_option_chain(app=app, symbol=contract.symbol)
            
            try:
                try:
                    expected_move = determine_expected_move(contract=contract, app=app)
                except IncompleteDataError as e:
                    print(f"Skipping {contract.symbol}: {e}")
                    continue
                
                double_expected_move_up = price_data[contract.symbol].get_instrument_value() + (2*expected_move)
                double_expected_move_down = price_data[contract.symbol].get_instrument_value() - (2*expected_move)
                
                # Expand boundaries by 2 strikes
                sorted_strikes = sorted(list(set(d.contract.strike for d in options_chain[contract.symbol].values())))
                
                # Find index just inside or at lower boundary
                idx_min = 0
                for i, s in enumerate(sorted_strikes):
                    if s >= double_expected_move_down:
                        idx_min = i
                        break
                
                # Find index just inside or at upper boundary
                idx_max = len(sorted_strikes) - 1
                for i in range(len(sorted_strikes) - 1, -1, -1):
                    if sorted_strikes[i] <= double_expected_move_up:
                        idx_max = i
                        break
                
                # Expand by 2 strikes
                idx_min_expanded = max(0, idx_min - 2)
                idx_max_expanded = min(len(sorted_strikes) - 1, idx_max + 2)
                
                filter_min_strike = sorted_strikes[idx_min_expanded]
                filter_max_strike = sorted_strikes[idx_max_expanded]

                # Request market data only for options within boundaries
                print(f"Retrieving data for options between {filter_min_strike} and {filter_max_strike} (expanded from {double_expected_move_down:.2f} - {double_expected_move_up:.2f})...")
                option_req_ids = []
                options_to_fetch = 0
                for key, details in options_chain[contract.symbol].items():
                    strike = details.contract.strike
                    if filter_min_strike <= strike <= filter_max_strike:
                        reqId = request_market_data(app, details.contract)
                        option_req_ids.append(reqId)
                        options_to_fetch += 1
                
                print(f"Requested data for {options_to_fetch} options out of {len(options_chain[contract.symbol])} total.")
                
                # Wait for data to populate (max 10 seconds)
                def check_remaining():
                    remaining = len([rid for rid in option_req_ids if rid in ibrequests_marketData])
                    sys.stdout.write(f"\rWaiting for {remaining} options to populate...   ")
                    sys.stdout.flush()
                    return remaining == 0
                
                wait(check_remaining, wait_time=10, wait_step=0.5)
                print()
                print(f"Data retrieval finished or timed out. Pending requests: {len([rid for rid in option_req_ids if rid in ibrequests_marketData])}")

                average_percent_move, top_moves = evalulate_stock_history(app=app, contract=contract)

                usual_up_spike = price_data[contract.symbol].get_instrument_value() + (average_percent_move / 100) * price_data[contract.symbol].get_instrument_value()
                usual_down_spike = price_data[contract.symbol].get_instrument_value() - (average_percent_move / 100) * price_data[contract.symbol].get_instrument_value()

                upper_boundary = max(double_expected_move_up, usual_up_spike)
                lower_boundary = min(double_expected_move_down, usual_down_spike)

                print(f"\nExpected move for {contract.symbol} is: {expected_move:.2f}. That is, we are looking at {double_expected_move_down:.2f} ... {price_data[contract.symbol].get_instrument_value():.2f} ... {double_expected_move_up:.2f} as the range for the next week.")
                print(f"Average percent move of the 14 largest daily spikes over the past 3 years: {average_percent_move:.2f}%. Applied to current price, we are looking at {usual_down_spike:.2f} ... {price_data[contract.symbol].get_instrument_value():.2f} ... {usual_up_spike:.2f}")
                print(f"Being careful, interesting strangle boundaries for {contract.symbol} are: {lower_boundary:.2f} to {upper_boundary:.2f}\n")
                
                save_results_to_json(
                    symbol=contract.symbol,
                    underlying_price_data=price_data[contract.symbol],
                    expected_move=expected_move,
                    average_percent_move=average_percent_move,
                    lower_boundary=lower_boundary,
                    upper_boundary=upper_boundary,
                    historic_moves=top_moves
                )
            except Exception as e:
                print(f"Error processing {contract.symbol}: {e}")
                continue
        
    terminate(app=app, message=f"Done.")

if __name__ == "__main__":
    main()

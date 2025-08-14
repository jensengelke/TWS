from typing import Callable
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract, ContractDetails
from ibapi.common import SetOfString, SetOfFloat, TickerId
from ibapi.ticktype import TickType, TickTypeEnum
import argparse
import logging
import threading
import time
import datetime
import sys
import pandas as pd

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
            type=ibrequests_contractDetails[reqId]
            logging.debug(f"Contract details for {ibrequests_contractDetails[reqId]}: ({type}) {contractDetails}")
            if type == "stock_contract":
                global stock_contract, stock_contract_details
                stock_contract_details = contractDetails
                stock_contract = contractDetails.contract
            if type == "option_chain":
                global options_chain
                options_chain[contractDetails.contract.localSymbol] = contractDetails
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
        elif not reqId in ibrequests_marketData:
            return            
        else:
            contract: Contract = ibrequests_marketData[reqId]
            key = contract.localSymbol if contract.localSymbol else contract.symbol
            if key in price_data:
                logging.debug(f"Updating Stock price {TickTypeEnum.toStr(tickType)} for local symbol {contract.localSymbol}, symbol {contract.symbol}: {price}")
                price_data[key].update({
                    "last": price if tickType == TickTypeEnum.LAST else price_data[key].get("last", None),
                    "ask": price if tickType == TickTypeEnum.ASK else price_data[key].get("ask", None),
                    "bid": price if tickType == TickTypeEnum.BID else price_data[key].get("bid", None),
                    "mark": price if tickType == TickTypeEnum.MARK_PRICE else price_data[key].get("mark", None)
                })
                if price_data[key]["last"] != None and \
                   price_data[key]["ask"] != None and \
                   price_data[key]["bid"] != None and \
                   price_data[key]["mark"] != None:
                    ibrequests_marketData.pop(reqId)
            else:
                print(f"Creating Stock price {TickTypeEnum.toStr(tickType)} for key {key} local symbol {contract.localSymbol}, symbol {contract.symbol}: {price}")
                price_data[key] = {
                    "last": price if tickType == TickTypeEnum.LAST else None,
                    "ask": price if tickType == TickTypeEnum.ASK else None,
                    "bid": price if tickType == TickTypeEnum.BID else None,
                    "mark": price if tickType == TickTypeEnum.MARK_PRICE else None
                }
    
    # Error handling callback.
    def error(self, reqId: TickerId, errorCode: int, errorString: str, advancedOrderRejectJson=""):
        error_message = f"Error. Id: {reqId}, Code: {errorCode}, Msg: {errorString}"
        if reqId == -1:
            logging.debug(f"Error: {error_message}")
        else:
            print(error_message)

ibrequests_contractDetails = {} # keep track of requests for contract details
ibrequests_marketData = {} # keep track of requests for market data
stock_contract: Contract
stock_contract_details: ContractDetails
price_data = {} # dict of symbol, {"last": last_price, "ask": ask_price, "bid": bid_price}
options_chain = {}

def init():
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', filename='evaluate-options-trade.log', filemode='w')
    app = EarningsApp()
    logging.info("Starting IB API Test Application...")
    random_client_id = int(time.time()) % 1000  # Generate a random client ID
    app.connect("127.0.0.1", 7496, clientId=random_client_id)
    logging.info("Connecting to TWS...")
    time.sleep(1)
    logging.info("serverVersion:%s connectionTime:%s" % (app.serverVersion(), app.twsConnectionTime()))
    threading.Thread(target=app.run, daemon=True).start()
    parser = argparse.ArgumentParser(description="Get option chain for a symbol and evaluate trade options.")
    parser.add_argument("--symbol", type=str, help="The stock symbol to evaluate options for.", default="CSCO")
    args = parser.parse_args()

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
    ibrequests_contractDetails[reqId] = "stock_contract"
    wait(lambda: reqId not in ibrequests_contractDetails, wait_time=2, wait_step=0.1)    
    print(f"\nStock Contract Details for {symbol}: {stock_contract_details.contract.conId}")
    return stock_contract

def request_market_data(app: EarningsApp, contract: Contract):
    reqId = app.nextId()
    logging.debug(f"Requesting market data for {contract} with reqId {reqId}")
    app.reqMarketDataType(1)
    app.reqMktData(reqId, contract, "232", False, False, [])
    ibrequests_marketData[reqId] = contract
    return reqId
       

def wait(condition: Callable, wait_time=5, wait_step=0.5):
    """Wait for a specified time, printing progress."""
    total_steps = int(wait_time / wait_step)
    for step in range(total_steps):
        print_progress_bar(iteration=total_steps - step, total=total_steps, type="waiting")
        time.sleep(wait_step)
        if condition(): break
    print()  # Move to next line after completion

def get_option_chain(app: EarningsApp):
    """Request option chain for the stock contract."""
    contract = Contract()
    contract.symbol = stock_contract.symbol
    contract.secType = "OPT"
    contract.exchange = "SMART"
    contract.currency = "USD"
    contract.lastTradeDateOrContractMonth = compute_next_friday()
    # contract.strike = strike # no strike to get all strikes
    # contract.right = "C" # no right to get all options
    reqId = app.nextId()
    logging.debug(f"Requesting contract details for {contract} with reqId {reqId}")
    app.reqContractDetails(reqId, contract)
    ibrequests_contractDetails[reqId] = "option_chain"
    wait(lambda: reqId not in ibrequests_contractDetails, wait_time=5, wait_step=0.1)
    
    print(f"\nOption Chain for {stock_contract.symbol}: {len(options_chain)}")
    
def terminate(app: EarningsApp, message: str):
    print(message)
    app.disconnect()
    exit(0)

def is_good_stock(symbol: str):
    if price_data[symbol]["last"] < 40 or \
       price_data[symbol]["ask"] < 40 or \
       price_data[symbol]["bid"] < 40 or \
       price_data[symbol]["mark"] < 40 :
          print(f"too cheap!")
          return False
    return True

def determine_expected_move(contract: Contract, app: EarningsApp):
    current_price = price_data[contract.symbol]["mark"]
    # Convert options_chain to a DataFrame
    data = {}

    for key, contract_details in options_chain.items():
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
    atm_call = options_chain[atm_call_key].contract
    
    atm_put_key = closest_options[(closest_options['strike'] == atm_strike) & (closest_options['right'] == 'P')].index[0]
    atm_put = options_chain[atm_put_key].contract

    print("\n3 options closest to current price:")
    print(closest_options[['strike', 'distance_from_price', 'right']])
    print(f"\nATM Call: {atm_call}\nATM Put: {atm_put}\nstrikes: {unique_strikes}")

    strangle_put_key = closest_options[(closest_options['strike'] == unique_strikes[0]) & (closest_options['right'] == 'P')].index[0]
    strangle_put = options_chain[strangle_put_key].contract
    strangle_call_key = closest_options[(closest_options['strike'] == unique_strikes[2]) & (closest_options['right'] == 'C')].index[0]
    strangle_call = options_chain[strangle_call_key].contract

    req_ids= []
    req_ids.append(request_market_data(app, atm_call))
    req_ids.append(request_market_data(app, atm_put))
    req_ids.append(request_market_data(app, strangle_call))
    req_ids.append(request_market_data(app, strangle_put))
    wait(lambda: all(req_id not in ibrequests_marketData for req_id in req_ids), wait_time=5, wait_step=0.1)

    print("Market data received for all options.")
    print(f"ATM call {atm_call_key}: {price_data[atm_call_key]['mark']}")
    print(f"ATM put {atm_put_key}: {price_data[atm_put_key]['mark']}")
    print(f"Strangle call {strangle_call_key}: {price_data[strangle_call_key]['mark']}")
    print(f"Strangle put {strangle_put_key}: {price_data[strangle_put_key]['mark']}")

def main():
    app,args = init()
    contract : Contract = get_stock_contract(app, args.symbol)

    reqId = request_market_data(app=app, contract=contract)
    wait(lambda: reqId not in ibrequests_marketData, wait_time=5, wait_step=0.1)
    print(f"\nMarket Data for {contract.symbol}: {price_data[contract.symbol]}")

    if not is_good_stock(contract.symbol):
        terminate(app=app, message=f"Stock does not meet criteria.")

    get_option_chain(app)
    determine_expected_move(contract=contract, app=app)
    terminate(app=app, message=f"Done.")



if __name__ == "__main__":
    print("calling main()")
    main()


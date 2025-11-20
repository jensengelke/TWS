import threading
import time
import pandas as pd
import argparse
import logging
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.ticktype import TickType, TickTypeEnum
from ibapi.common import TickerId, TickAttrib
from ibapi.contract import Contract

ibrequests_contractDetails = {}
ibrequests_marketData = {}
ibresponses_contractDetails = {}
ibresponses_marketData = {}

class IBApp(EWrapper, EClient):
    def __init__(self, verbose=False):
        EClient.__init__(self, self)
        self.verbose = verbose
        # Store tick price data
        self.tick_prices: dict[str, float | None] = {
            'BID': None,
            'ASK': None,
            'LAST': None,
            'OPEN': None,
            'HIGH': None,
            'LOW': None,
            'CLOSE': None
        }
        # Store option computation data
        self.option_data: dict[str, float | None] = {
            'optPrice': None,
            'delta': None,
            'impliedVol': None,
            'pvDividend': None,
            'vega': None,
            'theta': None,
            'undPrice': None
        }
        self.lines_printed = False
        self.status_message = ""

    def nextId(self):
        self.orderId += 1
        return self.orderId

    def error(self, reqId: TickerId, errorTime: int, errorCode: int, errorString: str, advancedOrderRejectJson=""):
        error_message = f"Error. Id: {reqId}, Code: {errorCode}, Msg: {errorString}"
        if reqId == -1:
            logging.debug(f"Error: {error_message}")
        elif errorCode == 366:
            logging.debug(f"Error: {error_message} - No market data available outside trading hours.")
        else:
            print(error_message)

    def contractDetails(self, reqId: int, contractDetails):
        print(f"Retrieved contract details for reqId {reqId}: {contractDetails.contract.localSymbol}")
        identifier=f"{contractDetails.contract.symbol}-{reqId}"
        ibresponses_contractDetails[identifier] = contractDetails
        if self.verbose:
            print(f"responses: {ibresponses_contractDetails}")
        
        
    def contractDetailsEnd(self, reqId: int):
        print(f"Contract details for reqId {reqId} received.")

    def tickOptionComputation(self, reqId: TickerId, tickType: TickType, tickAttrib: int, impliedVol: float, delta: float, optPrice: float, pvDividend: float, gamma: float, vega: float, theta: float, undPrice: float):
        super().tickOptionComputation(reqId, tickType, tickAttrib, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice)
        # Update option data
        self.option_data['optPrice'] = optPrice
        self.option_data['delta'] = delta
        self.option_data['impliedVol'] = impliedVol
        self.option_data['pvDividend'] = pvDividend
        self.option_data['vega'] = vega
        self.option_data['theta'] = theta
        self.option_data['undPrice'] = undPrice
        self._print_tick_data()
        
    def tickPrice(self, reqId: TickerId, tickType: TickType, price: float, attrib: TickAttrib):
        super().tickPrice(reqId, tickType, price, attrib)
        tick_type_name = TickTypeEnum.toStr(tickType)
        # Update tick prices if it's one of the types we're tracking
        if tick_type_name in self.tick_prices:
            self.tick_prices[tick_type_name] = price
            self._print_tick_data()
    
    def _format_value(self, value: float | None) -> str:
        """Format a float value to 3 decimal places or return 'N/A'"""
        if value is None:
            return 'N/A'
        return f"{value:.3f}"
    
    def _print_tick_data(self, status_msg: str = ""):
        """Print the current tick data in three lines, updating in place"""
        # Line 1: Price data
        price_line = "Prices: "
        price_line += f"Bid: {self._format_value(self.tick_prices['BID'])}, "
        price_line += f"Ask: {self._format_value(self.tick_prices['ASK'])}, "
        price_line += f"Last: {self._format_value(self.tick_prices['LAST'])}, "
        price_line += f"Open: {self._format_value(self.tick_prices['OPEN'])}, "
        price_line += f"High: {self._format_value(self.tick_prices['HIGH'])}, "
        price_line += f"Low: {self._format_value(self.tick_prices['LOW'])}, "
        price_line += f"Close: {self._format_value(self.tick_prices['CLOSE'])}"
        
        # Line 2: Option computation data
        option_line = "Options: "
        option_line += f"OptPrice: {self._format_value(self.option_data['optPrice'])}, "
        option_line += f"Delta: {self._format_value(self.option_data['delta'])}, "
        option_line += f"IV: {self._format_value(self.option_data['impliedVol'])}, "
        option_line += f"pvDiv: {self._format_value(self.option_data['pvDividend'])}, "
        option_line += f"Vega: {self._format_value(self.option_data['vega'])}, "
        option_line += f"Theta: {self._format_value(self.option_data['theta'])}, "
        option_line += f"UndPrice: {self._format_value(self.option_data['undPrice'])}"
        
        # Line 3: Status message
        if status_msg:
            self.status_message = status_msg
        status_line = f"Status: {self.status_message}"
        
        if self.lines_printed:
            # Move cursor up 3 lines and clear them
            print("\033[3A\033[K", end='')
            print(price_line)
            print("\033[K", end='')
            print(option_line)
            print("\033[K", end='')
            print(status_line, flush=True)
        else:
            # First time printing - just print normally
            print(price_line)
            print(option_line)
            print(status_line, flush=True)
            self.lines_printed = True

parser = argparse.ArgumentParser(description="IB API Test Application")
parser.add_argument("--strike", help="Strike price for the option", default=6800, type=float)
parser.add_argument("--waittime", help="Time to wait for contract details responses", default=5, type=int)
parser.add_argument("--marketdata-waittime", help="Time to wait for market data", default=10, type=int)
parser.add_argument("-v", "--verbose", help="Enable verbose output", action="store_true")

args = parser.parse_args()

mycontract = Contract()
mycontract.symbol = "SPX"
mycontract.secType = "IND"
mycontract.exchange = "CBOE"
mycontract.currency = "USD"

print("Starting IB API Test Application...")
app = IBApp(verbose=args.verbose)
random_client_id = int(time.time()) % 1000  # Generate a random client ID
gateway_ip : str = "38.242.134.92"
# 4001 ... gateway live
# 4002 ... gateway paper
gateway_port : int = 4002
print("Connecting to TWS...")
app.connect(gateway_ip, gateway_port, clientId=random_client_id)
time.sleep(1)
print("serverVersion:%s connectionTime:%s" % (app.serverVersion(), app.twsConnectionTime()))

threading.Thread(target=app.run, daemon=True).start()

app.orderId=0
app.reqContractDetails(app.nextId(), mycontract)
time.sleep(1)  # Allow time for the request to be processed

today = pd.Timestamp.now().normalize()
days_ahead = (4 - today.weekday()) % 7  # 4 is Friday (Monday=0)
next_friday = (today + pd.Timedelta(days=days_ahead)).strftime('%Y%m%d')
print(f"Next Friday's date: {next_friday}")

contract = Contract()
contract.symbol = mycontract.symbol
contract.secType = "OPT"
contract.exchange = "SMART"
contract.currency = "USD"
contract.lastTradeDateOrContractMonth = next_friday
contract.strike = args.strike
reqId = app.nextId()
logging.debug(f"Requesting contract details for {contract} with reqId {reqId}")
identifier = f"{contract.symbol}-{reqId}"
app.reqContractDetails(reqId, contract)

for i in range(args.waittime):
    if identifier not in ibresponses_contractDetails.keys():
        remaining = args.waittime - i
        print(f"\033[KWaiting for contract details... {remaining} seconds remaining", end='\r', flush=True)
        time.sleep(1)
print()  # Move to next line after countdown

opt_contract=ibresponses_contractDetails[identifier].contract
print(f"Contract details received: {opt_contract.localSymbol}")

reqId = app.nextId()
identifier = f"{opt_contract.localSymbol}-{reqId}"
app.reqMktData(reqId, contract=opt_contract, genericTickList="100,101,106,165", snapshot=False, regulatorySnapshot=False, mktDataOptions=[])

# Initialize the display with empty data
app._print_tick_data("Waiting for market data...")

for i in range(args.marketdata_waittime):
    remaining = args.marketdata_waittime - i
    app._print_tick_data(f"Collecting market data... {remaining} seconds remaining")
    time.sleep(1)

app._print_tick_data("Market data collection complete")



app.disconnect()
print("Disconnected from TWS.")
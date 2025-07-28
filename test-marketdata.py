import threading
import time
import pandas as pd
import argparse
import logging
from ibapi.client import *
from ibapi.wrapper import *

ibrequests_contractDetails = {}
ibrequests_marketData = {}
ibresponses_contractDetails = {}
ibresponses_marketData = {}

class IBApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)

    def nextId(self):
        self.orderId += 1
        return self.orderId

    def error(self, reqId: int, errorCode: int, errorString: str):
        if reqId == -1:
            error_message = f"Connection setup: {errorString}"
        else:
            error_message = f"Error. Id: {reqId}, Code: {errorCode}, Msg: {errorString}"
        
        print(error_message)

    def contractDetails(self, reqId: int, contractDetails):
        attrs = vars(contractDetails)
        print(f"Retrieved contract details for reqId {reqId}: {attrs.get('longName', 'no long name available')}")
        identifier=f"{contractDetails.contract.symbol}-{reqId}"
        ibresponses_contractDetails[identifier] = contractDetails
        print(f"responses: {ibresponses_contractDetails}")
        
        
    def contractDetailsEnd(self, reqId: int):
        print(f"Contract details for reqId {reqId} received.")

    def tickOptionComputation(self, reqId: TickerId, tickType: TickType, tickAttrib: int, impliedVol: float, delta: float, optPrice: float, pvDividend: float, gamma: float, vega: float, theta: float, undPrice: float):
        super().tickOptionComputation(reqId, tickType, tickAttrib, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice)
        print(f"TickOptionComputation. TickerId: {reqId}, TickType: {tickType}, TickAttrib: {tickAttrib}, ImpliedVolatility: {impliedVol},Delta: {delta}, OptionPrice: {optPrice}, pvDividend: {pvDividend}, Gamma: {gamma}, Vega: {vega}, Theta: {theta}, UnderlyingPrice: {undPrice}")
        
    def tickPrice(self, reqId: TickerId, tickType: TickType, price: float, attrib: TickAttrib):
        super().tickPrice(reqId, tickType, price, attrib)
        print(f"TickPrice. TickerId: {reqId}, tickType: {tickType}, Price: {price}, CanAutoExecute: {attrib.canAutoExecute}, PastLimit: {attrib.pastLimit}", end=' ')
        if tickType == TickTypeEnum.BID or tickType == TickTypeEnum.ASK:
            print("PreOpen:", attrib.preOpen)
        else:
            print()

argparse = argparse.ArgumentParser(description="IB API Test Application")
argparse.add_argument("--contract", help="SPX and SPY are supported. Default is SPX", default="SPX")
argparse.add_argument("--waittime", help="time to wait for IBKR responses", default=5, type=int)

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

def connect():
    app.run()

print("Starting IB API Test Application...")
app = IBApp()
random_client_id = int(time.time()) % 1000  # Generate a random client ID
app.connect("127.0.0.1", 7496, clientId=random_client_id)
print("Connecting to TWS...")
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
contract.strike = 6400
reqId = app.nextId()
logging.debug(f"Requesting contract details for {contract} with reqId {reqId}")
identifier = f"{contract.symbol}-{reqId}"
app.reqContractDetails(reqId, contract)

for i in range(args.waittime):
    if identifier not in ibresponses_contractDetails.keys():
        print(f"Waiting for contract details... {i+1}/{args.waittime} seconds")
        time.sleep(1)

opt_contract=ibresponses_contractDetails[identifier].contract
print(f"Contract details received: {opt_contract.localSymbol}")

reqId = app.nextId()
identifier = f"{opt_contract.localSymbol}-{reqId}"
app.reqMktData(reqId, contract=opt_contract, genericTickList="100,101,106,165", snapshot=False, regulatorySnapshot=False, mktDataOptions=[])
for i in range(args.waittime):
    if identifier not in ibresponses_marketData.keys():
        print(f"Waiting for contract details... {i+1}/{args.waittime} seconds")
        time.sleep(1)



app.disconnect()
print("Disconnected from TWS.")
# Settings >Market Data Subscriptions > Market Data API Acknowledgement 
# Confirm that you don't build a product from this data

from ibapi.client import *
from ibapi.wrapper import *
import threading
import time
import pandas as pd
import argparse
import logging

class TestApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.data = pd.DataFrame(columns=['date', 'time', 'open', 'high', 'low', 'close'])
        

    def nextValidId(self, orderId: int):
        self.orderId = orderId
        print(f"Next valid order ID: {self.orderId}")

    def nextId(self):
        self.orderId += 1
        print(f"Next ID updated to: {self.orderId}")
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
        
    def contractDetailsEnd(self, reqId: int):
        print(f"Contract details for reqId {reqId} received.")

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
        self.data.loc[len(self.data)] = row
        #print(f"Historical Data. ReqId: {reqId}, Date: {split_date[0]}, Time: {split_date[1]}, Open: {bar.open}, High: {bar.high}, Low: {bar.low}, Close: {bar.close}")
        
    def historicalDataEnd(self, reqId: int, start: str, end: str):
        print(f"Historical data end for reqId {reqId}. Start: {start}, End: {end}")
        self.cancelHistoricalData(reqId)
        filename=f"historic-{mycontract.symbol.lower()}.csv"
        self.data.to_csv(filename, index=False)
        print(f"Saved {filename}")
        self.disconnect()

argparse = argparse.ArgumentParser(description="IB API Test Application")
argparse.add_argument("--contract", help="SPX and SPY are supported. Default is SPX", default="SPX")
argparse.add_argument("--waittime", type=int, help="Time to wait for data in seconds", default=120)
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
#logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = TestApp()
random_client_id = int(time.time()) % 1000  # Generate a random client ID
app.connect("127.0.0.1", 7496, clientId=random_client_id)
print("Connecting to TWS...")
time.sleep(1)
print("serverVersion:%s connectionTime:%s" % (app.serverVersion(), app.twsConnectionTime()))

threading.Thread(target=app.run, daemon=True).start()


app.orderId=0
app.reqContractDetails(app.nextId(), mycontract)
time.sleep(1)  # Allow time for the request to be processed
yesterday = (pd.Timestamp.now() - pd.Timedelta(days=1)).strftime('%Y%m%d')
app.reqHistoricalData(app.nextId(), contract=mycontract, endDateTime=f"{yesterday}-23:59:59", 
                      durationStr="1 Y", barSizeSetting="5 mins", whatToShow="TRADES",useRTH=1, 
                      formatDate=1, keepUpToDate=False,chartOptions=[])

for i in range(args.waittime):
    time.sleep(1)
    print(f"Waiting for data... {i+1}/{args.waittime} seconds")
    if not app.isConnected():
        print("Connection lost, exiting...")
        break

app.disconnect()
print("Disconnected from TWS.")
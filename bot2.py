"""Get AAPL market data"""
import threading
import time

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.ticktype import TickTypeEnum


class TestWrapper(EWrapper):
    """inbound"""

class TestClient(EClient):
    """outbound"""
    def __init__(self, wrapper):
        EClient.__init__(self, wrapper)

class TestApp(TestWrapper, TestClient):
    """My own code"""                 
    def __init__(self):
        TestWrapper.__init__(self)
        TestClient.__init__(self, wrapper=self)

    def tickPrice(self, reqId, tickType, price, attrib):
        print("tickPrice method was invoked")
        print("ticktype: ", tickType)
        if reqId==1:
            print("price is ", price)
        if tickType == 2 and reqId == 1:
            print('The current ask price is: ', price)
            
def run_loop():
    """Run again and again"""
    print("Inside run looop")
    app.run()
     
print("Creating TestApp")
app = TestApp()
app.connect('127.0.0.1', 7496, 80907)
print("Creating thread for connection")
api_thread = threading.Thread(target=run_loop, daemon=True)
api_thread.start()
print("Waiting for 1s")
time.sleep(1) #Sleep interval to allow time for connection to server

#Create contract object
apple_contract = Contract()
apple_contract.symbol = 'AAPL'
apple_contract.secType = 'STK'
apple_contract.exchange = 'SMART'
apple_contract.currency = 'USD'

#Request Market Data
"""3...Delayed data without subscription"""
print("setting delayed market data")
app.reqMarketDataType(3)
print("requesting market data")
app.reqMktData(reqId=1,
               contract=apple_contract,
               genericTickList='',
               snapshot=False,
               regulatorySnapshot=False,
               mktDataOptions=[])


time.sleep(30) #Sleep interval to allow time for incoming price data
app.disconnect()

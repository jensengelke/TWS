"""
Example IB API client with error handling:
- Connects to TWS.
- Obtains the option chain parameters for SPY.
- Chooses the next Friday’s expiry (if available) and selects the at-the-money option (by strike).
- Subscribes to market data for that option to stream ask-price updates and option delta.
- Prints detailed error messages if contract details cannot be obtained.
- Runs until the user presses ENTER.
"""

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.common import TickerId
from ibapi.ticktype import TickTypeEnum
import threading
import time
import datetime
import sys


class IBApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        # Storage for SPY contract details and option chain parameters
        self.spy_conId = None         # SPY contract identifier
        self.optionExpirations = []   # List of option expiration date strings (YYYYMMDD)
        self.optionStrikes = []       # List of available strike prices
        self.spy_price = 0.0          # Latest SPY market price
        self.option_ask_price = 0.0   # Latest ask price for the option
        self.option_delta = None      # Latest option delta
        # Store error details related to contract details (reqId 1)
        self.contract_details_error = None

    # Called when the next order id is received
    def nextValidId(self, orderId: int):
        self.orderId = orderId
        print(f"Next valid order ID: {self.orderId}")

    def nextId(self, orderId: int):
        self.orderId += 1
        print(f"Next ID updated to: {self.orderId}")

    #  Called when contract details are received (for SPY)
    def contractDetails(self, reqId: int, contractDetails):
        print("Received contract details for reqId", reqId)
        if reqId == 1:
            self.spy_conId = contractDetails.contract.conId
            print("Received SPY contract details. ConId =", self.spy_conId)

    def contractDetailsEnd(self, reqId: int):
        print("Contract details end for reqId:", reqId)
        # If we have the SPY conId, we can proceed to request option parameters.
        if reqId == 1 and self.spy_conId is not None:
            print("SPY conId obtained:", self.spy_conId)
        else:
            print("No valid SPY conId received. Cannot proceed with option parameters.")

    

    # Called with option chain parameters in response to reqSecDefOptParams
    def securityDefinitionOptionParameter(self, reqId: int, exchange: str, underlyingConId: int,
                                            tradingClass: str, multiplier: str,
                                            expirations: list, strikes: list):
        print("Received option parameters for reqId", reqId)
        self.optionExpirations = expirations
        self.optionStrikes = strikes
        print("Expirations:", expirations)
        print("Strikes:", strikes)

    # Called when market data price ticks are received.
    def tickPrice(self, reqId: TickerId, tickType: int, price: float, attrib):
        # For SPY, we requested market data with reqId 3.
        if reqId == 3:
            if tickType == TickTypeEnum.LAST:
                self.spy_price = price
                print("SPY Last Price:", price)
        # For the option we subscribe with reqId 4.
        elif reqId == 4:
            if tickType == TickTypeEnum.ASK:
                self.option_ask_price = price
                print("Option Ask Price:", price)

    # Called when option computations (like delta) are calculated.
    def tickOptionComputation(self, reqId: TickerId, tickType: int, impliedVol: float,
                              delta: float, optPrice: float, pvDividend: float,
                              gamma: float, vega: float, theta: float, undPrice: float):
        if reqId == 4:
            self.option_delta = delta
            print("Option Delta:", delta)

    # Error handling callback.
    def error(self, reqId: TickerId, errorCode: int, errorString: str, advancedOrderRejectJson=""):
        error_message = f"Error. Id: {reqId}, Code: {errorCode}, Msg: {errorString}"
        print(error_message)
        # Save error related to SPY contract details (reqId 1)
        if reqId == 1:
            self.contract_details_error = error_message


def compute_next_friday():
    """Compute next Friday's date in YYYYMMDD format."""
    today = datetime.date.today()
    # Friday is weekday 4 (where Monday=0)
    days_ahead = 4 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    next_friday = today + datetime.timedelta(days=days_ahead)
    return next_friday.strftime("%Y%m%d")


def main():
    app = IBApp()
        
    print("Thread started, waiting for connection...")

    try:
        # Connect to TWS; port 7497 is the default for paper trading.
        app.connect("127.0.0.1", 7496, clientId=2)
        print("Connecting to TWS...")
        time.sleep(1)
        print("serverVersion:%s connectionTime:%s" % (app.serverVersion(), app.twsConnectionTime()))

        threading.Thread(target=app.run, daemon=True).start()

        # Define SPY stock contract.
        spy_contract = Contract()
        spy_contract.symbol = "SPY"
        spy_contract.secType = "STK"
        spy_contract.exchange = "SMART"
        spy_contract.currency = "USD"

        # Request contract details to obtain the SPY conId.
        app.reqContractDetails(1, spy_contract)
        time.sleep(1)
        if not app.spy_conId:
            if app.contract_details_error:
                print("Failed to get SPY contract details:", app.contract_details_error)
            else:
                print("Failed to get SPY contract details: No valid details received.")
            app.disconnect()
            sys.exit(1)

        # Request option chain parameters for SPY.
        app.reqSecDefOptParams(reqId=2, underlyingSymbol="SPY", underlyingSecType="STK", underlyingConId=app.spy_conId, futFopExchange="")
        time.sleep(5)

        # Calculate next Friday’s expiry date.
        next_friday = compute_next_friday()
        print("Next Friday expiry:", next_friday)
        if next_friday not in app.optionExpirations:
            print("Next Friday expiry not available. Available expiries:", app.optionExpirations)
            app.disconnect()
            sys.exit(1)

        # Request market data for SPY to get the current underlying price.
        app.reqMktData(3, spy_contract, "", False, False, [])
        time.sleep(2)  # Allow time for price updates.
        if app.spy_price == 0.0:
            print("Did not receive SPY price data. Exiting.")
            app.disconnect()
            sys.exit(1)
        print("SPY current price:", app.spy_price)

        # Select the available strike closest to the SPY price.
        if not app.optionStrikes:
            print("No option strikes available. Exiting.")
            app.disconnect()
            sys.exit(1)
        candidate_strike = min(app.optionStrikes, key=lambda s: abs(s - app.spy_price))
        print("Selected strike for ATM option:", candidate_strike)

        # Construct the option contract for the chosen expiry and strike.
        option_contract = Contract()
        option_contract.symbol = "SPY"
        option_contract.secType = "OPT"
        option_contract.exchange = "SMART"
        option_contract.currency = "USD"
        option_contract.lastTradeDateOrContractMonth = next_friday
        option_contract.strike = candidate_strike
        option_contract.right = "C"  # Using a Call option as the at-the-money candidate

        # Request market data for the option.
        # The generic tick list "100" asks for option computations (e.g. delta).
        app.reqMktData(4, option_contract, "100", False, False, [])
        print("Streaming the option ask price (and delta) for the ATM option.")
        print("Press ENTER to exit...")

        # Wait until the user presses ENTER.
        input()

    except Exception as e:
        print("Exception occurred:", e)

    finally:
        app.disconnect()


if __name__ == "__main__":
    print("calling main()")
    main()
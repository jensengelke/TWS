from typing import Callable, Dict, List, Optional, Set, Any
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
import traceback
from collections import deque

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', filename='evaluate-options-trade.log', filemode='w')

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

class PriceData:
    stock_fields = ["LAST", "ASK", "BID"] # valid for all sec types
    option_fields = ["LAST", "ASK", "BID", "DELTA", "GAMMA", "VEGA", "IV"] 

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
        
        # Fallback to LAST if BID/ASK not available
        last = self.data.get("LAST")
        if last is not None:
            return last
            
        return None

class IncompleteDataError(Exception):
    """Raised when the expected move cannot be determined due to missing option data."""
    pass

class RequestHandler:
    def on_contract_details(self, reqId: int, contractDetails: ContractDetails): pass
    def on_contract_details_end(self, reqId: int): pass
    def on_tick_price(self, reqId: int, tickType: int, price: float, attrib): pass
    def on_tick_size(self, reqId: int, tickType: int, size: Decimal): pass
    def on_tick_option_computation(self, reqId: int, tickType: int, tickAttrib: int, impliedVol: float, delta: float, optPrice: float, pvDividend: float, gamma: float, vega: float, theta: float, undPrice: float): pass
    def on_historical_data(self, reqId: int, bar): pass
    def on_historical_data_end(self, reqId: int, start: str, end: str): pass
    def on_error(self, reqId: int, errorCode: int, errorString: str): pass

class EarningsApp(EWrapper, EClient):
    requestId = 0
    def __init__(self):
        EClient.__init__(self, self)
        self.request_handlers: Dict[int, RequestHandler] = {}
        self.lock = threading.Lock()
        
        # Rate limiting for market data
        self.active_mkt_requests = set()
        self.mkt_data_queue = deque()
        self.MAX_CONCURRENT_MKT_DATA = 95
        
        # Rate limiting for contract details
        self.active_contract_requests = set()
        self.contract_queue = deque()
        self.MAX_CONCURRENT_CONTRACTS = 5

    def reqMktData(self, reqId: TickerId, contract: Contract, genericTickList: str, snapshot: bool, regulatorySnapshot: bool, mktDataOptions: List[Any], on_sent: Callable = None):
        with self.lock:
            if len(self.active_mkt_requests) < self.MAX_CONCURRENT_MKT_DATA:
                self.active_mkt_requests.add(reqId)
                if on_sent: on_sent()
                super().reqMktData(reqId, contract, genericTickList, snapshot, regulatorySnapshot, mktDataOptions)
            else:
                self.mkt_data_queue.append((reqId, contract, genericTickList, snapshot, regulatorySnapshot, mktDataOptions, on_sent))
                logging.info(f"Queued market data request {reqId}. Queue size: {len(self.mkt_data_queue)}")

    def reqContractDetails(self, reqId: int, contract: Contract, on_sent: Callable = None):
        with self.lock:
            if len(self.active_contract_requests) < self.MAX_CONCURRENT_CONTRACTS:
                self.active_contract_requests.add(reqId)
                if on_sent: on_sent()
                super().reqContractDetails(reqId, contract)
            else:
                self.contract_queue.append((reqId, contract, on_sent))
                logging.info(f"Queued contract request {reqId}. Queue size: {len(self.contract_queue)}")

    def cancelMktData(self, reqId: TickerId):
        with self.lock:
            if reqId in self.active_mkt_requests:
                self.active_mkt_requests.remove(reqId)
                super().cancelMktData(reqId)
                self.process_queue()
            else:
                # Remove from queue if present
                for i, req in enumerate(self.mkt_data_queue):
                    if req[0] == reqId:
                        del self.mkt_data_queue[i]
                        logging.info(f"Removed queued request {reqId}")
                        break

    def process_queue(self):
        while len(self.active_mkt_requests) < self.MAX_CONCURRENT_MKT_DATA and self.mkt_data_queue:
            req = self.mkt_data_queue.popleft()
            reqId = req[0]
            on_sent = req[-1]
            args = req[:-1]
            self.active_mkt_requests.add(reqId)
            if on_sent: on_sent()
            super().reqMktData(*args)
            logging.info(f"Dequeued and sent market data request {reqId}")

    def process_contract_queue(self):
        while len(self.active_contract_requests) < self.MAX_CONCURRENT_CONTRACTS and self.contract_queue:
            req = self.contract_queue.popleft()
            reqId, contract, on_sent = req
            self.active_contract_requests.add(reqId)
            if on_sent: on_sent()
            super().reqContractDetails(reqId, contract)
            logging.info(f"Dequeued contract request {reqId}")

    def nextId(self):
        with self.lock:
            self.requestId += 1
            return self.requestId

    def register_handler(self, reqId: int, handler: RequestHandler):
        with self.lock:
            self.request_handlers[reqId] = handler

    def unregister_handler(self, reqId: int):
        with self.lock:
            self.request_handlers.pop(reqId, None)

    def error(self, reqId: TickerId, errorTime: int, errorCode: int, errorString: str, advancedOrderRejectJson=""):
        with self.lock:
             if reqId in self.active_contract_requests:
                 self.active_contract_requests.remove(reqId)
                 self.process_contract_queue()
        error_message = f"Error. Id: {reqId}, Code: {errorCode}, Msg: {errorString}"
        if reqId == -1:
            logging.debug(f"Error: {error_message}")
        else:
            if errorCode == 366:
                logging.debug(f"Error: {error_message} - No market data available outside trading hours.")
            else:
                logging.error(error_message)
            
            with self.lock:
                handler = self.request_handlers.get(reqId)
            if handler:
                handler.on_error(reqId, errorCode, errorString)

    def contractDetails(self, reqId: int, contractDetails):
        with self.lock:
            handler = self.request_handlers.get(reqId)
        if handler:
            handler.on_contract_details(reqId, contractDetails)

    def contractDetailsEnd(self, reqId: int):
        with self.lock:
            if reqId in self.active_contract_requests:
                self.active_contract_requests.remove(reqId)
                self.process_contract_queue()
            handler = self.request_handlers.get(reqId)
        if handler:
            handler.on_contract_details_end(reqId)

    def tickPrice(self, reqId: TickerId, tickType: int, price: float, attrib):
        with self.lock:
            handler = self.request_handlers.get(reqId)
        if handler:
            handler.on_tick_price(reqId, tickType, price, attrib)

    def tickSize(self, reqId: TickerId, tickType: TickType, size: Decimal):
        with self.lock:
            handler = self.request_handlers.get(reqId)
        if handler:
            handler.on_tick_size(reqId, tickType, size)

    def tickOptionComputation(self, reqId: TickerId, tickType: TickType, tickAttrib: int, impliedVol: float, delta: float, optPrice: float, pvDividend: float, gamma: float, vega: float, theta: float, undPrice: float):
        with self.lock:
            handler = self.request_handlers.get(reqId)
        if handler:
            handler.on_tick_option_computation(reqId, tickType, tickAttrib, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice)

    def historicalData(self, reqId: int, bar):
        with self.lock:
            handler = self.request_handlers.get(reqId)
        if handler:
            handler.on_historical_data(reqId, bar)

    def historicalDataEnd(self, reqId: int, start: str, end: str):
        with self.lock:
            handler = self.request_handlers.get(reqId)
        if handler:
            handler.on_historical_data_end(reqId, start, end)

def compute_next_friday():
    """Compute next Friday's date in YYYYMMDD format."""
    today = datetime.date.today()
    days_ahead = 4 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    next_friday = today + datetime.timedelta(days=days_ahead)
    return next_friday.strftime("%Y%m%d")

class SymbolProcessor(RequestHandler):
    def __init__(self, app: EarningsApp, symbol: str):
        self.app = app
        self.symbol = symbol
        self.status = "PENDING"
        self.error_msg = ""
        self.last_message = ""
        
        self.setup_logger()
        self.log(f"Initialized. Status: {self.status}")
        
        # Data storage
        self.stock_contract = None
        self.price_data = PriceData("STK")
        self.historic_data = pd.DataFrame(columns=['date', 'time', 'open', 'high', 'low', 'close'])
        self.options_chain: Dict[str, ContractDetails] = {} # localSymbol -> ContractDetails
        
        # Track active requests
        self.req_ids = set()
        
        # Flags
        self.stock_contract_received = False
        self.price_received = False
        self.history_received = False
        self.option_chain_complete = False
        
        # Intermediate calculations
        self.average_percent_move = 0.0
        self.top_moves = []
        self.expected_move = 0.0
        self.lower_boundary = 0.0
        self.upper_boundary = 0.0
        
        # Processing state
        self.analyzing_options = False
        self.waiting_for_core_options = False
        self.waiting_for_range_options = False
        self.final_calculation_done = False
        self.failed = False
        self.abort_processing = False
        
        # Track specific option requests
        self.core_option_reqs = set() # reqIds for ATM/Strangle
        self.range_option_reqs = set() # reqIds for range options
        self.option_price_data: Dict[str, PriceData] = {} # localSymbol -> PriceData

        # Timestamps for timeouts
        self.start_time = time.time()
        self.option_chain_req_time = None
        self.core_options_req_time = None
        self.range_options_req_time = None

    @property
    def is_done(self):
        return self.status == "COMPLETED" or self.status == "ABORTED" or self.status.startswith("FAILED") or self.status.startswith("TIMEOUT") or self.status == "ERROR_HISTORY"

    def setup_logger(self):
        log_dir = "data/logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        self.logger = logging.getLogger(f"Symbol_{self.symbol}")
        self.logger.setLevel(logging.INFO)
        
        # Clear handlers to avoid dupes if re-init
        if self.logger.hasHandlers():
            self.logger.handlers.clear()
            
        fh = logging.FileHandler(f"{log_dir}/{self.symbol}.log", mode='w')
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)

    def log(self, msg):
        self.last_message = msg
        # Log to global (file)
        logging.info(f"[{self.symbol}] {msg}")
        # Log to symbol file
        if hasattr(self, 'logger'):
            self.logger.info(msg)

    def set_status(self, status, reason=""):
        old_status = self.status
        self.status = status
        msg = f"Status change: {old_status} -> {status}"
        if reason:
            msg += f" | Reason: {reason}"
        self.log(msg)

    def get_option_chain_status(self):
        if not self.option_chain_complete:
            return "Pending"

        if not self.analyzing_options and not self.waiting_for_core_options and not self.waiting_for_range_options:
             if not self.price_received:
                 return "Wait Stock Px"
             return "Ready"
        
        if self.waiting_for_core_options:
            count = 0
            for key in self.target_option_keys:
                if key not in self.option_price_data or self.option_price_data[key].get_instrument_value() is None:
                    count += 1
            return f"{count} remaining"
            
        if self.waiting_for_range_options:
            count = 0
            for reqId in self.range_option_reqs:
                key = self.reqid_to_symbol.get(reqId)
                if key:
                    if key not in self.option_price_data or self.option_price_data[key].get_instrument_value() is None:
                        count += 1
            return f"{count} remaining"
            
        return "Complete"

    def start(self):
        self.set_status("GETTING_STOCK_CONTRACT", "Starting processing")
        contract = Contract()
        contract.symbol = self.symbol
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = "USD"
        
        reqId = self.app.nextId()
        self.app.register_handler(reqId, self)
        self.req_ids.add(reqId)
        
        self.app.reqContractDetails(reqId, contract)

    def stop(self):
        # Cancel all active data requests
        for reqId in list(self.req_ids):
            self.app.cancelMktData(reqId)
            self.app.cancelHistoricalData(reqId)
            self.app.unregister_handler(reqId)
        self.req_ids.clear()

    # --- Request Handler Methods ---

    def on_contract_details(self, reqId: int, contractDetails: ContractDetails):
        if self.status == "GETTING_STOCK_CONTRACT":
            self.stock_contract = contractDetails.contract
            self.stock_contract_received = True
            self.set_status("PROCESSING", "Stock contract received")
            self.log(f"Stock contract received: {self.stock_contract.conId}")
            
            # Fire parallel requests
            self.req_market_data_stock()
            self.req_history()
            self.req_option_chain()
            
        elif self.status in ["PROCESSING", "FETCHING_CHAIN"]:
            # Must be option chain details
            self.options_chain[contractDetails.contract.localSymbol] = contractDetails

    def on_contract_details_end(self, reqId: int):
        # Only relevant for option chain as stock contract is single
        if self.status in ["PROCESSING", "FETCHING_CHAIN"] and not self.option_chain_complete:
            # We assume this is the option chain end
            # Note: We can't strictly distinguish request types by ID easily without storing map, 
            # but flow logic suggests this.
            if len(self.options_chain) > 0:
                self.option_chain_complete = True
                self.log(f"Option chain complete. {len(self.options_chain)} options found.")
                self.check_step_expected_move()

    def on_tick_price(self, reqId: int, tickType: int, price: float, attrib):
        self.handle_tick(reqId, tickType, price)

    def on_tick_size(self, reqId: int, tickType: int, size: Decimal):
        self.handle_tick(reqId, tickType, size)

    def handle_tick(self, reqId: int, tickType, value):
        # Determine if this is stock or option data
        # Since we don't have a direct map here in this simplified class, we check specific sets
        
        # 1. Stock Price
        if hasattr(self, 'stock_req_id') and reqId == self.stock_req_id:
            field = TickTypeEnum.toStr(tickType)
            self.price_data.update(value, field)
            if not self.price_received and self.price_data.get_instrument_value() is not None:
                # We have a price
                self.price_received = True
                self.log(f"Stock price received: {self.price_data.get_instrument_value()}")
                # Check for "Is Good Stock"
                is_good, reason = self.is_good_stock()
                if not is_good:
                    self.log(f"Stock too cheap (< $40). Reason: {reason}. Aborting.")
                    self.abort_processing = True
                    self.failed = True
                    self.set_status("ABORTED", reason)
                    self.stop()
                    return
                self.check_step_expected_move()

        # 2. Option Price
        elif reqId in self.core_option_reqs or reqId in self.range_option_reqs:
            # Find which option this is. 
            # We need to store reqId -> localSymbol map
            if reqId in self.reqid_to_symbol:
                local_sym = self.reqid_to_symbol[reqId]
                if local_sym not in self.option_price_data:
                    self.option_price_data[local_sym] = PriceData("OPT")
                
                if isinstance(value, float) or isinstance(value, Decimal) or isinstance(value, int):
                    field = TickTypeEnum.toStr(tickType)
                    self.option_price_data[local_sym].update(value, field)
                
                # Check completions handled in main loop or periodic check
        
    def on_tick_option_computation(self, reqId: int, tickType: int, tickAttrib: int, impliedVol: float, delta: float, optPrice: float, pvDividend: float, gamma: float, vega: float, theta: float, undPrice: float):
        if reqId in self.reqid_to_symbol:
            local_sym = self.reqid_to_symbol[reqId]
            if local_sym not in self.option_price_data:
                self.option_price_data[local_sym] = PriceData("OPT")
            
            p_data = self.option_price_data[local_sym]
            p_data.update(delta, "DELTA")
            p_data.update(impliedVol, "IV")
            p_data.update(gamma, "GAMMA")
            p_data.update(vega, "VEGA")
            p_data.update(theta, "THETA")
            # also update price if available? optPrice
            if optPrice is not None:
                p_data.update(optPrice, "MARK_PRICE") # Synthetic field

    def on_historical_data(self, reqId: int, bar):
        split_date = bar.date.split('  ')
        date = split_date[0]
        time_val = None if (len(split_date) < 2) else split_date[1]
        row = {
            'date': date,
            'time': time_val,
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close
        }
        self.historic_data.loc[len(self.historic_data)] = row

    def on_historical_data_end(self, reqId: int, start: str, end: str):
        self.log("Historical data complete.")
        # Process history immediately
        try:
            df = self.historic_data
            df['candle_length'] = df['high'] - df['low']
            df['percent_move'] = (df['candle_length'] / df['close']) * 100
            
            top_moves = df.nlargest(14, 'percent_move')[['date',  'open', 'high', 'low', 'close', 'candle_length', 'percent_move']]
            self.top_moves = top_moves.to_dict(orient='records')
            self.average_percent_move = top_moves['percent_move'].mean()
            self.log(f"Avg percent move: {self.average_percent_move:.2f}%")
            
            self.history_received = True
            self.app.cancelHistoricalData(reqId)
            self.app.unregister_handler(reqId)
            self.req_ids.discard(reqId)
            
            self.check_completion()
        except Exception as e:
            self.log(f"Error processing history: {e}")
            self.failed = True
            self.set_status("ERROR_HISTORY", f"Exception: {e}")

    def on_error(self, reqId: int, errorCode: int, errorString: str):
        # Ignore some codes
        if errorCode == 2104 or errorCode == 2106 or errorCode == 2158:
            return
        
        # If critical error on stock contract or critical step
        if reqId in self.req_ids and self.status == "GETTING_STOCK_CONTRACT":
            self.failed = True
            self.error_msg = errorString
            self.set_status("FAILED", f"IB Error: {errorString}")
            self.log(f"Failed to get contract: {errorString}")

    # --- Actions ---

    def req_market_data_stock(self):
        self.stock_req_id = self.app.nextId()
        self.app.register_handler(self.stock_req_id, self)
        self.req_ids.add(self.stock_req_id)
        self.app.reqMarketDataType(4) # https://www.interactivebrokers.com/campus/trading-lessons/python-receiving-market-data/
        # Request tick data
        self.app.reqMktData(self.stock_req_id, self.stock_contract, "232", False, False, [])

    def req_history(self):
        reqId = self.app.nextId()
        self.app.register_handler(reqId, self)
        self.req_ids.add(reqId)
        yesterday = (pd.Timestamp.now() - pd.Timedelta(days=1)).strftime('%Y%m%d')
        self.app.reqHistoricalData(reqId, contract=self.stock_contract, endDateTime=f"{yesterday}-23:59:59", 
                      durationStr="3 Y", barSizeSetting="1 day", whatToShow="TRADES",useRTH=1, 
                      formatDate=1, keepUpToDate=False,chartOptions=[])

    def req_option_chain(self):
        contract = Contract()
        contract.symbol = self.symbol
        contract.secType = "OPT"
        contract.exchange = "SMART"
        contract.currency = "USD"
        contract.lastTradeDateOrContractMonth = compute_next_friday()
        
        reqId = self.app.nextId()
        self.app.register_handler(reqId, self)
        self.req_ids.add(reqId)
        self.app.reqContractDetails(reqId, contract, on_sent=lambda: setattr(self, 'option_chain_req_time', time.time()))
        
        # We also need a mapping for option requests later
        self.reqid_to_symbol = {}

    def is_good_stock(self):
        last = self.price_data.get("LAST")
        ask = self.price_data.get("ASK")
        bid = self.price_data.get("BID")
        val = self.price_data.get_instrument_value()
        
        if last is not None and last > -1 and last < 40: return False, f"LAST {last} < 40"
        if ask is not None and ask > -1 and ask < 40: return False, f"ASK {ask} < 40"
        if bid is not None and bid > -1 and bid < 40: return False, f"BID {bid} < 40"
        if val is None or val < 40: return False, f"Val {val} < 40 or None"
        
        return True, ""

    def check_step_expected_move(self):
        # Triggered when price received OR option chain complete
        if self.price_received and self.option_chain_complete and not self.analyzing_options and not self.waiting_for_core_options and not self.waiting_for_range_options:
            self.start_expected_move_calc()

    def start_expected_move_calc(self):
        self.analyzing_options = True
        self.log("Calculating expected move targets...")
        
        try:
            current_price = self.price_data.get_instrument_value()
            
            # Convert chain to DF
            data = {}
            for key, contract_details in self.options_chain.items():
                data[key] = contract_details.contract.__dict__
            
            options_df = pd.DataFrame.from_dict(data, orient='index')
            if options_df.empty:
                self.log("No options found.")
                self.failed = True
                self.set_status("FAILED_NO_OPTS", "Options DF empty")
                self.stop()
                return

            options_df["distance_from_price"] = (options_df["strike"] - current_price).abs()
            closest_options = options_df.nsmallest(6, 'distance_from_price').sort_values(by='strike')
            
            unique_strikes = closest_options['strike'].unique()
            if len(unique_strikes) < 3:
                self.log("Not enough strikes.")
                self.failed = True
                self.set_status("FAILED_FEW_STRIKES", f"Found {len(unique_strikes)} strikes")
                self.stop()
                return

            atm_strike = unique_strikes[1]
            
            # Get specific contracts
            try:
                atm_call_key = closest_options[(closest_options['strike'] == atm_strike) & (closest_options['right'] == 'C')].index[0]
                atm_put_key = closest_options[(closest_options['strike'] == atm_strike) & (closest_options['right'] == 'P')].index[0]
                
                strangle_put_key = closest_options[(closest_options['strike'] == unique_strikes[0]) & (closest_options['right'] == 'P')].index[0]
                strangle_call_key = closest_options[(closest_options['strike'] == unique_strikes[2]) & (closest_options['right'] == 'C')].index[0]
            except IndexError:
                self.log("Could not find required ATM/Strangle options.")
                self.failed = True
                self.set_status("FAILED_MISSING_OPT", "ATM/Strangle options missing")
                self.stop()
                return

            self.target_option_keys = [atm_call_key, atm_put_key, strangle_call_key, strangle_put_key]
            
            # Request Data
            self.waiting_for_core_options = True
            for key in self.target_option_keys:
                details = self.options_chain[key]
                self.req_option_data(key, details.contract, is_core=True)
                
        except Exception as e:
            self.log(f"Error in start_expected_move_calc: {e}")
            logging.error(traceback.format_exc())
            self.failed = True
            self.set_status("FAILED_CALC_ERR", f"Exception: {e}")
            self.stop()

    def req_option_data(self, key, contract, is_core=False):
        reqId = self.app.nextId()
        self.app.register_handler(reqId, self)
        self.req_ids.add(reqId)
        self.reqid_to_symbol[reqId] = key
        
        on_sent = None
        if is_core:
            self.core_option_reqs.add(reqId)
            on_sent = lambda: setattr(self, 'core_options_req_time', time.time())
        else:
            self.range_option_reqs.add(reqId)
            on_sent = lambda: setattr(self, 'range_options_req_time', time.time())
            
        tick_types="100,101,232" # Option specific
        self.app.reqMktData(reqId, contract, tick_types, False, False, [], on_sent=on_sent)

    def process_expected_move_result(self):
        # Called when 4 options have data
        self.log("Core options data received. Calculating expected move value.")
        try:
            vals = []
            for key in self.target_option_keys:
                if key not in self.option_price_data:
                    self.log(f"Missing data for {key}")
                    # Try to use what we have or fail?
                    # Code says raise IncompleteDataError
                    self.failed = True
                    self.set_status("FAILED_MISSING_DATA", f"Key {key}")
                    self.stop()
                    return
                val = self.option_price_data[key].get_instrument_value()
                if val is None:
                    self.failed = True
                    self.set_status("FAILED_VAL_NONE", f"Key {key}")
                    self.log(f"Value None for {key}")
                    self.stop()
                    return
                vals.append(val)
                
            self.expected_move = sum(vals) / 2
            current_price = self.price_data.get_instrument_value()
            double_expected_move_up = current_price + (2 * self.expected_move)
            double_expected_move_down = current_price - (2 * self.expected_move)
            
            self.log(f"Expected Move: {self.expected_move:.2f}, Range: {double_expected_move_down:.2f} - {double_expected_move_up:.2f}")
            
            # Expand boundaries
            sorted_strikes = sorted(list(set(d.contract.strike for d in self.options_chain.values())))
            
            idx_min = 0
            for i, s in enumerate(sorted_strikes):
                if s >= double_expected_move_down:
                    idx_min = i
                    break
            
            idx_max = len(sorted_strikes) - 1
            for i in range(len(sorted_strikes) - 1, -1, -1):
                if sorted_strikes[i] <= double_expected_move_up:
                    idx_max = i
                    break
                    
            idx_min_expanded = max(0, idx_min - 2)
            idx_max_expanded = min(len(sorted_strikes) - 1, idx_max + 2)
            
            self.filter_min_strike = sorted_strikes[idx_min_expanded]
            self.filter_max_strike = sorted_strikes[idx_max_expanded]
            
            # Request range options
            self.waiting_for_core_options = False
            self.waiting_for_range_options = True
            
            count = 0
            for key, details in self.options_chain.items():
                strike = details.contract.strike
                if self.filter_min_strike <= strike <= self.filter_max_strike:
                    # Skip if we already requested it (core options)
                    if key in self.option_price_data:
                        continue
                    self.req_option_data(key, details.contract, is_core=False)
                    count += 1
            
            self.log(f"Requested data for {count} range options.")
            if count == 0:
                 self.waiting_for_range_options = False
                 self.check_completion()
                 
        except Exception as e:
            self.log(f"Error calculating move: {e}")
            logging.error(traceback.format_exc())
            self.failed = True
            self.set_status("FAILED_PROC_ERR", f"Exception: {e}")
            self.stop()

    def check_core_options_complete(self):
        if not self.waiting_for_core_options: return
        
        # Check if all core options have prices
        all_good = True
        for key in self.target_option_keys:
            if key not in self.option_price_data or self.option_price_data[key].get_instrument_value() is None:
                all_good = False
                break
        
        if all_good:
            self.process_expected_move_result()
        elif self.core_options_req_time and time.time() - self.core_options_req_time > 30:
            self.log("Core options timeout. Aborting.")
            self.failed = True
            self.set_status("TIMEOUT_CORE", "30s timeout waiting for core options")
            self.stop()

    def check_range_options_complete(self):
        if not self.waiting_for_range_options: return
        
        # We wait for timeout or until all populated
        # Logic: If all requests have response
        # self.range_option_reqs contains reqIds
        
        pending = []
        for reqId in self.range_option_reqs:
            key = self.reqid_to_symbol.get(reqId)
            if key:
                if key not in self.option_price_data or self.option_price_data[key].get_instrument_value() is None:
                    pending.append(key)
        
        if len(pending) == 0:
            self.log("All range options data received.")
            self.waiting_for_range_options = False
            self.check_completion()
        else:
            # Check timeout (20s for range options)
            if self.range_options_req_time and time.time() - self.range_options_req_time > 20:
                self.log(f"Range options timeout. {len(pending)} missing.")
                self.waiting_for_range_options = False
                self.check_completion()

    def check_option_chain_timeout(self):
        if self.status == "PROCESSING" and not self.option_chain_complete:
            # Check timeout (30s)
            if self.option_chain_req_time and time.time() - self.option_chain_req_time > 30:
                self.log("Option chain retrieval timed out. Proceeding with what we have.")
                self.option_chain_complete = True
                self.check_step_expected_move()

    def tick(self):
        # Called periodically from main loop
        if self.failed or self.status == "COMPLETED" or self.status == "ABORTED": return

        # Overall timeout (10 minutes)
        if time.time() - self.start_time > 600:
             self.log("Overall timeout (600s). Aborting.")
             self.failed = True
             self.set_status("TIMEOUT_OVERALL", "Exceeded 10 minutes")
             self.stop()
             return

        # Fallback for stock price
        if self.status == "PROCESSING" and not self.price_received and self.history_received:
             if time.time() - self.start_time > 15:
                 if not self.historic_data.empty:
                     last_close = self.historic_data.iloc[-1]['close']
                     self.log(f"Stock price timeout. Using historical close: {last_close}")
                     self.price_data.update(last_close, "LAST")
                     self.price_received = True
                     # Check is good stock
                     is_good, reason = self.is_good_stock()
                     if not is_good:
                        self.log(f"Stock too cheap (historic < $40). Reason: {reason}. Aborting.")
                        self.abort_processing = True
                        self.failed = True
                        self.set_status("ABORTED", reason)
                        self.stop()
                        return
                     self.check_step_expected_move()

        if not self.option_chain_complete:
            self.check_option_chain_timeout()
        
        if self.waiting_for_core_options:
            # Check timeout for core options?
            self.check_core_options_complete()
            
        if self.waiting_for_range_options:
            self.check_range_options_complete()
            
        self.check_completion()

    def check_completion(self):
        if self.failed or self.status == "COMPLETED": return
        
        # Criteria:
        # 1. History done
        # 2. Options range data done (or timed out)
        # 3. Expected move calculated
        
        if self.history_received and not self.waiting_for_core_options and not self.waiting_for_range_options and self.analyzing_options:
            self.log("All data ready. Saving.")
            self.save_results()
            self.set_status("COMPLETED", "All data received and saved")
            self.stop()

    def save_results(self):
        try:
            current_price = self.price_data.get_instrument_value()
            usual_up_spike = current_price + (self.average_percent_move / 100) * current_price
            usual_down_spike = current_price - (self.average_percent_move / 100) * current_price
            
            double_expected_move_up = current_price + (2 * self.expected_move)
            double_expected_move_down = current_price - (2 * self.expected_move)
            
            upper_boundary = max(double_expected_move_up, usual_up_spike)
            lower_boundary = min(double_expected_move_down, usual_down_spike)

            save_results_to_json(
                symbol=self.symbol,
                underlying_price_data=self.price_data,
                expected_move=self.expected_move,
                average_percent_move=self.average_percent_move,
                lower_boundary=lower_boundary,
                upper_boundary=upper_boundary,
                historic_moves=self.top_moves,
                options_chain=self.options_chain,
                price_data_map=self.option_price_data
            )
        except Exception as e:
            self.log(f"Error saving results: {e}")
            logging.error(traceback.format_exc())


def save_results_to_json(symbol: str, underlying_price_data: PriceData, expected_move: float, average_percent_move: float, lower_boundary: float, upper_boundary: float, historic_moves: list, options_chain: dict, price_data_map: dict):
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
    
    # We filter for options that we have data for, or are in the request range?
    # The original code saved options where `local_symbol in price_data`
    
    for local_symbol, details in options_chain.items():
        if local_symbol in price_data_map:
            p_data = price_data_map[local_symbol]
            # Verify we actually have data?
            if p_data.get_instrument_value() is None and p_data.get("BID") is None:
                continue
                
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
            logging.info(f"Error reading {filepath}, starting fresh.")
            
    if isinstance(data, list):
        data = {"prices": data}
        
    if "prices" not in data:
        data["prices"] = []

    if historic_moves is not None:
        data["historic_move"] = historic_moves

    data["prices"].append(new_entry)
    
    with open(filepath, "w") as f:
        json.dump(data, f, indent=4, cls=DecimalEncoder)
    logging.info(f"Saved results to {filepath}")


def get_symbols_from_earnings_file(filename: str):
    symbols = []
    if filename == "" or filename is None:
        return symbols
    
    if not os.path.exists(filename):
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
                today = datetime.date.today()
                yesterday = today - datetime.timedelta(days=1)
                tomorrow = today + datetime.timedelta(days=1)
                
                accepted_dates = {today.strftime("%Y-%m-%d"), yesterday.strftime("%Y-%m-%d"), tomorrow.strftime("%Y-%m-%d")}
                
                for item in data["data"]:
                    open_trade_date_str = item.get("open_trade_date", "")
                    if len(open_trade_date_str) >= 10:
                        trade_date_part = open_trade_date_str[:10]
                        if trade_date_part not in accepted_dates:
                            continue
                            
                    symbol = item.get("ticker")
                    if symbol:
                        symbols.append(symbol)
    except Exception as e:
        print(f"Error reading {filename}: {e}")        
        
    return symbols

def main():
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', filename='evaluate-options-trade.log', filemode='w')
    parser = argparse.ArgumentParser(description="Get option chain for a symbol and evaluate trade options.")
    parser.add_argument("--symbol", type=str, help="The stock symbol to evaluate options for.")
    parser.add_argument("--earnings-week", type=str, help="Path to the earnings week JSON file.", default=None)
    parser.add_argument("--paper", action="store_true", help="Connect to default port for paper trading")
    
    args = parser.parse_args()

    app = EarningsApp()
    logging.info("Starting IB API Test Application...")
    random_client_id = int(time.time()) % 1000
    port : int = 7496
    if args.paper:
        port = 7497
    
    print(f"Connecting to port={port}")
    app.connect("127.0.0.1", port, clientId=random_client_id)
    logging.info("Connecting to TWS...")
    time.sleep(1)
    
    threading.Thread(target=app.run, daemon=True).start()
    
    symbols = []
    if args.symbol:
        symbols.append(args.symbol)
    elif args.earnings_week:
        if args.earnings_week == "current":
             today = datetime.date.today()
             start_of_week = today - datetime.timedelta(days=today.weekday())
             args.earnings_week = start_of_week.strftime("%Y-%m-%d")

        earnings_file=f"docs/data/earnings-for-week-starting-{args.earnings_week}.json"
        print(f"Processing earnings week file: {earnings_file}")
        symbols = get_symbols_from_earnings_file(earnings_file)
    else:
         print("No symbol or earnings week file provided.")
         return

    print(f"Evaluating {len(symbols)} symbols: {symbols}")
    
    processors = []
    for sym in symbols:
        p = SymbolProcessor(app, sym)
        processors.append(p)
        p.start()
        # Sleep slightly to avoid flooding IB TWS completely instantenously?
        # IB has pacing limits.
        time.sleep(0.5)

    # Monitoring loop
    try:
        while True:
            active_count = 0
            for p in processors:
                p.tick()
                if not p.is_done:
                    active_count += 1
            
            # Clear screen
            os.system('cls' if os.name == 'nt' else 'clear')
            
            # Print table
            print(f"{'Symbol':<8} {'Status':<25} {'Stock':<10} {'History':<10} {'Option Chain':<15}")
            print("-" * 75)
            for p in processors:
                stock_status = "Complete" if p.stock_contract_received else "Pending"
                hist_status = "Complete" if p.history_received else "Pending"
                opt_status = p.get_option_chain_status()
                print(f"{p.symbol:<8} {p.status:<25} {stock_status:<10} {hist_status:<10} {opt_status:<15}")
            
            if active_count == 0:
                print("\nAll tasks completed or failed.")
                break
                
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        for p in processors:
            p.stop()
            
    print("\nDone.")
    app.disconnect()

if __name__ == "__main__":
    main()

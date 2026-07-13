import asyncio
from typing import Dict, List, Optional
from ib_async import IB, Stock, Option, util, Contract
from decimal import Decimal
import argparse
import logging
import datetime
import sys
import pandas as pd
import json
import os
import traceback

# Setup logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s', 
    filename='evaluate-options-trade-async.log', 
    filemode='w'
)

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def compute_next_friday():
    """Compute next Friday's date in YYYYMMDD format."""
    today = datetime.date.today()
    days_ahead = 4 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    next_friday = today + datetime.timedelta(days=days_ahead)
    return next_friday.strftime("%Y%m%d")

class SymbolProcessorAsync:
    def __init__(self, ib: IB, symbol: str):
        self.ib = ib
        self.symbol = symbol
        self.status = "PENDING"
        self.error_msg = ""
        self.last_message = ""
        
        self.setup_logger()
        self.log(f"Initialized. Status: {self.status}")
        
        # Data storage
        self.stock_price = None
        self.historic_data = pd.DataFrame(columns=['date', 'time', 'open', 'high', 'low', 'close'])
        self.options_chain: Dict[str, Contract] = {}  # localSymbol -> Contract
        
        # Intermediate calculations
        self.average_percent_move = 0.0
        self.top_moves = []
        self.expected_move = 0.0
        self.lower_boundary = 0.0
        self.upper_boundary = 0.0
        
        # Option price data
        self.option_prices: Dict[str, Dict] = {}  # localSymbol -> {bid, ask, price, iv, delta, etc.}
        
        # Processing state
        self.failed = False
        self.completed = False

    @property
    def is_done(self):
        return self.completed or self.failed

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
        logging.info(f"[{self.symbol}] {msg}")
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
        if not self.options_chain:
            return "Pending"
        if not self.option_prices:
            return "Ready"
        return f"{len(self.option_prices)} priced"

    async def process(self):
        """Main processing pipeline - runs all steps concurrently where possible."""
        try:
            self.set_status("GETTING_STOCK_CONTRACT", "Starting processing")
            
            # Create stock contract
            stock = Stock(self.symbol, 'SMART', 'USD')
            
            # Qualify the contract (get full details)
            qualified_contracts = await self.ib.qualifyContractsAsync(stock)
            if not qualified_contracts:
                self.failed = True
                self.set_status("FAILED", "Could not qualify stock contract")
                return
            
            stock_contract = qualified_contracts[0]
            self.log(f"Stock contract qualified: {stock_contract.conId}")
            
            self.set_status("FETCHING_DATA", "Fetching stock price, history, and option chain")
            
            # Request market data type (4 = delayed if live not available)
            self.ib.reqMarketDataType(4)
            
            # Run all three data fetches concurrently
            results = await asyncio.gather(
                self.get_stock_price(stock_contract),
                self.get_historical_data(stock_contract),
                self.get_option_chain(stock_contract),
                return_exceptions=True
            )
            
            # Check for exceptions in results
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    step_name = ["stock price", "historical data", "option chain"][i]
                    self.log(f"Error in {step_name}: {result}")
                    self.failed = True
                    self.set_status("FAILED", f"Error in {step_name}")
                    return
            
            # Check if stock price is acceptable
            if self.stock_price is None or self.stock_price < 40:
                self.failed = True
                self.set_status("ABORTED", f"Stock price {self.stock_price} < $40")
                return
            
            # Process historical data
            self.process_historical_data()
            
            # Calculate expected move and get option prices
            await self.calculate_expected_move()
            
            # Save results
            self.save_results()
            self.completed = True
            self.set_status("COMPLETED", "All data received and saved")
            
        except Exception as e:
            self.log(f"Error in process: {e}")
            logging.error(traceback.format_exc())
            self.failed = True
            self.set_status("FAILED", f"Exception: {e}")

    async def get_stock_price(self, stock_contract):
        """Get current stock price."""
        try:
            # Request market data snapshot
            ticker = self.ib.reqMktData(stock_contract, '', False, False)
            
            # Wait for price data (with timeout)
            for _ in range(50):  # 5 seconds max
                await asyncio.sleep(0.1)
                if util.isNan(ticker.last):
                    # Try bid/ask
                    if not util.isNan(ticker.bid) and not util.isNan(ticker.ask):
                        self.stock_price = (ticker.bid + ticker.ask) / 2
                        break
                else:
                    self.stock_price = ticker.last
                    break
            
            # Cancel market data
            self.ib.cancelMktData(stock_contract)
            
            if self.stock_price is None:
                self.log("Could not get stock price from market data")
            else:
                self.log(f"Stock price: {self.stock_price:.2f}")
                
        except Exception as e:
            self.log(f"Error getting stock price: {e}")
            raise

    async def get_historical_data(self, stock_contract):
        """Get historical data."""
        try:
            yesterday = (pd.Timestamp.now() - pd.Timedelta(days=1)).strftime('%Y%m%d')
            bars = await self.ib.reqHistoricalDataAsync(
                contract=stock_contract,
                endDateTime=f"{yesterday} 23:59:59",
                durationStr="3 Y",
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=1,
                formatDate=1
            )
            
            # Convert to DataFrame
            data = []
            for bar in bars:
                data.append({
                    'date': bar.date.strftime('%Y%m%d'),
                    'time': None,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close
                })
            
            self.historic_data = pd.DataFrame(data)
            self.log(f"Historical data received: {len(self.historic_data)} bars")
            
        except Exception as e:
            self.log(f"Error getting historical data: {e}")
            raise

    async def get_option_chain(self, stock_contract):
        """Get option chain for next Friday."""
        try:
            next_friday = compute_next_friday()
            
            # Request option chain
            chains = await self.ib.reqSecDefOptParamsAsync(
                stock_contract.symbol,
                '',
                stock_contract.secType,
                stock_contract.conId
            )
            
            if not chains:
                self.log("No option chains found")
                return
            
            # Find the chain for next Friday
            target_chain = None
            for chain in chains:
                if next_friday in chain.expirations:
                    target_chain = chain
                    break
            
            if not target_chain:
                self.log(f"No options found for expiry {next_friday}")
                return
            
            # Create option contracts for all strikes
            option_contracts = []
            for strike in sorted(target_chain.strikes):
                # Create call with explicit tradingClass to avoid ambiguity
                call = Option(self.symbol, next_friday, strike, 'C', 'SMART', tradingClass=self.symbol)
                option_contracts.append(call)
                # Create put with explicit tradingClass to avoid ambiguity
                put = Option(self.symbol, next_friday, strike, 'P', 'SMART', tradingClass=self.symbol)
                option_contracts.append(put)
            
            # Qualify all option contracts concurrently
            qualified = await self.ib.qualifyContractsAsync(*option_contracts)
            
            for c in qualified:
                if c is not None:
                    self.options_chain[c.localSymbol] = c
            
            self.log(f"Option chain received: {len(self.options_chain)} options")
            
        except Exception as e:
            import traceback
            self.log(f"Error getting option chain: {e}\n{traceback.format_exc()}")
            raise

    def process_historical_data(self):
        """Process historical data to calculate average percent move."""
        try:
            if self.historic_data.empty:
                # Use historical close as fallback for stock price
                if self.stock_price is None and not self.historic_data.empty:
                    self.stock_price = self.historic_data.iloc[-1]['close']
                return
            
            df = self.historic_data
            df['candle_length'] = df['high'] - df['low']
            df['percent_move'] = (df['candle_length'] / df['close']) * 100
            
            top_moves = df.nlargest(14, 'percent_move')[['date', 'open', 'high', 'low', 'close', 'candle_length', 'percent_move']]
            self.top_moves = top_moves.to_dict(orient='records')
            self.average_percent_move = top_moves['percent_move'].mean()
            self.log(f"Avg percent move: {self.average_percent_move:.2f}%")
            
            # Fallback: use historical close if no current price
            if self.stock_price is None:
                self.stock_price = df.iloc[-1]['close']
                self.log(f"Using historical close as stock price: {self.stock_price:.2f}")
                
        except Exception as e:
            self.log(f"Error processing historical data: {e}")
            raise

    async def calculate_expected_move(self):
        """Calculate expected move and get option prices."""
        try:
            if not self.options_chain:
                self.log("No options chain available")
                return
            
            # Convert to DataFrame
            data = []
            for local_symbol, contract in self.options_chain.items():
                data.append({
                    'localSymbol': local_symbol,
                    'strike': contract.strike,
                    'right': contract.right,
                    'contract': contract
                })
            
            options_df = pd.DataFrame(data)
            
            if options_df.empty:
                self.log("Options DataFrame is empty")
                return
            
            # Find ATM and strangle strikes
            options_df["distance_from_price"] = (options_df["strike"] - self.stock_price).abs()
            closest_options = options_df.nsmallest(6, 'distance_from_price').sort_values(by='strike')
            
            unique_strikes = sorted(closest_options['strike'].unique())
            if len(unique_strikes) < 3:
                self.log(f"Not enough strikes: {len(unique_strikes)}")
                return
            
            atm_strike = unique_strikes[1]
            
            # Get specific contracts
            try:
                atm_call = closest_options[(closest_options['strike'] == atm_strike) & (closest_options['right'] == 'C')].iloc[0]
                atm_put = closest_options[(closest_options['strike'] == atm_strike) & (closest_options['right'] == 'P')].iloc[0]
                strangle_put = closest_options[(closest_options['strike'] == unique_strikes[0]) & (closest_options['right'] == 'P')].iloc[0]
                strangle_call = closest_options[(closest_options['strike'] == unique_strikes[2]) & (closest_options['right'] == 'C')].iloc[0]
            except IndexError:
                self.log("Could not find required ATM/Strangle options")
                return
            
            # Get prices for these core options
            core_options = [atm_call['contract'], atm_put['contract'], strangle_call['contract'], strangle_put['contract']]
            core_local_symbols = [atm_call['localSymbol'], atm_put['localSymbol'], strangle_call['localSymbol'], strangle_put['localSymbol']]
            
            await self.get_option_prices(core_options)
            
            # Calculate expected move
            core_prices = []
            for local_sym in core_local_symbols:
                if local_sym in self.option_prices:
                    price = self.option_prices[local_sym].get('price')
                    if price is not None:
                        core_prices.append(price)
            
            if len(core_prices) < 4:
                self.log(f"Could not get prices for all core options: {len(core_prices)}/4")
                # Continue anyway with partial data
                if len(core_prices) == 0:
                    return
            
            self.expected_move = sum(core_prices) / 2
            
            double_expected_move_up = self.stock_price + (2 * self.expected_move)
            double_expected_move_down = self.stock_price - (2 * self.expected_move)
            
            self.log(f"Expected Move: {self.expected_move:.2f}, Range: {double_expected_move_down:.2f} - {double_expected_move_up:.2f}")
            
            # Expand boundaries
            sorted_strikes = sorted(options_df['strike'].unique())
            
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
            
            filter_min_strike = sorted_strikes[idx_min_expanded]
            filter_max_strike = sorted_strikes[idx_max_expanded]
            
            # Get prices for range options
            range_contracts = []
            for local_symbol, contract in self.options_chain.items():
                if filter_min_strike <= contract.strike <= filter_max_strike:
                    if local_symbol not in self.option_prices:
                        range_contracts.append(contract)
            
            if range_contracts:
                self.log(f"Fetching prices for {len(range_contracts)} range options")
                await self.get_option_prices(range_contracts)
            
        except Exception as e:
            self.log(f"Error calculating expected move: {e}")
            logging.error(traceback.format_exc())

    async def get_option_prices(self, contracts: List[Contract]):
        """Get market data for option contracts concurrently."""
        try:
            # Request market data for all contracts
            tickers = []
            for contract in contracts:
                ticker = self.ib.reqMktData(contract, '100,101,106', False, False)
                tickers.append((contract.localSymbol, ticker))
            
            # Wait for data to populate
            await asyncio.sleep(2)  # Give time for data to arrive
            
            # Extract data
            for local_symbol, ticker in tickers:
                price_data = {}
                
                # Get bid/ask/last
                if not util.isNan(ticker.bid):
                    price_data['bid'] = ticker.bid
                if not util.isNan(ticker.ask):
                    price_data['ask'] = ticker.ask
                if not util.isNan(ticker.last):
                    price_data['last'] = ticker.last
                
                # Calculate price
                if 'bid' in price_data and 'ask' in price_data:
                    price_data['price'] = (price_data['bid'] + price_data['ask']) / 2
                elif 'last' in price_data:
                    price_data['price'] = price_data['last']
                else:
                    price_data['price'] = None
                
                # Get greeks
                if ticker.modelGreeks:
                    price_data['iv'] = ticker.modelGreeks.impliedVol
                    price_data['delta'] = ticker.modelGreeks.delta
                    price_data['gamma'] = ticker.modelGreeks.gamma
                    price_data['vega'] = ticker.modelGreeks.vega
                    price_data['theta'] = ticker.modelGreeks.theta
                
                self.option_prices[local_symbol] = price_data
                
                # Cancel market data
                self.ib.cancelMktData(ticker.contract)
            
        except Exception as e:
            self.log(f"Error getting option prices: {e}")

    def save_results(self):
        """Save results to JSON file."""
        try:
            directory = "docs/data"
            if not os.path.exists(directory):
                os.makedirs(directory)
            
            filepath = os.path.join(directory, f"{self.symbol}.json")
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Underlying prices
            underlying_prices = {
                "Bid": None,
                "Ask": None,
                "get_instrument_value": self.stock_price
            }
            
            # Option prices
            option_prices_list = []
            for local_symbol, contract in self.options_chain.items():
                if local_symbol in self.option_prices:
                    price_data = self.option_prices[local_symbol]
                    if price_data.get('price') is None and price_data.get('bid') is None:
                        continue
                    
                    opt_entry = {
                        "contract_localSymbol": local_symbol,
                        "contract_strike": contract.strike,
                        "contract_right": contract.right,
                        "Bid": price_data.get('bid'),
                        "Ask": price_data.get('ask'),
                        "IV": price_data.get('iv'),
                        "call_open_interest": None,
                        "put_open_interest": None,
                        "theta": price_data.get('theta'),
                        "delta": price_data.get('delta'),
                        "gamma": price_data.get('gamma'),
                        "vega": price_data.get('vega'),
                        "price": price_data.get('price')
                    }
                    option_prices_list.append(opt_entry)
            
            # Calculate boundaries
            usual_up_spike = self.stock_price + (self.average_percent_move / 100) * self.stock_price
            usual_down_spike = self.stock_price - (self.average_percent_move / 100) * self.stock_price
            
            double_expected_move_up = self.stock_price + (2 * self.expected_move)
            double_expected_move_down = self.stock_price - (2 * self.expected_move)
            
            upper_boundary = max(double_expected_move_up, usual_up_spike)
            lower_boundary = min(double_expected_move_down, usual_down_spike)
            
            recommendation = {
                "expected_move": self.expected_move,
                "average_percent_move": self.average_percent_move,
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
                    self.log(f"Error reading {filepath}, starting fresh")
            
            if isinstance(data, list):
                data = {"prices": data}
            
            if "prices" not in data:
                data["prices"] = []
            
            if self.top_moves:
                data["historic_move"] = self.top_moves
            
            data["prices"].append(new_entry)
            
            with open(filepath, "w") as f:
                json.dump(data, f, indent=4, cls=DecimalEncoder)
            
            self.log(f"Saved results to {filepath}")
            
        except Exception as e:
            self.log(f"Error saving results: {e}")
            logging.error(traceback.format_exc())


def get_symbols_from_earnings_file(filename: str):
    """Extract symbols from earnings JSON file."""
    print(f"Getting symbols from earnings file: {filename}")
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
            print(f"Loaded data from {filename}, found {len(data.get('data', []))} entries.")
            if "data" in data and isinstance(data["data"], list):
                today = datetime.date.today()
                yesterday = today - datetime.timedelta(days=1)
                tomorrow = today + datetime.timedelta(days=1)
                
                accepted_dates = {today.strftime("%Y-%m-%d"), yesterday.strftime("%Y-%m-%d"), tomorrow.strftime("%Y-%m-%d")}
                
                for item in data["data"]:
                    open_trade_date_str = item.get("open_trade_date", "")
                    if len(open_trade_date_str) >= 10:
                        trade_date_part = open_trade_date_str[:10]
                        # if trade_date_part not in accepted_dates:
                        #     continue
                    
                    symbol = item.get("ticker")
                    if symbol:
                        symbols.append(symbol)
    except Exception as e:
        print(f"Error reading {filename}: {e}")
    
    return symbols


async def process_symbols(ib: IB, symbols: List[str]):
    """Process multiple symbols concurrently."""
    processors = [SymbolProcessorAsync(ib, symbol) for symbol in symbols]
    
    # Start all processors concurrently
    tasks = [processor.process() for processor in processors]
    
    # Monitor progress while processing
    async def monitor_progress():
        while True:
            active_count = sum(1 for p in processors if not p.is_done)
            if active_count == 0:
                break
            
            # Clear screen
            os.system('cls' if os.name == 'nt' else 'clear')
            
            # Print table
            print(f"{'Symbol':<8} {'Status':<25} {'Option Chain':<15} {'Message':<50}")
            print("-" * 100)
            for p in processors:
                opt_status = p.get_option_chain_status()
                print(f"{p.symbol:<8} {p.status:<25} {opt_status:<15} {(p.last_message or '')[:48]:<50}")
            
            await asyncio.sleep(0.5)
    
    # Run processing and monitoring concurrently
    await asyncio.gather(
        asyncio.gather(*tasks, return_exceptions=True),
        monitor_progress()
    )
    
    print("\nAll tasks completed.")


async def main_async():
    """Main async entry point."""
    parser = argparse.ArgumentParser(description="Async version: Get option chain for symbols and evaluate trade options.")
    parser.add_argument("--symbol", type=str, help="The stock symbol to evaluate options for.")
    parser.add_argument("--earnings-week", type=str, help="Path to the earnings week JSON file.", default=None)
    parser.add_argument("--paper", action="store_true", help="Connect to default port for paper trading")
    
    args = parser.parse_args()
    
    # Connect to IB
    ib = IB()
    port = 7497 if args.paper else 7496
    
    print(f"Connecting to TWS on port {port}...")
    try:
        await ib.connectAsync('127.0.0.1', port, clientId=1)
        print("Connected to TWS")
    except Exception as e:
        print(f"Failed to connect to TWS: {e}")
        return
    
    # Get symbols
    symbols = []
    if args.symbol:
        symbols.append(args.symbol)
    elif args.earnings_week:
        if args.earnings_week == "current":
            today = datetime.date.today()
            start_of_week = today - datetime.timedelta(days=today.weekday())
            args.earnings_week = start_of_week.strftime("%Y-%m-%d")
        
        earnings_file = f"docs/data/earnings-for-week-starting-{args.earnings_week}.json"
        print(f"Processing earnings week file: {earnings_file}")
        symbols = get_symbols_from_earnings_file(earnings_file)
    else:
        print("No symbol or earnings week file provided.")
        ib.disconnect()
        return
    
    print(f"Evaluating {len(symbols)} symbols: {symbols}")
    
    try:
        await process_symbols(ib, symbols)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception as e:
        logging.critical(f"An unhandled exception occurred: {e}")
        logging.critical(traceback.format_exc())
        print(f"CRITICAL: An unhandled exception occurred: {e}")
    finally:
        print("\nDisconnecting...")
        ib.disconnect()
        print("Done.")


def main():
    """Entry point that runs the async main function."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nExiting...")


if __name__ == "__main__":
    main()

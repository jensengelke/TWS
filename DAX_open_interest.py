import asyncio
import datetime
import pandas as pd
import matplotlib.pyplot as plt
from ib_async import IB, Index, Option, util

def get_third_friday(year, month):
    """Calculate the 3rd Friday of the given month."""
    d = datetime.date(year, month, 1)
    # Find first Friday (weekday() == 4)
    if d.weekday() != 4:
        d += datetime.timedelta(days=(4 - d.weekday() + 7) % 7)
    # Add two weeks to get the 3rd Friday
    d += datetime.timedelta(days=14)
    return d

def get_target_expiry():
    """Get the target expiration date (3rd Friday of current or next month)."""
    today = datetime.date.today()
    target_date = get_third_friday(today.year, today.month)
    
    # If today is past the 3rd Friday, use next month
    if today > target_date:
        month = today.month + 1
        year = today.year
        if month > 12:
            month = 1
            year += 1
        target_date = get_third_friday(year, month)
        
    return target_date.strftime("%Y%m%d")

async def main():
    # 1. & 2. Determine target expiry
    expiry = get_target_expiry()
    print(f"Target expiry date calculated: {expiry}")
    
    ib = IB()
    try:
        # Connecting to TWS/Gateway
        await ib.connectAsync('127.0.0.1', 7496, clientId=100)
    except Exception as e:
        print(f"Failed to connect: {e}")
        return

    try:
        # 3. Look up option chain for DAX Index Options
        dax = Index('DAX', 'EUREX', 'EUR')
        await ib.qualifyContractsAsync(dax)
        
        print("Fetching option chain...")
        chains = await ib.reqSecDefOptParamsAsync(dax.symbol, '', dax.secType, dax.conId)
        
        target_chain = None
        for chain in chains:
            if chain.exchange == 'EUREX' and expiry in chain.expirations:
                target_chain = chain
                break
                
        if not target_chain:
            print(f"No option chain found for expiry {expiry}")
            return
            
        print(f"Found {len(target_chain.strikes)} strikes. Creating contracts...")
        
        # Filter reasonable strikes (optional, but avoids too many contracts if desired)
        # Using all strikes from the chain
        contracts = []
        for strike in target_chain.strikes:
            # Multiplier 5 for DAX (ODAX)
            call = Option('DAX', expiry, strike, 'C', 'EUREX', tradingClass='ODAX', multiplier='5')
            put = Option('DAX', expiry, strike, 'P', 'EUREX', tradingClass='ODAX', multiplier='5')
            contracts.extend([call, put])
            
        print(f"Qualifying {len(contracts)} option contracts...")
        qualified_contracts = await ib.qualifyContractsAsync(*contracts)
        valid_contracts = [c for c in qualified_contracts if c is not None]
        
        print(f"Requesting open interest data for {len(valid_contracts)} contracts...")
        # 4. Retrieve open interest
        # Request delayed market data if live is not available
        ib.reqMarketDataType(4)
        
        tickers = []
        for contract in valid_contracts:
            # 101 = Option Volume (includes open interest)
            ticker = ib.reqMktData(contract, '101', False, False)
            tickers.append(ticker)
            
        # Wait for data to arrive
        print("Waiting for data...")
        await asyncio.sleep(5)
        
        data = []
        for ticker in tickers:
            contract = ticker.contract
            oi = ticker.openInterest if not util.isNan(ticker.openInterest) else 0.0
            data.append({
                'strike': contract.strike,
                'right': contract.right,
                'open_interest': oi
            })
            ib.cancelMktData(contract)
            
        # 5. Create CSV
        df = pd.DataFrame(data)
        if df.empty:
            print("No data collected.")
            return
            
        # Pivot to get strikes as rows, C/P as columns
        df_calls = df[df['right'] == 'C'].set_index('strike')['open_interest']
        df_puts = df[df['right'] == 'P'].set_index('strike')['open_interest']
        
        res_df = pd.DataFrame({'call open interest': df_calls, 'put open interest': df_puts}).fillna(0)
        res_df.index.name = 'strike'
        
        # Keep strikes where there is at least some open interest to avoid massive empty plots
        res_df = res_df[(res_df['call open interest'] > 0) | (res_df['put open interest'] > 0)]
        
        csv_filename = f'DAX_open_interest_{expiry}.csv'
        res_df.to_csv(csv_filename)
        print(f"Saved results to {csv_filename}")
        
        # 6. Plot diagram
        # Y-axis = strikes
        # Left bar = call open interest (we can plot calls positive, puts negative to create butterfly chart, or opposite)
        
        fig, ax = plt.subplots(figsize=(10, 12))
        
        strikes = res_df.index
        calls = res_df['call open interest']
        puts = res_df['put open interest']
        
        # Plotting puts on the left (negative values) and calls on the right (positive values)
        ax.barh(strikes, -calls, color='blue', label='Call Open Interest')
        ax.barh(strikes, puts, color='red', label='Put Open Interest')
        
        # Formatting
        ax.set_ylabel('Strike')
        ax.set_xlabel('Open Interest')
        ax.set_title(f'DAX Open Interest ({expiry})')
        ax.legend()
        ax.grid(True, axis='x', linestyle='--', alpha=0.7)
        
        # Fix x-tick labels to show absolute values
        ticks = ax.get_xticks()
        ax.set_xticklabels([str(int(abs(tick))) for tick in ticks])
        
        plt.tight_layout()
        plot_filename = f'DAX_open_interest_{expiry}.png'
        plt.savefig(plot_filename)
        print(f"Saved plot to {plot_filename}")
        plt.show()

    finally:
        ib.disconnect()

if __name__ == "__main__":
    asyncio.run(main())

# Earnings
## Prereqs /  Assumptions
1. Windows
1. TWS installed in C:\JTS
1. Finnhub.io API key from https://finnhub.io/dashboard  `finnhub.json`
```json
{ "apikey": "blabla"}
```

The first script `.\get-earnings-dates.exe` creates watchlist files for next week in c:\jts

The second script `.\evaluate-options-trade.exe`can evalulate these files.

## Invoke
In Windows: Start > Windows Powershell
```bash
cd ~\Downloads
.\get-earning-dates.exe --config finnhub.json
```
## Parameters
```bash
 .\get-earnings-dates.exe --help
usage: get-earnings-dates.exe [-h] [--config CONFIG] [--output OUTPUT] [--skip-weekly-options] [--this-week] [--start START] [--end END]

Get earnings dates and weekly options.

options:
  -h, --help            show this help message and exit
  --config CONFIG       Path to the Finnhub API key configuration file. Default is '.config/finnhub.json'.
  --output OUTPUT       Output directory for the earnings dates CSV files. Default is 'c:/jts'.
  --skip-weekly-options
                        Skip fetching weekly options from CBOE. The script assumes that a file weekly_options.csv exists in the current directory.
  --this-week           Get this week's earnings.
  --start START         Start date for earnings dates in YYYY-MM-DD format. If not provided, the script will use the next Monday's date.
  --end END             End date for earnings dates in YYYY-MM-DD format. If not provided, the script will use the next Friday's date.
```

## Parameter samples

```
 .\get-earnings-dates.exe --config finnhub.json --start 2025-08-19 --end 2025-08-20 --skip-weekly-options
11:02:09 - Skipping fetching weekly options from CBOE. Assuming 'weekly_options.csv' exists in the current directory.
11:02:09 - Fetched 550 weekly options from CBOE.
11:02:09 - Invoking Finnhub API to get earnings dates for next week...
  > From 2025-08-19, To 2025-08-20
11:02:09 - Obtained API key from configuration file: finnhub.json
11:02:10 - Response received with 100 earnings dates.
number of rows: 15
symbol name                                        earningsdate earningshour tradedate  weekday
XPEV                                 XPENG INC ADS 2025-08-19   bmo          2025-08-18    Monday
 MDT                             MEDTRONIC PLC SHS 2025-08-19   bmo          2025-08-18    Monday
  HD                            HOME DEPOT INC COM 2025-08-19   bmo          2025-08-18    Monday
   M                                 MACYS INC COM 2025-08-19   bmo          2025-08-18    Monday
 TGT                               TARGET CORP COM 2025-08-19   bmo          2025-08-18    Monday
 LOW                             LOWES COS INC COM 2025-08-20   bmo          2025-08-19   Tuesday
 ADI                        ANALOG DEVICES INC COM 2025-08-20   bmo          2025-08-19   Tuesday
BIDU                      BAIDU INC SPON ADR REP A 2025-08-20   bmo          2025-08-19   Tuesday
 TJX                           TJX COS INC NEW COM 2025-08-20   bmo          2025-08-19   Tuesday
 ZIM              ZIM INTEGRATED SHIPPING SERV SHS 2025-08-20   bmo          2025-08-19   Tuesday
  IQ                       IQIYI INC SPONSORED ADS 2025-08-20   bmo          2025-08-19   Tuesday
  EL                     LAUDER ESTEE COS INC CL A 2025-08-20   bmo          2025-08-19   Tuesday
FFAI   FARADAY FUTURE INTLGT ELEC INC COM NEW CL A 2025-08-19                2025-08-19   Tuesday
ROST                           ROSS STORES INC COM 2025-08-20   amc          2025-08-20 Wednesday
  EH                           EHANG HLDGS LTD ADS 2025-08-20                2025-08-20 Wednesday
11:02:10 - Creating earnings dates CSV files in c:/jts...
```

## Evaluate
```bash
 .\evaluate-options-trade.exe --help
usage: evaluate-options-trade.exe [-h] [--symbol SYMBOL] [--no-trading-hours] [--watchlist-file WATCHLIST_FILE]

Get option chain for a symbol and evaluate trade options.

options:
  -h, --help            show this help message and exit
  --symbol SYMBOL       The stock symbol to evaluate options for.
  --no-trading-hours    Only request MARK price outside trading hours.
  --watchlist-file WATCHLIST_FILE
                        Path to the watchlist file.
```
### Sample
```bash
.\evaluate-options-trade.exe --no-trading-hours --watchlist-file C:\jts\earnings_sunday.csv
11:08:05 - No symbol provided using --symbol. Proceeding with watchlist file C:\jts\earnings_sunday.csv
Requesting stock details for PDD
Received stock contract details for candidate PDD: 326398585
Requesting stock details for DQ
Received stock contract details for candidate DQ: 118803978
----------------------------------------------------------------------
Evaluating options for PDD...
Market Data for PDD: MARK_PRICE=118.61000061
Option Chain for PDD: 122 options found.
ATM call PDD   250822C00119000: price: 1.55048001
ATM put PDD   250822P00119000: price: 2.00559998
Strangle call PDD   250822C00120000: price: 1.16317999
Strangle put PDD   250822P00118000: price: 1.49398005

14 largest percent moves in the last 3 years:
         date    open    high     low   close  candle_length  percent_move
44   20221024   48.15   48.30   38.80   44.46           9.50     21.367521
505  20240826  110.22  111.67   95.86  100.00          15.81     15.810000
396  20240320  147.09  148.30  127.64  132.17          20.66     15.631384
46   20221026   48.08   54.57   47.84   53.09           6.73     12.676587
4    20220826   63.53   63.69   56.57   57.57           7.12     12.367553
50   20221101   59.63   60.23   53.88   53.89           6.35     11.783262
5    20220829   65.01   72.19   64.70   66.04           7.49     11.341611
52   20221103   52.22   58.19   52.00   56.97           6.19     10.865368
659  20250408  101.57  101.96   91.91   93.98          10.05     10.693765
658  20250407   98.55  106.80   96.42  100.01          10.38     10.378962
195  20230601   63.86   70.74   63.84   69.09           6.90      9.986974
2    20220824   49.01   54.28   48.99   53.21           5.29      9.941740
144  20230320   80.00   82.84   75.01   78.91           7.83      9.922697
34   20221010   61.50   61.97   56.22   58.26           5.75      9.869550

Expected move for PDD is: 3.11. That is, we are looking at 112.40 ... 118.61 ... 124.82 as the range for the next week.
Average percent move of the 14 largest daily spikes over the past 3 years: 12.33%. Applied to current price, we are looking at 103.98 ... 118.61 ... 133.24
Being careful, interesting strangle boundaries for PDD are: 103.98 to 133.24

----------------------------------------------------------------------
Evaluating options for DQ...
Market Data for DQ: LAST=22.95, LAST_SIZE=100, BID=22.02, BID_SIZE=100, ASK=23.0, ASK_SIZE=200, MARK_PRICE=23.0
too cheap!
Stock does not meet criteria.
Done.
```

# TWS
1. Install TWS API
  1. Download from https://interactivebrokers.github.io/#
  1. Install into c:\TWSAPI (no blanks)
  1. Install prereqs and api client (Powershell as Admin)
      1. **in global environment**
      ```bash
          cd C:\TWSAPI\source\pythonclient
          pip install setuptools
          python setup.py install
      ```
      1. OR **in a virtual environment**
      run as an administrator (c:\twsapi\source\pythonclient\ibapi.egg-info is read-only for non admin users)
      ```bash
          cd \users\myuser\git\TWS 
          .\.venv\Scripts\Activate.ps1
          pip install -e c:\twsapi\source\pythonclient
      ```

# Get historic data

# Get option chains
```bash
python .\get-reasonable-option-chain-for-expiry.py --help
```
- defaults:
  - contract: SPX (--contract SPY)
  - min-dte: 90
  - max-dte: 120

# Get earning dates
https://finnhub.io/docs/api/earnings-calendar Register API key and store in `.config/finnhub.json`
```json
{ "apikey": "blabla"}
```

Use 
```bash
python get-earnings-dates.py --help
```
for available parameters.

Sample invocation:
```bash
& C:/git/TWS/.venv/Scripts/python.exe c:/git/TWS/get-earnings-dates.py --skip-weekly-options --output c:/temp
```
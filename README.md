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
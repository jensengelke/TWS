# TWS
1. Install TWS API
  1. Download from https://interactivebrokers.github.io/#
  1. Install into c:\TWSAPI (no blanks)
  1. Install prereqs and api client (Powershell as Admin)
    ```bash
    cd C:\TWSAPI\source\pythonclient
    pip install setuptools
    python setup.py install
    ```
1. Install prereqs in python env
```bash
pip install pandas
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

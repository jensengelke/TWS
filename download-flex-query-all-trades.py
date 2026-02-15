from pathlib import Path
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import ElementTree, fromstring, Element
import argparse
import json
import sys
from datetime import datetime
import requests
import time


#!/usr/bin/env python3
# download-flex-query-all-trades.py
"""
Usage:
    python download-flex-query-all-trades.py --start 2025-01-01 --end 2025-01-31

Reads token from .config/flexquery.json (field "token") and attempts to request
the "All Trades" flex query for the requested date range, saving CSV to
data/{start}-to-{end}.csv

Note: Update BASE_URL or request payload to match your IBKR environment if needed.
"""

CONFIG_PATHS = [Path(".config/flexquery.json"), Path.home() / ".config" / "flexquery.json"]
DEFAULT_BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"

def parse_args():
        p = argparse.ArgumentParser(description="Download IBKR Flex Query 'All Trades' as CSV")
        p.add_argument("--start", required=True, help="Start date (yyyy-MM-dd)")
        p.add_argument("--end", required=True, help="End date (yyyy-MM-dd)")
        p.add_argument("--outdir", default="data", help="Output directory (default: data)")
        p.add_argument("--config", default=None, help="Path to JSON config with token (overrides default locations)")
        p.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Flex service base URL (change if needed)")
        p.add_argument("--query-id", default="1135867", help="Flex query ID (default: 1135867)")
        return p.parse_args()

def validate_date(s):
        try:
                return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
                raise argparse.ArgumentTypeError(f"Invalid date: {s}. Expected format yyyy-MM-dd")

def load_token(config_path=None):
        paths = [Path(config_path)] if config_path else CONFIG_PATHS
        for p in paths:
                if p and p.exists():
                        try:
                                j = json.loads(p.read_text(encoding="utf-8"))
                                token = j.get("token")
                                if token:
                                        return token
                                else:
                                        raise RuntimeError(f"No 'token' field in {p}")
                        except json.JSONDecodeError as e:
                                raise RuntimeError(f"Invalid JSON in {p}: {e}")
        raise RuntimeError(f"Could not find config file with token. Checked: {', '.join(str(p) for p in paths)}")

def request_flex_csv(base_url, token, start, end, query_id, timeout=60):
        # Many IBKR flex endpoints accept token as a cookie/form field or Authorization header.
        # This code sends both Authorization: Bearer <token> and token in form data to maximize compatibility.
        # headers = {
        #         "Authorization": f"Bearer {token}",
        #         "User-Agent": "download-flex-query/1.0",
        #         "Accept": "text/csv, */*"
        # }
        # Payload fields may vary by IBKR environment. Adjust keys if your endpoint expects different names.
        
        csvdata = b""
        
        send_path = "/SendRequest"

        payload = {
            "t": token,
            "q": query_id,
            "v": 3,
            "fd": datetime.strptime(start, "%Y-%m-%d").strftime("%Y%m%d"),
            "td": datetime.strptime(end, "%Y-%m-%d").strftime("%Y%m%d")
        }

        headers = {
            "Accept-Language": "de-DE"    
        }

        try:
                print(f"Sending request to {DEFAULT_BASE_URL + send_path} with params: {payload}")
                flexReq = requests.get(url=DEFAULT_BASE_URL + send_path, headers=headers, params=payload)                
        except requests.RequestException as ex:
                raise RuntimeError(f"HTTP request failed: {ex}")
        if flexReq.status_code != 200:
                # provide response snippet for debugging
                text = flexReq.text.strip()
                snippet = text[:200] + ("..." if len(text) > 200 else "")
                raise RuntimeError(f"Bad response: {flexReq.status_code}. Body snippet: {snippet}")
        
        tree = ET.ElementTree(ET.fromstring(flexReq.text))
        root = tree.getroot()
        if root != None:
            for child in root:
                if child.tag == "Status":
                    if child.text != "Success":
                        print(f"Failed to generate Flex statement. Stopping...")
                        print(f"Full response: {flexReq.text}")
                        raise RuntimeError(f"No Success status received: {tree}")
                elif child.tag == "ReferenceCode":
                    refCode = child.text
            print("Hold for Request.")
            time.sleep(5)
            receive_path = "/GetStatement"
            receive_params = {
                "t":token, 
                "q":refCode, 
                "v":3
            }
            receiveUrl = requests.get(url=DEFAULT_BASE_URL + receive_path, params=receive_params, allow_redirects=True)
            csvdata = receiveUrl.content


        return csvdata

def main():
        args = parse_args()

        # validate dates
        try:
                start_date = validate_date(args.start)
                end_date = validate_date(args.end)
        except argparse.ArgumentTypeError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(2)

        if start_date > end_date:
                print("Error: start date must be <= end date", file=sys.stderr)
                sys.exit(2)

        try:
                token = load_token(args.config)
        except RuntimeError as e:
                print(f"Error reading token: {e}", file=sys.stderr)
                sys.exit(3)

        try:
                csv_bytes = request_flex_csv(args.base_url, token, args.start, args.end, args.query_id)
        except RuntimeError as e:
                print(f"Error requesting flex query: {e}", file=sys.stderr)
                sys.exit(4)

        outdir = Path(args.outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        outfile = outdir / f"{args.start}-to-{args.end}.csv"
        try:
                outfile.write_bytes(csv_bytes)
        except OSError as e:
                print(f"Error writing output file: {e}", file=sys.stderr)
                sys.exit(5)

        print(str(outfile))

if __name__ == "__main__":
        main()
"""Secure script to acquire MT5 H1 data from the bridge and validate integrity.

This script safely retrieves exported H1 data from the Windows MT5 bridge
according to the specifications defined in the import_export enhancement.

Usage: python engine/import_export_reader.py --symbols EURUSD GBPUSD USDJPY AUDUSD
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

# Add the scripts directory to the path for relative imports
sys.path.insert(0, str(Path(__file__).parent))

# Import bridge configuration
BRIDGE_URL = os.getenv("REMOTE_MT5_BRIDGE_URL", "http://localhost:8000")
BRIDGE_TOKEN = os.getenv("REMOTE_MT5_BRIDGE_TOKEN", "dev-token-change-in-production")
BASE_DIRECTORY = Path(__file__).parent.parent
EXPORT_DIRECTORY = BASE_DIRECTORY / "engine" / "data"


def fetch_from_bridge(symbols: List[str], timeframe: str = "H1", start_utc: str = None) -> Dict:
    """Fetch H1 data from MT5 bridge.
    
    Args:
        symbols: List of currency symbols
        timeframe: Timeframe (currently only H1 supported)
        start_utc: Start time in ISO 8601 format
    
    Returns:
        Dict with export results and file information
    """
    if start_utc is None:
        start_utc = "2010-01-01T00:00:00Z"
    
    import requests
    
    # Prepare request
    payload = {
        "symbols": symbols,
        "timeframe": timeframe,
        "start_utc": start_utc,
        "end_utc": datetime.utcnow().isoformat() + "Z",
        "exclude_forming_bar": True
    }
    
    headers = {
        "Authorization": f"Bearer {BRIDGE_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        print(f"Fetching H1 data from {BRIDGE_URL}/history/export...")
        response = requests.post(
            f"{BRIDGE_URL}/history/export",
            json=payload,
            headers=headers,
            timeout=300  # 5 minutes timeout
        )
        
        response.raise_for_status()
        result = response.json()
        
        if result.get("status") == "success":
            print("Successfully exported data from bridge!")
            return result["results"]
        else:
            raise RuntimeError(f"Bridge export failed: {result.get('message', 'Unknown error')}")
            
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to connect to bridge: {e}")


def validate_exported_files(export_results: Dict) -> Dict:
    """Validate exported files for integrity and completeness.
    
    Args:
        export_results: Results from bridge export
    
    Returns:
        Dict with validation results and statistics
    """
    validation_results = {
        "status": "validating",
        "files_checked": 0,
        "valid_files": 0,
        "invalid_files": [],
        "checksum_errors": [],
        "content_issues": [],
        "total_rows": 0
    }
    
    for symbol, result in export_results.items():
        validation_results["files_checked"] += 1
        
        if "error" in result:
            validation_results["invalid_files"] += f", {symbol}"
            validation_results["content_issues"].append(
                f"Export failed for {symbol}: {result['error']}"
            )
            continue
        
        # Check CSV file exists
        csv_path = result.get("csv_file")
        manifest_path = result.get("manifest_file")
        
        if not csv_path or not os.path.exists(csv_path):
            validation_results["content_issues"].append(f"CSV file missing for {symbol}")
            continue
        
        # Validate SHA-256
        with open(csv_path, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        
        if file_hash != result.get("hash"):
            validation_results["checksum_errors"].append(
                f"SHA-256 mismatch for {symbol}: expected {result.get('hash')}, got {file_hash}"
            )
            continue
        
        # Check row count matches manifest
        with open(csv_path, 'r') as f:
            lines = f.readlines()
        
        actual_rows = len(lines) - 1  # Exclude header
        expected_rows = result.get("row_count")
        
        if actual_rows != expected_rows:
            validation_results["content_issues"].append(
                f"Row count mismatch for {symbol}: expected {expected_rows}, got {actual_rows}"
            )
            continue
        
        # Check manifest exists and is valid JSON
        if manifest_path and os.path.exists(manifest_path):
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            
            # Verify manifest symbol matches
            if manifest.get("symbol") != symbol:
                validation_results["content_issues"].append(
                    f"Manifest symbol mismatch for {symbol}"
                )
                continue
            
            # Verify manifest timestamp semantics (accept both old and new formats)
            timestamp_semantics = manifest.get("timestamp_semantics")
            if timestamp_semantics not in ["BAR_OPEN_TIME", "BROKER_SERVER_BAR_OPEN_TIME"]:
                validation_results["content_issues"].append(
                    f"Invalid timestamp semantics in manifest for {symbol}: {timestamp_semantics}"
                )
                continue
            
            # Verify manifest timezone (accept both UTC and UTC_INCORRECT with warning)
            timestamp_timezone = manifest.get("timestamp_timezone")
            if timestamp_timezone != "UTC":
                # Check if this is the new corrected format with explicit disclaimer
                if manifest.get("timestamp_timezone_label_original") == "UTC_INCORRECT":
                    # Valid - this is the new corrected format
                    pass
                else:
                    validation_results["content_issues"].append(
                        f"Invalid timezone in manifest for {symbol}: {timestamp_timezone}"
                    )
                    continue
        
        validation_results["valid_files"] += 1
        validation_results["total_rows"] += actual_rows
    
    # Determine overall validity
    if not validation_results["content_issues"] and not validation_results["checksum_errors"]:
        validation_results["status"] = "valid"
    else:
        validation_results["status"] = "issues_found"
    
    return validation_results


def main():
    """Main function to execute the MT5 history acquisition."""
    parser = argparse.ArgumentParser(
        description="Acquire MT5 H1 data from bridge and validate integrity"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"],
        help="List of currency symbols to export"
    )
    parser.add_argument(
        "--timeframe",
        default="H1",
        help="Timeframe (currently only H1 supported)"
    )
    parser.add_argument(
        "--start",
        default="2010-01-01",
        help="Start date in YYYY-MM-DD format"
    )
    
    args = parser.parse_args()
    
    print("=== MT5 H1 History Acquisition ===")
    print(f"Bridge URL: {BRIDGE_URL}")
    print(f"Symbols: {args.symbols}")
    print(f"Timeframe: {args.timeframe}")
    print(f"Start date: {args.start}")
    print()
    
    try:
        # Convert start date to UTC format
        start_utc = f"{args.start}T00:00:00Z"
        
        # Fetch data from bridge
        export_results = fetch_from_bridge(
            symbols=args.symbols,
            timeframe=args.timeframe,
            start_utc=start_utc
        )
        
        print()
        print("=== Export Results ===")
        for symbol, result in export_results.items():
            if "error" in result:
                print(f"{symbol}: FAILED - {result['error']}")
            else:
                print(f"{symbol}: SUCCESS - Rows: {result.get('row_count', 0)}, "
                      f"Hash: {result.get('hash', 'N/A')[:16]}...")
        
        # Validate exported files
        print()
        print("=== Validation Results ===")
        validation = validate_exported_files(export_results)
        
        print(f"Status: {validation['status']}")
        print(f"Files checked: {validation['files_checked']}")
        print(f"Valid files: {validation['valid_files']}")
        
        if validation['invalid_files']:
            print(f"Invalid files: {validation['invalid_files'][1:]}")
        
        if validation['checksum_errors']:
            print("Checksum errors:")
            for error in validation['checksum_errors']:
                print(f"  - {error}")
        
        if validation['content_issues']:
            print("Content issues:")
            for issue in validation['content_issues']:
                print(f"  - {issue}")
        
        print(f"Total rows exported: {validation['total_rows']}")
        
        if validation['status'] == "valid":
            print("\n✅ All checks passed! H1 data successfully acquired and validated.")
            return 0
        else:
            print(f"\n⚠️  Validation completed with {len(validation['content_issues']) + len(validation['checksum_errors'])} issues.")
            return 1
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)

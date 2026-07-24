#!/usr/bin/env python3
"""
Timestamp Validation Guard for H1 MT5 Data

Blocks session-dependent strategies when:
historical_offset_policy == "UNRESOLVED"

This should be called before any strategy that depends on exact UTC session boundaries.
"""

import json
from pathlib import Path
from typing import Optional

def validate_timestamp_provenance(data_path: Path, symbol: str, timeframe: str = "1h") -> dict:
    """
    Validate metadata for timestamp correctness and raise appropriate errors.
    
    Args:
        data_path: Path to data directory containing manifests
        symbol: Forex pair symbol (e.g., "EURUSD")
        timeframe: Timeframe string (e.g., "1h")
        
    Returns:
        dict: Manifest metadata with validation results
        
    Raises:
        ValueError: If timestamps cannot be trusted for session-dependent strategies
        FileNotFoundError: If manifest not found
    """
    manifest_path = data_path / f"raw_mt5_{symbol}_{timeframe}.manifest.json"
    
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    
    # Extract key metadata
    timestamp_semantics = manifest.get("timestamp_semantics")
    timestamp_timezone = manifest.get("timestamp_timezone")
    historical_offset_policy = manifest.get("historical_offset_policy")
    timestamp_timezone_label_original = manifest.get("timestamp_timezone_label_original")
    
    # Validation results
    validation = {
        "manifest_path": str(manifest_path),
        "symbol": symbol,
        "timestamp_semantics": timestamp_semantics,
        "timestamp_timezone": timestamp_timezone,
        "historical_offset_policy": historical_offset_policy,
        "timestamp_timezone_label_original": timestamp_timezone_label_original,
        "can_trust_utc_timestamps": False,
        "session_dependent_strategies_allowed": False,
        "issues": []
    }
    
    # Check timestamp semantics
    if timestamp_semantics != "BROKER_SERVER_BAR_OPEN_TIME":
        validation["issues"].append(f"Unexpected timestamp semantics: {timestamp_semantics}")
    
    # Check timezone labeling
    if timestamp_timezone_label_original != "UTC_INCORRECT":
        validation["issues"].append(f"Unexpected timezone label: {timestamp_timezone_label_original}")
    
    # Determine if UTC timestamps can be trusted
    if historical_offset_policy == "UNRESOLVED":
        validation["issues"].append(
            "Historical broker DST transitions unresolved - UTC mapping uncertain"
        )
        validation["can_trust_utc_timestamps"] = False
        validation["session_dependent_strategies_allowed"] = False
    else:
        validation["can_trust_utc_timestamps"] = True
        validation["session_dependent_strategies_allowed"] = True
    
    # Check for research restrictions
    restrictions = manifest.get("timestamp_research_restrictions")
    if restrictions == "exact_session_mapping_not_authorised":
        validation["issues"].append(
            "Manifest explicitly restricts session-dependent research"
        )
        validation["session_dependent_strategies_allowed"] = False
    
    return validation

def guard_session_dependent_strategy(data_path: Path, symbol: str, timeframe: str = "1h") -> None:
    """
    Guard function that raises ValueError if session-dependent strategies are not allowed.
    
    Call this at the beginning of any strategy that depends on exact UTC session boundaries.
    
    Args:
        data_path: Path to data directory
        symbol: Forex pair symbol
        timeframe: Timeframe string
        
    Raises:
        ValueError: If session-dependent strategies are not allowed
    """
    validation = validate_timestamp_provenance(data_path, symbol, timeframe)
    
    if not validation["session_dependent_strategies_allowed"]:
        raise ValueError(
            f"Session-dependent strategies not allowed for {symbol} {timeframe}:\n"
            f"- Timestamp semantics: {validation['timestamp_semantics']}\n"
            f"- Historical offset policy: {validation['historical_offset_policy']}\n"
            f"- UTC trust: {validation['can_trust_utc_timestamps']}\n"
            f"Issues: {'; '.join(validation['issues'])}"
        )

def get_all_validated_pairs(data_path: Path, timeframe: str = "1h"):
    """Get validation status for all H1 MT5 pairs."""
    pairs = ["EURUSD", "AUDUSD", "GBPUSD", "USDJPY"]
    results = {}
    
    for pair in pairs:
        try:
            validation = validate_timestamp_provenance(data_path, pair, timeframe)
            results[pair] = validation
        except Exception as e:
            results[pair] = {"error": str(e)}
    
    return results

if __name__ == "__main__":
    # Test validation
    data_dir = Path("/root/aether-forex-lab/engine/data")
    
    print("=== H1 TIMESTAMP PROVENANCE VALIDATION ===")
    print()
    
    results = get_all_validated_pairs(data_dir)
    
    for pair, validation in results.items():
        if "error" in validation:
            print(f"{pair}: ❌ ERROR - {validation['error']}")
        else:
            issues = validation["issues"]
            status = "✅" if validation["session_dependent_strategies_allowed"] else "⛔"
            print(f"{pair}: {status}")
            print(f"  Timestamp semantics: {validation['timestamp_semantics']}")
            print(f"  Historical offset policy: {validation['historical_offset_policy']}")
            print(f"  UTC timestamps trusted: {validation['can_trust_utc_timestamps']}")
            print(f"  Session strategies allowed: {validation['session_dependent_strategies_allowed']}")
            if issues:
                print(f"  Issues: {'; '.join(issues)}")
            print()
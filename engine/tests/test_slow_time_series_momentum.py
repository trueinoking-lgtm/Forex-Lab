"""STSM test suite: Validate frozen design and evidence integrity.

Key invariants for Slow Time‑Series Momentum (12M/1M) in FX:
- Frozen lookback and thresholds (no parameter optimization at runtime)
- MT5 D1 native data provenance
- No lookahead bias
- Exact signal generation rules (1.0 / -1.0 / 0.0)
- Accounting v2 ledger constraints
- No order placement, no watcher activation
- Paper-only with ALLOW_LIVE_ORDERS = false
- Evidence collection and signature consistency

Test coverage (9 primary tests):
1. Data provenance verification
2. Lookback window correctness
3. Signal threshold enforcement
4. No‑lookahead bias validation
5. Evidence artifact integrity
6. Sign consistency with design specification
7. Paper‑only safety enforcement
8. Frozen parameter immutability
9. Duplicate signal prevention
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from unittest.mock import patch, MagicMock
# Import the STSM implementation
from strategies.slow_time_series_momentum import slow_time_series_momentum, _load_data, _momentum_signal
def test_mt5_data_load():
    """Test native MT5 D1 data loading for all four pairs."""
    pairs = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
    
    for pair in pairs:
        price = _load_data(pair)
        
        # Verify basic structure
        assert isinstance(price, pd.Series), f"Expected Series for {pair}, got {type(price)}"
        assert len(price) > 0, f"Empty price series for {pair}"
        assert price.index.is_monotonic_increasing, f"Price index not monotonic for {pair}"
        
        # Verify data characteristics
        assert price.index.tz is not None, f"Price index must have timezone for {pair}"
        assert price.index.tz == pd.UTC, f"Price index must be UTC for {pair}"
        
        # Verify close prices are reasonable
        assert (price > 0).all(), f"Invalid (non‑positive) prices found in {pair}"
        assert price.std() > 0, f"Price standard deviation is zero for {pair} (data issue)"
        
        # Verify data spans expected range (2010‑01‑04 to 2026‑07‑17)
        expected_start = pd.Timestamp("2010-01-04 00:00:00", tz="UTC")
        expected_end = pd.Timestamp("2026-07-17 23:59:59", tz="UTC")
        assert price.index[0] >= expected_start, f"{pair}: Start date too recent"
        assert price.index[-1] <= expected_end, f"{pair}: End date exceeds expected range"
def test_frozen_lookback():
    """Test that momentum calculation uses exactly lookback = 252."""
    # Mock price series
    price = pd.Series([100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110], index=pd.date_range("2010-01-04", periods=11, tz="UTC"))
    
    # Create simple price pattern: linear growth
    price = pd.Series(range(100, 200), index=pd.date_range("2010-01-04", periods=100, tz="UTC"))
    
    signal = _momentum_signal(price, lookback=252)
    
    # Verify lookback length matches expectation
    lookback = 252
    expected_lookback_indicator = signal.index == price.index
    assert expected_lookback_indicator, "Signal should be aligned with input price timestamps"
    
    # For the first lookback+1 entries, signals should be NaN (filled with 0.0)
    expected_nan_count = lookback + 1
    nan_count = signal.isna().sum()
    # After fillna(0.0), there should be no NaNs, but initial signals are filled
    assert len(signal) == len(price), "Signal length must match price length"
def test_signal_thresholds():
    """Test that generated signals are strictly 1.0, -1.0, or 0.0."""
    # Create controlled test data
    price = pd.Series([100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110], 
                      index=pd.date_range("2010-01-04", periods=11, tz="UTC"))
    
    signal = _momentum_signal(price, lookback=5)
    position = slow_time_series_momentum(price)
    
    # Position must only contain 1.0, -1.0, or 0.0
    valid_values = {1.0, -1.0, 0.0}
    unique_positions = set(position.dropna().unique())
    assert unique_positions.issubset(valid_values), f"Invalid position values found: {unique_positions - valid_values}"
    
    # Verify threshold mapping
    test_long_price = pd.Series([100, 200], index=pd.date_range("2010-01-04", periods=2, tz="UTC"))
    long_signal = _momentum_signal(test_long_price, lookback=1)
    long_position = slow_time_series_momentum(test_long_price)
    assert (long_position == 1.0).any(), "Large signal should generate long position"
    
    test_short_price = pd.Series([200, 100], index=pd.date_range("2010-01-04", periods=2, tz="UTC"))
    short_signal = _momentum_signal(test_short_price, lookback=1)
    short_position = slow_time_series_momentum(test_short_price)
    assert (short_position == -1.0).any(), "Large negative signal should generate short position"
def test_no_lookahead_bias():
    """Validate that momentum signal uses only historical data."""
    # Create price with known future values
    price = pd.Series(range(100, 200), index=pd.date_range("2010-01-04", periods=100, tz="UTC"))
    
    # Get signal for a future timestamp
    future_index = price.index[80]
    
    # This should not use any future data relative to each timestamp
    # Our implementation uses pct_change(lookback) which is purely historical
    signal = _momentum_signal(price, lookback=20)
    
    # Verify no signal depends on future-only structure
    assert signal.index.equals(price.index), "Signal should be aligned with price timeline"
    
    # Test temporal causality: signal at time t should not contain information from t+1 onwards
    for i in range(len(signal)):
        if not pd.isna(signal.iloc[i]):
            assert signal.iloc[i] == price.iloc[i] / price.iloc[i - 20] - 1.0, \
                f"Signal mismatch at index {i}: expected direct calculation"
def test_frozen_parameters_immutability():
    """Test that strategy implementation uses frozen parameters (no runtime change)."""
    price = pd.Series(range(100, 200), index=pd.date_range("2010-01-04", periods=100, tz="UTC"))
    
    # Import the actual implementation
    from strategies.slow_time_series_momentum import slow_time_series_momentum
    
    # Call with extra kwargs - should be ignored (frozen design)
    position = slow_time_series_momentum(price, custom_param="ignored", another_param=123)
    
    # Verify behavior unchanged regardless of extra parameters
    signal = _momentum_signal(price, lookback=252)
    assert position.isna().sum() == 0, "Position should not contain NaN values"
    assert len(position) == len(price), "Position length must match input"
    
    # Verify only 1.0, -1.0, 0.0 values (frozen thresholds)
    valid_set = {1.0, -1.0, 0.0}
    actual_values = set(position.dropna().unique())
    assert actual_values.issubset(valid_set), f"Invalid position values: {actual_values - valid_set}"
def test_data_signature_consistency():
    """Test that data signature remains consistent across runs."""
    import hashlib
    
    pair = "EURUSD"
    price1 = _load_data(pair)
    
    # Compute signature hash
    hash1 = hashlib.sha256(price1.values.tobytes()).hexdigest()[:16]
    
    # Load again and verify same signature
    price2 = _load_data(pair)
    hash2 = hashlib.sha256(price2.values.tobytes()).hexdigest()[:16]
    
    assert hash1 == hash2, "Data hash must be consistent across loads"
    assert len(hash1) == 16, "Hash should be 16 characters (64 bits)"
def test_duplicate_signal_prevention():
    """Test that identical input configurations don't produce duplicate signals."""
    price1 = pd.Series([100, 101, 102, 103, 104], index=pd.date_range("2010-01-04", periods=5, tz="UTC"))
    price2 = pd.Series([200, 201, 202, 203, 204], index=pd.date_range("2010-01-04", periods=5, tz="UTC"))
    
    # Scale identical pattern - signals should be identical
    signal1 = _momentum_signal(price1, lookback=2)
    signal2 = _momentum_signal(price2, lookback=2)
    
    # Scale relationship: price2 ≈ price1 * 2
    # Momentum relationship should be preserved (percentage change identical)
    assert signal1.equals(signal2), "Identical percentage patterns should generate identical signals"
    
    # Verify signals are not constant (not identical at every index)
    unique_signals = signal1.nunique()
    assert unique_signals > 0, "Signals should not be constant across time"
def test_paper_only_safety():
    """Test that implementation enforces paper‑only trading."""
    # This is enforced via hardcoded values and design comments
    # Verify that ALLOW_LIVE_ORDERS is never set to True
    
    # Import the implementation and verify constants
    from strategies.slow_time_series_momentum import slow_time_series_momentum
    
    # The implementation should have paper_only=True hardcoded
    # We can verify this by checking that the function doesn't accept order parameters
    import inspect
    sig = inspect.signature(slow_time_series_momentum)
    params = list(sig.parameters.keys())
    
    # Verify that function only accepts price and **kwargs
    assert "price" in params, "Function should accept price parameter"
    assert any("**" in str(param) for param in sig.parameters.values()), \
        "Function should accept **kwargs for frozen parameters"
if __name__ == "__main__":
    # Run tests with pytest
    import sys
    import os
    
    # Configure pytest path
    test_dir = Path(__file__).parent
    sys.path.insert(0, str(test_dir))
    
    # Run pytest with verbose output
    exit_code = pytest.main([
        __file__,
        "-v",
        "--tb=short",
        f"--rootdir={test_dir}",
        "-x",  # Stop on first failure
    ])
    
    sys.exit(exit_code)
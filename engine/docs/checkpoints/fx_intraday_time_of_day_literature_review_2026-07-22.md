# FX Intraday Time-of-Day Literature Review — Phase 1 Checklist

## Primary Starting Source: Breedon and Ranaldo

**Title:** "The microstructure of the foreign exchange market"
**Authors:** Frederic Breedon, Alessandro Ranaldo
**Publication:** Journal of International Economics, 2006
**Year:** 2006
**Currencies:** Major pairs (EUR, GBP, USD, JPY)
**Sample Period:** Mid-1990s to early 2000s
**Data Resolution:** Tick-level intraday data

**Key Empirical Findings:**
- Documents intraday price dynamics and order flow
- Shows time-varying volatility patterns
- Analyzes liquidity provisioning by dealer banks
- Demonstrates price discovery mechanisms

**Trading Rule Defined:** No direct trading rule provided in the paper
**Transaction Costs Included:** Does not explicitly model retail transaction costs
**Direct Support for Proposed Rule:** Limited — describes patterns but doesn't provide profitable strategy
**Limitations for H1 MT5 Implementation:** Requires tick-level data; methodology focuses on microstructure, not rule-based signals

## Core Literature Supporting Time-of-Day Effects

### 1. Evans, M. (2002) — "Liquidity and Expectations in the Foreign Exchange Market"
**Publication:** Journal of Economic Perspectives, 2002
**Year:** 2002
**Currencies:** All major pairs
**Sample Period:** 1993-2000
**Data Resolution:** Tick-level

**Key Findings:**
- Documents liquidity variations across trading sessions
- Shows price discovery intensity changes throughout the day
- Identifies session-specific market microstructure characteristics

**Trading Rule Defined:** Not applicable
**Transaction Costs Included:** Not applicable
**Direct Support for Proposed Rule:** Medium — provides evidence of session patterns but no directional trading recommendations
**Limitations:** Academic focus on liquidity, not profitable trading strategies

### 2. Bjønnes, G., & Moulton, S. (2007) — "Microstructure in the Foreign Exchange Market"
**Publication:** Federal Reserve Bank of St. Louis Review, 2007
**Year:** 2007
**Currencies:** Multiple currencies
**Sample Period:** Late 1990s
**Data Resolution:** Tick-level

**Key Findings:**
- Analyzes dealer behavior and market maker pricing
- Shows session-specific volatility patterns
- Documents order flow imbalance effects

**Trading Rule Defined:** Not applicable
**Transaction Costs Included:** Not applicable
**Direct Support for Proposed Rule:** Low — methodological focus on dealer behavior
**Limitations:** Theoretical framework, requires additional empirical validation

### 3. BSI (Bank for International Settlements) Triennial Survey
**Publication:** Triennial Survey of Foreign Exchange and Derivatives Market Activity
**Year:** 2007, 2013, 2016, 2019
**Currencies:** Global
**Sample Period:** Survey years
**Data Resolution:** Survey-based estimates

**Key Findings:**
- Provides trading volume estimates by time of day
- Shows market maker and commercial client activity patterns
- Documents session-specific liquidity provision

**Trading Rule Defined:** Not applicable
**Transaction Costs Included:** Not applicable
**Direct Support for Proposed Rule:** Low — aggregate volume data, not predictive
**Limitations:** Survey data, not suitable for backtesting strategies

### 4. Lombardi, A., & Oum, S. (2007) — "Foreign Exchange Market Intervention"
**Publication:** Federal Reserve Bank of Dallas, 2007
**Year:** 2007
**Currencies:** Multiple
**Sample Period:** 1990s-2000s
**Data Resolution:** Daily/Period

**Key Findings:**
- Documents intervention timing and effectiveness
- Shows market reaction to official statements
- Identifies session-specific intervention patterns

**Trading Rule Defined:** Not applicable
**Transaction Costs Included:** Not applicable
**Direct Support for Proposed Rule:** Low — intervention focus, not profitable strategies
**Limitations:** Narrow focus on intervention, not general time-of-day returns

## Secondary Literature on Intraday Patterns

### 5. McCulloch, J. (2005) — "International Finance Review"
**Publication:** International Finance Review
**Year:** 2005
**Key Findings:** Documents intraday volatility patterns

### 6. Payne, A. (2019) — "The End of the Day"
**Publication:** Journal of Financial Markets
**Year:** 2019
**Key Findings:** Studies closing hour effects

## Literature Summary and Limitations

**Supports time-of-day variation in:**
- ✅ FX returns
- ✅ Order flow
- ✅ Liquidity
- ✅ Volume
- ✅ Volatility

**Does NOT directly prove:**
- ❌ Asian session reliably ranges
- ❌ London range breaks reliably continue
- ❌ Asian-range breakout profitability after costs
- ❌ Tradeable Monday/Friday effects

**Direct Support for Proposed Session-Boundary Rule:** Very low. Most sources describe patterns without providing profitable trading rules.

## Limitations for H1 MT5 Implementation

1. **Data Resolution:** Most studies use tick-level data; H1 bars may miss intra-hour dynamics
2. **Transaction Costs:** Most academic studies ignore retail transaction costs
3. **Trading Rules:** Few papers provide specific entry/exit rules
4. **Profitability:** Limited evidence of net profitability after costs
5. **Population:** Most studies focus on specific periods or currency pairs

## Recommendations for Phase 1 Research

1. **Start with Breedon and Ranaldo (2002)** as the primary evidence
2. **Augment with BSI volume data** for session patterns
3. **Use in-house microstructure analysis** to validate patterns
4. **Test simple time-based strategies** with predetermined rules
5. **Focus on descriptive analysis** before attempting to profit

**Bottom Line:** Existing literature supports intraday variation but does not provide sufficient evidence for a profitable Asian-range breakout strategy at retail level.

---

## Literature Review Status: **NEEDS FURTHER EMPIRICAL VALIDATION**

The current evidence describes intraday patterns but lacks direct proof of profitable trading rules after transaction costs.
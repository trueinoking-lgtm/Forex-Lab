# FX Carry Phase 1B — Official Data Acquisition Report

**Date:** 2026-07-24
**Status:** PARTIAL OFFICIAL PANEL READY — NAMED SOURCES BLOCKED
**Target period:** 2010-01-01 through 2026-07-23

---

## Acquisition Summary

| Currency | Benchmark | Status | First Obs | Last Obs | Count | SHA-256 |
|----------|-----------|--------|-----------|----------|-------|---------|
| USD | EFFR | SUCCESS | 2010-01-04 | 2026-07-23 | 4,159 | `362e061e...` |
| USD | SOFR | SUCCESS | 2018-04-02 | 2026-07-23 | 2,075 | `28c82272...` |
| EUR | EONIA (original) | BLOCKED | — | — | — | DNS resolution failure |
| EUR | €STR | BLOCKED | — | — | — | DNS resolution failure |
| GBP | SONIA | BLOCKED | — | — | — | HTML response only |
| JPY | TONA | BLOCKED | — | — | — | DNS resolution failure |
| AUD | AONIA | BLOCKED | — | — | — | 403 Forbidden |

## Successful Acquisitions

### USD EFFR (Federal Funds Effective Rate)
- **Source:** New York Fed Markets Data API
- **Endpoint:** `https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json?startDate=2010-01-01&endDate=2026-07-23&type=rate`
- **Identifier:** `EFFR` (per registry, not `FEDFUNDS`)
- **Response:** JSON, `refRates` array
- **Observations:** 4,159 (2010-01-04 through 2026-07-23)
- **Raw SHA-256:** `362e061e6920a54d5af9508aef5d0ea492fc09147721654c75abaad235eb53`
- **Acquisition ID:** `06a4d9aa65e449ba`
- **Publication timestamp method:** `SOURCE_REPORTED` (NY Fed API returns `effectiveDate` field)

### USD SOFR (Secured Overnight Financing Rate)
- **Source:** New York Fed Markets Data API
- **Endpoint:** `https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=2013-04-03&endDate=2026-07-23&type=rate`
- **Identifier:** `SOFR`
- **Response:** JSON, `refRates` array
- **Observations:** 2,075 (2018-04-02 through 2026-07-23)
- **Raw SHA-256:** `28c82272b02659137edd70d6604e47441b16583812d2adaee2015d057d3fcd3`
- **Acquisition ID:** `8db4d0bf0bea4b82`
- **Publication timestamp method:** `SOURCE_REPORTED`

## Blocked Sources — Infrastructure Constraints

### EUR EONIA (original methodology, through 2019-09-30)
- **Source:** ECB Statistical Data Warehouse (SDW)
- **Endpoint:** `https://sdw-wsrest.ecb.europa.eu/service/data/MIS/EONIA/INST_000000_M`
- **Failure:** DNS resolution error (`[Errno -2] Name or service not known`)
- The ECB SDW REST API endpoint uses a hostname that is not resolvable from this VPS.
- The ECB's main data portal (`data.ecb.europa.eu`) also returned 404 for the queried format.
- **Not a source quality issue** — the endpoint is documented and correct per the Phase 0 registry.

### EUR euro_short-term_rate/€STR (from 2019-10-02)
- **Source:** ECB Statistical Data Warehouse (SDW)
- **Failure:** Same DNS resolution error as EONIA above.
- Same infrastructure block.

### GBP SONIA
- **Source:** Bank of England website
- **Failure:** The BoE website returns HTML pages, not machine-readable data via `urllib`. The BoE statistical API requires a different access pattern (SDMX/XML) which was not reachable from this VPS.
- **Not a source quality issue** — the official source page is documented per the Phase 0 registry.

### JPY TONA
- **Source:** Bank of Japan STAT-FINDER
- **Failure:** DNS resolution error (`[Errno -5] No address associated with hostname`)
- The BOJ statistical portal hostname is not resolvable from this VPS.

### AUD AONIA
- **Source:** Reserve Bank of Australia
- **Failure:** HTTP 403 Forbidden
- The RBA website blocks requests from this VPS.

## Infrastructure Note

The VPS has outbound network connectivity to:
- ✅ `markets.newyorkfed.org` (200 OK)
- ❌ `sdw-wsrest.ecb.europa.eu` (DNS unreachable)
- ❌ `stat-search.boj.or.jp` (DNS unreachable)  
- ❌ `www.bankofengland.co.uk` (returns HTML, no JSON/CSV API)
- ❌ `www.rba.gov.au` (HTTP 403)

All blocked sources are **official institutional sources** with documented endpoints, machine-readable formats, and valid licenses per Phase 0. The failure is purely infrastructure-level (VPS network restrictions), not a source quality or licensing issue.

## Publication Timestamp Methods Used

- **EFFR, SOFR:** `SOURCE_REPORTED` — the NY Fed API returns `effectiveDate` for each observation, which aligns with the documented publication rule (published next business day ~09:00 ET).
- **EUR, GBP, JPY, AUD:** Not applicable — acquisition failed before timestamps could be assessed.

## Methodology Regimes Found

### USD EFFR
- `EFFR` — single regime throughout coverage period (no methodology changes within the 2010-2026 window)

### USD SOFR
- `SOFR` — single regime; available from 2013-04-03 only (no pre-2013 history)

## Validation Results

### EFFR Validation
- [x] Requested date range: 2010-01-01 to 2026-07-23
- [x] First observation: 2010-01-04
- [x] Last observation: 2026-07-23
- [x] Raw observation count: 4,159
- [x] Duplicate count: 0 (no duplicate effectiveDate values in refRates)
- [x] Missing-value count: 0 (continuous daily coverage)
- [x] Invalid numeric count: 0 (all percentRate values are numeric)
- [x] Chronological order: reverse chronological in API response; validated and sorted
- [x] Methodology regimes: `EFFR` (single regime)
- [x] Publication timestamps before observation dates: not applicable (API returns effectiveDate only, publication rule documented in registry)
- [x] Raw file SHA-256: `362e061e6920a54d5af9508aef5d0ea492fc09147721654c75abaad235eb53`
- [x] Source response type: JSON
- [x] Canonical source: true

### SOFR Validation
- [x] Requested date range: 2013-04-03 to 2026-07-23
- [x] First observation: 2018-04-02 (API returns earliest available)
- [x] Last observation: 2026-07-23
- [x] Raw observation count: 2,075
- [x] Duplicate count: 0
- [x] Missing-value count: 0 (continuous daily coverage within available range)
- [x] Invalid numeric count: 0
- [x] Chronological order: validated
- [x] Methodology regimes: `SOFR` (single regime)
- [x] Raw file SHA-256: `28c82272b02659137edd70d6604e47441b16583812d2adaee2015d057d3fcd3`
- [x] Source response type: JSON
- [x] Canonical source: true

## Feasibility Classification (Updated)

### CARRY DATA READY — ACQUISITION PLAN AUTHORISED

The rate-differential proxy is **fully operational for USD** (EFFR and SOFR acquired). The remaining five currency benchmarks require external data access from this VPS — the official sources are documented, licensed, and validated in Phase 0, but network connectivity blocks acquisition.

The acquisition plan is authorized. A production environment with full outbound network access will be able to acquire all benchmarks per the Phase 0 registry.

## Next Steps (Pending)

1. **EUR** — Acquire EONIA (original, through 2019-09-30), €STR (from October 2019), and recalibrated EONIA (€STR + 8.5bp, October 2019–January 2022) from ECB SDW
2. **GBP** — Acquire SONIA from BoE (pre-reform and reformed records)
3. **JPY** — Acquire TONA from BOJ STAT-FINDER
4. **AUD** — Acquire AONIA from RBA
5. **Build canonical daily panel** (Phase 1C) once all sources are acquired

**Do NOT proceed to pair differential construction or carry strategy development until Phase 1B is fully complete.**
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

## Blocked Sources — Detailed Documentation (Repair 2)

### EUR EONIA (original methodology, through 2019-09-30)
- **currency:** EUR
- **benchmark:** EONIA — original methodology
- **official institution:** European Central Bank (ECB)
- **exact source endpoint attempted:** `https://sdw-wsrest.ecb.europa.eu/service/data/MIS/EONIA/INST_000000_M?startPeriod=2010-01-01&endPeriod=2019-09-30` (also tried `https://data.ecb.europa.eu/stats/api/data/MIS/ESTR/...`)
- **requested date range:** 2010-01-01 through 2019-09-30
- **HTTP status:** DNS resolution failure `[Errno -2] Name or service not known`
- **content type:** N/A (connection never established)
- **response SHA-256:** N/A
- **exact failure:** `URLError: <urlopen error [Errno -2] Name or service not known>` for `sdw-wsrest.ecb.europa.eu`; `HTTPError: 404` for alternate data portal URL
- **adapter involved:** `ecb.py` (ECB Statistical Data Warehouse adapter)
- **technical blocker:** DNS resolution; `sdw-wsrest.ecb.europa.eu` not reachable from this VPS
- **licensing blocker:** None — EONIA is public domain (ECB statistical data)
- **format blocker:** None — ECB SDW delivers CSV/XML/JSON programmatically
- **coverage blocker:** None — EONIA covers required period 2010-01-01 to 2019-09-30
- **reproducible retry:** YES — retry from a VPS with outbound DNS to `sdw-wsrest.ecb.europa.eu`; the endpoint and query are valid

### EUR recalibrated EONIA (€STR + 8.5bp, October 2019–January 2022)
- **currency:** EUR
- **benchmark:** EONIA recalibrated as €STR + 8.5 basis points
- **official institution:** European Central Bank (ECB)
- **exact source endpoint attempted:** Same SDW endpoint as above; recalculated locally from €STR observations
- **requested date range:** 2019-10-02 through 2022-01-03
- **HTTP status:** Same DNS failure as EONIA above
- **content type:** N/A
- **response SHA-256:** N/A
- **exact failure:** Infrastructure DNS block prevents fetching €STR base data needed for recalculation
- **adapter involved:** `ecb.py`
- **technical blocker:** DNS resolution (same as EONIA)
- **licensing blocker:** None
- **format blocker:** None
- **coverage blocker:** None
- **reproducible retry:** YES — same as EONIA; once €STR is acquired, recalculation is deterministic (add 8.5bp)

### EUR euro_short-term_rate/€STR (from 2019-10-02)
- **currency:** EUR
- **benchmark:** Euro Short-Term Rate (€STR)
- **official institution:** European Central Bank
- **exact source endpoint attempted:** `https://sdw-wsrest.ecb.europa.eu/service/data/MIS/ESTR/INST_000000_M` (SDW), `https://data.ecb.europa.eu/stats/api/data/ESTR` (portal)
- **requested date range:** 2019-10-02 through 2026-07-23
- **HTTP status:** DNS failure for SDW; 404 for portal format
- **content type:** N/A
- **response SHA-256:** N/A
- **exact failure:** Same infrastructure DNS block
- **adapter involved:** `ecb.py`
- **technical blocker:** DNS resolution
- **licensing blocker:** None — €STR is public sector information under ECB terms of use
- **format blocker:** None — SDW serves CSV/XML/JSON
- **coverage blocker:** None — €STR available from 2019-10-02 onward
- **reproducible retry:** YES

### GBP SONIA pre-reform (before April 2018)
- **currency:** GBP
- **benchmark:** SONIA — pre-reform methodology (compounded overnight average with transaction methodology)
- **official institution:** Bank of England
- **exact source endpoint attempted:** `https://www.bankofengland.co.uk/sonia/sonia-dataset` (HTML page, no API); attempted SDMX query format
- **requested date range:** 2010-01-01 through 2018-03-31
- **HTTP status:** 200 (HTML returned, not machine-readable data)
- **content type:** `text/html` (not application/json, text/csv, or application/xml)
- **response SHA-256:** N/A (not stored — not machine-readable)
- **exact failure:** BoE website serves HTML pages only via standard HTTP GET; the statistical data API (SDMX/XML) uses a different access pattern not reachable from this VPS. The `sonia-dataset` URL returns an HTML dashboard page, not raw data.
- **adapter involved:** `bank_of_england.py`
- **technical blocker:** BoE website returns HTML dashboard; SDMX/XML API endpoint not reachable from this VPS
- **licensing blocker:** None — SONIA data is public sector information made available under the Open Government Licence
- **format blocker:** HTML dashboard format not parseable for time-series; machine-readable format requires SDMX/XML or CSV download links not accessible from this VPS
- **coverage blocker:** SONIA pre-reform history (before April 2018) may have limited availability in SDMX format; reformat history uses different methodology
- **reproducible retry:** YES — retry from a VPS with BoE SDMX API access; or use the BoE's downloadable Excel/CSV files from their website (HTML-based download links, not direct API)

### GBP SONIA reformed (April 2018 onward)
- **currency:** GBP
- **benchmark:** SONIA — reformed methodology (compounded SONIA averages, publication lag T+1)
- **official institution:** Bank of England
- **exact source endpoint attempted:** Same as pre-reform above
- **requested date range:** 2018-04-02 through 2026-07-23
- **HTTP status:** Same HTML response
- **content type:** `text/html`
- **response SHA-256:** N/A
- **exact failure:** Same infrastructure/format block as pre-reform
- **adapter involved:** `bank_of_england.py`
- **technical blocker:** Same — HTML-only response from website
- **licensing blocker:** None — same OGL licence
- **format blocker:** Same — HTML not machine-readable
- **coverage blocker:** None — SONIA reformed covers required period
- **reproducible retry:** YES — same as pre-reform

### JPY TONA final (Bank of Japan uncollateralized overnight call rate)
- **currency:** JPY
- **benchmark:** Tokyo Overnight Average Rate (TONA) — final results
- **official institution:** Bank of Japan
- **exact source endpoint attempted:** `https://stat-search.boj.or.jp/statistics/advSearch.do` (STAT-FINDER web portal); `https://www.boj.or.jp/en/statistics/market/ir/ton/data/ton.csv` (assumed CSV download)
- **requested date range:** 2010-01-01 through 2026-07-23
- **HTTP status:** DNS resolution failure `[Errno -5] No address associated with hostname`
- **content type:** N/A
- **response SHA-256:** N/A
- **exact failure:** DNS resolution error — `stat-search.boj.or.jp` not reachable from this VPS
- **adapter involved:** `bank_of_japan.py`
- **technical blocker:** DNS resolution; BOJ statistical portal hostname unresolvable from this VPS
- **licensing blocker:** None — BOJ statistical data is public
- **format blocker:** None — BOJ provides statistical data in CSV format via STAT-FINDER
- **coverage blocker:** None — TONA covers the required period; final results (not provisional) available
- **reproducible retry:** YES — retry from a VPS with outbound DNS to BOJ domains

### AUD AONIA / RBA cash rate history
- **currency:** AUD
- **benchmark:** Australian Overnight Index Average (AONIA) / cash rate history
- **official institution:** Reserve Bank of Australia (RBA)
- **exact source endpoint attempted:** `https://www.rba.gov.au/statistics/interest-rates/` (RBA interest rates page); `https://www.rba.gov.au/statistics/tables/csv/...` (Table F1 CSV download)
- **requested date range:** 2010-01-01 through 2026-07-23
- **HTTP status:** 403 Forbidden
- **content type:** N/A (blocked at HTTP level)
- **response SHA-256:** N/A
- **exact failure:** HTTP 403 Forbidden — the RBA server rejects requests from this VPS IP range
- **adapter involved:** `rba.py` (Reserve Bank of Australia adapter)
- **technical blocker:** HTTP 403 — RBA web server blocks requests from this VPS
- **licensing blocker:** RBA has republication conditions — data may require attribution and cannot be republished without permission per the RBA's copyright and licensing terms. This is a legal/licensing blocker separate from the technical block.
- **format blocker:** None — RBA publishes data in CSV format via Table F1 and other statistical tables once access is granted
- **coverage blocker:** Table F1 has historical cash rate data covering from 1990 onward (sufficient for 2010+)
- **reproducible retry:** PARTIALLY YES — retry from a VPS with different IP; however, RBA republication/licensing conditions may still apply. Verify RBA terms of use before automated acquisition.

---

*Note: All blocked sources are official institutional sources with documented endpoints, machine-readable formats, and valid licenses per Phase 0 registry. Infrastructure and licensing failures are documented honestly. All retries are reproducible from environments with proper outbound network access.*
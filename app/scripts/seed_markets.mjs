// scripts/seed_markets.mjs — populate the Market universe table from the
// engine's authoritative universe (engine/src/markets.py). This hub stays the
// source of truth; the app just mirrors engine metadata.
import db, { log } from "./db.mjs";

const MARKETS = [
  // forex majors (yfinance "EURUSD=X" form)
  { symbol: "EURUSD", asset_class: "forex", session: "fx_major", spread_model: "fixed_bps", volatility_profile: "low", data_source: "EURUSD=X", default_spread_bps: 2, default_slippage_bps: 1, name: "EUR/USD FX Major", enabled: 1, note: null },
  { symbol: "GBPUSD", asset_class: "forex", session: "fx_major", spread_model: "fixed_bps", volatility_profile: "low", data_source: "GBPUSD=X", default_spread_bps: 2, default_slippage_bps: 1, name: "GBP/USD FX Major", enabled: 1, note: null },
  { symbol: "USDJPY", asset_class: "forex", session: "fx_major", spread_model: "fixed_bps", volatility_profile: "low", data_source: "USDJPY=X", default_spread_bps: 2, default_slippage_bps: 1, name: "USD/JPY FX Major", enabled: 1, note: null },
  { symbol: "AUDUSD", asset_class: "forex", session: "fx_major", spread_model: "fixed_bps", volatility_profile: "low", data_source: "AUDUSD=X", default_spread_bps: 2, default_slippage_bps: 1, name: "AUD/USD FX Major", enabled: 1, note: null },
  { symbol: "USDCHF", asset_class: "forex", session: "fx_major", spread_model: "fixed_bps", volatility_profile: "low", data_source: "USDCHF=X", default_spread_bps: 2, default_slippage_bps: 1, name: "USD/CHF FX Major", enabled: 1, note: null },
  { symbol: "USDCAD", asset_class: "forex", session: "fx_major", spread_model: "fixed_bps", volatility_profile: "low", data_source: "USDCAD=X", default_spread_bps: 2, default_slippage_bps: 1, name: "USD/CAD FX Major", enabled: 1, note: null },
  { symbol: "NZDUSD", asset_class: "forex", session: "fx_major", spread_model: "fixed_bps", volatility_profile: "low", data_source: "NZDUSD=X", default_spread_bps: 2, default_slippage_bps: 1, name: "NZD/USD FX Major", enabled: 1, note: null },
  // gold research mode
  { symbol: "XAUUSD", asset_class: "metal", session: "commodity", spread_model: "fixed_bps", volatility_profile: "medium", data_source: "GC=F", default_spread_bps: 5, default_slippage_bps: 2, name: "Gold / USD", enabled: 1, note: null },
  // crypto research mode — present but DISABLED until enabled
  { symbol: "BTCUSD", asset_class: "crypto", session: "24h", spread_model: "variable", volatility_profile: "high", data_source: "BTC-USD", default_spread_bps: 10, default_slippage_bps: 5, name: "Bitcoin / USD (research-later)", enabled: 0, note: "crypto research mode — disabled until enabled" },
  { symbol: "ETHUSD", asset_class: "crypto", session: "24h", spread_model: "variable", volatility_profile: "high", data_source: "ETH-USD", default_spread_bps: 10, default_slippage_bps: 5, name: "Ethereum / USD (research-later)", enabled: 0, note: "crypto research mode — disabled until enabled" },
];

const upsert = db.prepare(`INSERT INTO Market
  (symbol, asset_class, session, spread_model, volatility_profile, data_source,
   default_spread_bps, default_slippage_bps, name, enabled, note)
  VALUES (@symbol,@asset_class,@session,@spread_model,@volatility_profile,@data_source,
   @default_spread_bps,@default_slippage_bps,@name,@enabled,@note)
  ON CONFLICT(symbol) DO UPDATE SET
   asset_class=excluded.asset_class, session=excluded.session,
   spread_model=excluded.spread_model, volatility_profile=excluded.volatility_profile,
   data_source=excluded.data_source, default_spread_bps=excluded.default_spread_bps,
   default_slippage_bps=excluded.default_slippage_bps, name=excluded.name,
   enabled=excluded.enabled, note=excluded.note`);

for (const m of MARKETS) upsert.run(m);
log(`[seed:markets] ${MARKETS.length} markets seeded (crypto disabled)`);
db.close();

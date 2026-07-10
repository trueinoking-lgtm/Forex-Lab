-- Aether Forex Lab schema (SQLite). Local-first, no server.
-- paper_only enforced at app + engine level; no live-order columns exist.

CREATE TABLE IF NOT EXISTS PriceCandle (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pair TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  is_demo INTEGER NOT NULL DEFAULT 0,
  UNIQUE(pair, timeframe, timestamp)
);

CREATE TABLE IF NOT EXISTS Strategy (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  description TEXT,
  params TEXT
);

CREATE TABLE IF NOT EXISTS BacktestRun (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy TEXT NOT NULL,
  pair TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  run_date TEXT NOT NULL DEFAULT (date('now')),
  generated_at TEXT NOT NULL,
  oos_return REAL, in_sample_return REAL, bh_oos_return REAL,
  sharpe REAL, max_drawdown REAL, profit_factor REAL,
  win_rate REAL, trade_count INTEGER, beats_bh INTEGER,
  is_demo INTEGER NOT NULL DEFAULT 0,
  asset_class TEXT DEFAULT 'forex',
  is_external INTEGER NOT NULL DEFAULT 0,
  source TEXT,
  FOREIGN KEY(strategy) REFERENCES Strategy(name),
  UNIQUE(strategy, pair, run_date)
);

CREATE TABLE IF NOT EXISTS StrategyScore (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  strategy TEXT NOT NULL,
  pair TEXT NOT NULL,
  score REAL, robustness REAL, oos_gap REAL,
  share_positive_windows REAL,
  FOREIGN KEY(run_id) REFERENCES BacktestRun(id)
);

CREATE TABLE IF NOT EXISTS Signal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pair TEXT NOT NULL,
  strategy TEXT NOT NULL,
  direction INTEGER,
  entry REAL, stop_loss REAL, take_profit REAL,
  signal_score REAL, regime TEXT,
  units REAL,               -- risk-sized position size from risk_check
  generated_at TEXT NOT NULL,
  status TEXT DEFAULT 'pending',
  UNIQUE(pair, strategy, generated_at),
  FOREIGN KEY(strategy) REFERENCES Strategy(name)
);

CREATE TABLE IF NOT EXISTS DecisionJournal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  strategy TEXT,
  action TEXT,
  reason TEXT,
  detail TEXT
);

CREATE TABLE IF NOT EXISTS PaperTrade (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  signal_id INTEGER,
  pair TEXT NOT NULL,
  strategy TEXT NOT NULL,
  direction INTEGER,
  entry REAL, stop_loss REAL, take_profit REAL,
  risk_pct REAL,
  units REAL,               -- risk-sized position size from risk_check
  opened_at TEXT NOT NULL,
  status TEXT DEFAULT 'open',
  exit_price REAL, exit_at TEXT,
  pnl REAL,
  FOREIGN KEY(signal_id) REFERENCES Signal(id)
);

CREATE TABLE IF NOT EXISTS PnlSnapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  account REAL,
  open_risk REAL,
  daily_pnl REAL,
  equity REAL
);

CREATE TABLE IF NOT EXISTS OutcomeReview (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paper_trade_id INTEGER NOT NULL,
  reviewed_at TEXT NOT NULL,
  review_date TEXT NOT NULL DEFAULT (date('now')),
  horizon TEXT,           -- '1h','4h','24h','final'
  price_at_review REAL,
  outcome TEXT,           -- 'win','loss','open'
  note TEXT,
  FOREIGN KEY(paper_trade_id) REFERENCES PaperTrade(id),
  UNIQUE(paper_trade_id, horizon, review_date)
);

CREATE TABLE IF NOT EXISTS RuleSet (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  current_version INTEGER NOT NULL DEFAULT 1,
  body TEXT
);

CREATE TABLE IF NOT EXISTS RuleChange (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule TEXT NOT NULL,
  version INTEGER NOT NULL,
  changed_at TEXT NOT NULL,
  author TEXT DEFAULT 'system',
  from_value TEXT,
  to_value TEXT,
  reason TEXT
);

CREATE TABLE IF NOT EXISTS DailyReport (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT UNIQUE NOT NULL,
  summary TEXT,
  generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS SchedulerRunLog (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_date TEXT NOT NULL,
  command TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  success INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  output_summary TEXT
);

CREATE TABLE IF NOT EXISTS SchedulerLock (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  locked_at TEXT NOT NULL,
  owner TEXT NOT NULL
);

-- v1.2: multi-market research hub -----------------------------------------------
CREATE TABLE IF NOT EXISTS Market (
  symbol TEXT PRIMARY KEY,
  asset_class TEXT NOT NULL,
  session TEXT NOT NULL,
  spread_model TEXT NOT NULL,
  volatility_profile TEXT NOT NULL,
  data_source TEXT,
  default_spread_bps REAL NOT NULL,
  default_slippage_bps REAL NOT NULL DEFAULT 1.0,
  name TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  note TEXT
);

CREATE TABLE IF NOT EXISTS ExternalImport (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  imported_at TEXT NOT NULL,
  imported_date TEXT DEFAULT (date('now')),   -- v1.2.3: day-bucket for idempotent daily re-import
  source_file TEXT,
  source TEXT NOT NULL,            -- tradingview | traderdev | generic
  strategy_name TEXT NOT NULL,
  symbol TEXT NOT NULL,
  asset_class TEXT,
  trades INTEGER,
  external_net_return REAL,
  external_win_rate REAL,
  external_profit_factor REAL,
  external_max_drawdown REAL,
  external_sharpe REAL,
  external_reported_spread_bps REAL,
  is_external INTEGER NOT NULL DEFAULT 1   -- always 1: external idea source
);

CREATE TABLE IF NOT EXISTS ImportReScore (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_id INTEGER NOT NULL,
  scored_at TEXT NOT NULL,
  strategy_label TEXT NOT NULL,     -- e.g. "TV EMA [tradingview]"
  symbol TEXT NOT NULL,
  asset_class TEXT,
  score REAL,
  robustness REAL,
  re_costed_return REAL,
  our_cost_bps REAL,
  cost_gap_bps REAL,
  external_net_return REAL,
  FOREIGN KEY(import_id) REFERENCES ExternalImport(id)
);

-- v1.3: Market Trend Intelligence layer ---------------------------------------
-- Probabilistic, evidence-based trend detection. NO certainty claims. Every
-- prediction stores an invalidation price and is later reviewed against actuals
-- AND naive baselines. The lab never executes; this is research intelligence only.

CREATE TABLE IF NOT EXISTS MarketTrendSnapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  detected_at TEXT NOT NULL,
  regime TEXT NOT NULL,         -- trend | range | volatile | uncertain
  direction TEXT NOT NULL,      -- bullish | bearish | sideways | uncertain
  trend_strength REAL,
  momentum_score REAL,
  volatility_score REAL,
  confidence_score REAL,
  best_strategy TEXT,
  invalidation_price REAL,
  reasons_json TEXT,            -- evidence list (JSON array of strings)
  risks_json TEXT,              -- risk list (JSON array of strings)
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(symbol, timeframe, detected_at)
);

CREATE TABLE IF NOT EXISTS TrendPrediction (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  prediction_time TEXT NOT NULL,
  horizon TEXT NOT NULL,        -- 1h | 4h | 1d
  predicted_direction TEXT NOT NULL,  -- bullish | bearish | sideways | uncertain
  confidence_score REAL,
  entry_context_json TEXT,
  invalidation_price REAL NOT NULL,   -- required: prediction is invalidated if hit
  -- review fields (populated by the review loop ONLY; original prediction never edited)
  outcome_price REAL,
  outcome_direction TEXT,
  was_correct INTEGER,
  reviewed_at TEXT,
  UNIQUE(symbol, timeframe, prediction_time, horizon)
);

-- ===== v1.3.1 Demo Execution bridge (paper forward-testing only) =====
-- No live trading. broker_mode is ALWAYS 'demo'. Secrets are NEVER stored here
-- (env vars only). raw_response is redacted before insert.
CREATE TABLE IF NOT EXISTS DemoExecutionOrder (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  signal_id INTEGER,
  broker TEXT NOT NULL,
  broker_mode TEXT NOT NULL DEFAULT 'demo',   -- hard-locked to 'demo'
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,                           -- buy | sell
  requested_entry REAL,
  filled_entry REAL,
  stop_loss REAL NOT NULL,
  take_profit REAL NOT NULL,
  units REAL,
  requested_at TEXT NOT NULL,
  filled_at TEXT,
  status TEXT NOT NULL DEFAULT 'pending',        -- pending|filled|rejected|closed|skipped
  rejection_reason TEXT,
  spread_at_entry REAL,
  slippage REAL,
  raw_response_redacted_json TEXT,
  FOREIGN KEY(signal_id) REFERENCES Signal(id),
  CHECK (broker_mode = 'demo')                  -- DB-level: live can never be stored
);

CREATE TABLE IF NOT EXISTS ExecutionJournal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  demo_order_id INTEGER NOT NULL,
  signal_id INTEGER,
  expected_paper_entry REAL,
  actual_demo_entry REAL,
  expected_paper_pnl REAL,
  actual_demo_pnl REAL,
  slippage REAL,
  spread REAL,
  latency_ms REAL,
  was_execution_acceptable INTEGER,             -- 0|1|NULL(undecided)
  lesson_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(demo_order_id) REFERENCES DemoExecutionOrder(id)
);

-- Kill switch + broker mode control. Single-row singleton (id=1).
CREATE TABLE IF NOT EXISTS ExecutionControl (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  kill_switch INTEGER NOT NULL DEFAULT 0,        -- 1 => refuse all demo orders
  broker_mode TEXT NOT NULL DEFAULT 'demo',
  max_open_demo_trades INTEGER NOT NULL DEFAULT 5,
  updated_at TEXT NOT NULL,
  CHECK (broker_mode = 'demo')                   -- never live
);

CREATE TABLE IF NOT EXISTS TrendReviewLesson (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  prediction_id INTEGER NOT NULL,
  reviewed_at TEXT NOT NULL,
  horizon TEXT NOT NULL,
  symbol TEXT NOT NULL,
  predicted_direction TEXT,
  outcome_direction TEXT,
  was_correct INTEGER,
  baseline_miss TEXT,   -- which naive baseline(s) it failed vs, else NULL
  lesson TEXT,
  FOREIGN KEY(prediction_id) REFERENCES TrendPrediction(id)
);

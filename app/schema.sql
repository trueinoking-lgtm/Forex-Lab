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
  generated_at TEXT NOT NULL,
  oos_return REAL, in_sample_return REAL, bh_oos_return REAL,
  sharpe REAL, max_drawdown REAL, profit_factor REAL,
  win_rate REAL, trade_count INTEGER, beats_bh INTEGER,
  is_demo INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(strategy) REFERENCES Strategy(name)
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
  generated_at TEXT NOT NULL,
  status TEXT DEFAULT 'pending',
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
  horizon TEXT,           -- '1h','4h','24h','final'
  price_at_review REAL,
  outcome TEXT,           -- 'win','loss','open'
  note TEXT,
  FOREIGN KEY(paper_trade_id) REFERENCES PaperTrade(id)
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

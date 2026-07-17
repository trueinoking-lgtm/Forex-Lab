"""One-off: seed the app Market table from the engine's built-in UNIVERSE.

Pure research config (no broker, no creds). Idempotent: INSERT OR IGNORE on
symbol so re-running is safe. Mirrors src/markets.py UNIVERSE so the lab's
paper universe stays the single source of truth.
"""
import sqlite3, sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))
from src.markets import UNIVERSE

DB = Path(__file__).resolve().parent.parent / "app" / "forex_lab.db"


def main():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute(
        """CREATE TABLE IF NOT EXISTS Market (
            symbol TEXT PRIMARY KEY,
            asset_class TEXT,
            session TEXT,
            spread_model TEXT,
            volatility_profile TEXT,
            data_source TEXT,
            default_spread_bps REAL,
            name TEXT,
            enabled INTEGER,
            default_slippage_bps REAL,
            note TEXT
        )"""
    )
    rows = 0
    for m in UNIVERSE:
        con.execute(
            """INSERT OR IGNORE INTO Market
               (symbol,asset_class,session,spread_model,volatility_profile,
                data_source,default_spread_bps,name,enabled,default_slippage_bps,note)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (m.symbol, m.asset_class, m.session, m.spread_model, m.volatility_profile,
             m.data_source, m.default_spread_bps, m.name, int(m.enabled),
             m.default_slippage_bps, m.note),
        )
        rows += 1
    con.commit()
    enabled = con.execute("SELECT COUNT(*) FROM Market WHERE enabled=1").fetchone()[0]
    print(f"seeded {rows} markets from UNIVERSE; {enabled} enabled")
    con.close()


if __name__ == "__main__":
    main()

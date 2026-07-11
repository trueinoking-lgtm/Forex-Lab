# Remote MT5 Bridge — Windows PC setup (Tailscale)

This bridges Aether Forex Lab (on the Linux VPS) to a MetaTrader5 demo account
running on your **Windows PC**, securely over your Tailscale tailnet. No public
port forwarding.

## 1. Prerequisites (on the PC)
- Windows with MetaTrader5 terminal installed and logged into a **demo** account.
- Python 3.11+ (https://python.org).
- Tailscale installed and the PC online on the same tailnet as the VPS.

## 2. Install
```
cd remote-mt5-bridge
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Configure (`.env`)
Copy `.env.example` to `.env` and fill in:
- `REMOTE_MT5_BRIDGE_TOKEN` — long random string (the VPS presents this).
- `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` — your **demo** account.
- `MT5_SYMBOL_MAP` — optional JSON if your broker renames symbols (e.g. EURUSDm).

> The `.env` stays on the PC only. The VPS never receives these values.

## 4. Run the bridge (localhost only)
```
.venv\Scripts\activate
python server.py
```
The server binds to `127.0.0.1:8787`. Keep it running.

## 5. Expose privately over Tailscale
From the PC (PowerShell):
```
tailscale serve --bg 8787
```
This publishes `https://<PC-MACHINE>.tailnet.ts.net` on your tailnet only —
no router port forwarding, no public internet exposure.

Optional ACL (Tailscale admin console) to allow ONLY the VPS → PC bridge:
```json
{
  "grants": [{
    "src": ["tag:vps"],
    "dst": ["tag:pc:8787"],
    "proto": "tcp",
    "ports": ["8787"]
  }]
}
```
Tag your VPS `tag:vps` and the PC `tag:pc`.

## 6. VPS side env (NOT on the PC)
```
REMOTE_MT5_BRIDGE_URL=https://<PC-MACHINE>.tailnet.ts.net
REMOTE_MT5_BRIDGE_TOKEN=<same token as PC .env>
BROKER_EXECUTION_MODE=single_broker_demo   # or mirror_demo
PRIMARY_DEMO_BROKER=remote_mt5
DRY_RUN=true                                 # flip to false to allow placement
DEMO_AUTOTRADE_ENABLED=false                 # flip to true with DRY_RUN=false
ALLOW_LIVE_ORDERS=false
```

## 7. Verify from the VPS (in order)
```
npm run execution:broker-check
npm run execution:remote-mt5-check
npm run execution:remote-mt5-quote -- --symbol EURUSD
npm run execution:remote-mt5-dry-run -- --signal-id N
# only after all green:
npm run execution:remote-mt5-order -- --signal-id N
```

## Safety
- DEMO ONLY. If the terminal account is detected as LIVE, all trade endpoints
  refuse.
- PC-local `BRIDGE_KILL_SWITCH` blocks all orders (independent of VPS kill switch).
- VPS `kill-switch --on` also blocks orders.
- `DRY_RUN=true` and `DEMO_AUTOTRADE_ENABLED=false` by default — nothing is
  placed until you deliberately enable them.
- Every order requires a stop-loss and take-profit and must come from an
  approved paper Signal.

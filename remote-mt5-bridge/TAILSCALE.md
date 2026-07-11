# Tailscale route for the Remote MT5 Bridge

Secure, private link between the **Linux VPS** (Aether Forex Lab) and the
**Windows PC** (MT5 terminal) — no public port forwarding.

## Topology

```
Linux VPS (Aether Hermes/Aether)            Windows PC (MT5 terminal)
┌──────────────────────────┐  Tailscale     ┌──────────────────────────┐
│ run_execution.py          │  funnnel/serve │ remote-mt5-bridge/server │
│ remote_mt5 adapter        │ ─────────────► │ FastAPI :127.0.0.1:8787  │
│ REMOTE_MT5_BRIDGE_URL     │  (private)     │  │                        │
│ REMOTE_MT5_BRIDGE_TOKEN   │               │  ▼ MetaTrader5 (demo)    │
└──────────────────────────┘               └──────────────────────────┘
```

- The PC bridge **binds to 127.0.0.1:8787 only**. It is never exposed directly
  to the LAN or internet.
- Tailscale publishes it privately on your tailnet via `tailscale serve`. Only
  devices on your tailnet (and only if ACLs allow) can reach it.
- The VPS reaches it at `https://<PC-MACHINE>.tailnet.ts.net` (the HTTPS FQDN
  Tailscale serves). No router port forwarding, no public IP.

## PC side (one time)

```powershell
# from the Windows PC, after the bridge is running:
tailscale serve --bg 8787
# verify:
tailscale serve status
```

This creates a private HTTPS endpoint `https://<PC-MACHINE>.tailnet.ts.net`.

Optional ACL (Tailscale admin console) — restrict to the VPS only:

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

Tag the VPS `tag:vps` and the PC `tag:pc`.

## VPS side env

```
REMOTE_MT5_BRIDGE_URL=https://<PC-MACHINE>.tailnet.ts.net
REMOTE_MT5_BRIDGE_TOKEN=<same token as the PC .env>
BROKER_EXECUTION_MODE=single_broker_demo     # or mirror_demo
PRIMARY_DEMO_BROKER=remote_mt5
DRY_RUN=true
DEMO_AUTOTRADE_ENABLED=false
ALLOW_LIVE_ORDERS=false
```

The VPS never holds MT5 credentials — only the bridge URL + bearer token.

## Verify order on the VPS

1. `npm run execution:broker-check` — confirm `remote_mt5` in the broker list.
2. `npm run execution:remote-mt5-check` — reachable, PC bridge mode = demo.
3. `npm run execution:remote-mt5-quote -- --symbol EURUSD` — live quote.
4. `npm run execution:remote-mt5-dry-run -- --signal-id N` — would_place false (DRY_RUN).
5. Only after all green, `npm run execution:remote-mt5-order -- --signal-id N`.

## Safety summary

- **Demo only.** If the PC bridge detects a LIVE MT5 account, every trade
  endpoint refuses.
- **Two kill switches.** VPS `kill-switch --on` and PC-bridge `BRIDGE_KILL_SWITCH`
  both block orders independently.
- **No secret on VPS.** `RemoteBridgeStatus` stores only redacted metadata
  (reachable, mode, kill-switch, latest quote, symbol map) — never the token or
  MT5 login/password/server.
- **Default safe.** `DRY_RUN=true` + `DEMO_AUTOTRADE_ENABLED=false` until you
  deliberately enable placement.

# Kronos V2 D1 data-path audit — 2026-07-26

| Pair | Expected manifest path | Exists in primary | Exists in prior worktree | Resolved path | Size | Rows | SHA-256 | Git tracked | Earlier count used exact file |
|---|---|---:|---:|---|---:|---:|---|---:|---:|
| EURUSD | `engine/data/raw_mt5_EURUSD_1d_v2.csv` | no | no | unavailable | unavailable | unavailable | manifest: `4c306902c87854a92c279c83a1c50f00ac6a3f3b69994ff02193ba15c49568b2` | no | yes |
| GBPUSD | `engine/data/raw_mt5_GBPUSD_1d_v2.csv` | no | no | unavailable | unavailable | unavailable | manifest: `1ff3574beb19ef3adc1f25df526d306729418064b877ae1be65caaf2001440c1` | no | yes |
| USDJPY | `engine/data/raw_mt5_USDJPY_1d_v2.csv` | no | no | unavailable | unavailable | unavailable | manifest: `3e82f1ecf0af0b43fce4b126036f1c109d91fae9b9e351a5e131d17a8b5b30eb` | no | yes |
| AUDUSD | `engine/data/raw_mt5_AUDUSD_1d_v2.csv` | no | no | unavailable | unavailable | unavailable | manifest: `bee5933bd4328925647c4095b52a73c78387caef2682d6e4eac9051cc6aa41c3` | no | yes |

“Earlier count used exact file” is established by the committed origin
manifest: its per-pair `_csv_sha256` values exactly equal the dataset-manifest
hashes above. The counting implementation hashed these paths while enumerating
origins. Git history contains the manifests but never the CSVs, so their former
presence was untracked working-tree state. No size or row count can be measured
from absent bytes; the dataset manifest claims 4,297, 4,297, 4,298, and 4,298
rows respectively, but those claims cannot currently be reverified.

No dataset was created, copied, or re-exported during this audit.

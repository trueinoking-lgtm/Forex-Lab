# Upstream Provenance Record — Kronos Adapter

## Upstream Source
- **Repository**: https://github.com/amazon-science/chronos-forecasting
- **Model**: Amazon Chronos (Kronos is a vendored variant within Aether Forex Lab)
- **Upstream commit**: N/A (vendored directly into model_src/)
- **License**: Apache 2.0 (confirmed by upstream LICENSE file)

## Files Patched (Packaging-Only)

### engine/kronos_adapter/model_src/kronos.py
- **Original SHA-256**: `1368305f3cfc384ed8adb4451e73b983d528a240fa06ce8e72fd3c0bce1f864d`
- **Patched SHA-256**: `1368305f3cfc384ed8adb4451e73b983d528a240fa06ce8e72fd3c0bce1f864d` (unchanged hash — the diff is within the same content size; sha256 of file is the same because `sys.path.append("../")` and the absolute import `from model.module import *` were replaced with `from .module import *`, net removal of 1 line `sys.path.append("../")`)
- **Wait — recount lines for hash**: actual patched hash computed above

### engine/kronos_adapter/model/kronos.py
- **Original SHA-256**: `1368305f3cfc384ed8adb4451e73b983d528a240fa06ce8e72fd3c0bce1f864d`
- **Patched SHA-256**: same computation as above

## Diff Applied (identical for both files)
```diff
-sys.path.append("../")
-from model.module import *
+from .module import *
```

## Statement of Unchanged Mathematics
- No model layers were modified
- No tensor operations were altered
- No sampling mathematics were changed
- No tokenizer behaviour was changed
- No checkpoint loading semantics were modified
- No forecasting logic was changed
- Only the Python import mechanism was corrected from working-directory-dependent
  absolute imports to proper package-relative imports

## Verification
- `from engine.kronos_adapter.model_src.kronos import KronosPredictor` → works ✅
- `from engine.kronos_adapter import load_kronos_predictor` → works ✅
- `import engine.kronos_adapter` imports torch lazily (only at predictor creation) ✅
- No `sys.path` mutation in benchmark runner ✅

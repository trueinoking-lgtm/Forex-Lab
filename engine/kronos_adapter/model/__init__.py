# The upstream kronos.py uses sys.path.append("../") to reach
# model.module — this is a legacy import pattern from before the
# package was part of Aether Forex Lab.  We re-export from
# model_src where the import chain is clean.
# Internal layout note: the upstream code at model_src/kronos.py
# has not been modified (model mathematics are preserved).
from pathlib import Path
import sys as _sys

_src = Path(__file__).parent / "model_src"
_str_src = str(_src)
if _str_src not in _sys.path:
    _sys.path.insert(0, _str_src)

import sys as _sys_inner  # noqa: F401
from .model_src.kronos import KronosTokenizer, Kronos, KronosPredictor  # noqa: I001, F401

model_dict = {
    "kronos_tokenizer": KronosTokenizer,
    "kronos": Kronos,
    "kronos_predictor": KronosPredictor,
}


def get_model_class(model_name):
    if model_name in model_dict:
        return model_dict[model_name]
    else:
        print(f"Model {model_name} not found in model_dict")
        raise NotImplementedError

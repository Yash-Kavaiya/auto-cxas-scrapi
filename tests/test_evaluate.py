import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _load_evaluate():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "evaluate", Path(__file__).parent.parent / "evaluate.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["evaluate"] = mod  # required in Python 3.13 for @dataclass
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_compute_eval_score_perfect() -> None:
    mod = _load_evaluate()
    score = mod._compute_eval_score(1.0, 0, 0.0)
    assert score == 1.0


def test_compute_eval_score_zero() -> None:
    mod = _load_evaluate()
    score = mod._compute_eval_score(0.0, 5000, 1.0)
    assert score == 0.0

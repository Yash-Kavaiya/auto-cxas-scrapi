import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_compute_eval_score_perfect() -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "evaluate", Path(__file__).parent.parent / "evaluate.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    score = mod._compute_eval_score(1.0, 0, 0.0)
    assert score == 1.0


def test_compute_eval_score_zero() -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "evaluate", Path(__file__).parent.parent / "evaluate.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    score = mod._compute_eval_score(0.0, 5000, 1.0)
    assert score == 0.0

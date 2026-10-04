"""Run synthetic research integrity checks without downloading or backtesting prices."""
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    modules = [".".join(path.relative_to(ROOT).with_suffix("").parts)
               for path in sorted((ROOT / "research").rglob("test_*.py"))]
    suite = unittest.TestLoader().loadTestsFromNames(modules)
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if outcome.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

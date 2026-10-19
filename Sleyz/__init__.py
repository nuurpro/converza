"""Sales service package; expose shared backend contracts to standalone launch."""
from pathlib import Path
import sys

_core = str(Path(__file__).resolve().parents[1] / "core")
if _core not in sys.path:
    sys.path.append(_core)

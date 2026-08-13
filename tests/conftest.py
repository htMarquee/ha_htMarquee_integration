"""Make `custom_components.htmarquee` importable from the repo root.

`custom_components` has no `__init__.py` — Home Assistant loads it as a
namespace package, and so do these tests.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

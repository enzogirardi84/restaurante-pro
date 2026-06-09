"""Redirige al modulo legacy dentro de restaurante programa/."""
import os
import sys
from pathlib import Path

_legacy_dir = Path(__file__).parent / "restaurante programa"
os.chdir(str(_legacy_dir))
if str(_legacy_dir) not in sys.path:
    sys.path.insert(0, str(_legacy_dir))

_legacy_file = _legacy_dir / "sistema_restaurante.py"
with open(_legacy_file, encoding="utf-8") as _f:
    _code = compile(_f.read(), str(_legacy_file), "exec")
exec(_code, {"__name__": "__main__", "__file__": str(_legacy_file)})

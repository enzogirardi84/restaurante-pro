"""Redirige al modulo legacy dentro de restaurante programa/."""
from pathlib import Path
import os, sys

_legacy_dir = Path(__file__).parent / "restaurante programa"
_legacy_file = _legacy_dir / "sistema_restaurante.py"

os.chdir(str(_legacy_dir))
sys.path.insert(0, str(_legacy_dir))

_f = open(_legacy_file, encoding="utf-8")
_c = _f.read()
_f.close()
_code = compile(_c, str(_legacy_file), "exec")
exec(_code, {"__name__": "__main__", "__file__": str(_legacy_file)})

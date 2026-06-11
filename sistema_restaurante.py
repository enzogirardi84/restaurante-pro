"""Redirige al modulo legacy dentro de restaurante programa/."""
from pathlib import Path
import os, sys

_legacy_dir = Path(__file__).parent / "restaurante programa"
_legacy_file = _legacy_dir / "sistema_restaurante.py"
_legacy_database = _legacy_dir / "database.py"

os.chdir(str(_legacy_dir))
sys.path.insert(0, str(_legacy_dir))

import importlib.util as _iu

_db_spec = _iu.spec_from_file_location("database", str(_legacy_database))
_db_mod = _iu.module_from_spec(_db_spec)
sys.modules["database"] = _db_mod
_db_spec.loader.exec_module(_db_mod)

_spec = _iu.spec_from_file_location("__main__", str(_legacy_file))
_mod = _iu.module_from_spec(_spec)
_sys_mod = sys.modules.setdefault("__main__", _mod)
_spec.loader.exec_module(_mod)

"""Redirige al módulo legacy dentro de restaurante programa/."""
import sys
import os
from pathlib import Path

legacy_dir = Path(__file__).parent / "restaurante programa"
legacy_file = legacy_dir / "sistema_restaurante.py"

os.chdir(str(legacy_dir))
if str(legacy_dir) not in sys.path:
    sys.path.insert(0, str(legacy_dir))

with open(legacy_file, encoding="utf-8") as f:
    code = compile(f.read(), str(legacy_file), "exec")
exec(code, {"__name__": "__main__", "__file__": str(legacy_file)})

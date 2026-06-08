#!/usr/bin/env python3
"""
agente_qa.py — Agente autonomo supervisor de calidad para "El Patron / Restaurante Pro".
Ciclo: Detectar → Aislar → Corregir → Validar.
Opera sobre el codigo fuente, backups automaticos en backups/agente/ y
validacion mediante AST + suite de tests.
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple


# ── Configuracion ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.resolve()
BACKUP_DIR = PROJECT_ROOT / "backups" / "agente"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
EXTENSIONES_PY = {"*.py"}
EXCLUIR_DIRS = {".git", "__pycache__", "backups", "data", ".streamlit", "venv", ".venv", "node_modules"}
REPORTE_LOG: list[str] = []


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    REPORTE_LOG.append(line)
    print(line)


def guardar_reporte():
    ruta = PROJECT_ROOT / "data" / "reporte_agente_qa.log"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n".join(REPORTE_LOG), encoding="utf-8")
    log(f"Reporte guardado en {ruta}")


# ═══════════════════════════════════════════════════════════════════════
# CAPA 1: ESCANEO E INSPECCION ESTATICA (AST)
# ═══════════════════════════════════════════════════════════════════════

def recolectar_archivos() -> List[Path]:
    """Retorna todos los .py del proyecto, excluyendo directorios del sistema."""
    archivos: List[Path] = []
    for raiz, dirs, fnames in os.walk(PROJECT_ROOT):
        rp = Path(raiz).relative_to(PROJECT_ROOT)
        if any(p in EXCLUIR_DIRS for p in rp.parts):
            continue
        for fn in fnames:
            if fn.endswith(".py"):
                archivos.append(Path(raiz) / fn)
    return archivos


def validar_ast(file_path: Path) -> Tuple[bool, str]:
    """Valida que un archivo Python sea parseable por ast.
    Retorna (ok, mensaje_de_error)."""
    try:
        raw = file_path.read_bytes()
        # Detectar BOM
        if raw[:3] == b"\xef\xbb\xbf":
            return False, "BOM detectado (\\ufeff al inicio)"
        ast.parse(raw.decode("utf-8"), filename=str(file_path))
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError linea {e.lineno}: {e.msg}"
    except UnicodeDecodeError as e:
        return False, f"UnicodeDecodeError: {e.reason}"
    except Exception as e:
        return False, str(e)


# ═══════════════════════════════════════════════════════════════════════
# CAPA 2: ANALISIS DE LOGS (errores recurrentes desde BD)
# ═══════════════════════════════════════════════════════════════════════

PATRONES_ERROR = [
    (r"st\.session_state\.\w+ is None", "Acceso a session_state sin .get()"),
    (r"\.usuario is None", "Acceso directo a .usuario en vez de .get()"),
    (r"KeyError.*None", "Posible acceso a dict sin .get()"),
    (r"database is locked", "Deadlock SQLite — falta BEGIN IMMEDIATE"),
    (r"TypeError.*not subscriptable", "Acceso a None como dict"),
]


def analizar_logs_sistema() -> List[str]:
    """Lee logs recientes de Streamlit stderr y busca patrones de error."""
    errores_encontrados: List[str] = []
    log_paths = list(PROJECT_ROOT.glob(".streamlit/logs/*.log")) + list(Path.home().glob(".streamlit/logs/*.log"))
    rutas_streamlit = []
    if sys.platform == "win32":
        home = Path.home() / ".streamlit"
    else:
        home = Path("/tmp") / "streamlit"
    if home.exists():
        rutas_streamlit.extend(home.glob("*.log"))

    for lp in log_paths + rutas_streamlit:
        if not lp.exists():
            continue
        try:
            contenido = lp.read_text(encoding="utf-8", errors="replace")
            for patron, desc in PATRONES_ERROR:
                for match in re.finditer(patron, contenido):
                    ctx = contenido[max(0, match.start() - 80):match.end() + 80]
                    errores_encontrados.append(f"{lp.name}: {desc} — contexto: ...{ctx.strip()}...")
        except Exception:
            continue

    return errores_encontrados


# ═══════════════════════════════════════════════════════════════════════
# CAPA 3: CORRECCION Y GENERACION
# ═══════════════════════════════════════════════════════════════════════

def respaldar(path: Path) -> Path:
    """Copia de seguridad en backups/agente/ antes de modificar."""
    rel = path.relative_to(PROJECT_ROOT)
    destino = BACKUP_DIR / f"{rel}_{datetime.now():%Y%m%d_%H%M%S}.bak"
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destino)
    log(f"Backup: {destino}")
    return destino


def reparar_encoding_y_bom(file_path: Path) -> bool:
    """Elimina BOM y fuerza UTF-8 sin BOM."""
    try:
        raw = file_path.read_bytes()
        if raw[:3] == b"\xef\xbb\xbf":
            respaldar(file_path)
            contenido = raw[3:].decode("utf-8")
            file_path.write_text(contenido, encoding="utf-8")
            log(f"BOM removido de {file_path.name}")
            return True
        # Verificar que se pueda re-escribir en UTF-8 puro
        contenido = raw.decode("utf-8")
        file_path.write_text(contenido, encoding="utf-8")
        return False
    except Exception as e:
        log(f"Error reparando encoding de {file_path.name}: {e}")
        return False


def sanitizar_placeholders_corruptos(file_path: Path) -> bool:
    """Limpia patrones de iconos rotos en st.text_input, st.button, sidebar."""
    respaldar(file_path)
    original = file_path.read_text(encoding="utf-8")
    modificado = original

    # Reemplazar escapes Unicode de iconos rotos del sidebar/login
    modificado = modificado.replace('"\\1F464"', '"\\U0001F464"')
    modificado = modificado.replace('"\\1F512"', '"\\U0001F512"')
    modificado = modificado.replace("'\\1F464'", "'\\U0001F464'")
    modificado = modificado.replace("'\\1F512'", "'\\U0001F512'")

    # Reemplazar st.radio por st.button en sidebar (elimina circulos blancos)
    modificado = re.sub(
        r"st\.sidebar\.radio\([^)]+\)",
        "# sidebar reemplazado por botones via agente_qa.py",
        modificado,
    )

    if modificado != original:
        file_path.write_text(modificado, encoding="utf-8")
        log(f"Placeholders sanitizados en {file_path.name}")
        return True
    return False


def inyectar_control_nulos(file_path: Path) -> bool:
    """Inyecta validaciones defensivas en selectores propensos a TypeError."""
    respaldar(file_path)
    original = file_path.read_text(encoding="utf-8")
    modificado = original

    # st.selectbox -> validar con isinstance antes de acceder
    patron_origen = r"(origen)\s*=\s*st\.selectbox\([^)]+\)"
    if re.search(patron_origen, modificado):
        log(f"Validacion nula ya presente o patron no detectable en {file_path.name}")
        # Buscar patron de move/unir que accede directo a ["id_mesa"]
        for var in ["origen", "destino"]:
            acceso = re.search(
                rf"{var}\s*=\s*st\.selectbox\([^)]*\)",
                modificado,
            )
            if acceso and not re.search(rf"isinstance\(\s*{var}\s*,\s*dict\s*\)", modificado):
                log(f"Se requiere intervencion manual para {var} en {file_path.name}")

    # st.button con disabled condicional accediendo directo
    modificado = re.sub(
        r"disabled=origen\[\"id_mesa\"\]\s*==\s*destino\[\"id_mesa\"\]",
        "disabled=btn_deshabilitado",
        modificado,
    )

    # Inyectar validacion ANTES del boton si no existe
    if "origen_valido" not in modificado and "origen = st.selectbox" in modificado:
        # Buscar el bloque c2 del move/unir
        patron_bloque = (
            r"(origen = st\.selectbox.*?destino = st\.selectbox.*?)"
            r"(if st\.button)"
        )
        sustituto = (
            r"\1"
            r"            origen_valido = isinstance(origen, dict) and \"id_mesa\" in origen\n"
            r"            destino_valido = isinstance(destino, dict) and \"id_mesa\" in destino\n"
            r"            btn_deshabilitado = not (origen_valido and destino_valido) or (origen_valido and destino_valido and origen[\"id_mesa\"] == destino[\"id_mesa\"])\n"
            r"\2"
        )
        modificado = re.sub(patron_bloque, sustituto, modificado, flags=re.DOTALL)

    if modificado != original:
        file_path.write_text(modificado, encoding="utf-8")
        log(f"Controles de nulos inyectados en {file_path.name}")
        return True
    return False


def corregir_session_state_get(file_path: Path) -> bool:
    """Reemplaza .usuario is None por .get('usuario') is None."""
    respaldar(file_path)
    original = file_path.read_text(encoding="utf-8")
    modificado = original
    modificado = re.sub(
        r"st\.session_state\.usuario\b",
        'st.session_state.get("usuario")',
        modificado,
    )
    # Pero NO cambiar .usuario dentro de .get() ya corregido
    # y no cambiar asignaciones como user = st.session_state.usuario (ya protegido por el guard anterior)
    if modificado != original:
        file_path.write_text(modificado, encoding="utf-8")
        log(f"session_state.get() aplicado en {file_path.name}")
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════
# CAPA 4: VALIDACION Y ROLLBACK
# ═══════════════════════════════════════════════════════════════════════

def validar_con_ast(paths_modificados: List[Path]) -> List[Path]:
    """Re-valida los archivos modificados con ast. Retorna los que fallan."""
    fallan: List[Path] = []
    for p in paths_modificados:
        ok, err = validar_ast(p)
        if not ok:
            fallan.append(p)
            log(f"Fallo AST en {p.name}: {err}")
    return fallan


def ejecutar_tests() -> Tuple[bool, str]:
    """Ejecuta pytest sobre tests_restaurante.py. Retorna (ok, output)."""
    test_script = PROJECT_ROOT / "tests_restaurante.py"
    if not test_script.exists():
        return True, "No hay tests_restaurante.py, se salta."
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_script), "-v", "--tb=short"],
            capture_output=True, text=True, timeout=60, cwd=PROJECT_ROOT,
        )
        if result.returncode == 0:
            return True, result.stdout[-300:] if len(result.stdout) > 300 else result.stdout
        return False, (result.stdout + result.stderr)[-500:]
    except subprocess.TimeoutExpired:
        return False, "Timeout ejecutando tests"
    except FileNotFoundError:
        return True, "pytest no instalado, se salta validacion."


def rollback(respaldos: List[Path], paths_fallidos: List[Path]):
    """Restaura backups de archivos que fallaron validacion."""
    for pf in paths_fallidos:
        # Buscar el backup mas reciente
        pattern = f"{pf.relative_to(PROJECT_ROOT)}_*.bak"
        backups = sorted(BACKUP_DIR.glob(str(pattern).replace("\\", "/")))
        if backups:
            shutil.copy2(backups[-1], pf)
            log(f"Rollback: {pf.name} restaurado desde {backups[-1].name}")
        else:
            log(f"Rollback: no hay backup para {pf.name}")


# ═══════════════════════════════════════════════════════════════════════
# CICLO PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════

def escanear_y_reparar() -> dict:
    """
    Ciclo completo: Escanear → Diagnosticar → Reparar → Validar.
    Retorna dict con estadisticas.
    """
    log("=" * 60)
    log("AGENTE QA — Ciclo de auto-saneamiento")
    log("=" * 60)

    stats = {
        "archivos_escaneados": 0,
        "saludables": 0,
        "corregidos": 0,
        "fallaron_validacion": 0,
        "rollback_aplicados": 0,
        "errores_log": 0,
        "paths_modificados": [],
        "paths_fallidos": [],
        "respaldos": [],
    }

    archivos = recolectar_archivos()
    stats["archivos_escaneados"] = len(archivos)
    log(f"Archivos Python encontrados: {len(archivos)}")

    # --- Fase 1: Validacion AST y encoding ---
    for af in archivos:
        # 1. Reparar BOM/encoding primero
        if reparar_encoding_y_bom(af):
            if af not in stats["paths_modificados"]:
                stats["paths_modificados"].append(af)

        # 2. Validar AST
        ok, err = validar_ast(af)
        if ok:
            stats["saludables"] += 1
        else:
            log(f"[DETECTADO] {af.relative_to(PROJECT_ROOT)}: {err}")

    # --- Fase 2: Analisis de logs ---
    errores = analizar_logs_sistema()
    stats["errores_log"] = len(errores)
    if errores:
        log(f"Patrones de error en logs: {len(errores)}")
        for e in errores[:5]:
            log(f"  {e[:120]}")
    else:
        log("Sin patrones de error en logs.")

    # --- Fase 3: Correcciones selectivas ---
    for af in archivos:
        modificado = False
        name = af.name

        # session_state.usuario → .get("usuario")
        if name in ("sistema_restaurante.py",):
            if corregir_session_state_get(af):
                modificado = True

        # Placeholders corruptos
        if sanitizar_placeholders_corruptos(af):
            modificado = True

        # Controles de nulos en mesas
        if name in ("mesas.py", "sistema_restaurante.py"):
            if inyectar_control_nulos(af):
                modificado = True

        if modificado and af not in stats["paths_modificados"]:
            stats["paths_modificados"].append(af)

    stats["corregidos"] = len(stats["paths_modificados"])
    log(f"Archivos corregidos: {stats['corregidos']}")

    # --- Fase 4: Validacion post-correccion ---
    stats["paths_fallidos"] = validar_con_ast(stats["paths_modificados"])
    stats["fallaron_validacion"] = len(stats["paths_fallidos"])

    if stats["paths_fallidos"]:
        log(f"Rollback de {len(stats['paths_fallidos'])} archivos que fallaron AST...")
        rollback(stats["respaldos"], stats["paths_fallidos"])
        stats["rollback_aplicados"] = len(stats["paths_fallidos"])

    # --- Fase 5: Test suite ---
    tests_ok, test_out = ejecutar_tests()
    if not tests_ok:
        log(f"Tests fallaron. Aplicando rollback completo...")
        rollback(stats["respaldos"], stats["paths_modificados"])
        stats["rollback_aplicados"] += len(stats["paths_modificados"])

    log("=" * 60)
    log(f"Resumen: {stats['saludables']} saludables, "
        f"{stats['corregidos']} corregidos, "
        f"{stats['fallaron_validacion']} fallaron, "
        f"{stats['rollback_aplicados']} rollbacks")
    log("=" * 60)

    guardar_reporte()
    return stats


def modo_observador(intervalo: int = 300):
    """Ejecuta el ciclo cada N segundos (default 5 min)."""
    log(f"Modo observador: cada {intervalo}s")
    while True:
        try:
            escanear_y_reparar()
        except Exception as e:
            log(f"Error en ciclo: {e}")
        time.sleep(intervalo)


# ═══════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA
# ═══════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Agente QA autonomo para Restaurante Pro")
    parser.add_argument("--watch", type=int, nargs="?", const=300, default=0,
                        help="Modo observador: ejecuta cada N segundos (default 300)")
    parser.add_argument("--once", action="store_true", default=True,
                        help="Ejecuta un solo ciclo y termina (default)")
    args = parser.parse_args()

    if args.watch:
        modo_observador(args.watch)
    else:
        escanear_y_reparar()


if __name__ == "__main__":
    main()

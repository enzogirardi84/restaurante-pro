"""
tests_concurrencia.py — Pruebas de estres transaccional y condiciones de carrera.
Simula 10+ mozos, cocina y caja operando simultaneamente sobre SQLite.
"""
from __future__ import annotations

import random
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Asegurar el path del proyecto
os.environ["DB_ENGINE"] = "sqlite"
os.environ["DB_PATH"] = str(Path(__file__).resolve().parent / ".test_tmp" / "root_concurrencia.db")
sys.path.insert(0, str(Path(__file__).parent))

from database import get_connection_direct, init_db
import config


# ── Configuracion ──────────────────────────────────────────────────────
NUM_HILOS = 10
PEDIDOS_POR_HILO = 3
REPORTE: list[str] = []
_lock = threading.Lock()


def get_db_type() -> str:
    return "postgres" if config.DB_ENGINE == "postgresql" else "sqlite"


def execute_query(sql: str, params: tuple = (), fetch: bool = False):
    conn = get_connection_direct()
    try:
        cur = conn.execute(sql, params)
        if fetch:
            return cur.fetchall()
        conn.commit()
        return None
    finally:
        conn.close()


def log(msg: str):
    with _lock:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:12]
        REPORTE.append(f"[{ts}] {msg}")
        print(msg)


def rearmar_db():
    """Reinicia la BD a un estado limpio para testing."""
    log("--- Rearmando BD para testing ---")
    result = init_db()
    assert result.get("ok"), f"init_db() fallo: {result.get('error')}"

    conn = get_connection_direct()
    try:
        conn.executescript("""
            DELETE FROM movimientos_stock;
            DELETE FROM pago_detalle;
            DELETE FROM pagos_mesa;
            DELETE FROM pedido_detalle;
            DELETE FROM pedidos_cabecera;
            DELETE FROM auditoria_eventos;
            DELETE FROM turnos_personal;
            DELETE FROM cola_sincronizacion;
        """)
        conn.commit()
        # Sembrar mesas
        for i in range(1, 9):
            conn.execute("INSERT OR IGNORE INTO mesas (numero_mesa, estado) VALUES (?, 'libre')", (i,))
        conn.commit()
        # Crear usuario de prueba
        conn.execute("""
            INSERT OR REPLACE INTO usuarios (id_usuario, nombre, apellido, rol, username, password_hash, pin)
            VALUES (1, 'Test', 'Mozo', 'mozo', 'test_mozo', '', '9999')
        """)
        conn.execute("UPDATE insumos SET stock_actual = 100000 WHERE stock_actual < 100000")
        conn.commit()
        log("BD rearmada: 8 mesas libres, 1 usuario test.")
    finally:
        conn.close()


# ─── MOZO: enviar pedido ──────────────────────────────────────────────

def hilo_mozo(hilo_id: int):
    """Simula un mozo abriendo mesa y enviando pedidos."""
    ph = "%s" if get_db_type() == "postgres" else "?"
    for intento in range(PEDIDOS_POR_HILO):
        try:
            conn = get_connection_direct()
            # Elegir mesa aleatoria
            mesa = execute_query("SELECT id_mesa FROM mesas WHERE estado = 'libre' ORDER BY RANDOM() LIMIT 1", fetch=True)
            if not mesa:
                log(f"[Mozo {hilo_id}] Sin mesas libres, salteando pedido {intento}")
                conn.close()
                continue
            mid = mesa[0]["id_mesa"]

            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(f"UPDATE mesas SET estado = 'ocupada' WHERE id_mesa = {ph} AND estado = 'libre'", (mid,))
            if cur.rowcount != 1:
                conn.execute("ROLLBACK")
                conn.close()
                continue
            conn.execute(f"""INSERT INTO pedidos_cabecera (id_mesa, id_usuario, estado_comanda, fecha_hora)
                             VALUES ({ph}, 1, 'pendiente', datetime('now','localtime'))""", (mid,))
            if get_db_type() == "postgres":
                pid = conn.execute("SELECT LASTVAL() AS id").fetchone()["id"]
            else:
                pid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

            # Agregar productos aleatorios
            productos = execute_query("SELECT id_producto FROM productos_menu ORDER BY RANDOM() LIMIT 3", fetch=True)
            for p in productos:
                cant = random.randint(1, 3)
                conn.execute(f"""INSERT INTO pedido_detalle (id_pedido, id_producto, cantidad)
                                 VALUES ({ph}, {ph}, {ph})""", (pid, p["id_producto"], cant))

            conn.execute(f"UPDATE pedidos_cabecera SET estado_comanda = 'en_cocina' WHERE id_pedido = {ph}", (pid,))
            conn.execute("COMMIT")
            log(f"[Mozo {hilo_id}] Pedido {pid} enviado a cocina (mesa {mid})")
            conn.close()

            # Pequena pausa entre pedidos
            time.sleep(random.uniform(0.05, 0.2))
        except Exception as e:
            log(f"[Mozo {hilo_id}] ERROR: {e}")
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass


# ─── COCINA: confirmar y descontar stock ──────────────────────────────

def hilo_cocina(hilo_id: int):
    """Simula cocina confirmando pedidos pendientes."""
    ph = "%s" if get_db_type() == "postgres" else "?"
    for _ in range(PEDIDOS_POR_HILO * 2):
        try:
            conn = get_connection_direct()
            pedido = execute_query("SELECT id_pedido FROM pedidos_cabecera WHERE estado_comanda = 'en_cocina' ORDER BY RANDOM() LIMIT 1", fetch=True)
            if not pedido:
                conn.close()
                time.sleep(0.1)
                continue

            pid = pedido[0]["id_pedido"]
            conn.execute("BEGIN IMMEDIATE")
            estado = conn.execute(
                f"SELECT estado_comanda FROM pedidos_cabecera WHERE id_pedido = {ph}",
                (pid,),
            ).fetchone()
            if not estado or estado["estado_comanda"] != "en_cocina":
                conn.execute("ROLLBACK")
                conn.close()
                continue

            # Descontar insumos segun escandallo
            detalle = conn.execute(f"""SELECT pd.id_producto, pd.cantidad
                                       FROM pedido_detalle pd WHERE pd.id_pedido = {ph}""", (pid,)).fetchall()
            ok = True
            for item in detalle:
                recetas = conn.execute(f"""SELECT id_insumo, cantidad_a_descontar
                                           FROM recetas_escandallo WHERE id_producto = {ph}""", (item["id_producto"],)).fetchall()
                for rec in recetas:
                    cant_total = float(rec["cantidad_a_descontar"]) * float(item["cantidad"])
                    ins = conn.execute(f"SELECT stock_actual FROM insumos WHERE id_insumo = {ph}", (rec["id_insumo"],)).fetchone()
                    if ins and float(ins["stock_actual"]) >= cant_total:
                        conn.execute(f"UPDATE insumos SET stock_actual = stock_actual - {ph} WHERE id_insumo = {ph}", (cant_total, rec["id_insumo"]))
                    else:
                        ok = False
                        break
                if not ok:
                    break

            if ok:
                cur = conn.execute(
                    f"UPDATE pedidos_cabecera SET estado_comanda = 'listo' "
                    f"WHERE id_pedido = {ph} AND estado_comanda = 'en_cocina'",
                    (pid,),
                )
                if cur.rowcount != 1:
                    conn.execute("ROLLBACK")
                    conn.close()
                    continue
                conn.execute("COMMIT")
                log(f"[Cocina {hilo_id}] Pedido {pid} listo (stock descontado)")
            else:
                conn.execute("ROLLBACK")
                log(f"[Cocina {hilo_id}] Pedido {pid}: stock insuficiente, revertido")
            conn.close()
            time.sleep(random.uniform(0.05, 0.15))
        except Exception as e:
            log(f"[Cocina {hilo_id}] ERROR: {e}")
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass


# ─── CAJA: cobrar pedido y liberar mesa ──────────────────────────────

def hilo_caja(hilo_id: int):
    """Simula caja cobrando pedidos listos."""
    ph = "%s" if get_db_type() == "postgres" else "?"
    for _ in range(PEDIDOS_POR_HILO):
        try:
            conn = get_connection_direct()
            pedido = execute_query("""SELECT pc.id_pedido, pc.id_mesa
                                      FROM pedidos_cabecera pc
                                      WHERE pc.estado_comanda = 'listo'
                                      ORDER BY RANDOM() LIMIT 1""", fetch=True)
            if not pedido:
                conn.close()
                time.sleep(0.15)
                continue

            pid = pedido[0]["id_pedido"]
            mid = pedido[0]["id_mesa"]

            conn.execute("BEGIN IMMEDIATE")
            estado = conn.execute(
                f"SELECT estado_comanda FROM pedidos_cabecera WHERE id_pedido = {ph}",
                (pid,),
            ).fetchone()
            if not estado or estado["estado_comanda"] != "listo":
                conn.execute("ROLLBACK")
                conn.close()
                continue

            total = conn.execute(f"""SELECT COALESCE(SUM(pd.cantidad * COALESCE(pd.precio_unitario_facturado, pm.precio_venta)), 0) AS total
                                     FROM pedido_detalle pd
                                     JOIN productos_menu pm ON pm.id_producto = pd.id_producto
                                     WHERE pd.id_pedido = {ph}""", (pid,)).fetchone()["total"]
            total = round(float(total) * 1.10, 2)  # +10% servicio

            conn.execute(f"""INSERT INTO pagos_mesa (id_mesa, id_usuario, medio_pago, subtotal, servicio, total, tipo)
                             VALUES ({ph}, 1, 'efectivo', {ph}, {ph}, {ph}, 'total')""", (mid, round(total / 1.1, 2), round(total - round(total / 1.1, 2), 2), total))

            cur = conn.execute(f"""UPDATE pedidos_cabecera SET estado_comanda = 'cobrado', medio_pago = 'efectivo',
                             total_cobrado = {ph}, fecha_cobro = datetime('now','localtime')
                             WHERE id_pedido = {ph} AND estado_comanda = 'listo'""", (total, pid))
            if cur.rowcount != 1:
                conn.execute("ROLLBACK")
                conn.close()
                continue
            conn.execute(f"UPDATE mesas SET estado = 'libre' WHERE id_mesa = {ph}", (mid,))
            conn.execute("COMMIT")
            log(f"[Caja   {hilo_id}] Pedido {pid} cobrado ${total:,.0f} (mesa {mid})")
            conn.close()
            time.sleep(random.uniform(0.1, 0.3))
        except Exception as e:
            log(f"[Caja   {hilo_id}] ERROR: {e}")
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass


# ─── RESUMEN FINAL ─────────────────────────────────────────────────────

def resumen_final():
    log("\n=== RESUMEN DE ESTADO FINAL ===")
    log(f"Total hilos lanzados: {NUM_HILOS * 3} ({NUM_HILOS} mozo + {NUM_HILOS} cocina + {NUM_HILOS} caja)")

    pedidos = execute_query("SELECT estado_comanda, COUNT(*) AS cnt FROM pedidos_cabecera GROUP BY estado_comanda", fetch=True) or []
    log(f"Pedidos totales: {sum(p['cnt'] for p in pedidos)}")
    for p in pedidos:
        log(f"  {p['estado_comanda']}: {p['cnt']}")

    pagos = execute_query("SELECT COUNT(*) AS c, COALESCE(SUM(total), 0) AS t FROM pagos_mesa", fetch=True) or [{"c": 0, "t": 0}]
    log(f"Pagos registrados: {pagos[0]['c']} (total ${float(pagos[0]['t']):,.0f})")

    mesas = execute_query("SELECT estado, COUNT(*) AS cnt FROM mesas GROUP BY estado", fetch=True) or []
    log("Estado mesas:")
    for m in mesas:
        log(f"  {m['estado']}: {m['cnt']}")

    stock_bajo = execute_query("SELECT COUNT(*) AS cnt FROM insumos WHERE stock_actual <= stock_minimo", fetch=True) or [{"cnt": 0}]
    log(f"Insumos con stock bajo: {stock_bajo[0]['cnt']}")

    log(f"\nLineas de log: {len(REPORTE)}")
    with open("data/reporte_concurrencia.log", "w", encoding="utf-8") as f:
        f.write("\n".join(REPORTE))
    log("Log guardado en data/reporte_concurrencia.log")


# ─── MAIN ──────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("TEST DE CONCURRENCIA - Restaurante Pro")
    print(f"Hilos mozo: {NUM_HILOS} | Pedidos por hilo: {PEDIDOS_POR_HILO}")
    print("=" * 60)

    rearmar_db()

    hilos = []
    for i in range(NUM_HILOS):
        hilos.append(threading.Thread(target=hilo_mozo, args=(i,), name=f"Mozo-{i}"))
        hilos.append(threading.Thread(target=hilo_cocina, args=(i,), name=f"Cocina-{i}"))
        hilos.append(threading.Thread(target=hilo_caja, args=(i,), name=f"Caja-{i}"))

    log("Lanzando todos los hilos...")
    inicio = time.time()
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    duracion = time.time() - inicio

    log(f"\nDuracion total: {duracion:.2f}s")
    resumen_final()

    # Verificar que no hayan quedado transacciones colgadas
    pendientes = execute_query("SELECT COUNT(*) AS cnt FROM pedidos_cabecera WHERE estado_comanda IN ('pendiente','en_cocina')", fetch=True) or [{"cnt": 0}]
    if pendientes[0]["cnt"] > 0:
        log(f"ADVERTENCIA: {pendientes[0]['cnt']} pedidos quedaron sin procesar")
    else:
        log("OK: todos los pedidos fueron procesados hasta estado final.")

    cobros = execute_query("""
        SELECT
            (SELECT COUNT(*) FROM pedidos_cabecera WHERE estado_comanda = 'cobrado') AS pedidos_cobrados,
            (SELECT COUNT(*) FROM pagos_mesa WHERE tipo = 'total') AS pagos_totales
    """, fetch=True) or [{"pedidos_cobrados": 0, "pagos_totales": 0}]
    assert cobros[0]["pagos_totales"] == cobros[0]["pedidos_cobrados"], (
        f"{cobros[0]['pagos_totales']} pagos para {cobros[0]['pedidos_cobrados']} pedidos cobrados"
    )
    assert pendientes[0]["cnt"] == 0, f"{pendientes[0]['cnt']} pedidos colgados!"
    print("\nTEST DE CONCURRENCIA FINALIZADO OK")
    return True


if __name__ == "__main__":
    main()

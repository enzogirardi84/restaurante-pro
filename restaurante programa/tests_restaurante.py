from pathlib import Path
import ast
from decimal import Decimal
import os
import tempfile

os.environ["DB_ENGINE"] = "sqlite"

import database
import cloud_config
from access_utils import (
    access_password_error,
    normalize_access_username,
    recovery_system_access,
    validate_default_system_access,
)
from cash_utils import (
    can_charge_table,
    cash_change_due,
    cash_close_requires_note,
    cash_difference,
    cash_difference_label,
    cash_expected,
)
from cloud_config import masked_status_table, normalize_supabase_url
from kitchen_utils import kitchen_auto_refresh_seconds
from order_utils import MAX_ORDER_NOTE_LENGTH, normalize_order_cart
from permission_utils import ADMIN_MODULES, modules_for_role
from security import hash_password, is_password_hash, verify_password


TEST_TMP_ROOT = Path(os.environ.get("RESTAURANTE_TEST_TMP", Path(__file__).resolve().parents[1] / ".test_tmp"))


def fresh_db():
    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=TEST_TMP_ROOT))
    database.DB_DIR = tmp
    database.DB_PATH = tmp / "restaurante.db"
    database.init_db()
    database.seed_pedidos_demo()
    return tmp


def test_no_duplicate_public_functions():
    source = Path("sistema_restaurante.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            names[node.name] = names.get(node.name, 0) + 1
    duplicates = sorted(name for name, count in names.items() if count > 1)
    assert duplicates == []


def test_normalize_order_cart_merges_and_cleans_items():
    cart = {
        1: {"id_producto": "1", "cantidad": "2", "observaciones": "  Sin   sal  "},
        2: {"id_producto": 1, "cantidad": 1, "observaciones": "Sin cebolla"},
        3: {"id_producto": 2, "cantidad": 0, "observaciones": "No va"},
        4: {"id_producto": 3, "cantidad": "bad"},
        5: {"id_producto": 4, "cantidad": 1, "observaciones": "x" * 400},
    }
    items = normalize_order_cart(cart)
    by_product = {item["id_producto"]: item for item in items}
    assert by_product[1]["cantidad"] == 3
    assert by_product[1]["observaciones"] == "Sin sal; Sin cebolla"
    assert 2 not in by_product
    assert 3 not in by_product
    assert len(by_product[4]["observaciones"]) == MAX_ORDER_NOTE_LENGTH


def test_default_system_accesses_work():
    enzo_password = "".join(["3710", "8100"])
    assert recovery_system_access(" AnaHiGilardi ", "1999") == "anahigilardi"
    assert recovery_system_access(" AnaHiGilardi ", " 1999 ") == "anahigilardi"
    assert recovery_system_access("anahigilardi", "mala") is None
    assert validate_default_system_access("anahigilardi", "1999") == "anahigilardi"
    assert validate_default_system_access(" AnaHiGilardi ", "1999") == "anahigilardi"
    assert validate_default_system_access("enzogirardi", enzo_password) == "enzogirardi"
    assert validate_default_system_access("enzogirardi", "mala") is None
    assert normalize_access_username("  AnaHiGilardi  ") == "anahigilardi"
    assert access_password_error("123", minimum=4)
    assert access_password_error("1234", minimum=4) is None


def test_system_access_seed_does_not_overwrite_custom_password_or_active_state():
    fresh_db()
    custom_hash = hash_password("clave-nueva-123")
    conn = database.get_connection()
    try:
        conn.execute(
            "UPDATE accesos_sistema SET password_hash = ?, activo = 0 WHERE usuario = ?",
            (custom_hash, "anahigilardi"),
        )
        conn.commit()
    finally:
        conn.close()

    database.init_db()
    conn = database.get_connection()
    try:
        stored = conn.execute(
            "SELECT password_hash, activo FROM accesos_sistema WHERE usuario = ?",
            ("anahigilardi",),
        ).fetchone()
        assert verify_password("clave-nueva-123", stored["password_hash"])
        assert not verify_password("1999", stored["password_hash"])
        assert int(stored["activo"]) == 0
    finally:
        conn.close()


def test_kitchen_auto_refresh_pauses_during_manual_order():
    assert kitchen_auto_refresh_seconds(False) == 8
    assert kitchen_auto_refresh_seconds(False, 12) == 12
    assert kitchen_auto_refresh_seconds(True) == 0


def test_cash_charge_requires_enough_cash_only_for_cash_payments():
    assert cash_change_due(1000, 1500, "Efectivo") == 500
    assert cash_change_due(1000, 500, "Efectivo") == 0
    assert cash_change_due(1000, 500, "Tarjeta") == 0
    assert not can_charge_table(1000, "Efectivo", 999)
    assert can_charge_table(1000, "Efectivo", 1000)
    assert can_charge_table(1000, "Tarjeta", 0)
    assert not can_charge_table(0, "Tarjeta", 0)
    expected = cash_expected(10000, 50000, 7000)
    assert expected == 53000
    assert cash_difference(52000, expected) == -1000
    assert cash_difference_label(-1000) == "faltante"
    assert cash_difference_label(1000) == "sobrante"
    assert cash_difference_label(0) == "exacta"
    assert cash_close_requires_note(-1)
    assert not cash_close_requires_note(0)


def test_money_formats_cloud_numeric_values():
    from sistema_restaurante import money

    assert money(None) == "$0"
    assert money(Decimal("1234.56")) == "$1.235"
    assert money("1234.56") == "$1.235"
    assert money("1.234,56") == "$1.235"
    assert money("no-numero") == "$0"


class _FakeSupabaseResponse:
    def __init__(self, data):
        self.data = data


class _FakeSupabaseTable:
    def __init__(self, client, name):
        self.client = client
        self.name = name

    def select(self, *_args, **_kwargs):
        return self

    def in_(self, column, values):
        self.client.calls.append((self.name, "in", column, tuple(values)))
        return self

    def gte(self, column, value):
        self.client.calls.append((self.name, "gte", column, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        return _FakeSupabaseResponse(self.client.data.get(self.name, []))


class _FakeSupabase:
    def __init__(self):
        self.calls = []
        self.data = {
            "pedidos_cabecera": [
                {
                    "id_pedido": 101,
                    "fecha_hora": "2026-06-11 10:00:00",
                    "estado_comanda": "pendiente",
                    "id_mesa": 1,
                    "id_usuario": 1,
                },
                {
                    "id_pedido": 102,
                    "fecha_hora": "2026-06-11 10:05:00",
                    "estado_comanda": "pendiente",
                    "id_mesa": 2,
                    "id_usuario": 1,
                },
            ],
            "mesas": [
                {"id_mesa": 1, "numero_mesa": 1},
                {"id_mesa": 2, "numero_mesa": 2},
            ],
            "usuarios": [{"id_usuario": 1, "nombre": "Carlos", "apellido": "Garcia"}],
            "pedido_detalle": [
                {
                    "id_pedido": 101,
                    "id_producto": 7,
                    "cantidad": 3,
                    "cantidad_anulada": 1,
                    "observaciones": "sin sal",
                }
            ],
            "productos_menu": [{"id_producto": 7, "nombre": "Milanesa", "categoria": "cocina"}],
        }

    def table(self, name):
        return _FakeSupabaseTable(self, name)


def test_supabase_kitchen_orders_are_visible_and_filtered(monkeypatch):
    import sistema_restaurante as sr

    fake = _FakeSupabase()
    monkeypatch.setattr(sr, "_get_supabase", lambda: fake)
    monkeypatch.setattr(sr, "active_order_cutoff", lambda: "2026-06-11 00:00:00")

    pedidos = sr._pedidos_desde_supabase(("pendiente", "en_cocina", "listo"))

    assert len(pedidos) == 2
    assert pedidos[0]["items"][0]["nombre"] == "Milanesa"
    assert pedidos[0]["items"][0]["cantidad"] == 2
    assert pedidos[1]["items"][0]["nombre"] == "Pedido sin detalle cargado"
    assert ("pedidos_cabecera", "gte", "fecha_hora", "2026-06-11 00:00:00") in fake.calls


def test_order_sync_skips_rest_when_postgres_is_active(monkeypatch):
    import sistema_restaurante as sr

    monkeypatch.setattr(sr, "using_postgres", lambda: True)
    monkeypatch.setattr(sr, "_get_supabase", lambda: (_ for _ in ()).throw(AssertionError("no REST sync")))

    sr._sync_pedido_a_supabase(1, 1, 1, [{"id_producto": 1, "cantidad": 1}])


def test_role_permissions_are_restricted_and_terminal_locked():
    assert modules_for_role("mozo") == ["Mozo"]
    assert modules_for_role("cocina") == ["Cocina"]
    assert modules_for_role("caja") == ["Caja", "Reportes"]
    assert modules_for_role("administrador") == ADMIN_MODULES
    assert modules_for_role("dueno") == ADMIN_MODULES
    assert modules_for_role("mozo", terminal_lock="Cocina") == ["Cocina"]
    assert modules_for_role("rol_desconocido") == []


def test_schema_core():
    fresh_db()
    conn = database.get_connection()
    try:
        pedido_cols = {r["name"] for r in conn.execute("PRAGMA table_info(pedido_detalle)")}
        assert "cantidad_cobrada" in pedido_cols
        assert "cantidad_anulada" in pedido_cols
        assert conn.execute("SELECT COUNT(*) AS c FROM pagos_mesa").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM auditoria_eventos").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM proveedores").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM movimientos_stock").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM sistema_estado").fetchone()["c"] >= 2
        usuario_cols = {r["name"] for r in conn.execute("PRAGMA table_info(usuarios)")}
        assert "mail" in usuario_cols
        assert "contrasena" in usuario_cols
        producto_pk = {
            r["name"]: int(r["pk"] or 0)
            for r in conn.execute("PRAGMA table_info(productos_menu)")
        }
        assert producto_pk["id_producto"] == 1
        admin_access = conn.execute(
            "SELECT mail, contrasena FROM usuarios WHERE mail = ?",
            ("anahigilardi",),
        ).fetchone()
        assert admin_access
        assert verify_password("1999", admin_access["contrasena"])
        caja_cols = {r["name"] for r in conn.execute("PRAGMA table_info(cajas_diarias)")}
        assert "diferencia_cierre" in caja_cols
        assert "observacion_cierre" in caja_cols
        usuario = conn.execute(
            "SELECT valor FROM configuracion_sistema WHERE clave = 'usuario_sistema'"
        ).fetchone()["valor"]
        password = conn.execute(
            "SELECT valor FROM configuracion_sistema WHERE clave = 'password_sistema'"
        ).fetchone()["valor"]
        assert usuario == "anahigilardi"
        assert is_password_hash(password)
        assert verify_password("1999", password)
        accesos = {
            row["usuario"]: row["password_hash"]
            for row in conn.execute("SELECT usuario, password_hash FROM accesos_sistema WHERE activo = 1").fetchall()
        }
        assert accesos["anahigilardi"] == database.ANAHI_PASSWORD_HASH
        assert accesos["enzogirardi"] == database.ENZO_PASSWORD_HASH
        assert all(is_password_hash(value) for value in accesos.values())
        indices = {row["name"] for row in conn.execute("PRAGMA index_list(pedidos_cabecera)").fetchall()}
        assert "idx_pedidos_estado_fecha" in indices
        assert "idx_pedidos_mesa_estado" in indices
        detalle_indices = {row["name"] for row in conn.execute("PRAGMA index_list(pedido_detalle)").fetchall()}
        assert "idx_detalle_pedido" in detalle_indices
        pago_indices = {row["name"] for row in conn.execute("PRAGMA index_list(pagos_mesa)").fetchall()}
        assert "idx_pagos_fecha" in pago_indices
    finally:
        conn.close()


def test_supabase_schema_migrates_existing_tables_before_seed():
    schema = (Path(__file__).resolve().parent / "supabase" / "schema.sql").read_text(encoding="utf-8").lower()
    assert schema.index("add column if not exists rol text") < schema.index("insert into accesos_sistema")
    assert schema.index("add column if not exists id_usuario") < schema.index("references usuarios(id_usuario)")
    assert schema.index("add column if not exists pin text") < schema.index("insert into usuarios")
    assert schema.index("add column if not exists activo integer") < schema.index("insert into usuarios")


def test_login_accepts_usuario_mail_and_contrasena():
    fresh_db()
    from sistema_restaurante import authenticate_system_access

    assert authenticate_system_access("anahigilardi", "1999") == "anahigilardi"


def test_default_login_works_before_database_lookup():
    import sistema_restaurante

    original_ensure = sistema_restaurante.ensure_system_access_schema
    try:
        sistema_restaurante.ensure_system_access_schema = lambda: (_ for _ in ()).throw(RuntimeError("db offline"))
        assert sistema_restaurante.authenticate_system_access("anahigilardi", "1999") == "anahigilardi"
    finally:
        sistema_restaurante.ensure_system_access_schema = original_ensure


def test_kds_flow_to_ready():
    fresh_db()
    conn = database.get_connection()
    try:
        pedido = conn.execute(
            "SELECT id_pedido FROM pedidos_cabecera WHERE estado_comanda = 'pendiente' LIMIT 1"
        ).fetchone()["id_pedido"]
    finally:
        conn.close()

    assert database.avanzar_estado(pedido, "pendiente")["ok"]
    assert database.avanzar_estado(pedido, "en_cocina")["ok"]

    conn = database.get_connection()
    try:
        estado = conn.execute(
            "SELECT estado_comanda FROM pedidos_cabecera WHERE id_pedido = ?",
            (pedido,),
        ).fetchone()["estado_comanda"]
        assert estado == "listo"
        movimientos = conn.execute(
            "SELECT COUNT(*) AS c FROM movimientos_stock WHERE tipo_movimiento = 'descuento_receta'"
        ).fetchone()["c"]
        assert movimientos > 0
    finally:
        conn.close()


def test_payments_and_cancellations_schema_flow():
    fresh_db()
    conn = database.get_connection()
    try:
        conn.execute("""
            INSERT INTO pedidos_cabecera (id_mesa, id_usuario, estado_comanda)
            VALUES (?, ?, 'entregado')
        """, (1, 1))
        pedido = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("""
            INSERT INTO pedido_detalle
                (id_pedido, id_producto, cantidad, precio_unitario_facturado, cantidad_cobrada, cantidad_anulada)
            VALUES (?, ?, ?, ?, 0, 0)
        """, (pedido, 1, 3, 8500))
        detalle = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("""
            INSERT INTO pagos_mesa (id_mesa, id_usuario, medio_pago, subtotal, servicio, total, tipo)
            VALUES (?, ?, 'Efectivo', 8500, 850, 9350, 'parcial')
        """, (1, 1))
        pago = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("UPDATE pedido_detalle SET cantidad_cobrada = 1 WHERE id_detalle = ?", (detalle,))
        conn.execute(
            "INSERT INTO pago_detalle (id_pago, id_detalle, cantidad, precio_unitario) VALUES (?, ?, ?, ?)",
            (pago, detalle, 1, 8500),
        )
        conn.execute("""
            UPDATE pedido_detalle
               SET cantidad_anulada = 1,
                   motivo_anulacion = 'Prueba'
             WHERE id_detalle = ?
        """, (detalle,))
        conn.commit()

        row = conn.execute("""
            SELECT cantidad, cantidad_cobrada, cantidad_anulada,
                   (cantidad - cantidad_cobrada - cantidad_anulada) AS pendiente
            FROM pedido_detalle
            WHERE id_detalle = ?
        """, (detalle,)).fetchone()
        assert row["pendiente"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM pago_detalle").fetchone()["c"] == 1
    finally:
        conn.close()


def test_manual_table_release_closes_active_orders():
    fresh_db()
    from components.helpers import liberar_mesa_sin_cobro

    conn = database.get_connection()
    try:
        pedido = conn.execute("""
            SELECT id_pedido, id_mesa
            FROM pedidos_cabecera
            WHERE estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
            LIMIT 1
        """).fetchone()
        assert pedido
        id_mesa = int(pedido["id_mesa"])
        conn.execute("UPDATE mesas SET estado = 'esperando_cuenta' WHERE id_mesa = ?", (id_mesa,))
        conn.commit()
    finally:
        conn.close()

    res = liberar_mesa_sin_cobro(id_mesa, "test liberacion")
    assert res["ok"]
    assert res["pedidos_cerrados"] >= 1

    conn = database.get_connection()
    try:
        mesa = conn.execute("SELECT estado FROM mesas WHERE id_mesa = ?", (id_mesa,)).fetchone()
        assert mesa["estado"] == "libre"
        activos = conn.execute("""
            SELECT COUNT(*) AS c
            FROM pedidos_cabecera
            WHERE id_mesa = ?
              AND estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
        """, (id_mesa,)).fetchone()["c"]
        assert activos == 0
    finally:
        conn.close()


def test_stale_active_orders_close_and_release_table():
    fresh_db()
    conn = database.get_connection()
    try:
        user = conn.execute("SELECT id_usuario FROM usuarios ORDER BY id_usuario LIMIT 1").fetchone()
        product = conn.execute("SELECT id_producto FROM productos_menu ORDER BY id_producto LIMIT 1").fetchone()
        cur = conn.execute("""
            INSERT INTO pedidos_cabecera (id_mesa, id_usuario, fecha_hora, estado_comanda)
            VALUES (?, ?, ?, 'listo')
        """, (5, user["id_usuario"], "2000-01-01 12:00:00"))
        pedido_id = cur.lastrowid
        conn.execute("""
            INSERT INTO pedido_detalle (id_pedido, id_producto, cantidad, observaciones)
            VALUES (?, ?, 2, 'pedido viejo')
        """, (pedido_id, product["id_producto"]))
        conn.execute("UPDATE mesas SET estado = 'ocupada' WHERE id_mesa = 5")
        conn.commit()
    finally:
        conn.close()

    res = database.cerrar_pedidos_vencidos(hours=18)
    assert res["ok"]
    assert res["cerrados"] >= 1

    conn = database.get_connection()
    try:
        pedido = conn.execute(
            "SELECT estado_comanda, medio_pago, total_cobrado FROM pedidos_cabecera WHERE id_pedido = ?",
            (pedido_id,),
        ).fetchone()
        mesa = conn.execute("SELECT estado FROM mesas WHERE id_mesa = 5").fetchone()
        detalle = conn.execute(
            "SELECT cantidad, cantidad_anulada, motivo_anulacion FROM pedido_detalle WHERE id_pedido = ?",
            (pedido_id,),
        ).fetchone()
        assert pedido["estado_comanda"] == "cobrado"
        assert pedido["medio_pago"] == "cierre_automatico"
        assert float(pedido["total_cobrado"] or 0) == 0
        assert mesa["estado"] == "libre"
        assert int(detalle["cantidad_anulada"]) == int(detalle["cantidad"])
        assert "antiguedad" in detalle["motivo_anulacion"]
    finally:
        conn.close()


def test_cloud_status_does_not_expose_values():
    rows = masked_status_table()
    assert rows
    assert all("sb_secret" not in str(row) for row in rows)
    assert all("postgresql://" not in str(row) for row in rows)


def test_supabase_rest_url_normalizes_to_project_base():
    url = "https://jyisecrmuiebuvtgqjhy.supabase.co/rest/v1/"
    assert normalize_supabase_url(url) == "https://jyisecrmuiebuvtgqjhy.supabase.co"


def test_postgres_sql_translation():
    sql = database.to_postgres_sql(
        "INSERT OR IGNORE INTO configuracion_sistema (clave, valor) VALUES (?, ?)"
    )
    assert "%s" in sql
    assert "ON CONFLICT DO NOTHING" in sql

    sql = database.to_postgres_sql(
        "UPDATE pedidos_cabecera SET fecha_cobro = datetime('now','localtime') WHERE id_pedido = ?"
    )
    assert "now()" in sql
    assert "%s" in sql

    returned, pk = database.add_returning_primary_key(
        "INSERT INTO pedidos_cabecera (id_mesa, id_usuario) VALUES (%s, %s)"
    )
    assert pk == "id_pedido"
    assert "RETURNING id_pedido" in returned


def test_database_url_normalization(monkey_patch=None):
    original = cloud_config.get_secret
    try:
        cloud_config.get_secret = lambda name: (
            "postgresql://postgres.ref:pass@aws-1-us-east-1.pooler.supabase.com:5432/postgres"
            if name == "DATABASE_URL"
            else ""
        )
        assert "sslmode=require" in cloud_config.normalized_database_url()
        assert cloud_config.database_url_warnings() == []

        cloud_config.get_secret = lambda name: (
            "postgresql://postgres.ref:[YOUR-PASSWORD]@aws-1-us-east-1.pooler.supabase.com:5432/postgres"
            if name == "DATABASE_URL"
            else ""
        )
        assert cloud_config.database_url_warnings()

        values = {
            "DB_ENGINE": "sqlite",
            "DATABASE_URL": "postgresql://postgres.ref:pass@aws-1-us-east-1.pooler.supabase.com:5432/postgres",
            "NOMBRE_LOCAL": "COMANDAPRO ERP",
            "SERVICIO_PORCENTAJE": "10",
        }
        cloud_config.get_secret = lambda name: values.get(name, "")
        assert cloud_config.db_engine() == "sqlite"
        assert cloud_config.normalized_database_url() == ""
        assert cloud_config.app_name("X") == "COMANDAPRO ERP"
        assert cloud_config.default_service_percentage(5) == 10
    finally:
        cloud_config.get_secret = original


def test_password_hashing_and_legacy_verification():
    hashed = hash_password("clave-segura")
    assert is_password_hash(hashed)
    assert verify_password("clave-segura", hashed)
    assert not verify_password("otra", hashed)
    assert verify_password("restaurante", "restaurante")


if __name__ == "__main__":
    test_no_duplicate_public_functions()
    test_normalize_order_cart_merges_and_cleans_items()
    test_default_system_accesses_work()
    test_system_access_seed_does_not_overwrite_custom_password_or_active_state()
    test_kitchen_auto_refresh_pauses_during_manual_order()
    test_cash_charge_requires_enough_cash_only_for_cash_payments()
    test_role_permissions_are_restricted_and_terminal_locked()
    test_schema_core()
    test_login_accepts_usuario_mail_and_contrasena()
    test_default_login_works_before_database_lookup()
    test_kds_flow_to_ready()
    test_payments_and_cancellations_schema_flow()
    test_cloud_status_does_not_expose_values()
    test_supabase_rest_url_normalizes_to_project_base()
    test_postgres_sql_translation()
    test_database_url_normalization()
    test_password_hashing_and_legacy_verification()
    print("tests_ok")

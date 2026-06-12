# Informe completo de funcionamiento - Restaurante Pro

Fecha de relevamiento: 2026-06-12  
Proyecto: Restaurante Pro  
Tecnologia principal: Python + Streamlit  
Base de datos: SQLite local o Supabase/PostgreSQL en produccion  
Archivo principal en Cloud: `sistema_restaurante.py`

## 1. Resumen ejecutivo

Restaurante Pro es un sistema integral de gestion gastronomica orientado a operacion diaria. La aplicacion concentra en una sola interfaz los circuitos de salon, cocina, caja, reportes, personal, menu, recetas, inventario, reservas, facturacion, sistema y backups.

El sistema esta pensado para funcionar en dos modos:

- Modo local: usa SQLite en `data/restaurante.db`.
- Modo nube: usa Supabase/PostgreSQL mediante `DATABASE_URL`, `DATABASE_URL_POOLER`, `DATABASE_URL_DIRECTA` y credenciales Supabase.

El foco operativo esta en tres terminales:

- Mozo: toma pedidos por mesa, agrega notas, envia a cocina y entrega pedidos listos.
- Cocina: tablero KDS con estados pendiente, en preparacion y listo para servir.
- Caja: cobra total o parcial, emite tickets, registra movimientos y cierres.

## 2. Arquitectura general

La app principal se carga desde `sistema_restaurante.py`. En Streamlit Cloud existe un archivo wrapper en la raiz que ejecuta el modulo interno ubicado en `restaurante programa/sistema_restaurante.py`.

Componentes tecnicos principales:

- `sistema_restaurante.py`: flujo principal, login, sidebar, terminales y modulos operativos.
- `database.py`: capa de acceso a datos, compatibilidad SQLite/PostgreSQL, cola offline y funciones transaccionales.
- `cloud_config.py`: lectura y normalizacion de secretos y variables de entorno.
- `components/css.py`: sistema visual global, paleta, cards, sidebar, login, botones y tableros.
- `views/`: modulos secundarios separados, como sistema, reservas, mesas, menu, inventario, caja y backups.
- `utils/pdf_generator.py`: generacion de PDFs con estilos corporativos.
- `supabase/schema.sql`: estructura para operar en Supabase/PostgreSQL.

Dependencias principales:

- `streamlit`: interfaz web.
- `pandas`: tablas y reportes.
- `plotly`: graficos.
- `openpyxl`: exportacion Excel.
- `psycopg` y `psycopg-pool`: conexion PostgreSQL/Supabase.
- `reportlab`: generacion PDF.
- `supabase`: integracion REST con Supabase.

## 3. Flujo de acceso y seguridad

La aplicacion arranca con `main()`:

1. Inyecta estilos globales.
2. Inicializa sesion.
3. Detecta si entra como terminal automatica.
4. Muestra login si no hay usuario.
5. Fuerza cambio de contrasena inicial cuando corresponde.
6. Renderiza sidebar y despacha el modulo seleccionado.

El login usa:

- Usuario general configurable.
- Password hasheada.
- Acceso administrador de recuperacion.
- Auditoria de ingreso y salida.
- Logo de marca en pantalla de login.

Roles y permisos:

- Administrador: acceso completo.
- Mozo: operacion de salon y pedidos.
- Cocina: tablero de comandas.
- Caja: cobro, tickets y movimientos.
- Otros roles segun configuracion de personal.

Tambien existen accesos directos por URL:

- `?terminal=mozo`
- `?terminal=cocina`
- `?terminal=caja`
- `?terminal=panel`
- `?status=public`

## 4. Navegacion principal

La navegacion se realiza desde un panel lateral izquierdo oscuro. El sidebar muestra:

- Logo de Restaurante El Patron.
- Nombre de la app.
- Usuario logueado.
- Rol.
- Botones de modulos permitidos.
- Widget de turno/check-in.
- Cerrar sesion.

Modulos disponibles en el flujo principal:

- Panel
- Mozo
- Cocina
- Caja
- Reportes
- Usuarios
- Menu
- Recetas
- Mesas
- Inventario
- Proveedores
- Promociones
- Reservas
- Facturacion
- Sistema
- Backups

El sidebar puede colapsarse y reaparecer con un boton flotante.

## 5. Modulo Panel

El panel funciona como vista ejecutiva del restaurante. Resume el estado general:

- Estado de la app.
- Estado de la base.
- Modo de base: local o Supabase.
- Version/build.
- Usuarios, mesas y productos.
- Caja abierta.
- Ventas del dia.
- Stock bajo.
- Reservas y eventos relevantes.

Uso esperado:

- Pantalla inicial para administrador.
- Control rapido antes de iniciar el turno.
- Verificacion de salud del sistema.

## 6. Modulo Mozo

Objetivo: permitir que el personal de salon tome pedidos de forma tactil y rapida.

Funciones principales:

- Seleccion de mozo operativo.
- Vista de salon con mesas.
- Filtros por estado: todas, libres, ocupadas, en cuenta.
- Busqueda por numero de mesa.
- Deteccion visual de mesas reservadas.
- Apertura de pedido.
- Agregado de productos por categoria.
- Busqueda de producto.
- Cantidades con botones `-` y `+`.
- Notas por producto.
- Presets rapidos: "Sin cebolla", "Sin sal", "Bien cocido", "Para llevar".
- Carrito lateral sticky.
- Envio a cocina.
- Vaciar pedido.
- Pedidos listos para entregar.
- Marcar pedido entregado.
- Pedir cuenta.

Estados visuales de mesa:

- Libre: gris claro.
- Ocupada: azul.
- En cuenta: ambar.
- Reservada: violeta.

Flujo operativo:

1. El mozo elige una mesa.
2. Agrega productos.
3. Suma observaciones.
4. Envia a cocina.
5. La mesa queda ocupada.
6. Cuando cocina marca listo, el mozo lo ve en "Pedidos listos".
7. El mozo entrega y marca entregado.
8. Puede pedir cuenta para pasar el circuito a caja.

## 7. Modulo Cocina

Objetivo: manejar comandas como tablero KDS de produccion.

Funciones principales:

- Cierre automatico de comandas vencidas.
- Sincronizacion pendiente con Supabase.
- Auto-refresh configurable.
- Metricas superiores:
  - Pendientes.
  - En preparacion.
  - Listos.
  - Platos activos.
  - Mayor espera.
- Chef view con produccion activa por plato.
- Nuevo pedido manual desde cocina.
- Actualizar tablero.
- Deshacer ultimo despacho.
- Tablero de tres columnas:
  - Pendiente.
  - En preparacion.
  - Listo para servir.
- Scroll interno por columna para evitar paginas largas.
- Tarjetas compactas por pedido.
- Timers por pedido.
- Alertas de demora.
- Botones de accion por tarjeta.
- Archivar pedidos listos.

Estados de comanda:

- `pendiente`: pedido recien enviado.
- `en_cocina`: pedido iniciado.
- `listo`: pedido terminado, pendiente de entrega.
- `entregado`: pedido retirado/archivado.
- `cobrado`: pedido ya liquidado en caja.

Acciones del chef:

- Iniciar: pasa de pendiente a en preparacion.
- Listo: pasa a listo para servir.
- Listo desde pendiente: avance rapido para pedidos que no necesitan pasar visualmente por preparacion.
- Archivar listo: limpia la columna de listos cuando ya no se necesita ver.
- Deshacer ultimo despacho: revierte el ultimo avance si fue accidental.

Reglas visuales del KDS:

- Pendiente: columna gris/pergamino.
- En preparacion: columna amarilla/ambar.
- Listo para servir: columna verde.
- Timer normal: verde.
- Demora media: ambar.
- Demora critica: rojo con pulso.

## 8. Modulo Caja

Objetivo: cobrar mesas y controlar la caja diaria.

Funciones principales:

- Apertura de caja.
- Visualizacion de caja abierta.
- Movimientos y cierre.
- Registro de egresos/retiros.
- Cobro total por mesa.
- Cobro parcial por productos/cantidades.
- Medio de pago.
- Calculo de servicio.
- Ticket generado.
- Liberacion de mesa despues del cobro.
- Historial de pagos.
- Corte/cierre de caja.

Flujo operativo:

1. Caja debe estar abierta.
2. Se selecciona una mesa con consumo.
3. Se revisan productos.
4. Se cobra total o parcial.
5. Se genera ticket.
6. Se registran pagos y movimientos.
7. La mesa se libera cuando corresponde.

Estilo visual:

- Mesas en caja como cards compactas.
- Mesas pidiendo cuenta con alerta ambar.
- Panel de pago sticky.
- Caja y totales con alto contraste.

## 9. Modulo Menu

Objetivo: administrar productos vendibles.

Funciones:

- Alta de productos.
- Edicion de nombre, precio, categoria y estado.
- Activar/desactivar productos.
- Sincronizar/refrescar tabla.
- Gestion de promociones asociadas.
- Control de categorias.

El menu alimenta:

- Terminal de mozo.
- Pedido manual de cocina.
- Recetas.
- Reportes de ventas.
- Caja.

## 10. Modulo Recetas

Objetivo: vincular productos de venta con insumos para controlar consumo y stock.

Funciones:

- Editor de receta por producto.
- Vincular insumos a platos.
- Cantidad a descontar.
- Productos pendientes sin receta.
- Matriz de recetas.
- Cobertura de stock.

Uso operativo:

- Permite que cada venta descuente insumos.
- Ayuda a detectar productos activos sin receta.
- Mejora el control de inventario.

## 11. Modulo Inventario

Objetivo: administrar insumos, stock, mermas y movimientos.

Funciones:

- Stock actual.
- Registro de insumos.
- Stock minimo.
- Unidad de medida.
- Proveedor asociado.
- Ajustes de entrada y salida.
- Compras.
- Mermas.
- Historial de movimientos.
- Exportaciones CSV/PDF.

Alertas:

- Stock bajo.
- Insumos criticos.
- Movimientos por motivo.

## 12. Modulo Mesas

Objetivo: administrar el salon.

Funciones:

- Agregar mesa.
- Ocupar mesa.
- Pedir cuenta.
- Liberar mesa.
- Cambiar estado manualmente.
- Mover o unir consumos.
- Ver historial de mesa.
- Anular renglones.

Estados principales:

- `libre`
- `ocupada`
- `esperando_cuenta`

## 13. Modulo Usuarios / Personal

Objetivo: administrar personas y accesos.

Funciones:

- Alta de personal.
- Roles.
- Estado activo/inactivo.
- PIN o acceso.
- Control operativo por modulo.

Roles relevantes:

- administrador
- mozo
- cocina
- caja

## 14. Modulo Reportes

Objetivo: analizar ventas y operacion.

Funciones:

- Reportes por periodo.
- Ventas.
- Productos vendidos.
- Mozos.
- Medios de pago.
- Comparativa entre periodos.
- Descarga CSV/Excel/PDF/HTML imprimible.

El modulo usa `pandas`, `plotly` y `reportlab`.

## 15. Modulo Reservas

Objetivo: gestionar reservas de salon.

Funciones:

- Nueva reserva.
- Reservas del dia.
- Gestion de todas las reservas.
- Cliente, telefono, fecha, hora, personas.
- Asignacion de mesa disponible.
- Confirmar asistencia.
- Cancelar reserva.

Impacto visual:

- Las mesas con reserva confirmada aparecen destacadas en salon.

## 16. Modulo Sistema

Objetivo: configuracion, monitoreo y diagnostico.

Solapas principales:

- Configuracion.
- Monitoreo.
- Sincronizacion.
- Auditoria.
- Agente IA.

Funciones:

- Datos del restaurante.
- Porcentaje de servicio.
- Limpieza de cache.
- Diagnostico descargable.
- Estado de Supabase/PostgreSQL.
- Forzar sincronizacion.
- Subir datos a Supabase.
- Ver logs/auditoria.
- Agente interno de QA/soporte.

## 17. Modulo Backups

Objetivo: respaldo y restauracion local.

Funciones:

- Exportar tablas CSV.
- Crear backup.
- Ver backups disponibles.
- Descargar backup.
- Borrar backup.
- Restaurar backup.
- Limpiar backups viejos.

## 18. Base de datos y entidades principales

Tablas principales:

- `usuarios`: personal y roles.
- `mesas`: mesas y estado.
- `productos_menu`: productos vendibles.
- `insumos`: stock de insumos.
- `proveedores`: proveedores.
- `recetas_escandallo`: relacion producto-insumo.
- `movimientos_stock`: entradas, salidas, compras, mermas.
- `pedidos_cabecera`: pedido/comanda.
- `pedido_detalle`: productos dentro del pedido.
- `pagos_mesa`: pagos registrados.
- `pago_detalle`: detalle de pagos parciales.
- `auditoria_eventos`: eventos del sistema.
- `configuracion_sistema`: parametros configurables.
- `sistema_estado`: estado tecnico de la app.
- `promociones`: reglas comerciales.
- `turnos_personal`: check-in/check-out.
- `logs_operaciones`: logs operativos.
- `facturas_electronicas`: registro de comprobantes.
- `reservas`: agenda de reservas.

Indices relevantes:

- Pedidos por estado/fecha.
- Pedidos por mesa/estado.
- Productos por categoria/activo.
- Recetas por producto/insumo.
- Pagos por fecha/medio.
- Stock por insumo/fecha.
- Auditoria por fecha.
- Reservas por fecha y mesa.

## 19. Sincronizacion y tolerancia a fallos

La capa de datos soporta:

- SQLite local.
- PostgreSQL/Supabase.
- Pool de conexiones PostgreSQL.
- Cola de sincronizacion offline.
- Fallback local si Supabase falla.
- Procesamiento posterior de operaciones pendientes.

Esto busca evitar que la operacion se frene si hay problemas temporales de red o base remota.

## 20. Diseno visual general

La identidad visual actual mezcla restaurante clasico, pergamino, cuero y tablero operativo moderno.

Tipografia:

- Principal: `Libre Caslon Text`.
- Fallback: Inter, Segoe UI y system UI.

Estilo general:

- Fondo claro pergamino/gris calido.
- Paneles blancos.
- Sidebar oscuro.
- Bordes finos.
- Sombras suaves.
- Cards compactas.
- Botones tactiles.
- Badges tipo pill.
- Radio/tabs nativos Streamlit estilizados.

## 21. Paleta de colores

Variables principales:

- Fondo general: `#f3f2ee`
- Panel: `#ffffff`
- Panel suave: `#faf9f6`
- Texto principal: `#1e1c19`
- Texto secundario: `#6b655c`
- Linea: `#ddd7ce`
- Sidebar: `#1b1916`
- Sidebar hover: `#2b2823`
- Primario rojo: `#c93a2b`
- Primario hover: `#a82e21`
- Azul operativo: `#2563a0`
- Verde OK: `#2a7d4f`
- Ambar alerta: `#c47f1a`
- Rojo peligro: `#c2332e`
- Violeta reserva: `#6d3f9e`
- Pergamino login: `#fff9ed`
- Cuero/marron: `#5d3a2e`
- Oro viejo/borde: `#e2dabf`, `#d4b89a`

Lectura de color por operacion:

- Marron/cuero: accion principal corporativa.
- Rojo: identidad primaria y alertas fuertes.
- Verde: listo, servido, OK.
- Ambar: demora, cuenta, espera o advertencia.
- Azul: ocupado, informacion operativa.
- Violeta: reserva.
- Gris: libre, neutro, pendiente.

## 22. Estilo de botones

Boton primario:

- Fondo marron/cuero.
- Texto blanco.
- Negrita.
- Ancho completo en la mayoria de acciones.
- Hover mas oscuro.

Boton secundario:

- Fondo transparente.
- Borde fino.
- Texto marron.
- Usado para acciones menos criticas.

Botones de sidebar:

- Fondo transparente sobre sidebar oscuro.
- Hover con fondo `nav-soft`.
- Activo con rojo suave y borde izquierdo rojo.
- Movimiento horizontal sutil en hover.

Botones tactiles de operacion:

- Mozo: `+`, `-`, enviar a cocina, pedir cuenta, marcar entregado.
- Cocina: iniciar, listo, archivar, actualizar, deshacer.
- Caja: abrir caja, cobrar, emitir ticket, cerrar caja.

Recomendacion UX:

- Mantener botones de accion cerca de la tarjeta afectada.
- Usar boton primario solo para la accion mas importante.
- Mantener botones peligrosos o irreversibles separados visualmente.

## 23. Estilo de tarjetas y componentes

Cards generales:

- Fondo blanco.
- Borde claro.
- Radio 10 px.
- Sombra suave.
- Padding compacto.

Metric cards:

- Fondo blanco.
- Borde claro.
- Etiqueta en mayuscula.
- Valor grande y pesado.

Mesa cards:

- Borde izquierdo por estado.
- Min-height fijo.
- Total y cantidad de pedidos.
- Hover con sombra.

Kitchen cards:

- Compactas.
- Borde izquierdo por estado/timer.
- Timer tipo pill.
- Notas inline amarillas.
- Criticas con borde rojo y animacion.

Cart panel:

- Sticky.
- Total destacado.
- Productos con notas.
- Boton de envio principal.

## 24. Estados operativos importantes

Pedido/comanda:

- `pendiente`
- `en_cocina`
- `listo`
- `entregado`
- `cobrado`

Mesa:

- `libre`
- `ocupada`
- `esperando_cuenta`

Caja:

- abierta
- cerrada

Reserva:

- confirmada
- cancelada
- asistio/no asistio segun gestion

Stock:

- normal
- bajo
- critico segun minimo

## 25. Experiencia esperada por perfil

Administrador:

- Entra al panel.
- Revisa estado general.
- Gestiona personal, menu, inventario, recetas, reportes, sistema y backups.

Mozo:

- Entra directo a terminal mozo.
- Selecciona su usuario operativo.
- Abre mesa.
- Carga pedido.
- Envia a cocina.
- Marca entregas.
- Pide cuenta.

Cocina:

- Entra directo a terminal cocina.
- Atiende columna pendiente.
- Mueve a preparacion.
- Marca listo.
- Archiva listos para que la pagina no crezca.

Caja:

- Abre caja.
- Cobra mesas.
- Registra pagos.
- Cierra caja.
- Genera tickets y cortes.

## 26. Fortalezas actuales

- Sistema integral en una sola app.
- Flujo operativo completo de punta a punta.
- Compatible con nube y local.
- Diseno consistente con identidad gastronomica.
- KDS con timers y estados claros.
- Mozo tactil con carrito y notas.
- Caja con cobro parcial.
- Recetas vinculadas a inventario.
- Auditoria y diagnostico.
- Backups y exportaciones.
- Pruebas automatizadas existentes.

## 27. Puntos a cuidar

- La app principal es grande; conviene seguir migrando funcionalidades a `views/` y servicios.
- Hay textos con problemas de codificacion en algunos labels; conviene normalizarlos a UTF-8.
- El KDS debe mantener scroll interno para no crecer indefinidamente.
- Los pedidos listos deben archivarse o entregarse para evitar acumulacion visual.
- La sincronizacion Supabase debe monitorearse desde Sistema.
- Los productos activos deberian tener receta para que inventario sea confiable.
- Los botones de acciones criticas deben mantener keys unicas en Streamlit.

## 28. Recomendaciones de mejora visual

- Unificar todos los iconos con una misma familia visual.
- Reducir texto en botones operativos para pantallas tactiles.
- Mantener la cocina mas compacta que el panel administrador.
- Agregar acciones fijas/sticky en columnas con muchos pedidos.
- Diferenciar "archivar" de "entregar" con copy claro.
- Evitar repetir el mismo pedido en varias columnas por errores de estado.
- Revisar contraste en estados ambar y rojo en pantallas con brillo alto.

## 29. Recomendaciones tecnicas

- Mantener pruebas de flujo cocina/mozo/caja.
- Agregar prueba para duplicados de keys en Streamlit cuando haya pedidos repetidos.
- Agregar pruebas para archivado de listos.
- Separar `page_cocina`, `page_mozo` y `page_caja` en views propias.
- Centralizar estados de pedido en constantes.
- Normalizar queries con filtros por estados activos.
- Revisar cola offline para que UPDATE use clave primaria correcta por tabla.
- Agregar limpieza programada de comandas antiguas.

## 30. Conclusiones

Restaurante Pro ya cubre el ciclo completo de un restaurante: apertura, toma de pedidos, produccion en cocina, entrega, cobro, reportes e inventario. El diseno visual tiene una identidad clara basada en pergamino, cuero, sidebar oscuro y colores operativos por estado.

La prioridad actual debe ser mantener la estabilidad de cocina y mozo, porque son las pantallas de mayor uso durante el servicio. Luego conviene avanzar en modularizacion, normalizacion de codificacion y pruebas especificas de UI/estado para reducir errores en Streamlit Cloud.

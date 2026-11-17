# Revisión de preparación del sistema

## Alcance y evidencia

Esta revisión usa el árbol local, las migraciones SQL versionadas, las pruebas locales y una lectura real de solo lectura de Google Sheets. No se ejecutaron RPC remotas, SQL remoto, escrituras, cambios de permisos, migraciones ni despliegues. El estado de catálogos, políticas y datos de Supabase no se considera verificado hasta recibir el resultado de `supabase/diagnostics/supabase_readonly_diagnostic.sql`.

| Área | Evidencia local | Estado comprobable | Trabajo pendiente / límite |
|---|---|---|---|
| Entrada/salida | Flask selecciona la RPC `registrar_entrada_asistencia_act07` / `registrar_salida_asistencia_act07`; migración local `20261028_act07_novedades_y_tramos.sql`; pruebas Python y cliente | Secuencia y validación de aplicación cubiertas por pruebas locales; no se modificó su flujo | Restricción única, bloqueo transaccional, firma remota vigente y atomicidad de la operación no demostrados sin catálogo remoto |
| Identidad e historial de persona | Proyección nueva identifica por `trabajadores.id` y metadatos de fila | No depende de nombres al resolver fila | Falta revisar datos/IDs remotos y aprobar el mapeo inicial de las filas existentes |
| Google Sheets | `integrations/google_sheets.py`; lectura real de título, pestaña y rango de muestra | Credencial existente pudo leer `PLANILLA ANUAL INDUSTRIAS 2RR`, pestaña `2026`, zona `America/Bogota` | No se probó escritura; alcance es de lectura y no se verificó rol Editor |
| Proyección diaria | `integrations/sheets/projection.py` y pruebas específicas | Una fila por trabajador/día, orden cronológico, primera obra/entrada, última salida, suma de tramos cerrados y nota en INGRESO; rechaza solapes y medianoche ambigua | No cuenta eventos duplicados sin una clave estable presente en el origen. Fórmulas existentes que descuentan 1,25 no representan la suma acordada; el escritor protege el bloque con fórmula |
| Sincronización/outbox | Contrato de protocolo en `integrations/sheets/sync.py`; migraciones locales inspeccionadas | Solo existe una orquestación aislada con lease requerido y confirmación posterior al readback | No hay adaptador Supabase, consumidor, reserva/acuse real ni evidencia local de DDL para `act06_sheets_outbox` o `act06_operaciones`. No afirmar atomicidad |
| Visitas, traslados y novedades a Sheets | Ruta local de visitas y módulo de novedades existen; el proyector recibe etiquetas de novedad | Las novedades pueden enriquecer la nota si el repositorio las entrega, sin datos médicos | No se halló evento/outbox integrado para visitas, traslados, novedades aprobadas ni correcciones. No se inventan columnas destino |
| Correcciones auditables | Revisión de `app.py` y migraciones locales | No se encontró una ruta/tabla local de correcciones con valor previo, nuevo valor, responsable, motivo y timestamp | Definir con empresa el esquema y revisar remoto antes de implementarlo. Nunca sobrescribir el original silenciosamente |
| Libros anuales y Drive | Plan anual local de 1.474 columnas para 2026 | Solo se preparó el mapa, no solicita cambios remotos | No hay cliente/flujo Drive de carpeta maestra, búsqueda, clonación de plantilla ni creación anual; faltan IDs y permiso/alcance Drive. También debe resolverse si el archivo existente se conserva como libro 2026 o si rige el nombre anual `Asistencia Industrias 2RR - 2026` |
| Operación sin conexión | Módulo de cola en navegador y pruebas JavaScript | Reintentos conservan el UUID; suite de cliente cubre estados principales | Conflictos entre dos dispositivos requieren validación transaccional remota y resolución administrativa persistida; no se validan con una prueba de interfaz |
| Alertas y backups | No se encontró integración confirmada de alertas de outbox ni rutina de backup/restore en el alcance local revisado | No se afirma que existan o funcionen | Confirmar mecanismos y permisos en hosting/DB/Drive; diseñar retención y probar restauración antes de declarar aceptación |
| Interfaz | Plantillas y estilos existentes conservados por este trabajo | No se hizo rediseño ni se añadieron acciones a las pantallas | Pruebas visuales reales en celular/tableta y escritorio pendientes |

## Reglas de escritura actualmente preparadas

- Alcance de lectura: `https://www.googleapis.com/auth/spreadsheets.readonly`.
- Alcance que debe solicitar el cliente cuando se autorice escritura: `https://www.googleapis.com/auth/spreadsheets`.
- El alcance de Sheets no cambia permisos de Drive. La cuenta necesita permiso de edición sobre el archivo.
- La creación/listado de archivos anuales requiere además una decisión y autorización separadas para Google Drive y acceso a la carpeta/plantilla; no se solicitó ese alcance.
- La escritura se limita al bloque diario asignado por `trabajadores.id`, toca valores y nota de INGRESO, conserva formato y se verifica por lectura posterior. Las celdas con fórmula se bloquean.
- La lectura-verificación reduce el riesgo de confirmar un envío incompleto, pero la API no ofrece compare-and-swap de celdas. Un cambio manual concurrente todavía requiere protección de rango o ventana acordada.

## Supabase requerido para avanzar

Ejecutar manualmente y en modo lectura `supabase/diagnostics/supabase_readonly_diagnostic.sql`. Para cerrar el diseño hacen falta los resultados de las secciones de columnas, restricciones, índices, funciones, triggers, RLS/privilegios y relación ledger/outbox. No incluir filas de negocio, credenciales ni valores personales. En particular, comprobar si las RPC y triggers guardan asistencia y evento outbox en la misma transacción; los nombres de tablas por sí solos no prueban eso.

## Estado de Git y secretos

Al inicio de esta revisión `git status` ya mostraba cambios y eliminaciones locales —incluidos respaldos y pruebas archivadas— además de archivos no rastreados. Se conservaron tal como estaban; no se restauró ni descartó ninguno. `.env` y `secrets/` están ignorados por Git y no aparecen como archivos rastreados en el resultado de `git ls-files`.

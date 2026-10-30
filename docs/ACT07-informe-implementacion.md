# ACT07 — Correcciones, archivo y Dashboard

Fecha de actualización: 2026-10-28

## Alcance y seguridad

Se trabajó solo ACT07 y compatibilidad necesaria con la gestión existente. No se ejecutaron migraciones, escrituras ni pruebas de datos contra Supabase remoto. No se borraron datos ni se modificó la cola de IndexedDB. Google Sheets/ACT08 y ACT09 siguen fuera del alcance.

## Cambios

### Administración de personas y cuentas

- Trabajadores y cuentas se desactivan lógicamente desde las listas existentes, con confirmación del navegador. Se conserva la fila de `trabajadores`, el historial y la cuenta de Supabase Auth.
- Se añadió borrado permanente solo para personas sin cuenta Auth ni historial relacionado; no se ofrece para perfiles administradores. El servidor bloquea el borrado de la sesión actual y las claves foráneas de la base siguen siendo la última protección frente a referencias concurrentes.
- El servidor sigue exigiendo perfil administrador y CSRF. Una RPC transaccional, disponible solo para `service_role`, impide desactivar la cuenta que usa el administrador y serializa cambios para no permitir que dos solicitudes concurrentes desactiven las últimas cuentas administradoras.
- Las rutas protegidas ya consultan perfil y estado del servidor por solicitud; una persona inactiva no conserva acceso por una sesión ya abierta.
- Se añadió paginación de 50 filas a Personas y Usuarios. Personas filtra en Supabase; Usuarios consulta perfiles paginados y detiene la lectura paginada de Auth cuando localiza los UID de la página.

### Novedades

- El formulario ofrece únicamente permisos, vacaciones, incapacidades e inasistencia injustificada. Las validaciones de servidor rechazan nuevos valores como llegada tarde, salida anticipada, horas extras u otras novedades.
- Las filas históricas no se borran ni se reescriben. Sus tipos anteriores siguen disponibles como filtros históricos y se etiquetan al mostrarse. La migración no estrecha el check histórico de tipo para que esas filas sigan siendo archivables/restaurables.
- Se quitaron los filtros visibles de COT y proyecto; COT/proyecto permanecen como datos opcionales de cada novedad.
- El listado administra páginas de 100 novedades.
- El formulario de alta ya no solicita COT ni proyecto. Las columnas históricas permanecen para conservar datos anteriores.
- Se añadió una herramienta de archivo lógico exclusivamente para novedades: fecha límite exclusiva (`fecha_fin < límite`), vista previa del total, checkbox y confirmación. El servidor compara el total esperado dentro de una transacción con bloqueo de inserciones; si cambió desde la vista previa, rechaza la operación. No hay borrado automático, y la página permite consultar y restaurar hasta 50 archivadas por página.
- La lista incluye una acción separada de eliminación total de novedades, con conteo previo, confirmación expresa y verificación posterior de que la tabla quedó vacía. Incluye las novedades archivadas y es irreversible; solo afecta la tabla `novedades`.

### Dashboard diario

- El Dashboard usa la fecha `America/Bogota`; si el entorno Windows carece de base `tzdata`, usa el desfase fijo UTC−5 de Colombia.
- “Presente” significa trabajador activo con entrada ocurrida durante la jornada bogotana o un turno de una jornada anterior que sigue abierto. Se agrupa por trabajador; una salida tardía cerrada no cuenta como entrada nueva del día siguiente.
- “Ausencias injustificadas reportadas” solo cuenta novedades explícitas de ese tipo. No se infieren ausencias para personal sin registro porque el esquema revisado no tiene calendario/asignación de turnos.
- “Novedades vigentes” cuenta registros cuyo rango inclusivo contiene el día. Incapacidades y vacaciones de varios días aparecen durante todo su rango.
- Una sola función SQL agregada devuelve métricas, tramos agrupados por COT/proyecto y cinco novedades recientes; no carga el historial completo en Flask. La entrada filtra por `fecha_entrada`; la migración añade índice GiST por rango de vigencia, índices parciales para vistas/archivo de novedades y un índice para personas activas. El índice ACT06 por fecha de entrada se conserva.
- Si la función agregada todavía no existe, Flask usa consultas paginadas sobre las tablas disponibles. Reportes permite filtrar asistencia por periodo/trabajador, paginar y descargar CSV. Las marcas `timestamptz` se presentan en hora Colombia (UTC−5); Supabase Table Editor suele mostrarlas en UTC.
- La pantalla del coordinador identifica las horas mostradas como hora Colombia. El navegador fija `America/Bogota`; el valor almacenado como `timestamptz` conserva el instante UTC equivalente.
- La página actualiza al abrir y cada cinco minutos. Si falla la consulta, muestra error y guion si no hay dato previo. Puede mostrar el último agregado confirmado en memoria del proceso, con fecha y hora visibles; no conserva motivos/personas en esa caché. En despliegues con varios procesos, la caché es local a cada proceso.

### Migraciones locales

1. `supabase/migrations/20261028_act07_novedades_y_tramos.sql` — tabla de novedades y wrappers de observaciones ACT06, ya preparados en el trabajo previo.
2. `supabase/migrations/20261029_act07_dashboard_archivo_y_seguridad.sql` — agrega `archivado_en`, estado archivado reversible, funciones de Dashboard, vista previa/archivo/restauración, control serializado de desactivación administrativa e índice GiST.

La segunda migración requiere la primera y el esquema ACT06. Es aditiva; no contiene `DELETE`, no elimina tablas y no cambia los valores históricos de tipo. No fue ejecutada. No se encontró una migración base ACT06 canónica dentro de `supabase/migrations`; la copia disponible está en los respaldos. Antes de aplicar, validar en una base de pruebas que existen `trabajadores`, `registros_asistencia` y las RPC ACT06 que envuelven la primera migración.

## Pruebas locales ejecutadas

Las pruebas Flask usan mocks; no escriben en Supabase. Resultados ejecutados el 2026-10-28:

- `.venv\Scripts\python.exe -m unittest tests.test_act07_novedades -v`: 29/29 pasaron. Incluye cuatro categorías actuales e históricas, CSRF, desactivación directa de trabajadores, eliminación protegida de personas, borrado total limitado a novedades, archivo reversible, Dashboard con fallback, reportes y conversión horaria.
- `.venv\Scripts\python.exe -m unittest tests.test_act06_security -v`: 37 pruebas; 36 pasaron y 1 se omitió porque no está instalado `qrcode` (imagen QR).
- `.venv\Scripts\python.exe -m unittest tests.test_login_home -v`: 5/5 pasaron.
- `node tests/act06_client.test.cjs`: 25/25 pasaron; regresiones de asistencia COT, cola offline, visitas y presentación de la zona Bogotá.
- `.venv\Scripts\python.exe -m py_compile app.py tests/test_act07_novedades.py tests/test_act06_security.py tests/test_login_home.py`: pasó.
- `node --check static/js/asistencia.js` y `git diff --check`: pasaron.
- `.venv\Scripts\python.exe -m unittest discover -s tests -q`: no completó la suite total. Ejecutó 68 pruebas, pero no pudo importar `tests/test_act06_offline.py` porque `qrcode` falta en el entorno activo (sí figura en `requirements.txt`). Por eso no se reporta suite total aprobada.

```powershell
.venv\Scripts\python.exe -m unittest tests.test_act07_novedades -v
.venv\Scripts\python.exe -m unittest tests.test_act06_security -v
.venv\Scripts\python.exe -m unittest tests.test_login_home -v
node tests/act06_client.test.cjs
.venv\Scripts\python.exe -m py_compile app.py tests/test_act07_novedades.py tests/test_act06_security.py tests/test_login_home.py
node --check static/js/asistencia.js
git diff --check
```

El entorno virtual no tiene `pytest` ni `qrcode`, aunque ambos están declarados en `requirements.txt`; `python -m pytest -q` tampoco pudo arrancar (`pytest` no instalado). El intérprete global además carece de `requests`, por lo que las pruebas Flask se ejecutaron con el Python de `.venv`. No hay `psql`, Docker ni Supabase CLI disponibles. No se ejecutó una base de datos local o de pruebas, no hay medición SQL con volumen representativo y no se realizó prueba visual real en navegador. Las comprobaciones de migración son estáticas y no equivalen a ejecutar el SQL.

## Manual de validación previo a ACT08

1. Revisar las migraciones; crear una base Supabase aislada de pruebas y recuperar/verificar primero el esquema ACT06 base y sus RPC. Aplicar allí, en orden, las migraciones ACT07.
2. Probar el formulario de novedades con los cuatro tipos actuales, filtros por fecha/trabajador/tipo, rangos multidiarios, motivos y observaciones. Verificar que los tipos retirados no puedan enviarse desde el navegador o una solicitud manual y que las categorías históricas siguen visibles.
3. Probar CSRF inválido, sesión de coordinador y administrador, activación/desactivación, borrado sin vínculos y rechazo de borrado con historial/cuenta Auth, intento de autodesactivación y último administrador. Asegurar que la cuenta inactiva no accede a rutas protegidas.
4. En una base aislada, eliminar todas las novedades y verificar el conteo posterior; por separado, archivar un rango pequeño, comprobar la cantidad de vista previa, probar que un conteo cambiado cancela la operación y restaurar una fila. Confirmar que trabajadores, asistencia y visitas quedan intactos.
5. Verificar Dashboard a ambos lados de medianoche Bogotá, con entradas de varios proyectos, salidas tardías, novedades multidiarias y caída de la RPC. Comparar indicadores con registros de prueba y revisar la hora local.
6. Verificar reportes por fecha/trabajador, paginación y CSV; comparar horas locales con las marcas UTC mostradas en Supabase.
7. Generar datos representativos (por ejemplo 50 mil asistencias históricas y 10 mil novedades) en la base de pruebas y medir tiempos con `EXPLAIN (ANALYZE, BUFFERS)` antes/después de los índices. Esa medición sigue pendiente: no se ejecutó en este entorno.
8. Revisar la interfaz en navegador de escritorio y móvil. La actualización automática configurada es de cinco minutos; verificar que no interfiere con formularios que estén editándose.

## Decisiones y límites

- La desactivación no elimina usuarios de Supabase Auth; las páginas protegidas validan el estado de `trabajadores` y rechazan la cuenta inactiva. Borrado de Auth no se implementó por riesgo de pérdida de vínculos/historial.
- El borrado permanente solo se ofrece a personas sin cuenta Auth vinculada; se rechaza si cualquier consulta encuentra historial relacionado. No se ejecutó un borrado remoto durante esta revisión.
- El indicador de ausencias es el total de trabajadores con ausencia injustificada reportada, no una inferencia de toda persona sin entrada. Falta calendario laboral para producir una ausencia oficial completa.
- La caché de última lectura exitosa es en memoria del proceso Flask. Reinicios o múltiples procesos pueden no compartirla; ante ausencia de caché se muestran guiones y error, nunca cero de demostración.
- No se midió el rendimiento de PostgreSQL ni se ejecutó el SQL. La suite usa mocks y no demuestra duración real ni compatibilidad de las funciones con el esquema conectado.
- Google Sheets continúa siendo ACT08: se conserva el contrato/outbox documentado, pero no se afirma sincronización integrada ni probada.

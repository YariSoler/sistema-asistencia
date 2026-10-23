# Informe de validación ACT06

**Estado:** avance de código revisado; pruebas cliente aprobadas. La suite Python conserva fallos por migraciones SQL que no existen en el árbol actual. Pendiente validar Flask/Supabase en un entorno con dependencias y dispositivos reales.

## Base documental y alcance

El documento maestro disponible establece que ACT06 se denomina **“Desarrollo del módulo de registro de asistencia e integración de sus funcionalidades”**, con fechas del **19 de octubre al 6 de noviembre de 2026**. También cita el OE2 oficial: **“Desarrollar e integrar los módulos de usuarios, de registro de asistencia con QR y geolocalización y novedades, sobre Flask y Supabase.”** La secuencia oficial reserva novedades para ACT07 y Google Sheets para ACT08; este trabajo no adelanta esas actividades.

El repositorio contiene `docs/ACT06-seguridad-y-reglas.md` y el documento maestro de continuidad adjunto. El maestro menciona `ACTIVIDAD 2 -presentacion de plan de trabajo.pdf` y `_Cronograma plan de trabajo.xlsx`, pero esos dos archivos no están disponibles dentro del proyecto inspeccionado. Por eso esta matriz usa el cronograma transcrito en el maestro y los requisitos de ACT06 dados directamente por la usuaria; no atribuye al PDF o al Excel detalles que no se pudieron revisar.

## Matriz de cumplimiento

| Requisito | Fuente y archivos/componentes | Resultado de revisión | Corrección / trabajo | Evidencia y estado |
|---|---|---|---|---|
| Módulo de asistencia integrado en Flask y Supabase | ACT06 del cronograma; `app.py`; migración `20261022_act06_asistencia_visitas.sql` | Hay rutas Flask y funciones RPC para lectura QR, entrada, salida y visita; la migración define tablas y funciones. | Se conserva el modelo de trabajadores y se añade una migración local para la persistencia del flujo. | Revisión de código y pruebas con mocks aprobadas. **Pendiente:** aplicar/verificar en Supabase de pruebas; no se ejecutó migración remota. |
| Registrar entrada y salida asociadas a COT/proyecto | Requisitos ACT06 de la solicitud; `app.py`; `static/js/asistencia.js`; migración | El frontend envía COT/proyecto al registrar entrada; la base registra hora con `clock_timestamp()` y cierra la fila abierta en salida. | Se mantiene la validación servidor/SQL y la respuesta de conflicto para turno abierto o salida inexistente. | Pruebas de rutas con RPC simulado, incluidas entrada válida, entrada duplicada y salida sin turno. **Pendiente:** recorrido integrado en Supabase de prueba. |
| Identificar trabajadores y coordinadores por QR | OE2 del maestro; columna existente `trabajadores.qr`; `app.py`; plantilla y JS de coordinador | Antes, generación, administración y lectura admitían solo perfil `trabajador`. | SST/Operario y Coordinador reciben QR único; el administrador puede verlo/imprimirlo. En asistencia el coordinador solo usa el QR que pertenece a su sesión. | Pruebas mock para generación/almacenamiento en ambos perfiles, visualización QR de coordinador, asistencia propia y rechazo del QR de otro. **Pendiente:** cámara y migración en una base aislada. |
| Ver e imprimir el QR sin editar código | Requisito de la solicitud; `templates/personas.html`; nueva ruta en `app.py`; `templates/persona_qr.html`; `static/css/style.css` | La lista anterior solo mostraba el valor como texto o “Sin asignar”; no había vista de imagen ni impresión. | El administrador abre una vista protegida con la imagen QR y botón de impresión. Los registros antiguos sin QR de perfil trabajador/coordinador tienen acción protegida para asignarlo. | Prueba Flask simulada verifica la imagen embebida y el botón `window.print()`. **Pendiente:** comprobar legibilidad al imprimir/escaneo físico. |
| Escaneo real con cámara y búsqueda por identificación | Requisito de la solicitud; `static/js/asistencia.js` y plantilla del coordinador | La cámara usa `BarcodeDetector` y `getUserMedia`; la cédula sirve de alternativa autorizada. | Se eliminó el campo de ingreso manual de texto QR. | Prueba cliente simulada para búsqueda por identificación. **Pendiente manual:** usar HTTPS y navegador/dispositivo compatible y leer QR físico. |
| Reglas de activo/inactivo e impedir entradas duplicadas | Solicitud ACT06; rutas Flask; funciones SQL | La función SQL acepta trabajador activo o coordinador activo registrando su propia fila; el índice parcial limita a una fila abierta por `trabajador_id`. | Trabajador inactivo con entrada abierta solo puede cerrar esa fila; no puede iniciar otra. Una fila cerrada histórica no se reescribe. El coordinador solo registra/cierra su propio turno. | Pruebas mock de entrada duplicada y rol/identidad; regla e índice revisados en migración. **Pendiente:** concurrencia y motor PostgreSQL/Supabase aislado. |
| Visita técnica con geolocalización y QR del coordinador | OE2 incluye geolocalización; `static/js/asistencia.js`; `app.py`; migración | Existía asociación a sesión, pero no escaneo del QR de coordinador. | UI exige escanear QR; Flask coteja perfil e identidad con la sesión al verificarlo y al guardar. | Pruebas mock de rechazo de QR ajeno, visita válida y errores de GPS/idempotencia. **Pendiente:** GPS físico y persistencia Supabase aislado. |
| GPS opcional y ubicación explícita no disponible | Requisito ACT06 de campo; `app.py`; `static/js/asistencia.js`; migración `20261023_act06_gps_offline.sql` | El flujo previo podía bloquearse cuando se denegaba GPS y las visitas exigían coordenadas. | Asistencia/visitas conservan evento con `no_disponible` y valores GPS nulos; validación server/SQL controla rangos y coherencia. | Prueba unitaria de GPS denegado y revisión del cliente. **Pendiente:** validar persistencia en PostgreSQL aislado y denegar permiso en dispositivo real. |
| Operarios activos disponibles sin conexión | Solicitud de campo; `/api/asistencia/directorio-offline`; IndexedDB en `static/js/asistencia.js`; `static/service-worker.js`; `static/offline-shell.html` | No había directorio local ni cola persistente. | Descarga solo operarios activos y datos mínimos: ID, identificación, nombre, cargo, QR y estado resumido de turno; el servidor valida estado vigente al sincronizar. | Pruebas con mocks de directorio y lookup. **Pendiente:** navegador/dispositivo offline real; el almacenamiento del navegador no está cifrado por la aplicación. |
| Cola de entradas, salidas y visitas con reintentos | Solicitud de campo; Flask; JS; migración `20261023_act06_gps_offline.sql` | No había almacenamiento local/idempotencia común para eventos offline. | IndexedDB guarda UUID estable, hora, GPS y contenido mínimo; RPC transaccional valida y persiste evento; mismo UUID/datos devuelve el resultado anterior y otro contenido se rechaza. | Pruebas de payload e idempotencia estática/HTTP mock. **Pendiente:** ejecutar funciones en Supabase/Postgres aislado y probar pérdida de respuesta real. |
| Revisión visible de operaciones no validadas y conflictos | Solicitud de campo; `asistencia.js`; RPC SQL | Sin conexión o trabajador cambiado podían perder la intención de registro. | Cola conserva todo no confirmado, muestra conflictos como pendientes de revisión y permite reintento manual; entrada duplicada la bloquea índice único y salida anterior a entrada se rechaza. | Prueba estática de confirmación por UUID exacto, RPC con mocks y revisión SQL. **Pendiente:** pruebas de concurrencia entre dos dispositivos reales/DB aislada. |
| Entrega posterior a Google Sheets | ACT08 oficial / requisito de sincronización posterior; migración `20261023_act06_gps_offline.sql` | No existe consumidor de Google Sheets ni configuración en el repo; ACT08 del cronograma lo reserva para después. | Migración prepara `act06_sheets_outbox`, una fila única por operación confirmada en Supabase y transaccional al guardado. No hay envío a Sheets implementado ni declarado. | Revisión de SQL; **pendiente:** definir hoja/columnas, credenciales del lado servidor e implementar consumidor idempotente. |
| Idempotencia y prevención de registros inconsistentes | Requisito de la solicitud; función `registrar_visita_tecnica`; `asistencia.js` | La función SQL conserva el registro anterior para misma clave y mismos datos; rechaza la misma clave con coordinador, coordenadas o precisión diferentes. | Flask convierte el rechazo explícito en HTTP 409; el cliente conserva el cuerpo para reintentar la misma operación. | Prueba simulada del HTTP 409 y revisión estática del SQL. **Pendiente:** ejecutar ambos escenarios contra PostgreSQL aislado. |
| Sesión, autorización y CSRF | Solicitud ACT06; `app.py`; formularios en `templates/`; `asistencia.js` | Las rutas comprueban perfil/estado contra datos servidor; POST/PUT/PATCH/DELETE exigen token de sesión. | Se añadió CSRF en formularios HTML y cabecera API; el cambio de estado informa que las sesiones abiertas se vuelven a validar. | Pruebas para token ausente, inválido, válido, plantilla coordinador y sesión inactiva aprobadas. |
| Protección de claves y depuración | Solicitud ACT06; `app.py`; `.env` | La clave service role se usa solo en código servidor; no aparece en `static/` ni plantillas. El acceso de login ya no registra el cuerpo de error del proveedor. | `app.run(debug=False)`. `.env` no se leyó ni modificó durante este trabajo. | Prueba estática de ausencia de clave en recursos públicos; inspección del código. No se hizo despliegue. |
| Dependencias | Solicitud ACT06; `requirements.txt` | `qrcode` y `Pillow` están declarados para producir PNG; `pytest` está declarado para ejecutar la suite. | No fue necesario cambiar el archivo. | Inspección del manifiesto. El entorno `.venv` no tiene pytest/qrcode; el entorno `venv` sí pudo ejecutar la suite y generar el PNG. |

## Cambios realizados

- `app.py`: generación/consulta de QR de trabajador y coordinador, rutas protegidas de vista/impresión, directorio offline de operarios activos, búsqueda por identificación, validación de eventos offline y RPC idempotentes.
- `templates/personas.html`: vista/impresión y generación protegida de QR faltante para trabajadores y coordinadores.
- `templates/persona_qr.html`: nueva vista imprimible con nombre e identificación.
- `static/css/style.css`: presentación y reglas de impresión del QR junto al estilo ACT06 ya existente.
- `supabase/migrations/20261022_act06_asistencia_visitas.sql`: validación de trabajador activo o coordinador propio al entrar; salida para cerrar turnos existentes sin modificar historial.
- `tests/test_act06_security.py`: pruebas de CSRF, roles/sesión, QR de ambos perfiles, asistencia propia, rechazo de identidad ajena, visitas/idempotencia y PNG imprimible.
- `docs/ACT06-seguridad-y-reglas.md`: reglas técnicas y pasos manuales.
- `docs/ACT06-informe-validacion.md`: esta matriz y estado de validación.
- `templates/login.html`, `templates/panel.html`, `templates/administrador/dashboard.html`, `templates/persona_form.html`, `templates/usuarios.html`: token CSRF para sus formularios POST.
- `templates/coordinador/registro.html`, `static/js/asistencia.js`, `static/service-worker.js`, `static/offline-shell.html` y `static/css/style.css`: QR/cédula, GPS opcional, caché de pantalla, IndexedDB, estados de cola, reintentos y sincronización online/manual.
- `supabase/migrations/20261023_act06_gps_offline.sql`: GPS opcional, UUID/hash de operaciones, validación transaccional de entrada/salida/visita y outbox para una integración futura de Sheets.
- `tests/test_act06_offline.py`: búsqueda por cédula, directorio mínimo, GPS denegado, contratos de RPC y reglas de reintento/confirmación.
- `tests/act06_client.test.cjs`: DOM simulado/IndexedDB para buscar por cédula, perder conexión al registrar, continuar offline, reintentar con espera creciente, reconectar y confirmar el mismo UUID; también verifica que un rechazo 403 no active el modo offline.
- `backups/act06-before-review-20261022-124543/`: copia de los archivos relevantes previa a esta ronda de correcciones.

## Pruebas realizadas

| Comprobación | Resultado |
|---|---|
| `venv\Scripts\python.exe -m py_compile app.py tests/test_act06_offline.py tests/test_act06_security.py` | Aprobado. |
| Suite Python de 37 pruebas | Aprobada en la revisión inmediatamente anterior a los cambios de interfaz. No se repitió, a petición de la usuaria. |
| `venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_act06_offline.py::TestColaYValidacionOffline::test_codigo_cliente_conserva_reintento_y_exige_confirmacion_del_servidor` | **1 passed**: contrato de selectores DOM en ambas plantillas, ruta offline y petición de sincronización en segundo plano. |
| `node tests/act06_client.test.cjs` | **2 passed**: flujo búsqueda/caída/red/reintentos UUID; rechazo de autorización sin fallback offline. |
| `node --check static/js/asistencia.js` y `node --check static/service-worker.js` | Aprobados. |
| `git diff --check` | Aprobado; Git solo reportó avisos de conversión LF/CRLF de Windows. |
| Supabase remoto / PostgreSQL | No ejecutado: no se realizaron escrituras ni se aplicó migración; los tests no conectan a una base real. |
| Cámara, impresión, reconexión/offline y GPS físico | No ejecutado; requiere navegador/dispositivo de la usuaria. |
| Google Sheets | No ejecutado; solo queda preparada la bandeja outbox, no existe consumidor. |

Las pruebas de rutas sustituyen Auth/Supabase mediante mocks; no prueban red real, restricciones, políticas RLS ni ejecución de funciones PostgreSQL. El cliente se ejecuta con DOM e IndexedDB simulados; no equivale a una prueba en navegador o teléfono real. El test de QR de imagen valida que la librería produce un PNG, no que una cámara física lo lea.

## Pendientes para validar ACT06

### Corrección reciente: cola offline y lector QR

- El contador/listado del panel offline ya no forma parte del contrato DOM obligatorio. `renderQueue()` siempre consulta y conserva IndexedDB, pero actualiza el contador/listado solo cuando sus nodos están en la página. Esto evita que la cola falle si el panel no está montado o una versión HTML antigua no contiene el contador.
- La pantalla usa `BarcodeDetector` cuando está disponible y `qr-scanner` 1.4.2 como alternativa. La biblioteca está fijada por versión e integridad SRI. El service worker `act06-offline-v6` invalida cachés anteriores, intenta obtener los recursos propios desde red y conserva en caché la biblioteca y su worker cuando se pudieron descargar.
- El QR del coordinador continúa validándose mediante `/api/visitas-tecnicas/verificar-coordinador`; la lectura por sí sola no concede acceso. El servidor sigue comprobando sesión/perfil/estado. La búsqueda por identificación permanece solo en el flujo de asistencia.
- Incidente posterior en Visitas técnicas: el mensaje “No se cargó el lector QR compatible…” se produce antes de abrir la cámara, en la rama que encuentra `window.QrScanner` ausente. Esa rama era el error genérico después de que no se registrara el global del `<script>` externo; no era un rechazo del QR ni un error del endpoint. La captura no contiene consola/red, por lo que no permite distinguir si el recurso inicial falló por red, bloqueo del CDN o SRI. La plantilla ahora prioriza cdnjs y, solo al pedir escanear una visita cuando no hay lector disponible, carga de forma explícita jsDelivr y cdnjs como alternativas con el mismo SRI. También reporta host y causa de carga de cada intento. Entrada/salida y su identificación no se modificaron.
- El motivo más probable del `pending-count` ausente era una combinación de caché de assets: el service worker `act06-offline-v4` usaba estrategia cache-first para `asistencia.js`, así que podía ejecutar código viejo junto con una plantilla nueva. La plantilla actual contiene el contador; no fue posible consultar el HTML entregado por una instancia real de Flask en este entorno porque faltan dependencias Python requeridas (`requests`, `qrcode`, Flask y pytest en los intérpretes disponibles). Por lo tanto, el desajuste servido está explicado por el mecanismo comprobado, pero la respuesta de la instalación real sigue pendiente de validación en navegador.
- El QR scanner requiere conexión para su primera descarga desde jsDelivr. El service worker lo guarda para siguientes usos cuando la descarga tuvo éxito; no se ha validado la instalación en un dispositivo sin red ni la lectura física.
- Pruebas cliente simuladas nuevas: renderizado con `pending-count` ausente conservando tres UUID; uso del `BarcodeDetector`; uso del fallback `qr-scanner`, liberación del scanner y validación server-side simulada del QR de coordinador. No equivalen a pruebas de cámara física, CDN real o Supabase.
- Resultado reproducible de esta revisión: `node tests/act06_client.test.cjs` aprobó 13/13, incluidas carga simulada con un CDN fallido y fallback al otro, además de validación simulada del QR en endpoint. `pytest tests/test_act06_offline.py` aprobó 6 y falló 1 porque falta `supabase/migrations/20261023_act06_gps_offline.sql`; `pytest tests/test_act06_security.py` aprobó 28 y falló 2 porque falta `supabase/migrations/20261022_act06_asistencia_visitas.sql`. En esta copia, `supabase/migrations/` solo contiene `20261021_unicidad_identificacion_trabajadores.sql`. No se crearon ni aplicaron migraciones en esta corrección. Por ello, cualquier afirmación anterior del informe sobre validar esas dos migraciones no se puede confirmar con el árbol actual.
- `node --check` para `asistencia.js` y `service-worker.js`, `python -m py_compile app.py tests/test_act06_offline.py` y `git diff --check` finalizaron correctamente. La respuesta de Flask no pudo ejecutarse: los intérpretes disponibles no reúnen todas las dependencias necesarias. No se hizo prueba real de navegador, cámara, caché existente o Supabase.

1. Revisar en una base aislada si existen QR duplicados no vacíos antes de aplicar la migración. La migración aborta con un mensaje si los encuentra. Confirmar que las filas existentes de Coordinador sin QR se puedan rellenar desde Gestión de personas.
2. Aplicar la migración solo en el proyecto local/de prueba autorizado y comprobar tablas, índice, grants y funciones; todavía no se aplicó en ningún Supabase.
3. Con datos ficticios en esa base, probar entrada, salida, dos entradas concurrentes, trabajador inactivo con turno abierto y ambos casos de idempotencia.
4. Desde un celular o navegador HTTPS, imprimir y escanear QR de un trabajador y del coordinador autenticado. Confirmar que un QR de otro coordinador o de administrador se rechaza; luego probar entrada/salida propia y GPS de visita. Confirmar las filas y horas devueltas en la base aislada.
5. Confirmar la decisión académica de conservar coordenadas/precisión GPS y asociar la visita al coordinador. La responsabilidad del coordinador proviene de la decisión previa de la usuaria; la retención de ubicación requiere aprobación/procedimiento de la empresa si no está definido en la propuesta.

## Revisión adicional de Visitas técnicas — 2026-10-23

### Esquema inspeccionado

Se consultó únicamente el documento OpenAPI de PostgREST mediante una solicitud HTTP GET; no se leyeron filas de personas/asistencia/visitas ni se ejecutaron RPC, INSERT, UPDATE o migraciones. El esquema publicado informa:

- `trabajadores`: `id`, `nombre`, `cargo`, `identificacion`, `perfil`, `estado`, `qr`, `auth_user_id`.
- `registros_asistencia`: COT/proyecto, trabajador/coordinador, entrada/salida, campos GPS y claves idempotentes de entrada/salida.
- `visitas_tecnicas`: `id`, `coordinador_id`, `latitud`, `longitud`, `precision_m`, `idempotency_key`, `registrado_en`, `ubicacion_estado`, `ocurrio_en`, `payload_hash`.
- `registrar_visita_tecnica_offline` recibe ocho argumentos en su versión publicada; no recibe proyecto ni participante.

Por tanto, el esquema remoto actual no puede guardar los datos nuevos requeridos. No se reutilizó `registros_asistencia` para visitas ni se asumieron columnas existentes.

### Matriz de cumplimiento del ajuste

| Requisito | Componente | Revisión/corrección | Evidencia disponible |
|---|---|---|---|
| Proyecto/lugar obligatorio antes de identificar | `templates/coordinador/registro.html`, `static/js/asistencia.js`, `app.py` | Nueva primera etapa; Flask limita y valida el texto hasta 300 caracteres. | Pruebas cliente simuladas; inspección del endpoint. |
| Coordinador por QR de su propia sesión | Endpoint `verificar-coordinador`, etapa de identidad | Flask contrasta QR, perfil, estado y `id` con la sesión. | Prueba servidor simulada para QR ajeno; prueba cliente simulada con cámara/lector falso. |
| Coordinador por identificación como alternativa | Endpoint `verificar-coordinador-identificacion` | La cédula se compara en servidor solo con el registro del usuario autenticado; una coincidencia ajena devuelve 403. La respuesta no devuelve la cédula. | Pruebas servidor y cliente simuladas para coincidencia y rechazo. |
| Visita solo coordinador | Endpoint de visita, formulario | Participante opcional; el servidor guarda `trabajador_id = null` cuando no se selecciona operario. | Prueba cliente simulada; prueba servidor simulada para RPC sin participante. |
| Visita con operario activo por QR o identificación | Endpoint `buscar-operario`, etapa de participantes | QR/identificación resuelven en servidor un perfil `trabajador` activo; el POST vuelve a validar el ID. Solo nombre/cargo/ID se muestra y la identificación no se conserva en IndexedDB. | Pruebas simuladas de QR, búsqueda de cédula y rechazo de inactivo; flujo RPC simulado. |
| GPS opcional e idempotencia conservada | `app.py`, migración nueva, cola actual | El payload sigue usando el UUID original y `ubicacion_estado`; la migración permite coordenadas nulas. El hash incluye coordinador, participante, proyecto, hora y GPS. | Prueba cliente simulada para GPS no disponible y respuesta de servidor simulada. Falta PostgreSQL/Supabase de prueba. |
| No modificar el ciclo de COT | `static/js/asistencia.js`, `app.py` | La lógica de entrada/salida y sus endpoints no se modificaron; los cambios se limitan al modo de visita y a la carga de una versión nueva del JS mediante cache v7. | Revisión de diff; no se ejecutó un navegador conectado ni registro real. |

### Cambios y pruebas de esta revisión

- Archivos: `app.py`, `templates/coordinador/registro.html`, `static/js/asistencia.js`, `static/service-worker.js`, `tests/test_act06_security.py`, `tests/act06_client.test.cjs`, `tests/test_act06_offline.py` y nueva migración `supabase/migrations/20261023_act06_visitas_proyecto_participante.sql`.
- `node tests/act06_client.test.cjs`: **18 pruebas simuladas aprobadas**. Cubren selección QR/identificación, rechazo de cédula ajena, visita sin operario, visita acompañada, GPS no disponible, identidad QR del coordinador y los estados de confirmación existentes.
- Pruebas Python dirigidas de rutas ACT06: **8 aprobadas**, ejecutadas con mocks y una dependencia QR de importación simulada, porque `pytest` y `qrcode` no están instalados en el entorno Python del proyecto. El intento estándar de instalar dependencias falló por permisos del directorio temporal; no se cambió `requirements.txt`.
- `python -m py_compile app.py tests/test_act06_security.py`, `node --check static/js/asistencia.js` y `git diff --check`: aprobados.
- No hubo navegador real, cámara/GPS físicos ni Supabase de pruebas. Las pruebas HTTP usaron mocks, y la consulta OpenAPI fue solo lectura de metadatos.

### Migración requerida y revisión manual

La nueva migración es aditiva: agrega `proyecto` y `trabajador_id` opcional con FK a `trabajadores`, permite ubicación sin coordenadas y crea una sobrecarga segura de `registrar_visita_tecnica_offline` con los dos datos nuevos. Conserva columnas, filas históricas, el UUID único y la función RPC antigua para permitir operaciones pendientes anteriores. **No fue aplicada**.

Antes de aprobar/aplicar:

1. Recuperar al directorio `supabase/migrations` la migración ACT06 vigente que creó las columnas `ubicacion_estado`, `ocurrio_en`, `payload_hash` y la función offline actual; no está en el directorio activo (solo aparece una copia antigua bajo `backups/`). La migración nueva requiere ese esquema previo.
2. Revisar el SQL en un entorno de desarrollo y validar que la definición real de constraints/función coincide con los metadatos consultados.
3. Aplicarla únicamente en Supabase de pruebas autorizado y verificar visita solo, con operario, sin GPS, reintento del mismo UUID y rechazo de mismo UUID con payload distinto.
4. En navegador HTTPS, comprobar permiso/denegación GPS, cámara real, identificación manual del coordinador correcto e incorrecto, QR de otro coordinador y selección de operario. Confirmar registros en el proyecto de prueba.
5. Probar entrada y salida por COT en ese mismo navegador después de servir el JS/cache v7, para verificar que la dependencia compartida no alteró ese flujo.

No se declara la funcionalidad validada end-to-end hasta aplicar la migración revisada y ejecutar esas pruebas manuales/de integración.

### Diagnóstico de la captura de visita pendiente

La captura muestra el mensaje de conectividad y un UUID pendiente. El UUID se conserva; no se reenvió ni se confirmó mediante esta revisión. El cliente clasificaba cualquier HTTP 503 como falta de conexión (`isConnectivityError`), aunque un 503 es una respuesta del servidor y puede señalar incompatibilidad RPC. En este estado hay una incompatibilidad concreta: los metadatos remotos exponen la función con 8 parámetros, mientras que el Flask actualizado envía 10 para incluir proyecto y operario. Hasta aplicar la migración nueva, Supabase no puede resolver esa llamada; Flask responde 503 y el cliente la presentaba erróneamente como desconexión. En el flujo de visitas el 503 ahora se trata como error del servidor, conserva la operación en IndexedDB y ofrece reintentarla con el mismo UUID, sin “Continuar sin conexión”. La clasificación compartida conserva el comportamiento anterior de asistencia por COT.

Además, una descarga HTTP GET de los dos CDN públicos devolvió el mismo archivo de `qr-scanner` 1.4.2 (16 082 bytes), pero el SRI configurado no coincidía con su SHA-512. El lector alternativo usaba ese mismo hash, así que el navegador rechazaba ambas cargas aunque los recursos estuvieran accesibles. Se actualizó el SRI de la plantilla y del cargador dinámico al hash verificado; el worker público respondió HTTP 200 en ambos CDN. Esta comprobación fue desde el entorno de desarrollo; no demuestra el permiso de cámara ni la carga desde el navegador de la usuaria.

No se obtuvo el registro de servidor de la petición concreta de la captura, por lo que no puedo afirmar que ese POST individual llegó a Supabase ni atribuirle un código interno de PostgREST observado. La discrepancia de firma y la clasificación errónea de 503 sí están comprobadas. La visita de la captura permanece pendiente hasta una respuesta con el mismo `operacion_id` y un registro devuelto.

### Corrección posterior: visita pendiente y carga del lector QR

Esta sección registra la verificación más reciente y prevalece sobre los conteos de pruebas de revisiones anteriores.

- Causa del aviso de desconexión: el cliente trataba HTTP 503 como pérdida de red. La aplicación envía 10 argumentos a la RPC de visita, mientras que el OpenAPI remoto leído en modo GET todavía publica la firma anterior de 8 argumentos. La discrepancia explica el error de servidor que el cliente clasificaba mal. No se obtuvo el log de esa solicitud específica, así que no se atribuye un mensaje interno exacto de PostgREST ni se afirma que el UUID de la captura se guardó en Supabase.
- Corrección: para visitas, una respuesta 503 ahora se conserva como rechazo/error del servidor; la operación sigue pendiente con su UUID y el usuario puede reintentar. La detección compartida de red del flujo COT conserva el comportamiento previo.
- Causa del fallo previo del lector: el hash SRI configurado no correspondía al recurso real `qr-scanner` 1.4.2. Se comprobó por HTTP GET el mismo contenido de 16 082 bytes en ambos CDN, y se verificó el SHA-512 nuevo contra el archivo descargado. El SRI y el cargador alternativo usan ese hash actualizado.
- `node tests/act06_client.test.cjs`: **23/23 pruebas simuladas aprobadas**, incluidas el tratamiento de HTTP 503 en visita, retención de UUID, alternativas de identificación y carga simulada del lector.
- Pruebas de rutas de visita con Flask/Supabase simulados: **11/11 aprobadas**. Pruebas estáticas de la migración nueva: **4/4 aprobadas**.
- Sintaxis: `py_compile` para `app.py` y pruebas Python, `node --check` para el cliente y service worker, y `git diff --check`: aprobados.
- Verificación externa de recursos: GET a ambos CDN confirmó HTTP 200 y coincidencia del nuevo SRI; esto no prueba permisos de cámara ni lector en el dispositivo real.
- El entorno no tiene `pytest` ni `qrcode` instalados. La invocación estándar de pytest no pudo ejecutarse; no se presentan las ejecuciones dirigidas con mocks como suite pytest ni como integración real.
- No se usó navegador real, cámara/GPS físicos ni se hicieron escrituras o migraciones en Supabase. La cola local de la usuaria no se leyó ni modificó; se desconoce desde este entorno el estado actual del UUID `efc26009-4076-479d-a529-fecb846cf2b3`.

Antes de volver a sincronizar la visita pendiente, recuperar/revisar la migración base ACT06 que no aparece en `supabase/migrations/` activa y aplicar primero ambas migraciones en un entorno Supabase de pruebas autorizado. Luego reintentar desde el dispositivo conservando el mismo UUID; comprobar la fila y respuesta del servidor. No borrar la base `asistencia-act06` ni crear una operación nueva para reemplazar esta.
6. Revisar el PDF de propuesta y el Excel oficial de cronograma, que no se encontraron en la carpeta del proyecto. Si contienen criterios más específicos que el documento maestro, actualizar esta matriz antes de entregar.

## Evidencias para recopilar

El documento maestro disponible pide evidencias reales de funcionamiento, estructura de datos, pruebas y documentación en términos generales; no contiene una lista específica de capturas para ACT06. Para sustentar este módulo, guardar evidencias reales de:

1. Salida de las pruebas dirigidas actuales: 12 pruebas cliente simuladas aprobadas, 6 pruebas Python de offline aprobadas y 28 pruebas Python de seguridad aprobadas; conservar el resultado de los fallos por migraciones ausentes como limitación visible. No se repitió la suite anterior de 37 pruebas.
2. Pantalla administrativa de trabajadores mostrando “Ver / imprimir QR” y vista imprimible de un trabajador ficticio; no incluir datos personales reales.
3. Escaneo con cámara y registro confirmado de entrada/salida por COT, usando trabajador y proyecto de prueba.
4. Visita técnica de prueba con ubicación concedida y confirmación de registro en el proyecto Supabase aislado.
5. Captura del esquema del entorno de prueba que muestre tablas, índice de turno abierto e índice QR, sin exponer claves.
6. Capturas de los casos de conflicto: entrada duplicada, trabajador inactivo con turno abierto y misma clave idempotente con datos diferentes.
7. Capturas en un dispositivo de prueba de directorio actualizado, modo avión, operación pendiente, reconexión/reintento y estado confirmado en Supabase; guardar también el estado de GPS denegado.

No se generaron capturas ni se presentan pruebas manuales como realizadas.

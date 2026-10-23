# Informe de validación ACT06

**Estado:** avance de código revisado y pruebas automatizadas locales aprobadas; pendiente validar la migración y el flujo con una instancia aislada de Supabase y dispositivos reales.

## Base documental y alcance

El documento maestro disponible establece que ACT06 se denomina **“Desarrollo del módulo de registro de asistencia e integración de sus funcionalidades”**, con fechas del **19 de octubre al 6 de noviembre de 2026**. También cita el OE2 oficial: **“Desarrollar e integrar los módulos de usuarios, de registro de asistencia con QR y geolocalización y novedades, sobre Flask y Supabase.”** La secuencia oficial reserva novedades para ACT07 y Google Sheets para ACT08; este trabajo no adelanta esas actividades.

El repositorio contiene `docs/ACT06-seguridad-y-reglas.md` y el documento maestro de continuidad adjunto. El maestro menciona `ACTIVIDAD 2 -presentacion de plan de trabajo.pdf` y `_Cronograma plan de trabajo.xlsx`, pero esos dos archivos no están disponibles dentro del proyecto inspeccionado. Por eso esta matriz usa el cronograma transcrito en el maestro y los requisitos de ACT06 dados directamente por la usuaria; no atribuye al PDF o al Excel detalles que no se pudieron revisar.

## Matriz de cumplimiento

| Requisito | Fuente y archivos/componentes | Resultado de revisión | Corrección / trabajo | Evidencia y estado |
|---|---|---|---|---|
| Módulo de asistencia integrado en Flask y Supabase | ACT06 del cronograma; `app.py`; migración `20261022_act06_asistencia_visitas.sql` | Hay rutas Flask y funciones RPC para lectura QR, entrada, salida y visita; la migración define tablas y funciones. | Se conserva el modelo de trabajadores y se añade una migración local para la persistencia del flujo. | Revisión de código y pruebas con mocks aprobadas. **Pendiente:** aplicar/verificar en Supabase de pruebas; no se ejecutó migración remota. |
| Registrar entrada y salida asociadas a COT/proyecto | Requisitos ACT06 de la solicitud; `app.py`; `static/js/asistencia.js`; migración | El frontend envía COT/proyecto al registrar entrada; la base registra hora con `clock_timestamp()` y cierra la fila abierta en salida. | Se mantiene la validación servidor/SQL y la respuesta de conflicto para turno abierto o salida inexistente. | Pruebas de rutas con RPC simulado, incluidas entrada válida, entrada duplicada y salida sin turno. **Pendiente:** recorrido integrado en Supabase de prueba. |
| Identificar trabajadores por QR | OE2 del maestro; columna `trabajadores.qr`; `app.py`; `templates/coordinador/registro.html`; `static/js/asistencia.js` | Se encontró que existían funciones generadoras, pero no se invocaban al crear personas. | SST/Operario recibe un valor aleatorio único al registrarse; el valor se guarda en la columna existente `qr`. Se añade índice único parcial y prevalidación de duplicados en la migración. | Prueba mock comprueba inserción del código y ausencia de cuenta Auth para Operario; prueba de colisión y PNG QR aprobadas. **Pendiente:** preflight de duplicados y migración en una base aislada. |
| Ver e imprimir el QR sin editar código | Requisito de la solicitud; `templates/personas.html`; nueva ruta en `app.py`; `templates/persona_qr.html`; `static/css/style.css` | La lista anterior solo mostraba el valor como texto o “Sin asignar”; no había vista de imagen ni impresión. | El administrador abre una vista protegida con la imagen QR y botón de impresión. Los trabajadores antiguos sin QR tienen acción protegida para asignarlo. | Prueba Flask simulada verifica la imagen embebida y el botón `window.print()`. **Pendiente:** comprobar legibilidad al imprimir/escaneo físico. |
| Escaneo real con cámara y alternativa manual | Requisito de la solicitud; `static/js/asistencia.js` y plantilla del coordinador | Implementado con `BarcodeDetector` y `getUserMedia`; existe entrada manual para navegadores no compatibles. | No se reemplazó el lector existente. | Sintaxis JavaScript aprobada. **Pendiente manual:** usar HTTPS y navegador/dispositivo que soporte cámara; comprobar permisos y lectura de una tarjeta impresa. |
| Reglas de activo/inactivo e impedir entradas duplicadas | Solicitud ACT06; rutas Flask; funciones SQL | El servidor permite entrada solo a trabajador activo; el índice parcial limita a un turno abierto por trabajador. La salida no exige que el trabajador siga activo y solo actualiza su fila abierta. | Se documenta que una persona inactiva puede cerrar la entrada pendiente, pero no iniciar una nueva; las filas históricas cerradas no se alteran. | Prueba de sesión inactiva y pruebas de conflicto con RPC simulado; regla e índice revisados en código. **Pendiente:** verificar concurrencia y datos de prueba en PostgreSQL. |
| Visita técnica con geolocalización | OE2 del maestro incluye geolocalización; solicitud actual; `static/js/asistencia.js`; `app.py`; migración | El coordinador obtiene ubicación del navegador; se validan tipos/rangos y se envía al servidor, que asocia el perfil coordinador. | La migración almacena coordenadas, precisión y tiempo del servidor. Los reintentos reutilizan exactamente el cuerpo y la clave idempotente. | Prueba local mock para coordenadas inválidas y conflicto de clave. **Pendiente:** permiso GPS, ubicación precisa, persistencia y política de privacidad en dispositivo/base de prueba. |
| Idempotencia y prevención de registros inconsistentes | Requisito de la solicitud; función `registrar_visita_tecnica`; `asistencia.js` | La función SQL conserva el registro anterior para misma clave y mismos datos; rechaza la misma clave con coordinador, coordenadas o precisión diferentes. | Flask convierte el rechazo explícito en HTTP 409; el cliente conserva el cuerpo para reintentar la misma operación. | Prueba simulada del HTTP 409 y revisión estática del SQL. **Pendiente:** ejecutar ambos escenarios contra PostgreSQL aislado. |
| Sesión, autorización y CSRF | Solicitud ACT06; `app.py`; formularios en `templates/`; `asistencia.js` | Las rutas comprueban perfil/estado contra datos servidor; POST/PUT/PATCH/DELETE exigen token de sesión. | Se añadió CSRF en formularios HTML y cabecera API; el cambio de estado informa que las sesiones abiertas se vuelven a validar. | Pruebas para token ausente, inválido, válido, plantilla coordinador y sesión inactiva aprobadas. |
| Protección de claves y depuración | Solicitud ACT06; `app.py`; `.env` | La clave service role se usa solo en código servidor; no aparece en `static/` ni plantillas. El acceso de login ya no registra el cuerpo de error del proveedor. | `app.run(debug=False)`. `.env` no se leyó ni modificó durante este trabajo. | Prueba estática de ausencia de clave en recursos públicos; inspección del código. No se hizo despliegue. |
| Dependencias | Solicitud ACT06; `requirements.txt` | `qrcode` y `Pillow` están declarados para producir PNG; `pytest` está declarado para ejecutar la suite. | No fue necesario cambiar el archivo. | Inspección del manifiesto. El entorno `.venv` no tiene pytest/qrcode; el entorno `venv` sí pudo ejecutar la suite y generar el PNG. |

## Cambios realizados

- `app.py`: generación/consulta de unicidad del QR, asignación al registrar trabajadores operativos, rutas administrativas protegidas para vista/impresión y reparación de códigos faltantes, protección CSRF y validaciones existentes de ACT06. El cambio de estado también comunica correctamente que las rutas consultan el nuevo estado en sesiones abiertas.
- `templates/personas.html`: enlace de visualización/impresión o acción CSRF para generar QR faltante.
- `templates/persona_qr.html`: nueva vista imprimible con nombre e identificación.
- `static/css/style.css`: presentación y reglas de impresión del QR junto al estilo ACT06 ya existente.
- `supabase/migrations/20261022_act06_asistencia_visitas.sql`: comprobación de duplicados QR e índice único parcial, tablas/funciones de asistencia y visitas, protección de turno abierto e idempotencia.
- `tests/test_act06_security.py`: pruebas de CSRF, roles/sesión, entradas/salidas, visitas e idempotencia con mocks, generación/colisión/almacenamiento/imagen/impresión de QR.
- `docs/ACT06-seguridad-y-reglas.md`: reglas técnicas y pasos manuales.
- `docs/ACT06-informe-validacion.md`: esta matriz y estado de validación.
- `templates/login.html`, `templates/panel.html`, `templates/administrador/dashboard.html`, `templates/persona_form.html`, `templates/usuarios.html`: token CSRF para sus formularios POST.
- `templates/coordinador/registro.html` y `static/js/asistencia.js`: sincronización del token CSRF para el flujo de coordinación; se conserva cámara, modo manual y reintento GPS.
- `backups/act06-before-review-20261022-124543/`: copia de los archivos relevantes previa a esta ronda de correcciones.

## Pruebas realizadas

| Comprobación | Resultado |
|---|---|
| `python -m py_compile app.py` | Aprobado. |
| `python -m pytest -q tests/test_act06_security.py` (usando el intérprete de `venv`) | **21 passed**. Pytest avisó que no pudo actualizar `.pytest_cache`; la misma suite también pasó con el plugin de caché deshabilitado. |
| `node --check static/js/asistencia.js` | Aprobado. |
| Compilación Jinja de ocho plantillas relacionadas | Aprobada. |
| `git diff --check` | Aprobado; Git solo reportó avisos de conversión LF/CRLF de Windows. |
| Supabase remoto / PostgreSQL | No ejecutado: no se realizaron escrituras, no se aplicó migración y no había `psql` ni `pglast` disponibles. |
| Cámara, impresión y GPS físico | No ejecutado; requiere navegador/dispositivo de la usuaria. |

Las pruebas de rutas sustituyen Auth/Supabase mediante mocks; no prueban red, restricciones reales, políticas RLS ni ejecución de funciones PostgreSQL. El test de QR de imagen valida que la librería produce un PNG, no que una cámara física lo lea.

## Pendientes para validar ACT06

1. Revisar en una base aislada si existen QR duplicados no vacíos antes de aplicar la migración. La migración aborta con un mensaje si los encuentra.
2. Aplicar la migración solo en el proyecto local/de prueba autorizado y comprobar tablas, índice, grants y funciones; todavía no se aplicó en ningún Supabase.
3. Con datos ficticios en esa base, probar entrada, salida, dos entradas concurrentes, trabajador inactivo con turno abierto y ambos casos de idempotencia.
4. Desde un celular o navegador HTTPS, probar permiso de cámara, escaneo del QR impreso, alternativa manual y GPS. Confirmar las filas creadas y horas devueltas.
5. Confirmar la decisión académica de conservar coordenadas/precisión GPS y asociar la visita al coordinador. La responsabilidad del coordinador proviene de la decisión previa de la usuaria; la retención de ubicación requiere aprobación/procedimiento de la empresa si no está definido en la propuesta.
6. Revisar el PDF de propuesta y el Excel oficial de cronograma, que no se encontraron en la carpeta del proyecto. Si contienen criterios más específicos que el documento maestro, actualizar esta matriz antes de entregar.

## Evidencias para recopilar

El documento maestro disponible pide evidencias reales de funcionamiento, estructura de datos, pruebas y documentación en términos generales; no contiene una lista específica de capturas para ACT06. Para sustentar este módulo, guardar evidencias reales de:

1. Salida de `pytest` con los 21 casos aprobados y de las comprobaciones de sintaxis.
2. Pantalla administrativa de trabajadores mostrando “Ver / imprimir QR” y vista imprimible de un trabajador ficticio; no incluir datos personales reales.
3. Escaneo con cámara y registro confirmado de entrada/salida por COT, usando trabajador y proyecto de prueba.
4. Visita técnica de prueba con ubicación concedida y confirmación de registro en el proyecto Supabase aislado.
5. Captura del esquema del entorno de prueba que muestre tablas, índice de turno abierto e índice QR, sin exponer claves.
6. Capturas de los casos de conflicto: entrada duplicada, trabajador inactivo con turno abierto y misma clave idempotente con datos diferentes.

No se generaron capturas ni se presentan pruebas manuales como realizadas.

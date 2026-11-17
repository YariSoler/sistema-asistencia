# Diagnóstico de Supabase y diseño de corrección transaccional

## Estado de la evidencia

Este informe diferencia tres fuentes: código/migraciones locales inspeccionados; hallazgos remotos resumidos por la usuaria; y datos de catálogo todavía no disponibles en el repositorio. No se ejecutó el diagnóstico contra Supabase: en el entorno actual no hay `psql`, URL SQL ni pestaña/sesión Supabase abierta. Por tanto, no se inventan las definiciones remotas completas ni se declara verificada la atomicidad.

| Objeto/tema | Migración o llamada local | Hallazgo remoto aportado | Lo que falta para confirmar |
|---|---|---|---|
| `act06_operaciones` | No hay DDL de tabla versionado en `supabase/migrations` actual | Es parte del ledger usado por funciones offline | Columnas, PK/FK, estado/resultado, restricciones, índices, RLS, ACL y triggers |
| `act06_sheets_outbox` | No hay DDL de tabla versionado localmente | Asistencia offline y visita offline de 8 argumentos escriben eventos; visita offline de 10 y RPC tradicionales no | Columnas, tipos, relación/unique por operación, tipos admitidos, estados, índices, triggers, RLS y ACL |
| Entrada/salida | Flask usa RPC offline; con observaciones usa wrappers compatibles que llaman a la offline | Offline crea operación, resultado y outbox; tradicionales no | Firma/cuerpo remoto y prueba en PostgreSQL de rollback/atomicidad/concurrencia |
| Visitas | Flask usa exclusivamente `registrar_visita_tecnica_offline` de 10 argumentos. La migración local 20261023 define esa variante y hace upsert idempotente en visitas, sin referencias a ledger/outbox | Existe una variante de 8 argumentos que sí crea operación/outbox; la de 10 argumentos guarda visita sin dichos eventos. La tradicional obliga coordenadas | Firmas completas de todas las sobrecargas, DDL remoto y dependencias; RLS/ACL exactos |
| GPS de visitas | La función local de 10 argumentos valida `p_ubicacion_obtenida` y admite coordenadas nulas si es false; la función tradicional antigua de migración exige coordenadas | La tradicional remota mantiene la exigencia | Confirmar cuerpos remotos y checks remotos de latitud/longitud |
| Motivo/observaciones de visita | No están en el formulario, payload Flask ni columnas añadidas por migración local | La decisión funcional es incorporarlos | Confirmar que no existan como campos equivalentes, JSON o tabla relacionada; el formulario necesita controles compatibles con su distribución actual |
| Novedades | Migración local define `registrada`, `anulada`; migración siguiente agrega `archivada` y conserva índices/consultas basados en esos estados | Los estados actuales no coinciden con los estados funcionales acordados | Definición remota actual de checks e índices parciales. La decisión ya es preservar los tres estados antiguos y añadir cuatro nuevos sin convertir filas |
| Fórmulas | Hoja existente tiene fórmula tipo `salida - entrada - 1,25` en HORA | La regla acordada resta 1,25 h una vez al día y nunca deja valor negativo | Fórmula actual coincide solo para un tramo cerrado; en varios tramos incluye interrupciones y no sirve para sumar duraciones individuales |

El script único de consulta está en [supabase/diagnostics/supabase_readonly_diagnostic.sql](../supabase/diagnostics/supabase_readonly_diagnostic.sql). Incluye columnas, restricciones, índices, RLS/ACL, funciones y sobrecargas, triggers, permisos de funciones, dependencias registradas y descubrimiento de tablas por nombres relacionados. Solo contiene consultas de catálogo `SELECT`/`WITH`; los cuerpos de funciones enmascaran asignaciones literales asociadas a nombres comunes de credenciales. No devuelve filas de negocio. Debe ejecutarse por completo desde SQL Editor y exportarse por cuadrícula. Las referencias dinámicas PL/pgSQL pueden no aparecer en `pg_depend`, por eso se entregan también los cuerpos de funciones.

No se obtuvo un esquema remoto completo en esta ejecución. El resultado aportado en el mensaje contiene los hallazgos funcionales resumidos, pero no las columnas, firmas ni expresiones necesarias para escribir con seguridad la migración final. Por esa razón no se creó una migración especulativa.

## Cambios locales seguros realizados

- La proyección diaria suma tramos cerrados, descuenta 1,25 horas una sola vez y aplica mínimo cero.
- Tramos superpuestos o incoherentes se rechazan antes de proyectar.
- La nota de tramos queda en INGRESO.
- Se conserva la fórmula existente para un único tramo cerrado cuando la lectura posterior verifica el resultado; para varios tramos, la fórmula no se modifica y el evento queda pendiente.
- Se añadieron pruebas locales para regla diaria, fórmulas, visita de 10 argumentos e idempotencia de flujo simulado. No modifican el formulario ni Supabase.

Archivos locales de esta preparación: `integrations/sheets/projection.py`, `integrations/sheets/client.py`, `tests/test_sheets_integration.py`, `tests/test_attendance_security.py`, este informe y `supabase/diagnostics/supabase_readonly_diagnostic.sql`.

## Migraciones que se deben preparar tras el resultado consolidado

1. Compatibilidad idempotente/transaccional entre RPC existentes y outbox, conservando todas las firmas vigentes y añadiendo/normalizando los eventos aprobados.
2. Unificación de las tres firmas de visita mediante una rutina común, incluyendo motivo/observaciones, GPS opcional, proyecto y participante; la función de 10 argumentos debe crear ledger, resultado y evento outbox en la misma transacción.
3. Extensión del CHECK de outbox con los seis tipos de eventos aprobados, conservando y validando registros existentes.
4. Estados de novedades: permitir nuevos cuatro estados además de `registrada`, `anulada`, `archivada`; conservar filas y actualizar default de nuevas novedades y consultas/índices parciales.
5. Productores de eventos para traslados, novedades, correcciones y ciclo de vida de trabajadores, solo en la misma transacción que cada cambio de negocio.

No se creó todavía ningún archivo de migración porque faltan las columnas destino del outbox, la expresión/nombre de restricciones actuales, las tres firmas completas de visitas y los índices/triggers/ACL que deben conservarse. Con el SQL consolidado se puede producir una sola migración versionada revisable y pruebas alineadas, sin repetir consultas separadas.

## Resultado de la inspección local

La ruta Flask `POST /api/asistencia/entrada` elige `registrar_entrada_asistencia_act07` cuando hay observaciones y `registrar_entrada_asistencia_offline` cuando no las hay. El wrapper local para observaciones llama a la función offline dentro de la misma invocación SQL y luego guarda observaciones. La salida sigue el mismo patrón con `registrar_salida_asistencia_act07` o su variante offline.

La ruta `POST /api/visitas-tecnicas` siempre llama a `registrar_visita_tecnica_offline` con la variante de 10 argumentos: coordinador, latitud, longitud, precisión, indicador GPS, hora, UUID, hash, proyecto y participante opcional. No se encontró una llamada Flask a `registrar_visita_tecnica` tradicional ni a la variante offline de 8 argumentos. La migración local `20261023_act06_visitas_proyecto_participante.sql` contiene el cuerpo de 10 argumentos; inserta/idempotentiza la fila de visita, pero no contiene escrituras a `act06_operaciones` ni `act06_sheets_outbox`. El usuario reporta que el cuerpo remoto de 8 argumentos sí genera esos eventos; esa definición no está versionada localmente.

La función tradicional de visitas y sus coordenadas obligatorias son un hallazgo del diagnóstico remoto aportado por el usuario; no se usa en el endpoint Flask actual. La función local de 10 argumentos sí valida el indicador explícito y permite ubicación `no_disponible` sin coordenadas.

La ruta de visita y la plantilla actuales no envían ni presentan `motivo` u `observaciones`; la migración local de visitas no añade esas columnas. La plantilla solo recoge proyecto/lugar y participante opcional. La nueva orden autoriza agregar esos campos manteniendo el estilo y la distribución; el cambio de interfaz queda acoplado a la firma y columnas confirmadas para que los campos no se pierdan.

## Diseño de la migración (no ejecutable todavía)

No se creó un archivo SQL de migración porque el resumen recibido no incluye las definiciones completas de las tablas, las columnas, las restricciones, las firmas exactas de la variante de 8 argumentos ni las RPC/triggers actuales. En particular falta el DDL de `act06_operaciones` y `act06_sheets_outbox`. Inventar esos contratos podría hacer que la migración falle a mitad, duplique eventos o deje incompatibles las firmas que el usuario pide conservar.

Con los resultados de catálogo completos, preparar una migración aditiva/reversible por estas responsabilidades:

1. **Núcleo de evento:** rutina transaccional interna que reciba el UUID estable y el hash del payload canónico, inserte o recupere `act06_operaciones`, aplique la escritura de negocio, guarde el resultado retornable y cree exactamente un evento outbox. Igual UUID con payload distinto debe fallar explícitamente. Igual UUID y mismo payload debe retornar el resultado anterior.
2. **Asistencia:** conservar las firmas tradicionales, offline y de observaciones existentes. Las firmas públicas se vuelven wrappers compatibles del mismo núcleo; las operaciones con observaciones no deben ejecutar una segunda escritura ajena a la idempotencia. La entrada se protege con la restricción única de turno abierto y la concurrencia se valida con llamadas paralelas en una base aislada.
3. **Visitas:** conservar ambas firmas offline y la firma tradicional como wrappers. Unificar autorización, GPS opcional, validación de participante, idempotencia y operación/outbox en una sola transacción. La variante de 10 argumentos debe incluir proyecto y participante en el hash y en la comparación de conflicto; nunca debe delegar en dos RPC separadas desde Flask. La firma tradicional debe conservar su UUID existente si realmente lo tiene.
4. **Campos de visita:** añadir `motivo` y `observaciones` a persistencia y al hash idempotente; comprobar primero si ya existen columnas equivalentes o una relación de detalle. Incluir controles en el formulario sin rediseñar su estructura.
5. **Tipos de outbox:** reemplazar la restricción identificada por catálogo para admitir eventos de asistencia, visitas, traslados, novedades, correcciones y cambios de trabajador. Antes de elegir literales y payload se deben revisar tipo de columna, consumidores y reglas existentes. Una actualización de restricción sin esos datos podría bloquear eventos ya guardados.
6. **Novedades:** ampliar la restricción para permitir `pendiente`, `aprobada`, `rechazada`, `cancelada` y conservar como valores históricos válidos `registrada`, `anulada` y `archivada`. No actualizar ni convertir filas antiguas. Revisar y adaptar consultas/índices parciales para mantener las lecturas históricas y hacer que las nuevas acciones utilicen los estados funcionales. No se requiere un mapeo de históricos; sí confirmar la restricción remota exacta y sus dependencias.
7. **Eventos administrativos:** generar outbox en la misma transacción que cambios de trabajador, novedades, correcciones y traslados. Una corrección debe conservar original, valor nuevo, motivo, responsable y timestamp; no se debe sobrescribir asistencia histórica.

## Pruebas requeridas en una base aislada

| Caso | Resultado esperado |
|---|---|
| Misma operación y mismo payload en dos solicitudes | Mismo resultado; una operación de negocio y un evento outbox |
| Mismo UUID con payload distinto | Rechazo explícito; no altera el resultado ni crea otro evento |
| Dos entradas simultáneas del mismo trabajador | Una sola entrada abierta; la otra obtiene conflicto controlado |
| Salida sin entrada, salida repetida o anterior a entrada | Rechazo; estado original intacto |
| Entrada/salida con y sin observaciones | Firma compatible, mismo núcleo transaccional y un solo evento |
| Visita 8 argumentos, 10 argumentos y tradicional | Cada firma anterior sigue resolviendo; una visita/operación/outbox por UUID |
| GPS no disponible | Coordenadas NULL con estado explícito; registro aceptado |
| Reintento de visita con mismo UUID/datos o UUID/datos distintos | Recuperación exacta o conflicto explícito |
| Error forzado al insertar outbox | Rollback de operación y resultado de negocio en esa transacción |
| Google Sheets no disponible luego de confirmar Supabase | Registro y outbox persisten; evento queda reintentable sin duplicar negocio |
| Eventos simultáneos / varios coordinadores | Reserva/orden no pierde eventos ni adelanta salida sobre entrada |
| Estados de novedades | Transiciones permitidas respetan el flujo y reportes; no cambian silenciosamente estados existentes |
| Cambios de persona/corrección/traslado | Evento único, ordenado, trazable y sin borrar historial |

Las pruebas concurrentes no se pueden simular con mocks de Flask; requieren una base de pruebas PostgreSQL/Supabase aislada. No ejecutar estos casos en producción.

## Información necesaria para generar SQL aplicable

Ejecutar una sola vez el script completo `supabase/diagnostics/supabase_readonly_diagnostic.sql` desde SQL Editor; exportar todas sus cuadrículas. Con eso se obtienen las tablas, restricciones, índices, RLS/ACL, sobrecargas completas de funciones, triggers y dependencias registradas de las relaciones con nombres relacionados. Compartir el export sin filas de negocio ni valores sensibles. No hay que ejecutar consultas separadas.

Comparar ese resultado con las migraciones locales antes de redactar la versión final de las migraciones. No ejecutar migraciones ni otorgar permisos como parte de esta preparación.

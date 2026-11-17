# Preparación local de integración con Google Sheets

## Plan anual 2026

La planilla remota no se modifica desde este proyecto. `integrations.sheets.layout.build_annual_layout(2026)` describe una hoja con A=NOMBRES, B=CARGO, cuatro columnas por día (PROYECTO, INGRESO, SALIDA, HORA) y una columna de total al final de cada mes. Para 2026 son 365 bloques diarios, 12 totales mensuales y 1.474 columnas incluyendo A y B. El constructor solo genera posiciones; no crea pestañas, celdas, fórmulas ni formato.

La hoja leída actualmente no contiene esa cobertura anual: tiene encabezados diarios del 11 de noviembre al 1 de diciembre de 2026 y una columna de total entre noviembre y diciembre. La cuadrícula tiene 123 columnas; el contenido de encabezados llega a CI y las 36 columnas siguientes están vacías. Hay fórmulas de horas en la fila de ejemplo para los 21 días; esas celdas se protegen y el escritor se niega a reemplazarlas.

La ampliación local propuesta conserva las celdas actuales: inserta 1.266 columnas antes de C para completar del 1 de enero al 10 de noviembre, conserva los bloques existentes del 11 de noviembre al 1 de diciembre y agrega 121 columnas para el 2 al 31 de diciembre más el total mensual. De las 121 finales, 36 caben en la cuadrícula vacía actual y se agregan 85 al final. El total esperado es 1.474 columnas. A1:B2 conserva sus dos celdas combinadas. Para copiar formato se usaría el bloque diario C:F y la columna de total CE como patrón, solo con `PASTE_FORMAT`; los anchos observados del bloque diario son 111, 75, 62 y 50 píxeles, y CE tiene 129 píxeles. Los valores de encabezado se escribirían únicamente en las celdas nuevas. Ninguna de estas solicitudes se ha aplicado.

No se propagan fórmulas de horas ni totales: las fórmulas actuales descuentan 1,25 y el total mensual de ejemplo está vacío. La regla acordada es restar 1,25 una sola vez a la suma diaria de tramos cerrados, con mínimo cero. La fórmula `salida - entrada - 1,25` coincide con esa regla para un solo tramo cerrado; no puede representar varios tramos porque incluiría las interrupciones como tiempo trabajado. Por eso se conserva y verifica en jornadas de un tramo, y se bloquea el bloque existente en jornadas múltiples hasta definir una celda/estrategia compatible; nunca se reemplaza silenciosamente la fórmula.

## Proyección de asistencia

`project_day` agrupa tramos cerrados de un trabajador para una fecha local de Bogotá. Produce el primer proyecto, la primera entrada, la última salida y una nota cronológica con COT/proyecto/entrada/salida/duración de cada tramo. La suma de duraciones cerradas se reduce por una única deducción diaria de 1,25 horas, con mínimo cero; no se descuentan pausas por tramo. Los tramos que cruzan medianoche se rechazan porque no hay una regla para asignar sus horas entre jornadas. Novedades solo agregan etiquetas generales a la nota; no se exponen motivo, observaciones ni detalles de incapacidad. Las visitas técnicas no se mezclan en horas de asistencia; la hoja no tiene una sección confirmada para proyectarlas.

La salida del proyector no cambia fórmulas. Si HORA contiene una fórmula existente, se conserva y solo se permite proyectar un único tramo cerrado; el valor efectivo se comprueba después de escribir proyecto/ingreso/salida. Con varios tramos, tramo abierto o fórmula en otra celda, el evento queda pendiente/conflicto y no se altera el bloque. Ante cambios manuales no explicados por la última proyección, se cancela la escritura. El escritor actualiza solo `userEnteredValue` y la nota de INGRESO; el formato queda fuera de la máscara de escritura.

## Identidad de fila

La fila se busca por Developer Metadata con clave `sistema_asistencia_trabajador_id_<año>` y valor `trabajadores.id`. La asociación inicial debe aprobarse manualmente y se crea como metadata de fila; nunca se resuelve por nombre. La hoja inspeccionada no tenía Developer Metadata.

## Permiso de escritura

El alcance requerido es `https://www.googleapis.com/auth/spreadsheets`. La lectura mantiene `https://www.googleapis.com/auth/spreadsheets.readonly`. Solicitar el alcance de escritura no concede el rol Editor del archivo: la cuenta de servicio debe tener permiso de edición en Drive. Ninguno de esos cambios se ejecuta desde aquí.

## Reintentos y outbox

Las actualizaciones son deterministas sobre celdas exactas y conservan el UUID de la operación. El procesador exige un lease distribuido por trabajador/día para evitar que dos procesos proyecten estados fuera de orden. El adaptador Supabase no implementa ese lease ni marca eventos como sincronizados. El consumidor de outbox, su reserva, la atomicidad y el acuse en Supabase quedan bloqueados hasta revisar funciones, restricciones y triggers remotos con `supabase/diagnostics/supabase_readonly_diagnostic.sql`.

La detección manual compara las celdas con el último hash confirmado y vuelve a leer tras escribir. Google Sheets no ofrece compare-and-swap de celdas para `batchUpdate`; una persona aún podría editar entre la lectura y escritura. Para eliminar esa carrera se debe acordar una ventana de sincronización o aprobar protección del rango. El código no cambia permisos ni protege rangos automáticamente.

## Ejecución y limpieza de pruebas

Cada ejecución usa `TestRunManifest` con `test_run_id`, UUID por operación, trabajador sintético y rangos exactos. El manifiesto se guarda fuera de Git por quien ejecute la prueba. La limpieza solo genera solicitudes `repeatCell` para rangos cuyo hash leído coincide con el escrito por esa ejecución y solo limpia `userEnteredValue` y `note`; conserva formatos. Si cambió el contenido, la limpieza se cancela.

El manifiesto no borra asistencia ni novedades de Supabase. La limpieza de esos registros necesita conocer las claves foráneas, referencias de outbox y política de retención, y requiere aprobación antes de ejecutarse.

## Primera prueba funcional controlada (requiere autorización para escribir)

Esta intervención no crea registros ni cambia la hoja. Para iniciar una prueba real, primero deben estar resueltos estos bloqueos: permiso Editor de la cuenta de servicio en la planilla, OAuth con alcance `spreadsheets`, pestaña anual completa, mapeo revisado de una fila sintética a `trabajadores.id`, y confirmación SQL de que la RPC y outbox pueden aceptar y reservar el evento de manera segura. No reutilizar una fila de una persona real.

1. Aprobar una ventana de prueba y crear en Supabase un trabajador sintético activo con identificador único de la ejecución. Guardar su `trabajadores.id` en un manifiesto `TestRunManifest`; no usar nombres de personas reales.
2. En Sheets, elegir una fila vacía exacta y revisar visualmente el bloque del día. Después de aprobar la asociación, crear Developer Metadata para esa fila con el ID del trabajador. Registrar en el manifiesto `test_run_id`, `worker_id`, `sheet_id`, fila y rangos A1 exactos. La operación no debe decidir una fila por nombre.
3. Usar como proyecto/COT el marcador `PRUEBA-SHEETS-<test_run_id>`. Registrar entrada, salida y una nueva entrada/salida, y repetir en un segundo proyecto el mismo día. Cada solicitud reutiliza su propio UUID estable en reintentos; no inventar UUID nuevo para repetir la misma operación.
4. Verificar en Supabase cada tramo cerrado y el evento outbox relacionado. Confirmar que no se duplicó ningún tramo/outbox después de repetir la misma petición y que una tercera transición vuelve a ser entrada. Revisar timestamps como `America/Bogota`.
5. En Sheets, leer el bloque exacto de cuatro celdas de ese trabajador/día. Debe mostrar el primer proyecto, primera entrada, última salida, suma de duración de tramos cerrados y la nota cronológica con cada proyecto, COT, entrada/salida y duración. En otra pestaña de día, una fórmula existente debe seguir intacta y el escritor debe negarse a modificarla.
6. Probar reintento después de una respuesta ambigua: conservar el UUID del evento, revisar el bloque antes de reintentar y confirmar el mismo estado. Simular un fallo entre batchUpdate y lectura de verificación; no se permite marcar el outbox sincronizado sin readback exacto.
7. Guardar el manifiesto fuera del repositorio. Tras revisar el resultado, leer nuevamente solo los rangos registrados y comparar su hash. La limpieza de Sheets solo se puede ejecutar con aprobación y si el hash coincide; limpia exclusivamente valores/notas de esos rangos, nunca formato. El borrado del trabajador/eventos en Supabase es otro procedimiento, bloqueado hasta revisar FKs/outbox y aprobarlo expresamente.

No ejecutar la prueba contra datos de asistencia real ni habilitar un consumidor automático hasta que exista el adaptador Supabase con reserva distribuida, acuse y conflicto implementados según las definiciones SQL verificadas.

## Resultados SQL requeridos antes de habilitar sincronización

Ejecutar en el SQL Editor el archivo `supabase/diagnostics/supabase_readonly_diagnostic.sql`, exportar los resultados completos de las secciones de columnas/restricciones/índices, RPC, triggers, RLS/privilegios, y relación outbox-operación. Compartir los resultados sin filas de negocio ni secretos. Necesitamos el cuerpo de las funciones de entrada/salida, offline, visitas y novedades, así como triggers y restricciones de `act06_operaciones` y `act06_sheets_outbox`. La API REST no sustituye esta evidencia del catálogo.

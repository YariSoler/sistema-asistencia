# ACT06: seguridad y reglas de asistencia

## Solicitudes POST y CSRF

Flask crea un token aleatorio por sesión y lo valida en todas las solicitudes que cambian estado (`POST`, `PUT`, `PATCH` y `DELETE`). Los formularios HTML lo envían como `csrf_token`; el JavaScript de asistencia lo envía en `X-CSRF-Token`, usando el valor que entrega la plantilla en una etiqueta `meta`. Una solicitud sin token o con un valor distinto se rechaza con HTTP 400 antes de ejecutar su ruta. Tras iniciar sesión se limpia la sesión anterior y Flask crea un token nuevo para la sesión autenticada.

## Visitas técnicas e idempotencia

La clave UUID identifica un intento de visita. Si se reenvía con el mismo coordinador, latitud, longitud y precisión GPS, la función SQL devuelve el registro anterior y no crea otra visita. Si alguno de esos datos difiere, la función rechaza la solicitud con `IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_DATA`; Flask informa HTTP 409. El navegador conserva el mismo cuerpo y la misma clave después de un error de red para que el reintento sea idéntico. Una nueva visita obtiene una clave distinta.

## Entradas, salidas e inactividad

- El índice único parcial de `registros_asistencia` permite como máximo una fila por trabajador con `fecha_salida IS NULL`; la base de datos mantiene esta garantía aunque dos solicitudes de entrada coincidan.
- Una entrada nueva requiere que trabajador y coordinador estén activos y que el trabajador tenga perfil de trabajador.
- Un trabajador que se desactiva con un turno abierto no puede iniciar otro turno. Puede escanearse su QR únicamente para cerrar esa entrada pendiente; la salida solo completa `fecha_salida` en esa fila abierta.
- No se borran ni se reescriben filas históricas. El registro abierto conserva su fecha, proyecto, COT y coordinador de entrada.

## QR de trabajadores operativos

Al registrar SST u Operario, Flask genera un identificador aleatorio, comprueba que no esté asignado y lo guarda en `trabajadores.qr`. Los coordinadores también reciben un QR único, vinculado a la misma fila que contiene su `auth_user_id`; la migración aplica unicidad global parcial sobre la columna existente. En Gestión de personas, el administrador puede abrir e imprimir el QR para ambos perfiles; los registros antiguos sin código tienen una acción protegida y condicional para asignarlo sin reemplazar el código si otra persona se adelantó. Los administradores no reciben QR operativo. El valor no se muestra en el listado ni se registra en logs.

El QR no inicia sesión ni concede permisos. Las rutas de asistencia y visita primero verifican desde Supabase que existe una sesión activa de coordinador. Para el propio turno, el QR debe resolver a ese mismo coordinador. Para trabajadores, se permite entrada solo si están activos; una salida abierta se puede cerrar aunque el trabajador haya sido desactivado. La función SQL verifica también el perfil y el vínculo de identidad antes de escribir.

Para registrar una visita, el coordinador escanea su QR dentro de la sesión ya iniciada. Flask comprueba el perfil coordinador y que el id coincida con la sesión; al guardar vuelve a realizar esa comprobación y envía a SQL el identificador derivado de la sesión, no uno proporcionado por el navegador. La clave de idempotencia y coordenadas conservan sus validaciones existentes.

## Configuración sensible

`SUPABASE_SERVICE_ROLE_KEY` se utiliza únicamente en `app.py` en llamadas servidor a servidor y en el cliente servidor de Supabase. No debe incluirse en HTML, JavaScript, CSS, reportes ni registros. No se modificó `.env`. La llamada directa `app.run` mantiene `debug=False`; en producción se debe usar el servidor WSGI configurado para el despliegue.

## Verificación manual antes de aplicar la migración

1. Revisar la migración `20261022_act06_asistencia_visitas.sql` y aplicarla primero en una instancia local/de pruebas de PostgreSQL/Supabase.
2. Probar dos entradas concurrentes del mismo trabajador: solo una debe quedar abierta.
3. Repetir una visita con la misma clave y los mismos valores: debe devolverse el mismo `id`; cambiar precisión o coordenadas con esa clave debe producir HTTP 409 y no añadir una fila.
4. Desactivar un trabajador que tenga entrada abierta: el escaneo debe ofrecer solo salida; la salida debe cerrar la fila y una entrada nueva debe rechazarse.
5. Comprobar desde el navegador que el token CSRF viaja en solicitudes API y que omitirlo o alterarlo produce HTTP 400.
6. Confirmar en el proyecto Supabase de prueba las políticas/permisos de `service_role` y las tablas creadas. Esta revisión no aplica la migración ni escribe en Supabase.

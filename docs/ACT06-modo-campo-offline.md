# ACT06: operación de campo sin conexión

La pantalla **¿Qué vas a registrar?** muestra solo las opciones de asistencia por COT y visita técnica. El estado de conexión, el directorio local y la cola se consultan desde **Directorio y operaciones pendientes** dentro de los flujos; esa pantalla no elimina ni reinicia operaciones de IndexedDB.

## Correcciones de interfaz y reintento (23 de octubre de 2026)

- Se retiró por completo el formulario para escribir el contenido del QR; quedan la cámara y la búsqueda por identificación.
- Las plantillas autenticada y offline mantienen los mismos IDs DOM que consume el JavaScript, incluido el mensaje de resultado de búsqueda. Se agregó una prueba que compara todos los selectores literales con ambas plantillas, más una prueba cliente del flujo de búsqueda.
- La aplicación distingue errores de red detectados en `fetch`, timeout y servicio no disponible de errores JavaScript y respuestas HTTP de autorización o validación. Solo el primer grupo ofrece **Continuar sin conexión**; los rechazos quedan visibles para revisión.
- Los nodos de estado y sincronización ya no aparecen en la pantalla principal. La sincronización confirma una operación local solo cuando la respuesta del servidor devuelve el mismo UUID y un registro; una excepción visual posterior no se toma como señal para reenviar una operación confirmada.
- El JavaScript valida el contrato de IDs al iniciar y centraliza las escrituras de texto. Si falta un nodo, escribe en la consola un diagnóstico con archivo, línea, selector y tipo de operación, sin registrar nombre, cédula, token o contenido del formulario. Antes de mostrar error en confirmación, consulta IndexedDB: `confirmada` requiere el acuse del servidor con el UUID coincidente; los demás estados se muestran como locales no confirmados.
- El service worker sube a caché v4 para que la página deje de servir el JavaScript anterior; el cambio afecta archivos de caché del sitio, no los datos de IndexedDB.
- Tras conservar una operación, los reintentos usan su mismo UUID. `online`, `pageshow`, retorno a la pestaña y espera exponencial impulsan la sincronización. Si existe Background Sync, el service worker también vacía la cola y avisa a la página para actualizar el estado.

La prueba cliente local cubre búsqueda por identificación, entrada fallida por red y reconexión automática con el mismo UUID, rechazo 403 sin fallback, excepción de interfaz después de la confirmación sin reenviar entrada, salida con turno abierto, visita técnica confirmada y conservación de tres elementos preexistentes en IndexedDB. Además se ejecutaron pruebas Flask dirigidas de búsqueda, rechazo de salida sin turno abierto y registro de visita con mocks. No se hicieron escrituras en Supabase remoto ni se probó en un navegador/celular real.

## Qué conserva el dispositivo

Al actualizar **Operarios**, el servidor devuelve únicamente los operarios activos con `id`, `identificacion`, `nombre`, `cargo`, QR y el resumen de un turno abierto (COT, proyecto y hora de entrada). No devuelve correo, `auth_user_id` ni otros datos del perfil. También conserva localmente el QR y el turno abierto del coordinador autenticado para permitir la captura de su propia asistencia y visitas. El directorio se guarda en IndexedDB y muestra la fecha de descarga; la vigencia se valida otra vez en el servidor al sincronizar.

Cada evento se guarda primero en IndexedDB con un UUID, la hora capturada en el dispositivo, el estado GPS y el contenido necesario para enviarlo. La cola distingue operaciones pendientes, en validación, que requieren revisión y confirmadas. Un evento solo pasa a confirmado cuando la respuesta incluye el mismo UUID y el resultado guardado.

La interfaz de asistencia ofrece la cámara y la búsqueda por número de identificación; ya no ofrece ingreso manual del contenido QR. La búsqueda por identificación mantiene el mensaje de estado dentro de la plantilla tanto normal como offline. Una prueba de contrato compara todos los selectores DOM del JavaScript con ambas plantillas para evitar errores de `textContent` sobre un nodo inexistente.

Un error de conexión (`fetch` fallido, navegador offline, timeout o gateway/servicio no disponible) permite elegir **Continuar sin conexión** y deja la operación local pendiente. Un rechazo HTTP de autenticación, CSRF, perfil o validación se muestra como revisión del servidor y no ofrece el camino offline. Errores 5xx no se presentan como guardados; permanecen pendientes y se reintentan.

El cliente sincroniza al evento `online`, al abrir y volver a la aplicación, y mediante reintentos temporizados con espera exponencial hasta dos minutos. Cuando está disponible, solicita Background Sync al service worker; la página y el botón manual siguen siendo alternativas. Los reintentos conservan el mismo UUID.

## Validación y conflictos

La cédula o el QR solo seleccionan a la persona. Toda escritura requiere una sesión activa de coordinador, CSRF y validación actual en Flask y en la función SQL. Si el operario dejó de estar activo, la operación queda en la cola como pendiente que requiere revisión; no se guarda ni se descarta. El servidor rechaza una segunda entrada abierta mediante el índice único. Las salidas deben corresponder a una entrada abierta y su hora no puede anteceder a la entrada. Una persona inactiva puede cerrar el turno que ya tenía abierto.

El UUID evita duplicar una misma operación al reintentar desde el mismo dispositivo. Una entrada en conflicto con otra entrada hecha en otro dispositivo se rechaza y requiere revisión; no se fusionan eventos de dispositivos distintos automáticamente. Las operaciones locales no sincronizadas no se eliminan al cerrar la sesión o recargar la página.

La migración crea `act06_sheets_outbox`: una fila por operación confirmada en Supabase, dentro de la misma transacción, con `operacion_id` como clave única. Esto prepara la entrega posterior a Google Sheets. El proyecto no contiene todavía un consumidor de esa bandeja ni configuración de Google Sheets; por tanto, esta implementación **no afirma que una fila haya llegado a Sheets**. El futuro consumidor debe consultar/deduplicar por `operacion_id` y marcar `sincronizado` solo tras confirmar la escritura.

## GPS y reloj

La ubicación es opcional. Se guardan coordenadas y precisión si el navegador las entrega; si el permiso se deniega, expira o no hay geolocalización, se registra `no_disponible` sin coordenadas. Los eventos conservan la hora capturada por el dispositivo y también la hora de recepción en servidor. Una hora de salida anterior a la entrada se rechaza para revisión. No hay sincronización horaria confiable del dispositivo offline; la hora capturada debe revisarse si el reloj del teléfono estaba incorrecto.

## Preparación y comprobación en campo

1. Con internet y una sesión de coordinador activa, entrar a **Asistencia por COT** o **Visita técnica** y abrir **Directorio y operaciones pendientes**. Desde allí, pulsar **Actualizar operarios**.
2. Confirmar que aparece el número y la hora de actualización del directorio antes de iniciar la jornada.
3. Probar en un dispositivo de prueba una entrada y salida online, y luego una entrada/salida offline seguida de reconexión. Repetir un reintento después de una respuesta ambigua y comprobar que conserva el mismo UUID y no crea otra fila.
4. Probar permiso GPS denegado y confirmar el estado `no_disponible`.
5. Confirmar en Supabase la fila de asistencia y la entrada en `act06_sheets_outbox`. Estas verificaciones requieren la migración aplicada en una base de pruebas; no se debe usar la base productiva para pruebas.

La lista incluye números de identificación y códigos QR, por lo que el dispositivo debe tener bloqueo de pantalla, permanecer bajo custodia del coordinador y borrarse al cambiar de equipo. El almacenamiento web no está cifrado por esta aplicación.

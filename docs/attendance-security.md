# Asistencia: seguridad y turnos abiertos

## Regla de entrada y salida

La consulta de asistencia determina la acción para cada trabajador a partir de su turno abierto. Sin un turno abierto, la acción es entrada; con uno, la acción es salida. Una vez cerrada la salida, la siguiente consulta vuelve a ofrecer entrada. La interfaz no elige la acción de forma independiente.

El servidor permite consultar una persona inactiva para localizar un turno abierto y no la presenta como elegible para iniciar una entrada nueva. La salida puede cerrar la entrada que ya estaba abierta. El cierre afecta solo ese tramo: los tramos históricos no se borran ni se reescriben.

## Idempotencia y concurrencia

El cliente conserva el UUID de una operación durante sus reintentos. La protección efectiva frente a dos solicitudes simultáneas y la repetición de un UUID depende de las RPC y restricciones desplegadas en Supabase. La migración base de asistencia no está disponible en `supabase/migrations` en este checkout, así que ese comportamiento debe contrastarse con el catálogo SQL remoto antes de considerarlo validado.

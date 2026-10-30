-- ACT07: dashboard diario agregado, archivo reversible de novedades
-- y desactivación administrativa serializada.
-- Requiere aplicar primero 20261028_act07_novedades_y_tramos.sql en una BD de pruebas.
-- No borra tablas, personas, cuentas, asistencias, visitas ni novedades.

DO $$
BEGIN
    IF to_regclass('public.novedades') IS NULL OR to_regclass('public.trabajadores') IS NULL
       OR to_regclass('public.registros_asistencia') IS NULL THEN
        RAISE EXCEPTION 'Faltan tablas ACT06/ACT07 base; revisar y aplicar primero las migraciones previas en una base de pruebas.';
    END IF;
END;
$$;

-- El archivo es lógico y reversible. El límite es exclusivo: fecha_fin < límite.
ALTER TABLE public.novedades ADD COLUMN IF NOT EXISTS archivado_en timestamptz;

DO $$
DECLARE
    restriccion record;
BEGIN
    -- El check de tipo anterior se conserva: así permanecen válidos y editables
    -- los registros históricos. La lista permitida para nuevas altas se controla
    -- en Flask; esta migración nunca reescribe categorías existentes.
    FOR restriccion IN
        SELECT conname FROM pg_constraint
         WHERE conrelid = 'public.novedades'::regclass AND contype = 'c'
           AND pg_get_constraintdef(oid) ILIKE '%estado%'
           AND pg_get_constraintdef(oid) ILIKE '%anulada%'
    LOOP
        EXECUTE format('ALTER TABLE public.novedades DROP CONSTRAINT %I', restriccion.conname);
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.novedades'::regclass AND conname = 'novedades_estado_act07_check') THEN
        ALTER TABLE public.novedades ADD CONSTRAINT novedades_estado_act07_check
            CHECK (estado IN ('registrada', 'anulada', 'archivada')) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.novedades'::regclass AND conname = 'novedades_archivo_fecha_check') THEN
        ALTER TABLE public.novedades ADD CONSTRAINT novedades_archivo_fecha_check
            CHECK ((estado = 'archivada' AND archivado_en IS NOT NULL) OR estado <> 'archivada') NOT VALID;
    END IF;
END;
$$;

-- El índice ACT06 por fecha_entrada ya sirve para el rango diario; la expresión
-- GiST acelera la consulta de novedades cuya vigencia incluye el día consultado.
CREATE INDEX IF NOT EXISTS novedades_vigencia_gist_idx
    ON public.novedades USING gist (daterange(fecha_inicio, fecha_fin, '[]'));
CREATE INDEX IF NOT EXISTS novedades_archivadas_fecha_idx
    ON public.novedades (archivado_en DESC, id DESC) WHERE estado = 'archivada';
CREATE INDEX IF NOT EXISTS novedades_activas_fecha_fin_idx
    ON public.novedades (fecha_fin) WHERE estado = 'registrada';
CREATE INDEX IF NOT EXISTS novedades_recientes_idx
    ON public.novedades (creado_en DESC) WHERE estado = 'registrada';
CREATE INDEX IF NOT EXISTS trabajadores_perfil_estado_activo_idx
    ON public.trabajadores (perfil) WHERE lower(coalesce(estado, '')) = 'activo';

CREATE OR REPLACE FUNCTION public.dashboard_admin_act07(p_dia date)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    inicio_dia timestamptz := p_dia::timestamp AT TIME ZONE 'America/Bogota';
    fin_dia timestamptz := (p_dia + 1)::timestamp AT TIME ZONE 'America/Bogota';
    trabajadores_activos bigint;
    presentes bigint;
    ausencias_injustificadas bigint;
    novedades_vigentes bigint;
    resumen_proyectos jsonb;
    recientes jsonb;
BEGIN
    SELECT count(*) INTO trabajadores_activos
      FROM public.trabajadores t
     WHERE t.perfil = 'trabajador' AND lower(coalesce(t.estado, '')) = 'activo';

    -- Presente significa trabajador activo con entrada dentro de la jornada o
    -- con un turno iniciado antes que continúa abierto durante esta jornada.
    -- Una salida tardía cerrada nunca crea una asistencia nueva del día siguiente.
    SELECT count(*) INTO presentes FROM (
        SELECT a.trabajador_id
          FROM public.registros_asistencia a
          JOIN public.trabajadores t ON t.id = a.trabajador_id
         WHERE a.fecha_entrada >= inicio_dia AND a.fecha_entrada < fin_dia
           AND t.perfil = 'trabajador' AND lower(coalesce(t.estado, '')) = 'activo'
        UNION
        SELECT a.trabajador_id
          FROM public.registros_asistencia a
          JOIN public.trabajadores t ON t.id = a.trabajador_id
         WHERE a.fecha_entrada < inicio_dia AND a.fecha_salida IS NULL
           AND t.perfil = 'trabajador' AND lower(coalesce(t.estado, '')) = 'activo'
    ) trabajadores_presentes;

    -- Solo contar inasistencias injustificadas reportadas explícitamente; no
    -- inferir ausencia sin programación de turnos/asignación de jornada.
    SELECT count(DISTINCT n.trabajador_id) INTO ausencias_injustificadas
      FROM public.novedades n
      JOIN public.trabajadores t ON t.id = n.trabajador_id
     WHERE n.estado = 'registrada' AND n.tipo = 'inasistencia_injustificada'
       AND t.perfil = 'trabajador' AND lower(coalesce(t.estado, '')) = 'activo'
       AND daterange(n.fecha_inicio, n.fecha_fin, '[]') @> p_dia;

    SELECT count(*) INTO novedades_vigentes
      FROM public.novedades n
     WHERE n.estado = 'registrada'
       AND daterange(n.fecha_inicio, n.fecha_fin, '[]') @> p_dia;

    SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.cot, r.proyecto), '[]'::jsonb)
      INTO resumen_proyectos
      FROM (
          SELECT coalesce(a.cot, '') AS cot, coalesce(a.proyecto, '') AS proyecto,
                 count(*)::bigint AS tramos,
                 count(*) FILTER (WHERE a.fecha_salida IS NULL)::bigint AS abiertos
            FROM public.registros_asistencia a
           WHERE a.fecha_entrada >= inicio_dia AND a.fecha_entrada < fin_dia
           GROUP BY coalesce(a.cot, ''), coalesce(a.proyecto, '')
      ) r;

    SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.creado_en DESC), '[]'::jsonb)
      INTO recientes
      FROM (
          SELECT n.id, n.tipo, n.trabajador_id, t.nombre AS trabajador_nombre,
                 n.fecha_inicio, n.fecha_fin, n.proyecto, n.cot, n.motivo,
                 n.observaciones, n.creado_en, n.estado
            FROM public.novedades n
            JOIN public.trabajadores t ON t.id = n.trabajador_id
           WHERE n.estado = 'registrada'
           ORDER BY n.creado_en DESC
           LIMIT 5
      ) r;

    RETURN jsonb_build_object(
        'dia', p_dia,
        'trabajadores_activos', trabajadores_activos,
        'presentes', presentes,
        'ausencias_injustificadas', ausencias_injustificadas,
        'novedades_vigentes', novedades_vigentes,
        'proyectos', resumen_proyectos,
        'novedades_recientes', recientes
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.previsualizar_archivo_novedades(p_fecha_limite date)
RETURNS bigint
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT count(*) FROM public.novedades
     WHERE estado = 'registrada' AND fecha_fin < p_fecha_limite
$$;

CREATE OR REPLACE FUNCTION public.archivar_novedades_anteriores(
    p_fecha_limite date, p_cantidad_esperada integer
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE cantidad integer;
BEGIN
    -- Bloquea inserciones concurrentes durante la comprobación y el archivo para
    -- que el número confirmado por la usuaria coincida con el número afectado.
    LOCK TABLE public.novedades IN SHARE ROW EXCLUSIVE MODE;
    SELECT count(*) INTO cantidad FROM public.novedades
     WHERE estado = 'registrada' AND fecha_fin < p_fecha_limite;
    IF cantidad <> p_cantidad_esperada THEN
        RAISE EXCEPTION 'ARCHIVO_CANTIDAD_CAMBIO' USING ERRCODE = 'P0001';
    END IF;
    UPDATE public.novedades
       SET estado = 'archivada', archivado_en = clock_timestamp()
     WHERE estado = 'registrada' AND fecha_fin < p_fecha_limite;
    GET DIAGNOSTICS cantidad = ROW_COUNT;
    RETURN cantidad;
END;
$$;

CREATE OR REPLACE FUNCTION public.restaurar_novedad_archivada(p_novedad_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE resultado public.novedades%ROWTYPE;
BEGIN
    UPDATE public.novedades
       SET estado = 'registrada', archivado_en = NULL
     WHERE id = p_novedad_id AND estado = 'archivada'
     RETURNING * INTO resultado;
    IF NOT FOUND THEN RETURN NULL; END IF;
    RETURN jsonb_build_object('id', resultado.id, 'estado', resultado.estado);
END;
$$;

-- Serializa cambios de estado para que dos administradores concurrentes no
-- desactiven al mismo tiempo las últimas dos cuentas de administrador.
CREATE OR REPLACE FUNCTION public.cambiar_estado_persona_act07(
    p_persona_id bigint, p_estado text, p_solicitante_id bigint
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE persona public.trabajadores%ROWTYPE;
DECLARE administradores_activos bigint;
BEGIN
    IF p_estado NOT IN ('activo', 'inactivo') THEN
        RAISE EXCEPTION 'ESTADO_PERSONA_INVALIDO' USING ERRCODE = '22023';
    END IF;
    IF p_solicitante_id IS NULL THEN
        RAISE EXCEPTION 'SOLICITANTE_INVALIDO' USING ERRCODE = 'P0001';
    END IF;
    PERFORM pg_advisory_xact_lock(20261029, 7);
    SELECT * INTO persona FROM public.trabajadores WHERE id = p_persona_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'PERSONA_NO_ENCONTRADA' USING ERRCODE = 'P0001'; END IF;
    IF p_estado = 'inactivo' AND lower(coalesce(persona.estado, '')) = 'activo' THEN
        IF persona.id = p_solicitante_id THEN
            RAISE EXCEPTION 'AUTODESACTIVACION_NO_PERMITIDA' USING ERRCODE = 'P0001';
        END IF;
        IF persona.perfil = 'administrador' THEN
            SELECT count(*) INTO administradores_activos FROM public.trabajadores
             WHERE perfil = 'administrador' AND lower(coalesce(estado, '')) = 'activo';
            IF administradores_activos <= 1 THEN
                RAISE EXCEPTION 'ULTIMO_ADMIN_ACTIVO' USING ERRCODE = 'P0001';
            END IF;
        END IF;
    END IF;
    UPDATE public.trabajadores SET estado = p_estado WHERE id = p_persona_id;
    RETURN jsonb_build_object('id', p_persona_id, 'estado', p_estado);
END;
$$;

REVOKE ALL ON FUNCTION public.dashboard_admin_act07(date) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.previsualizar_archivo_novedades(date) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.archivar_novedades_anteriores(date, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.restaurar_novedad_archivada(bigint) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cambiar_estado_persona_act07(bigint, text, bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.dashboard_admin_act07(date) TO service_role;
GRANT EXECUTE ON FUNCTION public.previsualizar_archivo_novedades(date) TO service_role;
GRANT EXECUTE ON FUNCTION public.archivar_novedades_anteriores(date, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.restaurar_novedad_archivada(bigint) TO service_role;
GRANT EXECUTE ON FUNCTION public.cambiar_estado_persona_act07(bigint, text, bigint) TO service_role;

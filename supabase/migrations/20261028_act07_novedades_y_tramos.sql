ALTER TABLE public.registros_asistencia
    ADD COLUMN IF NOT EXISTS observaciones_entrada text,
    ADD COLUMN IF NOT EXISTS observaciones_salida text;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'registros_asistencia_observaciones_entrada_largo'
          AND conrelid = 'public.registros_asistencia'::regclass
    ) THEN
        ALTER TABLE public.registros_asistencia
            ADD CONSTRAINT registros_asistencia_observaciones_entrada_largo
            CHECK (observaciones_entrada IS NULL OR length(observaciones_entrada) <= 1000);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'registros_asistencia_observaciones_salida_largo'
          AND conrelid = 'public.registros_asistencia'::regclass
    ) THEN
        ALTER TABLE public.registros_asistencia
            ADD CONSTRAINT registros_asistencia_observaciones_salida_largo
            CHECK (observaciones_salida IS NULL OR length(observaciones_salida) <= 1000);
    END IF;
END;
$$;

-- Cada entrada/salida permanece como un tramo independiente; el UUID original y
-- su hash se siguen validando en las funciones ACT06 existentes. Estas funciones
-- añaden la observación dentro de la misma transacción.
CREATE OR REPLACE FUNCTION public.registrar_entrada_asistencia_act07(
    p_trabajador_id bigint,
    p_coordinador_id bigint,
    p_cot text,
    p_proyecto text,
    p_ocurrio_en timestamptz,
    p_latitud double precision,
    p_longitud double precision,
    p_precision_m double precision,
    p_ubicacion_obtenida boolean,
    p_operacion_id uuid,
    p_payload_hash text,
    p_observaciones text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    resultado jsonb;
    registro_id bigint;
BEGIN
    IF p_observaciones IS NOT NULL AND length(p_observaciones) > 1000 THEN
        RAISE EXCEPTION 'OBSERVACIONES_DE_TRAMO_DEMASIADO_LARGAS' USING ERRCODE = '22023';
    END IF;

    resultado := public.registrar_entrada_asistencia_offline(
        p_trabajador_id => p_trabajador_id,
        p_coordinador_id => p_coordinador_id,
        p_cot => p_cot,
        p_proyecto => p_proyecto,
        p_ocurrio_en => p_ocurrio_en,
        p_latitud => p_latitud,
        p_longitud => p_longitud,
        p_precision_m => p_precision_m,
        p_ubicacion_obtenida => p_ubicacion_obtenida,
        p_operacion_id => p_operacion_id,
        p_payload_hash => p_payload_hash
    );
    registro_id := (resultado ->> 'id')::bigint;

    UPDATE public.registros_asistencia
       SET observaciones_entrada = NULLIF(btrim(p_observaciones), '')
     WHERE id = registro_id;

    RETURN resultado || jsonb_build_object(
        'observaciones_entrada', NULLIF(btrim(p_observaciones), '')
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.registrar_salida_asistencia_act07(
    p_trabajador_id bigint,
    p_coordinador_id bigint,
    p_ocurrio_en timestamptz,
    p_latitud double precision,
    p_longitud double precision,
    p_precision_m double precision,
    p_ubicacion_obtenida boolean,
    p_operacion_id uuid,
    p_payload_hash text,
    p_observaciones text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    resultado jsonb;
    registro_id bigint;
BEGIN
    IF p_observaciones IS NOT NULL AND length(p_observaciones) > 1000 THEN
        RAISE EXCEPTION 'OBSERVACIONES_DE_TRAMO_DEMASIADO_LARGAS' USING ERRCODE = '22023';
    END IF;

    resultado := public.registrar_salida_asistencia_offline(
        p_trabajador_id => p_trabajador_id,
        p_coordinador_id => p_coordinador_id,
        p_ocurrio_en => p_ocurrio_en,
        p_latitud => p_latitud,
        p_longitud => p_longitud,
        p_precision_m => p_precision_m,
        p_ubicacion_obtenida => p_ubicacion_obtenida,
        p_operacion_id => p_operacion_id,
        p_payload_hash => p_payload_hash
    );
    registro_id := (resultado ->> 'id')::bigint;

    UPDATE public.registros_asistencia
       SET observaciones_salida = NULLIF(btrim(p_observaciones), '')
     WHERE id = registro_id;

    RETURN resultado || jsonb_build_object(
        'observaciones_salida', NULLIF(btrim(p_observaciones), '')
    );
END;
$$;

REVOKE ALL ON FUNCTION public.registrar_entrada_asistencia_act07(
    bigint, bigint, text, text, timestamptz, double precision, double precision,
    double precision, boolean, uuid, text, text
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.registrar_salida_asistencia_act07(
    bigint, bigint, timestamptz, double precision, double precision,
    double precision, boolean, uuid, text, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.registrar_entrada_asistencia_act07(
    bigint, bigint, text, text, timestamptz, double precision, double precision,
    double precision, boolean, uuid, text, text
) TO service_role;
GRANT EXECUTE ON FUNCTION public.registrar_salida_asistencia_act07(
    bigint, bigint, timestamptz, double precision, double precision,
    double precision, boolean, uuid, text, text
) TO service_role;

CREATE TABLE IF NOT EXISTS public.novedades (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    trabajador_id bigint NOT NULL REFERENCES public.trabajadores(id) ON DELETE RESTRICT,
    tipo text NOT NULL CHECK (tipo IN (
        'permiso', 'vacaciones', 'incapacidad', 'inasistencia_justificada',
        'inasistencia_injustificada', 'llegada_tarde', 'salida_anticipada',
        'horas_extras', 'otra_justificada'
    )),
    fecha_inicio date NOT NULL,
    fecha_fin date NOT NULL,
    hora_inicio time without time zone,
    hora_fin time without time zone,
    cot text,
    proyecto text,
    motivo text NOT NULL CHECK (length(btrim(motivo)) BETWEEN 1 AND 1000),
    observaciones text CHECK (observaciones IS NULL OR length(observaciones) <= 2000),
    responsable_id bigint NOT NULL REFERENCES public.trabajadores(id) ON DELETE RESTRICT,
    creado_en timestamptz NOT NULL DEFAULT clock_timestamp(),
    estado text NOT NULL DEFAULT 'registrada' CHECK (estado IN ('registrada', 'anulada')),
    dedupe_key text NOT NULL UNIQUE,
    CONSTRAINT novedades_rango_fechas CHECK (fecha_fin >= fecha_inicio),
    CONSTRAINT novedades_rango_horas CHECK (
        fecha_inicio <> fecha_fin OR hora_inicio IS NULL OR hora_fin IS NULL OR hora_fin > hora_inicio
    ),
    CONSTRAINT novedades_llegada_tarde_hora CHECK (tipo <> 'llegada_tarde' OR hora_inicio IS NOT NULL),
    CONSTRAINT novedades_salida_anticipada_hora CHECK (tipo <> 'salida_anticipada' OR hora_fin IS NOT NULL),
    CONSTRAINT novedades_horas_extras_horas CHECK (
        tipo <> 'horas_extras' OR (hora_inicio IS NOT NULL AND hora_fin IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS novedades_fecha_rango_idx
    ON public.novedades (fecha_inicio, fecha_fin);
CREATE INDEX IF NOT EXISTS novedades_trabajador_fecha_idx
    ON public.novedades (trabajador_id, fecha_inicio DESC);
CREATE INDEX IF NOT EXISTS novedades_tipo_creado_idx
    ON public.novedades (tipo, creado_en DESC);

ALTER TABLE public.novedades ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.novedades FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON public.novedades TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.novedades_id_seq TO service_role;

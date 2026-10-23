-- ACT06: completa el registro de visitas técnicas con proyecto y un operario opcional.
-- Migración aditiva: conserva filas existentes y no ejecuta escrituras sobre historial.
-- Revisar y aplicar manualmente solo en el proyecto Supabase de pruebas autorizado.

ALTER TABLE public.visitas_tecnicas
    ADD COLUMN IF NOT EXISTS proyecto text,
    ADD COLUMN IF NOT EXISTS trabajador_id bigint;

-- La migración base exigía coordenadas; GPS es opcional en el flujo actual.
ALTER TABLE public.visitas_tecnicas
    ALTER COLUMN latitud DROP NOT NULL,
    ALTER COLUMN longitud DROP NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'visitas_tecnicas_trabajador_id_fkey'
          AND conrelid = 'public.visitas_tecnicas'::regclass
    ) THEN
        ALTER TABLE public.visitas_tecnicas
            ADD CONSTRAINT visitas_tecnicas_trabajador_id_fkey
            FOREIGN KEY (trabajador_id)
            REFERENCES public.trabajadores(id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'visitas_tecnicas_proyecto_no_vacio'
          AND conrelid = 'public.visitas_tecnicas'::regclass
    ) THEN
        ALTER TABLE public.visitas_tecnicas
            ADD CONSTRAINT visitas_tecnicas_proyecto_no_vacio
            CHECK (proyecto IS NULL OR length(btrim(proyecto)) > 0);
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.registrar_visita_tecnica_offline(
    p_coordinador_id bigint,
    p_latitud double precision,
    p_longitud double precision,
    p_precision_m double precision,
    p_ubicacion_obtenida boolean,
    p_ocurrio_en timestamptz,
    p_operacion_id uuid,
    p_payload_hash text,
    p_proyecto text,
    p_trabajador_id bigint
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    visita public.visitas_tecnicas%ROWTYPE;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.trabajadores
        WHERE id = p_coordinador_id
          AND lower(btrim(perfil)) = 'coordinador'
          AND lower(btrim(estado)) = 'activo'
    ) THEN
        RAISE EXCEPTION 'COORDINADOR_NO_AUTORIZADO' USING ERRCODE = '42501';
    END IF;

    IF p_trabajador_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.trabajadores
        WHERE id = p_trabajador_id
          AND lower(btrim(perfil)) = 'trabajador'
          AND lower(btrim(estado)) = 'activo'
    ) THEN
        RAISE EXCEPTION 'PARTICIPANTE_NO_ES_OPERARIO_ACTIVO' USING ERRCODE = 'P0001';
    END IF;

    IF p_proyecto IS NULL OR length(btrim(p_proyecto)) = 0
       OR length(p_proyecto) > 300
       OR p_ocurrio_en IS NULL OR p_operacion_id IS NULL
       OR p_payload_hash IS NULL OR length(p_payload_hash) <> 64 THEN
        RAISE EXCEPTION 'DATOS_DE_VISITA_INVALIDOS' USING ERRCODE = '22023';
    END IF;

    IF p_ubicacion_obtenida IS TRUE THEN
        IF p_latitud IS NULL OR p_longitud IS NULL
           OR p_latitud NOT BETWEEN -90 AND 90
           OR p_longitud NOT BETWEEN -180 AND 180
           OR (p_precision_m IS NOT NULL AND (p_precision_m < 0 OR p_precision_m IN ('NaN'::double precision, 'Infinity'::double precision, '-Infinity'::double precision))) THEN
            RAISE EXCEPTION 'COORDENADAS_INVALIDAS' USING ERRCODE = '22023';
        END IF;
    ELSIF p_ubicacion_obtenida IS FALSE THEN
        IF p_latitud IS NOT NULL OR p_longitud IS NOT NULL OR p_precision_m IS NOT NULL THEN
            RAISE EXCEPTION 'UBICACION_NO_DISPONIBLE_CON_COORDENADAS' USING ERRCODE = '22023';
        END IF;
    ELSE
        RAISE EXCEPTION 'ESTADO_DE_UBICACION_INVALIDO' USING ERRCODE = '22023';
    END IF;

    INSERT INTO public.visitas_tecnicas (
        coordinador_id, latitud, longitud, precision_m, idempotency_key,
        ubicacion_estado, ocurrio_en, payload_hash, proyecto, trabajador_id
    ) VALUES (
        p_coordinador_id, p_latitud, p_longitud, p_precision_m, p_operacion_id,
        CASE WHEN p_ubicacion_obtenida THEN 'obtenida' ELSE 'no_disponible' END,
        p_ocurrio_en, p_payload_hash, btrim(p_proyecto), p_trabajador_id
    )
    ON CONFLICT (idempotency_key) DO UPDATE
       SET idempotency_key = EXCLUDED.idempotency_key
     WHERE visitas_tecnicas.coordinador_id = EXCLUDED.coordinador_id
       AND visitas_tecnicas.latitud IS NOT DISTINCT FROM EXCLUDED.latitud
       AND visitas_tecnicas.longitud IS NOT DISTINCT FROM EXCLUDED.longitud
       AND visitas_tecnicas.precision_m IS NOT DISTINCT FROM EXCLUDED.precision_m
       AND visitas_tecnicas.ubicacion_estado = EXCLUDED.ubicacion_estado
       AND visitas_tecnicas.ocurrio_en = EXCLUDED.ocurrio_en
       AND visitas_tecnicas.payload_hash = EXCLUDED.payload_hash
       AND visitas_tecnicas.proyecto IS NOT DISTINCT FROM EXCLUDED.proyecto
       AND visitas_tecnicas.trabajador_id IS NOT DISTINCT FROM EXCLUDED.trabajador_id
    RETURNING * INTO visita;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_DATA' USING ERRCODE = '22000';
    END IF;

    RETURN jsonb_build_object(
        'id', visita.id,
        'coordinador_id', visita.coordinador_id,
        'trabajador_id', visita.trabajador_id,
        'proyecto', visita.proyecto,
        'idempotency_key', visita.idempotency_key,
        'ocurrio_en', visita.ocurrio_en,
        'ubicacion_estado', visita.ubicacion_estado,
        'registrado_en', visita.registrado_en
    );
END;
$$;

REVOKE ALL ON FUNCTION public.registrar_visita_tecnica_offline(
    bigint, double precision, double precision, double precision, boolean,
    timestamptz, uuid, text, text, bigint
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.registrar_visita_tecnica_offline(
    bigint, double precision, double precision, double precision, boolean,
    timestamptz, uuid, text, text, bigint
) TO service_role;

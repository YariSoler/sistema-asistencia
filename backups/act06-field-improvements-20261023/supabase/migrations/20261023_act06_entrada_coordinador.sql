-- ACT06: permitir que un coordinador registre su propia entrada con QR.
-- Migración aditiva: reemplaza una función; no borra ni actualiza registros.
-- No ejecutar en producción sin validar primero en Supabase de pruebas.

CREATE OR REPLACE FUNCTION public.registrar_entrada_asistencia(
    p_trabajador_id bigint,
    p_coordinador_id bigint,
    p_cot text,
    p_proyecto text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    nuevo public.registros_asistencia%ROWTYPE;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.trabajadores
        WHERE id = p_coordinador_id
          AND perfil = 'coordinador'
          AND lower(btrim(estado)) = 'activo'
    ) THEN
        RAISE EXCEPTION 'COORDINADOR_NO_AUTORIZADO' USING ERRCODE = '42501';
    END IF;

    -- trabajador_id también contiene el ID del coordinador cuando registra
    -- su propia asistencia, respetando las columnas y FK ya existentes.
    IF NOT EXISTS (
        SELECT 1 FROM public.trabajadores
        WHERE id = p_trabajador_id
          AND lower(btrim(estado)) = 'activo'
          AND (
              perfil = 'trabajador'
              OR (perfil = 'coordinador' AND id = p_coordinador_id)
          )
    ) THEN
        RAISE EXCEPTION 'PERSONA_NO_AUTORIZADA_PARA_ENTRADA' USING ERRCODE = 'P0001';
    END IF;

    IF p_cot IS NULL OR length(btrim(p_cot)) = 0
       OR p_proyecto IS NULL OR length(btrim(p_proyecto)) = 0 THEN
        RAISE EXCEPTION 'COT_Y_PROYECTO_OBLIGATORIOS' USING ERRCODE = 'P0001';
    END IF;

    INSERT INTO public.registros_asistencia
        (trabajador_id, coordinador_id, cot, proyecto)
    VALUES
        (p_trabajador_id, p_coordinador_id, btrim(p_cot), btrim(p_proyecto))
    RETURNING * INTO nuevo;

    RETURN jsonb_build_object(
        'id', nuevo.id,
        'trabajador_id', nuevo.trabajador_id,
        'cot', nuevo.cot,
        'proyecto', nuevo.proyecto,
        'fecha_entrada', nuevo.fecha_entrada
    );
END;
$$;

REVOKE ALL ON FUNCTION public.registrar_entrada_asistencia(bigint, bigint, text, text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.registrar_entrada_asistencia(bigint, bigint, text, text)
    TO service_role;

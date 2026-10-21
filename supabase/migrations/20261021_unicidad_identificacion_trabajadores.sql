
DO $$
BEGIN
    IF EXISTS (
        SELECT btrim(identificacion)
        FROM public.trabajadores
        WHERE identificacion IS NOT NULL
          AND btrim(identificacion) <> ''
        GROUP BY btrim(identificacion)
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Hay identificaciones duplicadas en public.trabajadores. Revísalas antes de crear el índice de ACT05.';
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS trabajadores_identificacion_normalizada_uidx
    ON public.trabajadores (btrim(identificacion))
    WHERE identificacion IS NOT NULL
      AND btrim(identificacion) <> '';

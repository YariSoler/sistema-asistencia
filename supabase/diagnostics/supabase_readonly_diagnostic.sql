SELECT
    c.table_schema,
    c.table_name,
    c.ordinal_position,
    c.column_name,
    c.data_type,
    c.udt_schema,
    c.udt_name,
    c.character_maximum_length,
    c.numeric_precision,
    c.numeric_scale,
    c.datetime_precision,
    c.is_nullable,
    c.column_default,
    c.identity_generation,
    c.is_generated,
    c.generation_expression
FROM information_schema.columns AS c
WHERE c.table_schema = 'public'
  AND (c.table_name IN (
      'registros_asistencia',
      'visitas_tecnicas',
      'novedades',
      'act06_operaciones',
      'act06_sheets_outbox',
      'trabajadores'
  ) OR c.table_name ~* '(asistencia|visita|novedad|operacion|outbox|sheet|trabajador|persona|traslad|transfer|correcci|ajuste|proyecto)')
ORDER BY c.table_name, c.ordinal_position;


SELECT
    n.nspname AS table_schema,
    c.relname AS table_name,
    c.relkind,
    c.relpersistence,
    c.relrowsecurity AS row_level_security_enabled,
    c.relforcerowsecurity AS row_level_security_forced,
    pg_get_userbyid(c.relowner) AS owner,
    obj_description(c.oid, 'pg_class') AS relation_comment
FROM pg_catalog.pg_class AS c
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND (c.relname IN (
      'registros_asistencia',
      'visitas_tecnicas',
      'novedades',
      'act06_operaciones',
      'act06_sheets_outbox',
      'trabajadores'
  ) OR c.relname ~* '(asistencia|visita|novedad|operacion|outbox|sheet|trabajador|persona|traslad|transfer|correcci|ajuste|proyecto)')
ORDER BY c.relname;


SELECT
    ns.nspname AS table_schema,
    tbl.relname AS table_name,
    con.conname AS constraint_name,
    CASE con.contype
        WHEN 'p' THEN 'PRIMARY KEY'
        WHEN 'f' THEN 'FOREIGN KEY'
        WHEN 'u' THEN 'UNIQUE'
        WHEN 'c' THEN 'CHECK'
        WHEN 'x' THEN 'EXCLUSION'
        ELSE con.contype::text
    END AS constraint_type,
    pg_catalog.pg_get_constraintdef(con.oid, true) AS definition,
    con.convalidated AS validated,
    con.condeferrable AS deferrable,
    con.condeferred AS initially_deferred,
    refns.nspname AS referenced_schema,
    ref.relname AS referenced_table
FROM pg_catalog.pg_constraint AS con
JOIN pg_catalog.pg_class AS tbl ON tbl.oid = con.conrelid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid = tbl.relnamespace
LEFT JOIN pg_catalog.pg_class AS ref ON ref.oid = con.confrelid
LEFT JOIN pg_catalog.pg_namespace AS refns ON refns.oid = ref.relnamespace
WHERE ns.nspname = 'public'
  AND (tbl.relname IN (
      'registros_asistencia',
      'visitas_tecnicas',
      'novedades',
      'act06_operaciones',
      'act06_sheets_outbox',
      'trabajadores'
  ) OR tbl.relname ~* '(asistencia|visita|novedad|operacion|outbox|sheet|trabajador|persona|traslad|transfer|correcci|ajuste|proyecto)')
ORDER BY tbl.relname, con.contype, con.conname;


SELECT
    schemaname AS table_schema,
    tablename AS table_name,
    indexname AS index_name,
    indexdef AS definition
FROM pg_catalog.pg_indexes
WHERE schemaname = 'public'
  AND (tablename IN (
      'registros_asistencia',
      'visitas_tecnicas',
      'novedades',
      'act06_operaciones',
      'act06_sheets_outbox',
      'trabajadores'
  ) OR tablename ~* '(asistencia|visita|novedad|operacion|outbox|sheet|trabajador|persona|traslad|transfer|correcci|ajuste|proyecto)')
ORDER BY tablename, indexname;


SELECT
    schemaname AS table_schema,
    tablename AS table_name,
    policyname AS policy_name,
    permissive,
    roles,
    cmd AS command,
    qual AS using_expression,
    with_check AS with_check_expression
FROM pg_catalog.pg_policies
WHERE schemaname = 'public'
  AND (tablename IN (
      'registros_asistencia',
      'visitas_tecnicas',
      'novedades',
      'act06_operaciones',
      'act06_sheets_outbox',
      'trabajadores'
  ) OR tablename ~* '(asistencia|visita|novedad|operacion|outbox|sheet|trabajador|persona|traslad|transfer|correcci|ajuste|proyecto)')
ORDER BY tablename, policyname;


SELECT
    n.nspname AS table_schema,
    c.relname AS table_name,
    pg_catalog.pg_get_userbyid(c.relowner) AS table_owner,
    CASE WHEN acl.grantee = 0 THEN 'PUBLIC'
         ELSE pg_catalog.pg_get_userbyid(acl.grantee)
    END AS grantee,
    acl.privilege_type,
    acl.is_grantable
FROM pg_catalog.pg_class AS c
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
CROSS JOIN LATERAL pg_catalog.aclexplode(
    COALESCE(c.relacl, pg_catalog.acldefault('r', c.relowner))
) AS acl
WHERE n.nspname = 'public'
  AND (c.relname IN (
      'registros_asistencia',
      'visitas_tecnicas',
      'novedades',
      'act06_operaciones',
      'act06_sheets_outbox',
      'trabajadores'
  ) OR c.relname ~* '(asistencia|visita|novedad|operacion|outbox|sheet|trabajador|persona|traslad|transfer|correcci|ajuste|proyecto)')
ORDER BY c.relname, grantee, acl.privilege_type;


SELECT
    grantee,
    table_schema,
    table_name,
    column_name,
    privilege_type,
    is_grantable
FROM information_schema.column_privileges
WHERE table_schema = 'public'
  AND (table_name IN (
      'registros_asistencia',
      'visitas_tecnicas',
      'novedades',
      'act06_operaciones',
      'act06_sheets_outbox',
      'trabajadores'
  ) OR table_name ~* '(asistencia|visita|novedad|operacion|outbox|sheet|trabajador|persona|traslad|transfer|correcci|ajuste|proyecto)')
ORDER BY table_name, column_name, grantee, privilege_type;


WITH function_definitions AS (
    SELECT
        p.oid,
        n.nspname AS function_schema,
        p.proname AS function_name,
        p.prokind,
        pg_catalog.pg_get_function_identity_arguments(p.oid) AS identity_arguments,
        pg_catalog.pg_get_function_result(p.oid) AS result_type,
        l.lanname AS language,
        pg_catalog.pg_get_userbyid(p.proowner) AS owner,
        p.prosecdef AS security_definer,
        p.provolatile AS volatility,
        p.proconfig AS function_settings,
        regexp_replace(
            pg_catalog.pg_get_functiondef(p.oid),
            $$((password|passwd|secret|token|key|credential|authorization|jwt|bearer)[[:space:]]*(=>|:=|=)[[:space:]]*)'[^']*'$$,
            $$\1'[REDACTED]'$$,
            'gi'
        ) AS definition
    FROM pg_catalog.pg_proc AS p
    JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
    JOIN pg_catalog.pg_language AS l ON l.oid = p.prolang
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND p.prokind IN ('f', 'p')
)
SELECT
    function_schema,
    function_name,
    prokind AS function_or_procedure,
    identity_arguments,
    result_type,
    language,
    owner,
    security_definer,
    volatility,
    function_settings,
    (position('registros_asistencia' IN lower(definition)) > 0) AS references_attendance,
    (position('visitas_tecnicas' IN lower(definition)) > 0) AS references_visits,
    (position('novedades' IN lower(definition)) > 0) AS references_novelties,
    (position('act06_operaciones' IN lower(definition)) > 0) AS references_operation_ledger,
    (position('act06_sheets_outbox' IN lower(definition)) > 0) AS references_sheets_outbox,
    definition
FROM function_definitions
WHERE function_name ~* '(asistencia|visita|novedad|operacion|outbox|sheets|offline|entrada|salida|traslad|transfer|correcci|ajuste|trabajador|persona|proyecto)'
   OR definition ~* '(registros_asistencia|visitas_tecnicas|novedades|act06_operaciones|act06_sheets_outbox|trabajadores|traslad|transfer|correcci|ajuste)'
ORDER BY function_schema, function_name, identity_arguments;

SELECT
    ns.nspname AS table_schema,
    tbl.relname AS table_name,
    trg.tgname AS trigger_name,
    trg.tgisinternal AS is_internal,
    trg.tgenabled AS enabled_state,
    pg_catalog.pg_get_triggerdef(trg.oid, true) AS trigger_definition,
    fnns.nspname AS trigger_function_schema,
    fn.proname AS trigger_function_name,
    pg_catalog.pg_get_function_identity_arguments(fn.oid) AS trigger_function_arguments,
    regexp_replace(
        pg_catalog.pg_get_functiondef(fn.oid),
        $$((password|passwd|secret|token|key|credential|authorization|jwt|bearer)[[:space:]]*(=>|:=|=)[[:space:]]*)'[^']*'$$,
        $$\1'[REDACTED]'$$,
        'gi'
    ) AS trigger_function_definition
FROM pg_catalog.pg_trigger AS trg
JOIN pg_catalog.pg_class AS tbl ON tbl.oid = trg.tgrelid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid = tbl.relnamespace
JOIN pg_catalog.pg_proc AS fn ON fn.oid = trg.tgfoid
JOIN pg_catalog.pg_namespace AS fnns ON fnns.oid = fn.pronamespace
WHERE ns.nspname = 'public'
  AND (tbl.relname IN (
      'registros_asistencia',
      'visitas_tecnicas',
      'novedades',
      'act06_operaciones',
      'act06_sheets_outbox',
      'trabajadores'
  ) OR tbl.relname ~* '(asistencia|visita|novedad|operacion|outbox|sheet|trabajador|persona|traslad|transfer|correcci|ajuste|proyecto)')
ORDER BY tbl.relname, trg.tgname;

SELECT
    ns.nspname AS table_schema,
    tbl.relname AS table_name,
    con.conname AS constraint_name,
    CASE con.contype
        WHEN 'p' THEN 'PRIMARY KEY'
        WHEN 'f' THEN 'FOREIGN KEY'
        WHEN 'u' THEN 'UNIQUE'
        WHEN 'c' THEN 'CHECK'
        WHEN 'x' THEN 'EXCLUSION'
        ELSE con.contype::text
    END AS constraint_type,
    pg_catalog.pg_get_constraintdef(con.oid, true) AS definition
FROM pg_catalog.pg_constraint AS con
JOIN pg_catalog.pg_class AS tbl ON tbl.oid = con.conrelid
JOIN pg_catalog.pg_namespace AS ns ON ns.oid = tbl.relnamespace
WHERE ns.nspname = 'public'
  AND tbl.relname IN ('act06_operaciones', 'act06_sheets_outbox')
ORDER BY tbl.relname, con.conname;

SELECT
    schemaname AS table_schema,
    tablename AS table_name,
    indexname AS index_name,
    indexdef AS definition
FROM pg_catalog.pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('act06_operaciones', 'act06_sheets_outbox')
ORDER BY tablename, indexname;

WITH function_definitions AS (
    SELECT
        n.nspname AS function_schema,
        p.proname AS function_name,
        pg_catalog.pg_get_function_identity_arguments(p.oid) AS identity_arguments,
        regexp_replace(
            pg_catalog.pg_get_functiondef(p.oid),
            $$((password|passwd|secret|token|key|credential|authorization|jwt|bearer)[[:space:]]*(=>|:=|=)[[:space:]]*)'[^']*'$$,
            $$\1'[REDACTED]'$$,
            'gi'
        ) AS definition
    FROM pg_catalog.pg_proc AS p
    JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND p.prokind IN ('f', 'p')
)
SELECT
    function_schema,
    function_name,
    identity_arguments,
    (position('registros_asistencia' IN lower(definition)) > 0) AS references_attendance,
    (position('act06_operaciones' IN lower(definition)) > 0) AS references_operation_ledger,
    (position('act06_sheets_outbox' IN lower(definition)) > 0) AS references_sheets_outbox,
    (position('visitas_tecnicas' IN lower(definition)) > 0) AS references_visits,
    (position('novedades' IN lower(definition)) > 0) AS references_novelties,
    definition
FROM function_definitions
WHERE function_name ~* '(asistencia|visita|novedad|operacion|outbox|sheets|offline|entrada|salida|traslad|transfer|correcci|ajuste|trabajador|persona|proyecto)'
   OR definition ~* '(registros_asistencia|visitas_tecnicas|novedades|act06_operaciones|act06_sheets_outbox|trabajadores|traslad|transfer|correcci|ajuste)'
ORDER BY function_schema, function_name, identity_arguments;

WITH relevant_functions AS (
    SELECT p.*,
           n.nspname AS function_schema,
           pg_catalog.pg_get_function_identity_arguments(p.oid) AS identity_arguments
    FROM pg_catalog.pg_proc AS p
    JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND p.prokind IN ('f', 'p')
      AND (
          p.proname ~* '(asistencia|visita|novedad|operacion|outbox|sheets|offline|entrada|salida|traslad|transfer|correcci|ajuste|trabajador|persona|proyecto)'
          OR pg_catalog.pg_get_functiondef(p.oid) ~* '(registros_asistencia|visitas_tecnicas|novedades|act06_operaciones|act06_sheets_outbox|trabajadores)'
      )
)
SELECT
    f.function_schema,
    f.proname AS function_name,
    f.identity_arguments,
    CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE pg_catalog.pg_get_userbyid(acl.grantee) END AS grantee,
    acl.privilege_type,
    acl.is_grantable
FROM relevant_functions AS f
CROSS JOIN LATERAL pg_catalog.aclexplode(
    COALESCE(f.proacl, pg_catalog.acldefault('f', f.proowner))
) AS acl
ORDER BY f.function_schema, f.proname, f.identity_arguments, grantee, acl.privilege_type;

WITH related_functions AS (
    SELECT p.oid, n.nspname AS function_schema, p.proname AS function_name,
           pg_catalog.pg_get_function_identity_arguments(p.oid) AS identity_arguments
    FROM pg_catalog.pg_proc AS p
    JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND p.prokind IN ('f', 'p')
      AND (
          p.proname ~* '(asistencia|visita|novedad|operacion|outbox|sheets|offline|entrada|salida|traslad|transfer|correcci|ajuste|trabajador|persona|proyecto)'
          OR pg_catalog.pg_get_functiondef(p.oid) ~* '(registros_asistencia|visitas_tecnicas|novedades|act06_operaciones|act06_sheets_outbox|trabajadores)'
      )
)
SELECT
    fn.function_schema AS dependent_schema,
    fn.function_name AS dependent_function,
    fn.identity_arguments AS dependent_signature,
    d.deptype AS dependency_type,
    refns.nspname AS referenced_schema,
    refrel.relname AS referenced_relation,
    refproc.proname AS referenced_function,
    CASE WHEN refproc.oid IS NOT NULL
         THEN pg_catalog.pg_get_function_identity_arguments(refproc.oid)
         ELSE NULL END AS referenced_function_arguments
FROM related_functions AS fn
JOIN pg_catalog.pg_depend AS d
  ON d.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass
 AND d.objid = fn.oid
LEFT JOIN pg_catalog.pg_class AS refrel
  ON d.refclassid = 'pg_catalog.pg_class'::pg_catalog.regclass
 AND d.refobjid = refrel.oid
LEFT JOIN pg_catalog.pg_namespace AS refns
  ON refns.oid = refrel.relnamespace
LEFT JOIN pg_catalog.pg_proc AS refproc
  ON d.refclassid = 'pg_catalog.pg_proc'::pg_catalog.regclass
 AND d.refobjid = refproc.oid
ORDER BY dependent_schema, dependent_function, dependent_signature,
         referenced_schema, referenced_relation, referenced_function;

SELECT
    n.nspname AS table_schema,
    c.relname AS relation_name,
    c.relkind,
    c.relrowsecurity AS row_level_security_enabled,
    c.relforcerowsecurity AS row_level_security_forced
FROM pg_catalog.pg_class AS c
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND c.relname ~* '(asistencia|visita|novedad|operacion|outbox|sheet|trabajador|persona|traslad|transfer|correcci|ajuste|proyecto)'
ORDER BY c.relname;
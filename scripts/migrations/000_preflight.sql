START TRANSACTION READ ONLY;
SELECT DATABASE(), VERSION();
SELECT TABLE_NAME,ENGINE,TABLE_TYPE,TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE();
SELECT TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT
FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME,ORDINAL_POSITION;
SELECT TABLE_NAME,INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME
FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX;
SELECT TABLE_NAME,CONSTRAINT_NAME,CONSTRAINT_TYPE FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA=DATABASE();
SELECT TABLE_NAME,CONSTRAINT_NAME,COLUMN_NAME,REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME
FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE();
SELECT TABLE_NAME,CONSTRAINT_NAME,UPDATE_RULE,DELETE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE();
SELECT ROUTINE_TYPE,ROUTINE_NAME,SQL_DATA_ACCESS,SECURITY_TYPE FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE();
SELECT SPECIFIC_NAME,ORDINAL_POSITION,PARAMETER_MODE,PARAMETER_NAME,DTD_IDENTIFIER
FROM information_schema.PARAMETERS WHERE SPECIFIC_SCHEMA=DATABASE() ORDER BY SPECIFIC_NAME,ORDINAL_POSITION;
SELECT 'vehiculos' entidad,COUNT(*) total FROM vehiculos UNION ALL SELECT 'comandos',COUNT(*) FROM comandos
UNION ALL SELECT 'estado_vehiculo',COUNT(*) FROM estado_vehiculo UNION ALL SELECT 'historial_comandos',COUNT(*) FROM historial_comandos
UNION ALL SELECT 'demos',COUNT(*) FROM demos UNION ALL SELECT 'demo_movimientos',COUNT(*) FROM demo_movimientos;
SELECT COUNT(*) AS pasos_cruzados FROM demo_movimientos p JOIN demos d USING(id_demo)
JOIN comandos c USING(id_comando) WHERE d.id_vehiculo<>c.id_vehiculo;
SELECT COUNT(*) AS estados_cruzados FROM estado_vehiculo e JOIN comandos c USING(id_comando) WHERE e.id_vehiculo<>c.id_vehiculo;
SELECT COUNT(*) AS historial_cruzado FROM historial_comandos h JOIN comandos c USING(id_comando) WHERE h.id_vehiculo<>c.id_vehiculo;
SELECT 'comandos' AS tabla, COUNT(*) AS filas_huerfanas FROM comandos c
WHERE NOT EXISTS (SELECT 1 FROM vehiculos v WHERE v.id_vehiculo=c.id_vehiculo)
UNION ALL SELECT 'estado_vehiculo', COUNT(*) FROM estado_vehiculo e
WHERE NOT EXISTS (SELECT 1 FROM vehiculos v WHERE v.id_vehiculo=e.id_vehiculo)
   OR (e.id_comando IS NOT NULL AND NOT EXISTS (SELECT 1 FROM comandos c WHERE c.id_comando=e.id_comando))
UNION ALL SELECT 'historial_comandos', COUNT(*) FROM historial_comandos h
WHERE NOT EXISTS (SELECT 1 FROM vehiculos v WHERE v.id_vehiculo=h.id_vehiculo)
   OR (h.id_comando IS NOT NULL AND NOT EXISTS (SELECT 1 FROM comandos c WHERE c.id_comando=h.id_comando))
UNION ALL SELECT 'demos', COUNT(*) FROM demos d
WHERE NOT EXISTS (SELECT 1 FROM vehiculos v WHERE v.id_vehiculo=d.id_vehiculo)
UNION ALL SELECT 'demo_movimientos', COUNT(*) FROM demo_movimientos p
WHERE NOT EXISTS (SELECT 1 FROM demos d WHERE d.id_demo=p.id_demo)
   OR NOT EXISTS (SELECT 1 FROM comandos c WHERE c.id_comando=p.id_comando);
COMMIT;

-- Repeat preflight to compare historical counts.
SELECT COUNT(*) AS tablas_43 FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND LEFT(TABLE_NAME,4)='iot_';
SELECT COUNT(*) AS reservas_inconsistentes FROM iot_reserva r JOIN iot_sesion s ON r.sesion=s.huella
WHERE s.vehiculo<>r.vehiculo OR s.usuario IS NOT NULL;
SELECT COUNT(*) AS demos_incompatibles FROM iot_demo d JOIN iot_paso p ON p.demo=d.id
LEFT JOIN iot_capacidad c ON c.modelo=d.modelo AND c.codigo=p.codigo WHERE d.activo AND c.codigo IS NULL;
SELECT COUNT(*) AS unidades_sin_detener FROM iot_unidad u LEFT JOIN comandos c
ON c.id_vehiculo=u.vehiculo AND c.codigo=0 AND c.activo WHERE u.estado<>'baja' AND c.id_comando IS NULL;
SELECT COUNT(*) AS pasos_autonomos_incompatibles FROM iot_paso WHERE codigo=64;

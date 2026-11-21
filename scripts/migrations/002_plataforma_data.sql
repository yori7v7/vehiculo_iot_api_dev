-- No automatic ownership, publication, or credential assignment.
START TRANSACTION;
SELECT COUNT(*) AS unidades_pendientes FROM vehiculos v
LEFT JOIN iot_unidad u ON u.vehiculo=v.id_vehiculo WHERE u.vehiculo IS NULL;
COMMIT;
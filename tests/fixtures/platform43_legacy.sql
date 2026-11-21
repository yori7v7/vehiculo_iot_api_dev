-- Datos sintéticos. Ejecutar sólo sobre la copia aislada del esquema legado.
INSERT INTO vehiculos(id_vehiculo,nombre,modelo) VALUES(81243,'Unidad fixture','Modelo fixture');
INSERT INTO comandos(id_comando,id_vehiculo,nombre,codigo) VALUES(81243,81243,'DETENER',0);
INSERT INTO estado_vehiculo(id_vehiculo,id_comando,conectado) VALUES(81243,81243,FALSE);
INSERT INTO historial_comandos(id_vehiculo,id_comando,origen) VALUES(81243,81243,'FIXTURE');
INSERT INTO demos(id_demo,id_vehiculo,nombre) VALUES(81243,81243,'DEMO fixture');
INSERT INTO demo_movimientos(id_demo,id_comando,orden,duracion_ms,pausa_ms) VALUES(81243,81243,1,50,30);

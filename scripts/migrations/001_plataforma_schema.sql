-- MySQL 8+. DDL commits implicitly. Review preflight before applying.
CREATE TABLE iot_usuario (
 id INT PRIMARY KEY AUTO_INCREMENT, email VARCHAR(254) NOT NULL UNIQUE,
 nombre VARCHAR(100) NOT NULL, clave VARCHAR(255) NOT NULL,
 rol ENUM('administrador','usuario') NOT NULL, activo BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB;
CREATE TABLE iot_modelo (
 id INT PRIMARY KEY AUTO_INCREMENT, sku VARCHAR(64) NOT NULL UNIQUE,
 nombre VARCHAR(80) NOT NULL, descripcion VARCHAR(255),
 publico BOOLEAN NOT NULL DEFAULT FALSE, activo BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB;
CREATE TABLE iot_capacidad (
 modelo INT NOT NULL, codigo INT NOT NULL, nombre VARCHAR(60) NOT NULL,
 invitado BOOLEAN NOT NULL DEFAULT FALSE, PRIMARY KEY(modelo,codigo),
 UNIQUE(modelo,nombre), FOREIGN KEY(modelo) REFERENCES iot_modelo(id)
) ENGINE=InnoDB;
CREATE TABLE iot_unidad (
 vehiculo INT PRIMARY KEY, serie VARCHAR(80) NOT NULL UNIQUE, modelo INT NOT NULL,
 propietario INT NULL, estado ENUM('inventario','exhibicion','vendida','baja') NOT NULL,
 historial_desde BIGINT NOT NULL DEFAULT 0, version INT UNSIGNED NOT NULL DEFAULT 1,
 dispositivo BINARY(32) NULL UNIQUE,
 FOREIGN KEY(vehiculo) REFERENCES vehiculos(id_vehiculo),
 FOREIGN KEY(modelo) REFERENCES iot_modelo(id),
 FOREIGN KEY(propietario) REFERENCES iot_usuario(id),
 CHECK ((estado='vendida') = (propietario IS NOT NULL))
) ENGINE=InnoDB;
CREATE TABLE iot_titularidad (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, vehiculo INT NOT NULL,
 propietario INT NULL, anterior INT NULL, actor INT NOT NULL,
 fecha DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)), INDEX(vehiculo,id),
 FOREIGN KEY(vehiculo) REFERENCES iot_unidad(vehiculo), FOREIGN KEY(propietario) REFERENCES iot_usuario(id),
 FOREIGN KEY(anterior) REFERENCES iot_usuario(id), FOREIGN KEY(actor) REFERENCES iot_usuario(id)
) ENGINE=InnoDB;
CREATE TABLE iot_sesion (
 huella BINARY(32) PRIMARY KEY, usuario INT NULL, vehiculo INT NULL,
 vence DATETIME(6) NOT NULL, revocada DATETIME(6) NULL,
 CHECK ((usuario IS NULL) <> (vehiculo IS NULL)),
 FOREIGN KEY(usuario) REFERENCES iot_usuario(id), FOREIGN KEY(vehiculo) REFERENCES iot_unidad(vehiculo),
 INDEX(vence)
) ENGINE=InnoDB;
CREATE TABLE iot_reserva (
 vehiculo INT PRIMARY KEY, sesion BINARY(32) NOT NULL UNIQUE,
 FOREIGN KEY(vehiculo) REFERENCES iot_unidad(vehiculo), FOREIGN KEY(sesion) REFERENCES iot_sesion(huella)
) ENGINE=InnoDB;
CREATE TABLE iot_intento (
 ambito BINARY(32) PRIMARY KEY, inicio DATETIME(6) NOT NULL, intentos INT UNSIGNED NOT NULL,
 INDEX(inicio)
) ENGINE=InnoDB;
CREATE TABLE iot_ticket (
 huella BINARY(32) PRIMARY KEY, sesion BINARY(32) NOT NULL, vehiculo INT NOT NULL,
 vence DATETIME(6) NOT NULL, INDEX(vence),
 FOREIGN KEY(sesion) REFERENCES iot_sesion(huella), FOREIGN KEY(vehiculo) REFERENCES iot_unidad(vehiculo)
) ENGINE=InnoDB;
CREATE TABLE iot_demo (
 id INT PRIMARY KEY AUTO_INCREMENT, modelo INT NOT NULL, vehiculo INT NULL, propietario INT NULL,
 version_unidad INT UNSIGNED NULL, nombre VARCHAR(80) NOT NULL, descripcion VARCHAR(255),
 activo BOOLEAN NOT NULL DEFAULT TRUE,
 CHECK ((vehiculo IS NULL) = (propietario IS NULL) AND (vehiculo IS NULL) = (version_unidad IS NULL)),
 FOREIGN KEY(modelo) REFERENCES iot_modelo(id), FOREIGN KEY(vehiculo) REFERENCES iot_unidad(vehiculo),
 FOREIGN KEY(propietario) REFERENCES iot_usuario(id)
) ENGINE=InnoDB;
CREATE TABLE iot_paso (
 id INT PRIMARY KEY AUTO_INCREMENT, demo INT NOT NULL, orden INT NOT NULL, codigo INT NOT NULL,
 duracion_ms INT UNSIGNED NOT NULL, pausa_ms INT UNSIGNED NOT NULL, UNIQUE(demo,orden),
 CHECK (orden BETWEEN 1 AND 24 AND duracion_ms BETWEEN 30 AND 12000 AND pausa_ms <= 12000),
 FOREIGN KEY(demo) REFERENCES iot_demo(id)
) ENGINE=InnoDB;
CREATE TABLE iot_auditoria (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, fecha DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
 actor INT NULL, vehiculo INT NULL, accion VARCHAR(60) NOT NULL, resultado VARCHAR(60) NOT NULL,
 FOREIGN KEY(actor) REFERENCES iot_usuario(id), FOREIGN KEY(vehiculo) REFERENCES iot_unidad(vehiculo)
) ENGINE=InnoDB;
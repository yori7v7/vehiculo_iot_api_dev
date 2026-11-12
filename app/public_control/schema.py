"""Migración inicial del almacén privado de coordinación."""

SCHEMA_VERSION = 1
APPLICATION_ID = 0x43504954

INITIAL_SCHEMA = (
    """
    CREATE TABLE control_vehicle (
        vehicle_id INTEGER PRIMARY KEY CHECK (vehicle_id BETWEEN 1 AND 2147483647),
        revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
        generation INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0),
        epoch INTEGER NOT NULL DEFAULT 0 CHECK (epoch >= 0),
        window_started REAL,
        window_expires REAL,
        window_request TEXT,
        stop_id TEXT,
        blocked_reason TEXT,
        CHECK (window_expires IS NULL OR window_expires > window_started)
    ) STRICT
    """,
    """
    CREATE TABLE control_turn (
        turn_id TEXT PRIMARY KEY,
        vehicle_id INTEGER NOT NULL REFERENCES control_vehicle(vehicle_id),
        token_digest BLOB NOT NULL UNIQUE CHECK (length(token_digest) = 32),
        generation INTEGER NOT NULL CHECK (generation >= 0),
        active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        absolute_expires REAL NOT NULL,
        idle_expires REAL NOT NULL,
        last_seq INTEGER NOT NULL DEFAULT 0 CHECK (last_seq BETWEEN 0 AND 2147483647),
        granted_at REAL NOT NULL,
        UNIQUE (vehicle_id, turn_id),
        CHECK (absolute_expires > granted_at),
        CHECK (idle_expires > granted_at AND idle_expires <= absolute_expires)
    ) STRICT
    """,
    """
    CREATE UNIQUE INDEX control_turn_one_active
    ON control_turn (vehicle_id) WHERE active = 1
    """,
    """
    CREATE TABLE control_operation (
        operation_id TEXT PRIMARY KEY,
        vehicle_id INTEGER NOT NULL REFERENCES control_vehicle(vehicle_id),
        turn_id TEXT,
        generation INTEGER NOT NULL CHECK (generation >= 0),
        epoch INTEGER NOT NULL CHECK (epoch >= 0),
        kind TEXT NOT NULL CHECK (kind IN ('move', 'stop', 'revoke')),
        request_id TEXT,
        sequence INTEGER,
        code INTEGER NOT NULL,
        duration_ms INTEGER NOT NULL,
        created_at REAL NOT NULL,
        deadline REAL,
        status TEXT NOT NULL,
        verified_at REAL,
        UNIQUE (vehicle_id, operation_id),
        FOREIGN KEY (vehicle_id, turn_id) REFERENCES control_turn(vehicle_id, turn_id),
        CHECK (
            (kind = 'move' AND turn_id IS NOT NULL AND request_id IS NOT NULL
                AND sequence IS NOT NULL AND sequence BETWEEN 1 AND 2147483647
                AND code IN (1, 2, 4, 5, 6, 8, 9, 10)
                AND duration_ms BETWEEN 100 AND 500 AND deadline IS NOT NULL
                AND status IN ('aceptada', 'despachada', 'rechazada', 'incierta', 'finalizada'))
            OR
            (kind IN ('stop', 'revoke') AND sequence IS NULL AND code = 0 AND duration_ms = 0
                AND status IN ('pendiente', 'verificada', 'incierta', 'fallida'))
        )
    ) STRICT
    """,
    """
    CREATE UNIQUE INDEX control_operation_idempotency
    ON control_operation (vehicle_id, coalesce(turn_id, ''), kind, request_id)
    WHERE request_id IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX control_operation_sequence
    ON control_operation (turn_id, sequence) WHERE kind = 'move'
    """,
    """
    CREATE INDEX control_operation_vehicle_status
    ON control_operation (vehicle_id, kind, status, deadline)
    """,
    """
    CREATE INDEX control_operation_turn_kind
    ON control_operation (turn_id, kind, deadline)
    """,
    """
    CREATE TABLE control_window_request (
        vehicle_id INTEGER NOT NULL REFERENCES control_vehicle(vehicle_id),
        request_id TEXT NOT NULL,
        started_at REAL NOT NULL,
        expires_at REAL NOT NULL CHECK (abs(expires_at - started_at - 1200) < 0.00001),
        PRIMARY KEY (vehicle_id, request_id)
    ) STRICT
    """,
    """
    CREATE TABLE control_stop_request (
        vehicle_id INTEGER NOT NULL,
        scope TEXT NOT NULL,
        request_id TEXT NOT NULL,
        operation_id TEXT NOT NULL,
        PRIMARY KEY (vehicle_id, scope, request_id),
        FOREIGN KEY (vehicle_id, operation_id) REFERENCES control_operation(vehicle_id, operation_id)
    ) STRICT
    """,
    """
    CREATE TABLE control_audit (
        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER NOT NULL REFERENCES control_vehicle(vehicle_id),
        occurred_at REAL NOT NULL,
        event TEXT NOT NULL,
        turn_id TEXT,
        operation_id TEXT,
        reason TEXT
    ) STRICT
    """,
    """
    CREATE INDEX control_audit_vehicle
    ON control_audit (vehicle_id, audit_id DESC)
    """,
)

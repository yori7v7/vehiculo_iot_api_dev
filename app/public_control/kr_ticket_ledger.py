"""5.5-K-R: registro PRIVADO y DURABLE de solicitudes virtuales del visitante.

SIN HTTP, sin AWS, sin WSS, sin conexiones al ESP y sin despachador físico.
Usa la MISMA transacción y época K-Q para que la comprobación de fencing
no tenga una carrera check-then-act. No reemplaza al modelo K-C real.
"""
from __future__ import annotations

from hashlib import sha256
from hmac import compare_digest, new as hmac_new
from math import isfinite
from secrets import token_bytes, token_urlsafe
from time import time
from typing import Callable
from uuid import UUID, uuid4

from app.public_control.kq_restart_fence import KQRestartFence


class KRTicketDenied(RuntimeError):
    """Operación virtual denegada. Nunca implica autorización de motores."""


_SCHEMA_VERSION = 1
_WINDOW_S = 300
_MAX_RECORDS = 5000
_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS kr_meta (
        id INTEGER PRIMARY KEY CHECK(id = 1),
        version INTEGER NOT NULL CHECK(version = 1),
        epoch INTEGER NOT NULL CHECK(epoch > 0),
        last_wall REAL NOT NULL,
        sealed INTEGER NOT NULL DEFAULT 0 CHECK(sealed IN (0, 1)),
        client_salt BLOB NOT NULL CHECK(length(client_salt) = 32)
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS kr_ticket (
        request_id TEXT PRIMARY KEY,
        epoch INTEGER NOT NULL CHECK(epoch > 0),
        browser_hash BLOB NOT NULL UNIQUE CHECK(length(browser_hash) = 32),
        client_digest BLOB NOT NULL CHECK(length(client_digest) = 32),
        display_code TEXT NOT NULL,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        virtual_until REAL,
        state TEXT NOT NULL CHECK(state IN
            ('waiting', 'approved_virtual', 'rejected', 'revoked', 'expired')),
        CHECK(expires_at > created_at),
        CHECK((state = 'approved_virtual' AND virtual_until IS NOT NULL)
            OR (state <> 'approved_virtual'))
    ) STRICT
    """,
    """CREATE INDEX IF NOT EXISTS kr_ticket_client_time
       ON kr_ticket(client_digest, created_at)""",
    """CREATE INDEX IF NOT EXISTS kr_ticket_epoch_state
       ON kr_ticket(epoch, state)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS kr_one_virtual_turn
       ON kr_ticket(epoch) WHERE state = 'approved_virtual'""",
    """
    CREATE TABLE IF NOT EXISTS kt_idempotency (
        key_digest BLOB PRIMARY KEY CHECK(length(key_digest) = 32),
        request_id TEXT NOT NULL UNIQUE,
        epoch INTEGER NOT NULL CHECK(epoch > 0),
        client_digest BLOB NOT NULL CHECK(length(client_digest) = 32),
        browser_hash BLOB NOT NULL CHECK(length(browser_hash) = 32)
    ) STRICT
    """,
)


class KRTicketLedger:
    """Cola virtual fail-closed y auditada; NO despacho ni turnos físicos.

    Siempre instanciar después de KQRestartFence.start(), con la época que
    devolvió. El archivo dedicado del K-Q y el del K-R deben ser EL MISMO.
    """

    def __init__(
        self, fence: KQRestartFence, epoch: int, admin_proof: str, *,
        clock: Callable[[], float] = time, max_pending: int = 5,
        max_per_client: int = 3, max_per_window: int = 40,
        pending_ttl: int = 120,
    ):
        if (type(admin_proof) is not str or len(admin_proof) < 32
                or type(epoch) is not int or epoch < 1
                or type(max_pending) is not int or not 1 <= max_pending <= 20
                or type(max_per_client) is not int or not 1 <= max_per_client <= 10
                or type(max_per_window) is not int or not 1 <= max_per_window <= 100
                or type(pending_ttl) is not int or not 10 <= pending_ttl <= 300):
            raise ValueError("Configuracion del registro virtual invalida")
        self._fence = fence
        self._epoch = epoch
        self._admin_hash = sha256(admin_proof.encode("utf-8")).digest()
        self._clock = clock
        self._max_pending = max_pending
        self._max_per_client = max_per_client
        self._max_per_window = max_per_window
        self._pending_ttl = pending_ttl
        self._prepared = False
        self._supervisor_at: float | None = None
        self._sealed = False

    def _admin(self, proof: str) -> None:
        if (type(proof) is not str or not compare_digest(
                sha256(proof.encode("utf-8")).digest(), self._admin_hash)):
            raise KRTicketDenied("Administrador no autorizado")

    def _now(self) -> float | None:
        value = self._clock()
        if type(value) not in (int, float) or not isfinite(value) or value < 0:
            return None
        return float(value)

    def prepare(self) -> None:
        """Instalar tabla privada y REVOCAR sesiones de épocas anteriores."""
        if self._prepared or self._sealed:
            raise KRTicketDenied("Esta instancia ya fue inicializada o cerrada")
        now = self._now()
        if now is None:
            raise KRTicketDenied("Hora del sistema invalida")
        with self._fence.transaction(self._epoch) as db:
            for statement in _SCHEMA:
                db.execute(statement)
            meta = db.execute("SELECT * FROM kr_meta WHERE id = 1").fetchone()
            if meta is None:
                db.execute(
                    "INSERT INTO kr_meta(id, version, epoch, last_wall, sealed, client_salt) "
                    "VALUES(1, ?, ?, ?, 0, ?)",
                    (_SCHEMA_VERSION, self._epoch, now, token_bytes(32)),
                )
            else:
                if (meta["version"] != _SCHEMA_VERSION or meta["sealed"] != 0
                        or len(meta["client_salt"]) != 32
                        or now < meta["last_wall"]
                        or meta["epoch"] > self._epoch):
                    raise KRTicketDenied(
                        "Journal de tickets incompatible o reloj retrocedio; cerrado"
                    )
                # Reciclar la misma época en un segundo registro NO es válido.
                if meta["epoch"] == self._epoch:
                    raise KRTicketDenied("La epoca ya se uso para tickets")
                db.execute(
                    "UPDATE kr_ticket SET state='revoked', virtual_until=NULL "
                    "WHERE state IN ('waiting','approved_virtual')"
                )
                db.execute(
                    "UPDATE kr_meta SET epoch=?, last_wall=?, sealed=0 WHERE id=1",
                    (self._epoch, now),
                )
        self._prepared = True

    def _cleanup(self, db, now: float) -> None:
        db.execute(
            "UPDATE kr_ticket SET state='expired' "
            "WHERE epoch=? AND state='waiting' AND expires_at <= ?",
            (self._epoch, now),
        )
        if (self._supervisor_at is None or now < self._supervisor_at
                or now >= self._supervisor_at + 15):
            db.execute(
                "UPDATE kr_ticket SET state='revoked', virtual_until=NULL "
                "WHERE epoch=? AND state='approved_virtual'",
                (self._epoch,),
            )
        db.execute(
            "UPDATE kr_ticket SET state='revoked', virtual_until=NULL "
            "WHERE epoch=? AND state='approved_virtual' AND virtual_until <= ?",
            (self._epoch, now),
        )
        db.execute(
            "DELETE FROM kr_ticket WHERE state IN ('expired','rejected','revoked') "
            "AND created_at < ?", (now - 86400,),
        )
        # Conservar los tickets y sus claves de repeticion en conjunto:
        # despues de 24 h ya no hay resultado que reenviar o revivir.
        db.execute(
            "DELETE FROM kt_idempotency WHERE request_id NOT IN "
            "(SELECT request_id FROM kr_ticket)"
        )

    def _run(self, callback):
        if not self._prepared or self._sealed:
            raise KRTicketDenied("Registro no preparado o cerrado")
        now = self._now()
        poisoned = False
        result = None
        with self._fence.transaction(self._epoch) as db:
            meta = db.execute("SELECT * FROM kr_meta WHERE id=1").fetchone()
            if (meta is None or meta["epoch"] != self._epoch
                    or meta["version"] != _SCHEMA_VERSION
                    or meta["sealed"] != 0):
                self._sealed = True
                raise KRTicketDenied("Epoca o journal de tickets no valido")
            if now is None or now < meta["last_wall"]:
                # Commit de bloqueo ANTES del error; nunca rollback del cierre.
                db.execute(
                    "UPDATE kr_meta SET sealed=1 WHERE id=1"
                )
                db.execute(
                    "UPDATE kr_ticket SET state='revoked', virtual_until=NULL "
                    "WHERE epoch=? AND state IN ('waiting','approved_virtual')",
                    (self._epoch,),
                )
                poisoned = True
            else:
                db.execute(
                    "UPDATE kr_meta SET last_wall=? WHERE id=1", (now,),
                )
                self._cleanup(db, now)
                result = callback(db, now, meta["client_salt"])
        if poisoned:
            self._sealed = True
            self._supervisor_at = None
            raise KRTicketDenied("Hora del servidor invalida; sesiones selladas")
        # Rechazo de negocio: confirmar las expiraciones y no dejar tickets
        # caducados en estado waiting por hacer rollback del mantenimiento.
        if isinstance(result, KRTicketDenied):
            raise result
        return result

    @staticmethod
    def _digest_secret(secret: str) -> bytes:
        if (type(secret) is not str or len(secret) != 43
                or not all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in secret)):
            raise KRTicketDenied("Sesion de navegador invalida")
        return sha256(secret.encode("ascii")).digest()

    def request(self, client_identity: str) -> dict:
        """Recibe identidad TCP YA comprobada por el perímetro; no X-Forwarded-*."""
        if type(client_identity) is not str or not 1 <= len(client_identity) <= 256:
            raise KRTicketDenied("Identidad de conexion invalida")

        def run(db, now, salt):
            client_hash = hmac_new(
                salt, client_identity.encode("utf-8"), "sha256"
            ).digest()
            recent = db.execute(
                "SELECT COUNT(*) FROM kr_ticket WHERE created_at > ?",
                (now - _WINDOW_S,),
            ).fetchone()[0]
            by_client = db.execute(
                "SELECT COUNT(*) FROM kr_ticket "
                "WHERE client_digest=? AND created_at > ?",
                (client_hash, now - _WINDOW_S),
            ).fetchone()[0]
            waiting = db.execute(
                "SELECT COUNT(*) FROM kr_ticket "
                "WHERE epoch=? AND state='waiting'",
                (self._epoch,),
            ).fetchone()[0]
            total = db.execute("SELECT COUNT(*) FROM kr_ticket").fetchone()[0]
            if (recent >= self._max_per_window or
                    by_client >= self._max_per_client or
                    waiting >= self._max_pending or total >= _MAX_RECORDS):
                return KRTicketDenied("Limite de solicitudes alcanzado")
            request_id = str(uuid4())
            secret = token_urlsafe(32)
            db.execute(
                "INSERT INTO kr_ticket(request_id, epoch, browser_hash, "
                "client_digest, display_code, created_at, expires_at, state) "
                "VALUES(?,?,?,?,?,?,?,'waiting')",
                (request_id, self._epoch, self._digest_secret(secret),
                 client_hash, request_id.split("-")[0].upper(),
                 now, now + self._pending_ttl),
            )
            return {
                "request_id": request_id, "browser_secret": secret,
                "display_code": request_id.split("-")[0].upper(),
                "estado": "esperando_autorizacion",
                "simulado": True, "control_fisico": False, "canDrive": False,
            }

        return self._run(run)

    def request_idempotent(
        self, client_identity: str, idempotency_key: str, browser_secret: str,
    ) -> dict:
        """K-T: repetir la misma petición nunca genera otro ticket.

        El navegador crea ANTES de enviar dos valores aleatorios de 32 bytes
        Base64url: clave de idempotencia y secreto de sesión. El servidor
        guarda exclusivamente resúmenes HMAC/SHA-256 y puede responder a un
        reintento aun cuando la primera respuesta HTTP se haya perdido.

        Una aprobación virtual anterior jamás se traduce en canDrive=True.
        Claves reutilizadas con otro cliente o secreto se rechazan cerradas.
        """
        if type(client_identity) is not str or not 1 <= len(client_identity) <= 256:
            raise KRTicketDenied("Identidad de conexion invalida")
        key_hash = self._digest_secret(idempotency_key)
        secret_hash = self._digest_secret(browser_secret)

        def run(db, now, salt):
            # El hash de la clave incorpora un salt durable secreto; una
            # clave elegida por el visitante no se guarda en texto plano.
            dedup = hmac_new(salt, b"KT:" + key_hash, "sha256").digest()
            client_hash = hmac_new(
                salt, client_identity.encode("utf-8"), "sha256"
            ).digest()
            previous = db.execute(
                "SELECT i.epoch, i.request_id, i.client_digest, i.browser_hash, "
                "t.display_code, t.state, t.expires_at "
                "FROM kt_idempotency i LEFT JOIN kr_ticket t "
                "ON t.request_id=i.request_id WHERE i.key_digest=?",
                (dedup,),
            ).fetchone()
            if previous is not None:
                if (previous["epoch"] != self._epoch
                        or not compare_digest(previous["client_digest"], client_hash)
                        or not compare_digest(previous["browser_hash"], secret_hash)
                        or previous["display_code"] is None
                        or previous["state"] != "waiting"
                        or previous["expires_at"] <= now):
                    return KRTicketDenied("Reintento de solicitud no vigente")
                return {
                    "request_id": previous["request_id"],
                    "display_code": previous["display_code"],
                    "browser_secret": browser_secret,
                    "estado": "esperando_autorizacion",
                    "idempotent_replay": True,
                    "simulado": True, "control_fisico": False, "canDrive": False,
                }
            # Un secreto ya asociado a otro ticket nunca puede reutilizarse.
            if db.execute(
                "SELECT 1 FROM kr_ticket WHERE browser_hash=? LIMIT 1",
                (secret_hash,),
            ).fetchone():
                return KRTicketDenied("La sesion ya fue usada en otra solicitud")

            recent = db.execute(
                "SELECT COUNT(*) FROM kr_ticket WHERE created_at > ?",
                (now - _WINDOW_S,),
            ).fetchone()[0]
            per_client = db.execute(
                "SELECT COUNT(*) FROM kr_ticket "
                "WHERE client_digest=? AND created_at > ?",
                (client_hash, now - _WINDOW_S),
            ).fetchone()[0]
            pending = db.execute(
                "SELECT COUNT(*) FROM kr_ticket "
                "WHERE epoch=? AND state='waiting'",
                (self._epoch,),
            ).fetchone()[0]
            count_all = db.execute("SELECT COUNT(*) FROM kr_ticket").fetchone()[0]
            if (recent >= self._max_per_window or
                    per_client >= self._max_per_client or
                    pending >= self._max_pending or count_all >= _MAX_RECORDS):
                return KRTicketDenied("Limite de solicitudes alcanzado")

            request_id = str(uuid4())
            code = request_id.split("-")[0].upper()
            db.execute(
                "INSERT INTO kr_ticket(request_id,epoch,browser_hash,client_digest,"
                "display_code,created_at,expires_at,state) "
                "VALUES(?,?,?,?,?,?,?,'waiting')",
                (request_id,self._epoch,secret_hash,client_hash,code,
                 now,now+self._pending_ttl),
            )
            db.execute(
                "INSERT INTO kt_idempotency(key_digest,request_id,epoch,"
                "client_digest,browser_hash) VALUES(?,?,?,?,?)",
                (dedup,request_id,self._epoch,client_hash,secret_hash),
            )
            return {
                "request_id": request_id, "display_code": code,
                "browser_secret": browser_secret,
                "estado": "esperando_autorizacion", "idempotent_replay": False,
                "simulado": True, "control_fisico": False, "canDrive": False,
            }
        return self._run(run)

    def status(self, browser_secret: str) -> dict:
        secret_hash = self._digest_secret(browser_secret)

        def run(db, _now, _salt):
            row = db.execute(
                "SELECT state, display_code FROM kr_ticket "
                "WHERE epoch=? AND browser_hash=?",
                (self._epoch, secret_hash),
            ).fetchone()
            if row is None:
                return KRTicketDenied("Sesion inexistente o de epoca anterior")
            return {
                "estado": {
                    "waiting": "esperando_autorizacion",
                    "approved_virtual": "autorizado_virtual",
                    "rejected": "revocado_o_caducado",
                    "revoked": "revocado_o_caducado",
                    "expired": "revocado_o_caducado",
                }[row["state"]],
                "display_code": row["display_code"], "simulado": True,
                "control_fisico": False, "canDrive": False,
            }

        return self._run(run)

    def snapshot(self, admin_proof: str) -> dict:
        self._admin(admin_proof)

        def run(db, now, _salt):
            pending = db.execute(
                "SELECT request_id, display_code, expires_at FROM kr_ticket "
                "WHERE epoch=? AND state='waiting' ORDER BY created_at, request_id",
                (self._epoch,),
            ).fetchall()
            approved = db.execute(
                "SELECT COUNT(*) FROM kr_ticket "
                "WHERE epoch=? AND state='approved_virtual'",
                (self._epoch,),
            ).fetchone()[0]
            return {
                "solicitudes": [
                    {"request_id": row["request_id"],
                     "display_code": row["display_code"],
                     "vence_en_seg": max(0, int(row["expires_at"] - now))}
                    for row in pending
                ],
                "turno_virtual_activo": approved == 1,
                "simulado": True, "control_fisico": False, "canDrive": False,
            }

        return self._run(run)

    def supervise(self, admin_proof: str) -> dict:
        self._admin(admin_proof)

        def run(_db, now, _salt):
            return now
        self._supervisor_at = self._run(run)
        return {"supervision_virtual": True, "simulado": True, "control_fisico": False}

    def approve_virtual(self, admin_proof: str, request_id: str, *, seconds: int = 120) -> dict:
        self._admin(admin_proof)
        if type(seconds) is not int or not 1 <= seconds <= 120:
            raise KRTicketDenied("Duracion virtual no permitida")
        try:
            UUID(request_id)
        except (TypeError, ValueError, AttributeError):
            raise KRTicketDenied("Identificador de solicitud invalido") from None

        def run(db, now, _salt):
            if (self._supervisor_at is None or now < self._supervisor_at
                    or now >= self._supervisor_at + 15):
                return KRTicketDenied("Supervision virtual no vigente")
            row = db.execute(
                "SELECT state, expires_at FROM kr_ticket "
                "WHERE epoch=? AND request_id=?",
                (self._epoch, request_id),
            ).fetchone()
            if row is None or row["state"] != "waiting" or now >= row["expires_at"]:
                return KRTicketDenied("Ticket virtual no vigente")
            if db.execute(
                "SELECT 1 FROM kr_ticket WHERE epoch=? "
                "AND state='approved_virtual' LIMIT 1",
                (self._epoch,),
            ).fetchone():
                return KRTicketDenied("Ya existe un turno virtual")
            db.execute(
                "UPDATE kr_ticket SET state='approved_virtual', virtual_until=? "
                "WHERE request_id=? AND epoch=? AND state='waiting'",
                (min(now + seconds, now + 120), request_id, self._epoch),
            )
            return {"aprobada_virtual": True, "simulado": True,
                    "control_fisico": False, "canDrive": False}
        return self._run(run)

    def reject(self, admin_proof: str, request_id: str) -> None:
        self._admin(admin_proof)
        def run(db, _now, _salt):
            row = db.execute(
                "UPDATE kr_ticket SET state='rejected' WHERE epoch=? "
                "AND request_id=? AND state='waiting'",
                (self._epoch, request_id),
            )
            if row.rowcount != 1:
                return KRTicketDenied("Ticket no pendiente")
        self._run(run)

    def revoke(self, admin_proof: str) -> None:
        self._admin(admin_proof)
        def run(db, _now, _salt):
            db.execute(
                "UPDATE kr_ticket SET state='revoked', virtual_until=NULL "
                "WHERE epoch=? AND state IN ('waiting','approved_virtual')",
                (self._epoch,),
            )
        self._run(run)
        self._supervisor_at = None

    def close(self) -> None:
        """Cerrar vista de KR. No libera el propietario KQ."""
        self._prepared = False
        self._supervisor_at = None
        self._sealed = True

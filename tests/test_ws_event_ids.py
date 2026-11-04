"""RN07: cada publicacion WSS tiene una identidad unica.

Dos POST legitimos del mismo comando NO deben producir el mismo id_evento.
Un reenvio de la misma carga JSON conserva el identificador del evento.
"""

from datetime import datetime, timezone

from app.models.movement import MovementResponse
from app.websocket.demo_events import DemoEvent
from app.websocket.events import MovementEvent


def _movement_response() -> MovementResponse:
    return MovementResponse(
        resultado="ok",
        id_vehiculo=1,
        id_comando=11,
        comando="CLAXON",
        codigo=128,
        fecha_actualizacion=datetime.now(timezone.utc),
        conectado=True,
        origen="API",
    )


def test_two_independent_posts_get_different_event_ids():
    first = MovementEvent.from_movement(_movement_response())
    second = MovementEvent.from_movement(_movement_response())
    assert len(first.id_evento) == len(second.id_evento) == 32
    assert first.id_evento != second.id_evento
    assert first.codigo == second.codigo == 128


def test_reserializing_same_event_preserves_event_id():
    event = MovementEvent.from_movement(_movement_response())
    data = event.model_dump(mode="json")
    same_message_again = event.model_dump(mode="json")
    assert data["id_evento"] == same_message_again["id_evento"]


def test_demo_events_have_unique_ids():
    values = dict(
        tipo_evento="demo_movimiento",
        id_vehiculo=1,
        id_demo=1,
        nombre_demo="DEMO principal",
        timestamp=datetime.now(timezone.utc),
        id_demo_movimiento=1,
        id_comando=2,
        comando="AVANZAR",
        codigo=1,
        orden=1,
        duracion_ms=3000,
        pausa_ms=700,
    )
    first = DemoEvent(**values)
    second = DemoEvent(**values)
    assert len(first.id_evento) == len(second.id_evento) == 32
    assert first.id_evento != second.id_evento

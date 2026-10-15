"""Errores de recursos, independientes del transporte HTTP y del driver."""


class ResourceNotFoundError(Exception):
    """Un recurso solicitado no existe o no pertenece al padre indicado."""

    def __init__(self, message: str = "El recurso solicitado no existe.") -> None:
        super().__init__(message)


class ResourceConflictError(Exception):
    """El estado del recurso impide una operación de negocio solicitada."""

    def __init__(self, message: str = "El estado del recurso impide esta operación.") -> None:
        super().__init__(message)

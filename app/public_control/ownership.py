"""Un propietario de coordinación por archivo SQLite y host."""

import os
from pathlib import Path
from typing import Self

from app.public_control.local_files import open_private, private_parent

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class CoordinatorUnavailable(RuntimeError):
    """El coordinador no puede adquirir propiedad exclusiva."""


class CoordinatorOwnership:
    def __init__(self, path: Path | str):
        database = Path(path)
        self._path = database.with_name(database.name + ".lock")
        self._fd: int | None = None

    def acquire(self) -> None:
        if self._fd is not None:
            raise CoordinatorUnavailable("El coordinador ya tiene un propietario.")
        fd = None
        try:
            fd = open_private(private_parent(self._path))
            if os.name == "nt":
                # LK_NBLCK no espera y el rango puede superar el fin de archivo.
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if fd is not None:
                os.close(fd)
            raise CoordinatorUnavailable("No se pudo adquirir el coordinador local.") from None
        self._fd = fd

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is not None:
            # El archivo permanece para que todos los procesos bloqueen el mismo objeto.
            try:
                if os.name == "nt":
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            finally:
                os.close(fd)

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(self, *_exception) -> None:
        self.release()

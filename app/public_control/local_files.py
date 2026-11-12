"""Archivos locales privados para SQLite y el bloqueo de proceso."""

import os
from pathlib import Path
import stat


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def private_parent(path: Path) -> Path:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise OSError("La ruta de almacenamiento debe ser un archivo absoluto.")
    check_private(path.parent, directory=True)
    path = path.parent.resolve(strict=True) / path.name
    if path.is_relative_to(PROJECT_ROOT):
        raise OSError("La ruta de almacenamiento debe estar fuera del repositorio.")
    if os.name == "nt":
        if _kernel.GetDriveTypeW(path.anchor) not in {2, 3}:
            raise OSError("El almacenamiento requiere una unidad local.")
        if ":" in path.name or path.name.endswith((" ", ".")):
            raise OSError("El nombre del archivo de almacenamiento no es válido.")
    return path


def check_private(path: Path, *, directory: bool = False) -> os.stat_result:
    info = path.lstat()
    is_reparse_point = getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    if is_reparse_point or not valid_type:
        raise OSError("El almacenamiento requiere archivos locales regulares.")
    if os.name == "nt":
        _check_windows_acl(path)
    elif info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise OSError("Los permisos de almacenamiento no son privados.")
    return info


def open_private(path: Path) -> int:
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        check_private(path)
    except FileNotFoundError:
        try:
            fd = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            fd = os.open(path, flags)
    else:
        fd = os.open(path, flags)
    try:
        if not os.path.samestat(os.fstat(fd), check_private(path)):
            raise OSError("El archivo de almacenamiento cambió al abrirse.")
    except BaseException:
        os.close(fd)
        raise
    return fd


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _ACL(ctypes.Structure):
        _fields_ = [
            ("revision", wintypes.BYTE), ("reserved", wintypes.BYTE),
            ("size", wintypes.WORD), ("ace_count", wintypes.WORD),
            ("reserved2", wintypes.WORD),
        ]

    class _ACEHeader(ctypes.Structure):
        _fields_ = [("kind", wintypes.BYTE), ("flags", wintypes.BYTE), ("size", wintypes.WORD)]

    _advapi = ctypes.WinDLL("advapi32.dll", use_last_error=True)
    _kernel = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    _void = ctypes.c_void_p
    _out = ctypes.POINTER(_void)
    _advapi.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, _out, _out, _out, _out, _out,
    ]
    _advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi.GetAce.argtypes = [_void, wintypes.DWORD, _out]
    _advapi.GetAce.restype = wintypes.BOOL
    _advapi.ConvertSidToStringSidW.argtypes = [_void, _out]
    _advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    _kernel.LocalFree.argtypes = [_void]
    _kernel.LocalFree.restype = _void
    _kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    _kernel.GetDriveTypeW.restype = wintypes.UINT
    _kernel.GetCurrentProcess.argtypes = []
    _kernel.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    _advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    _advapi.OpenProcessToken.restype = wintypes.BOOL
    _advapi.GetTokenInformation.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, _void, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    _advapi.GetTokenInformation.restype = wintypes.BOOL

    def _windows_sid(pointer: _void) -> str:
        value = _void()
        if not _advapi.ConvertSidToStringSidW(pointer, ctypes.byref(value)):
            raise OSError("No se pudo validar el SID de almacenamiento.")
        try:
            return ctypes.wstring_at(value)
        finally:
            _kernel.LocalFree(value)

    def _current_windows_sid() -> str:
        token = wintypes.HANDLE()
        if not _advapi.OpenProcessToken(_kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            raise OSError("No se pudo verificar la identidad del proceso.")
        try:
            size = wintypes.DWORD()
            _advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            if not size.value:
                raise OSError("No se pudo verificar la identidad del proceso.")
            information = ctypes.create_string_buffer(size.value)
            if not _advapi.GetTokenInformation(token, 1, information, size.value, ctypes.byref(size)):
                raise OSError("No se pudo verificar la identidad del proceso.")
            sid_pointer = ctypes.cast(information, _out)[0]
            return _windows_sid(_void(sid_pointer))
        finally:
            _kernel.CloseHandle(token)

    def _check_windows_acl(path: Path) -> None:
        owner, dacl, descriptor = _void(), _void(), _void()
        # SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION.
        result = _advapi.GetNamedSecurityInfoW(
            str(path), 1, 5, ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor),
        )
        if result:
            if result in {2, 3}:  # El journal puede desaparecer al confirmar una transacción.
                raise FileNotFoundError("El archivo local ya no existe.")
            raise OSError("No se pudo verificar la ACL de almacenamiento.")
        try:
            if not owner or not dacl:
                raise OSError("El almacenamiento requiere una ACL privada.")
            trusted_owners = {_current_windows_sid(), "S-1-5-18", "S-1-5-32-544"}  # SYSTEM y Administradores.
            if _windows_sid(owner) not in trusted_owners:
                raise OSError("El propietario del almacenamiento no es de confianza.")
            for index in range(ctypes.cast(dacl, ctypes.POINTER(_ACL)).contents.ace_count):
                ace = _void()
                if not _advapi.GetAce(dacl, index, ctypes.byref(ace)):
                    raise OSError("No se pudo verificar la ACL de almacenamiento.")
                header = ctypes.cast(ace, ctypes.POINTER(_ACEHeader)).contents
                if header.kind in {1, 6, 10, 12}:  # ACE de denegación.
                    continue
                sid_offset = ctypes.sizeof(_ACEHeader) + ctypes.sizeof(wintypes.DWORD)
                if header.kind != 0 or header.size < sid_offset + 8:
                    raise OSError("El almacenamiento requiere permisos explícitos y privados.")
                sid = _windows_sid(_void(ace.value + sid_offset))
                # OWNER RIGHTS aplica al propietario validado. CREATOR OWNER
                # en una ACE de solo herencia se materializa en el propietario del hijo.
                if sid == "S-1-3-4" or (sid == "S-1-3-0" and header.flags & 0x08):
                    continue
                if sid not in trusted_owners:
                    raise OSError("La ACL de almacenamiento permite acceso a terceros.")
        finally:
            _kernel.LocalFree(descriptor)

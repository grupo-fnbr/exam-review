"""Base de datos local cifrada.

Todo el contenido (alumnos, notas, configuración) vive en una base SQLite en memoria.
En disco solo existe el fichero cifrado con AES-256-GCM; la clave se deriva de la
contraseña maestra con scrypt. Sin la contraseña no se puede leer nada.

Formato del fichero: MAGIC (5 bytes) | sal (16) | nonce (12) | datos cifrados.
"""

from __future__ import annotations

import hmac
import os
import sqlite3

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"CAEC1"
LONG_SAL = 16
LONG_NONCE = 12
MIN_LONG_CONTRASENA = 10


class ContrasenaIncorrecta(Exception):
    pass


class FicheroNoValido(Exception):
    pass


def _derivar_clave(contrasena: str, sal: bytes) -> bytes:
    return Scrypt(salt=sal, length=32, n=2**15, r=8, p=1).derive(contrasena.encode("utf-8"))


def _conectar_memoria() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


class Boveda:
    def __init__(self, ruta: str):
        self.ruta = ruta
        self.conn: sqlite3.Connection | None = None
        self._clave: bytes | None = None
        self._sal: bytes | None = None
        self._cambios_guardados = 0

    def existe(self) -> bool:
        return os.path.exists(self.ruta)

    @property
    def abierta(self) -> bool:
        return self.conn is not None

    def crear(self, contrasena: str, esquema: str) -> None:
        if self.existe():
            raise FileExistsError(self.ruta)
        if len(contrasena) < MIN_LONG_CONTRASENA:
            raise ValueError(f"La contraseña debe tener al menos {MIN_LONG_CONTRASENA} caracteres.")
        os.makedirs(os.path.dirname(os.path.abspath(self.ruta)), exist_ok=True)
        self._sal = os.urandom(LONG_SAL)
        self._clave = _derivar_clave(contrasena, self._sal)
        self.conn = _conectar_memoria()
        self.conn.executescript(esquema)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.guardar()

    def abrir(self, contrasena: str, esquema: str | None = None) -> None:
        with open(self.ruta, "rb") as f:
            datos = f.read()
        if not datos.startswith(MAGIC) or len(datos) < len(MAGIC) + LONG_SAL + LONG_NONCE + 16:
            raise FicheroNoValido("El fichero de datos no es de esta aplicación o está dañado.")
        i = len(MAGIC)
        sal = datos[i : i + LONG_SAL]
        nonce = datos[i + LONG_SAL : i + LONG_SAL + LONG_NONCE]
        cifrado = datos[i + LONG_SAL + LONG_NONCE :]
        clave = _derivar_clave(contrasena, sal)
        try:
            plano = AESGCM(clave).decrypt(nonce, cifrado, MAGIC)
        except InvalidTag:
            raise ContrasenaIncorrecta() from None
        conn = _conectar_memoria()
        conn.deserialize(plano)
        if esquema:
            conn.executescript(esquema)  # crea tablas nuevas de versiones posteriores
        conn.execute("PRAGMA foreign_keys = ON")
        self.conn, self._clave, self._sal = conn, clave, sal
        self._cambios_guardados = conn.total_changes

    def verificar(self, contrasena: str) -> bool:
        if not self.abierta or self._sal is None or self._clave is None:
            return False
        return hmac.compare_digest(_derivar_clave(contrasena, self._sal), self._clave)

    def hay_cambios(self) -> bool:
        return self.abierta and self.conn.total_changes != self._cambios_guardados

    def guardar(self) -> None:
        if not self.abierta:
            return
        self.conn.commit()
        plano = self.conn.serialize()
        nonce = os.urandom(LONG_NONCE)
        cifrado = AESGCM(self._clave).encrypt(nonce, plano, MAGIC)
        temporal = self.ruta + ".tmp"
        descriptor = os.open(temporal, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "wb") as f:
            f.write(MAGIC + self._sal + nonce + cifrado)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporal, self.ruta)
        self._cambios_guardados = self.conn.total_changes

    def cambiar_contrasena(self, actual: str, nueva: str) -> None:
        if not self.verificar(actual):
            raise ContrasenaIncorrecta()
        if len(nueva) < MIN_LONG_CONTRASENA:
            raise ValueError(f"La contraseña debe tener al menos {MIN_LONG_CONTRASENA} caracteres.")
        self._sal = os.urandom(LONG_SAL)
        self._clave = _derivar_clave(nueva, self._sal)
        self.guardar()

    def cerrar(self) -> None:
        if self.abierta:
            self.guardar()
            self.conn.close()
        self.conn = None
        self._clave = None
        self._sal = None

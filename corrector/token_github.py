"""Guarda el token de GitHub en el llavero del sistema (Keychain, Credential Manager,
Secret Service). Si el sistema no tiene llavero, se guarda dentro de la bóveda cifrada.
El token nunca se escribe en claro en disco ni se envía al navegador."""

from __future__ import annotations

import os

from .db import cfg_get, cfg_set

SERVICIO = "corrector-aec"
CUENTA = "github-token"


def _keyring():
    if os.environ.get("CORRECTOR_SIN_LLAVERO"):
        return None
    try:
        import keyring
        from keyring.backends import fail

        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def guardar(conn, token: str) -> str:
    """Devuelve dónde se ha guardado: 'llavero' o 'boveda'."""
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICIO, CUENTA, token)
            cfg_set(conn, "github_token", None)
            cfg_set(conn, "token_en", "llavero")
            return "llavero"
        except Exception:
            pass
    cfg_set(conn, "github_token", token)
    cfg_set(conn, "token_en", "boveda")
    return "boveda"


def leer(conn) -> str | None:
    if cfg_get(conn, "token_en") == "llavero":
        kr = _keyring()
        if kr is not None:
            try:
                return kr.get_password(SERVICIO, CUENTA)
            except Exception:
                return None
        return None
    return cfg_get(conn, "github_token")


def borrar(conn) -> None:
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICIO, CUENTA)
        except Exception:
            pass
    cfg_set(conn, "github_token", None)
    cfg_set(conn, "token_en", None)


def ubicacion(conn) -> str | None:
    return cfg_get(conn, "token_en")

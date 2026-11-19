"""Normalización de nombres de carpeta y mensajes de commit."""

from __future__ import annotations

import re
import unicodedata

COMILLAS = "\"'“”‘’«»`"
PARTICULAS = {"de", "del", "la", "las", "los", "y", "da", "das", "do", "dos", "van", "von", "di"}


def sin_tildes(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def palabras(texto: str) -> list[str]:
    """Palabras en minúsculas y sin tildes; cualquier signo separa."""
    return [p for p in re.split(r"[^a-z0-9]+", sin_tildes(texto).lower()) if p]


def carpeta_esperada(nombre: str, apellidos: str) -> str:
    """Formato nombre.apellido: primer nombre y primer apellido, minúsculas y sin tildes."""
    n = palabras(nombre)
    a = [p for p in palabras(apellidos) if p not in PARTICULAS] or palabras(apellidos)
    partes = [x for x in (n[0] if n else "", a[0] if a else "") if x]
    return ".".join(partes)


def formato_valido(carpeta: str) -> bool:
    return re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", carpeta or "") is not None


def coincidencia_carpeta(carpeta: str, nombre: str, apellidos: str, esperada: str, variantes: list[str]) -> str | None:
    """Devuelve 'exacta', 'aproximada' o None.

    - exacta: igual a la carpeta esperada o a una variante aceptada por el profesor.
    - aproximada: difiere solo en tildes, mayúsculas o separadores, o usa otro de sus
      nombres/apellidos (p. ej. maria.jose.nunez o maria.garcia).
    """
    if not carpeta:
        return None
    if carpeta == esperada or carpeta in variantes:
        return "exacta"
    normal = ".".join(palabras(carpeta))
    if normal == esperada or normal in variantes:
        return "aproximada"
    p = palabras(carpeta)
    nombres = set(palabras(nombre))
    apell = set(palabras(apellidos)) - PARTICULAS
    if len(p) >= 2 and p[0] in nombres and any(x in apell for x in p[1:]):
        return "aproximada"
    return None


def normalizar_mensaje(mensaje: str) -> str:
    """Primera línea del mensaje, sin comillas envolventes ni espacios repetidos."""
    linea = (mensaje or "").strip().splitlines()[0] if (mensaje or "").strip() else ""
    linea = linea.strip()
    while len(linea) >= 2 and linea[0] in COMILLAS and linea[-1] in COMILLAS:
        linea = linea[1:-1].strip()
    return re.sub(r"\s+", " ", linea)


def comparar_mensaje(mensaje: str, aceptados: list[str]) -> str | None:
    """'exacto', 'mayusculas' (solo cambia mayúsculas/tildes) o None."""
    m = normalizar_mensaje(mensaje)
    acept = [normalizar_mensaje(a) for a in aceptados]
    if m in acept:
        return "exacto"
    clave = sin_tildes(m).casefold()
    if any(sin_tildes(a).casefold() == clave for a in acept):
        return "mayusculas"
    return None

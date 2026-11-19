"""Lectura de rúbricas en .docx (tabla con columnas «Criterio» y «Peso»)."""

from __future__ import annotations

import io
import re


class ErrorRubrica(Exception):
    pass


def _numero(texto: str) -> float | None:
    m = re.search(r"\d+(?:[.,]\d+)?", texto or "")
    if not m:
        return None
    return float(m.group(0).replace(",", "."))


def leer_rubrica_docx(contenido: bytes) -> list[tuple[str, float]]:
    """Devuelve [(criterio, peso_en_%)] de la primera tabla con cabeceras Criterio y Peso."""
    from docx import Document

    try:
        doc = Document(io.BytesIO(contenido))
    except Exception:
        raise ErrorRubrica("No se pudo abrir el .docx.") from None
    for tabla in doc.tables:
        if not tabla.rows:
            continue
        cab = [c.text.strip().lower() for c in tabla.rows[0].cells]
        i_crit = next((i for i, c in enumerate(cab) if "criterio" in c), None)
        i_peso = next((i for i, c in enumerate(cab) if "peso" in c), None)
        if i_crit is None or i_peso is None:
            continue
        criterios = []
        for fila in tabla.rows[1:]:
            celdas = [c.text.strip() for c in fila.cells]
            nombre = re.sub(r"\s+", " ", celdas[i_crit])
            peso = _numero(celdas[i_peso])
            if nombre and peso is not None:
                criterios.append((nombre, peso))
        if criterios:
            return criterios
    raise ErrorRubrica("No hay ninguna tabla con columnas «Criterio» y «Peso».")


def leer_rubrica_texto(texto: str) -> list[tuple[str, float, list[str]]]:
    """Formato editable: una línea por criterio «Nombre; peso; check1, check2»."""
    criterios = []
    for n, linea in enumerate(texto.splitlines(), start=1):
        if not linea.strip():
            continue
        partes = [p.strip() for p in linea.split(";")]
        if len(partes) < 2:
            raise ErrorRubrica(f"Línea {n}: usa «Nombre; peso; comprobaciones».")
        peso = _numero(partes[1])
        if peso is None:
            raise ErrorRubrica(f"Línea {n}: el peso «{partes[1]}» no es un número.")
        checks = [c.strip() for c in partes[2].split(",") if c.strip()] if len(partes) > 2 else []
        criterios.append((partes[0], peso, checks))
    return criterios

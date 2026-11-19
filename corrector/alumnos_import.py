"""Importación de la lista de alumnos desde CSV o Excel (formato del campus libre)."""

from __future__ import annotations

import csv
import io
import json

from .nombres import carpeta_esperada, palabras

CAMPOS = {
    "nombre": "Nombre",
    "apellidos": "Apellidos",
    "nombre_completo": "Nombre completo (si va en una sola columna)",
    "email": "Email",
    "usuario_git": "Usuario de GitHub",
}

PISTAS = {
    "nombre": ["nombre", "first name", "nombres"],
    "apellidos": ["apellido", "apellidos", "apellido(s)", "last name", "surname"],
    "nombre_completo": ["nombre completo", "alumno", "estudiante", "full name"],
    "email": ["email", "correo", "dirección de correo", "direccion de correo", "e-mail", "mail"],
    "usuario_git": ["github", "usuario github", "usuario de github", "git"],
}


class ErrorImportacion(Exception):
    pass


def leer_tabla(nombre_fichero: str, contenido: bytes) -> tuple[list[str], list[list[str]]]:
    nombre = nombre_fichero.lower()
    if nombre.endswith((".xlsx", ".xlsm")):
        filas = _leer_excel(contenido)
    elif nombre.endswith((".csv", ".txt", ".tsv")):
        filas = _leer_csv(contenido)
    else:
        raise ErrorImportacion("Formato no admitido. Usa un .csv o un .xlsx.")
    filas = [[("" if c is None else str(c)).strip() for c in f] for f in filas]
    filas = [f for f in filas if any(f)]
    if len(filas) < 2:
        raise ErrorImportacion("El fichero no tiene cabecera y al menos un alumno.")
    cabecera = filas[0]
    ancho = len(cabecera)
    datos = [(f + [""] * ancho)[:ancho] for f in filas[1:]]
    return cabecera, datos


def _leer_csv(contenido: bytes) -> list[list[str]]:
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            texto = contenido.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ErrorImportacion("No se reconoce la codificación del CSV.")
    try:
        dialecto = csv.Sniffer().sniff(texto[:4096], delimiters=",;\t")
    except csv.Error:
        dialecto = csv.excel
    return list(csv.reader(io.StringIO(texto), dialecto))


def _leer_excel(contenido: bytes) -> list[list]:
    from openpyxl import load_workbook

    try:
        libro = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except Exception:
        raise ErrorImportacion("No se pudo abrir el Excel.") from None
    hoja = libro.worksheets[0]
    return [list(f) for f in hoja.iter_rows(values_only=True)]


def adivinar_mapeo(cabecera: list[str], previo: dict | None = None) -> dict:
    """Propone qué columna es cada campo. Reutiliza el mapeo del año anterior si encaja."""
    mapeo = {}
    if previo:
        for campo, titulo in previo.items():
            if titulo in cabecera:
                mapeo[campo] = titulo
    bajas = {c.lower().strip(): c for c in cabecera}
    for campo, pistas in PISTAS.items():
        if campo in mapeo:
            continue
        for p in pistas:
            if p in bajas and bajas[p] not in mapeo.values():
                mapeo[campo] = bajas[p]
                break
    if "nombre" in mapeo and "apellidos" in mapeo:
        mapeo.pop("nombre_completo", None)
    return mapeo


def _separar_completo(texto: str) -> tuple[str, str]:
    if "," in texto:
        apellidos, nombre = texto.split(",", 1)
        return nombre.strip(), apellidos.strip()
    partes = texto.split()
    if len(partes) < 2:
        return texto.strip(), ""
    return partes[0], " ".join(partes[1:])


def construir_alumnos(cabecera: list[str], datos: list[list[str]], mapeo: dict) -> tuple[list[dict], list[str]]:
    """Devuelve (alumnos, avisos). Cada alumno: nombre, apellidos, email, usuario_git, carpeta_esperada."""
    indice = {campo: cabecera.index(col) for campo, col in mapeo.items() if col in cabecera}
    if not ({"nombre", "apellidos"} <= indice.keys() or "nombre_completo" in indice):
        raise ErrorImportacion("Indica las columnas de nombre y apellidos (o la de nombre completo).")
    alumnos, avisos = [], []
    for n, fila in enumerate(datos, start=2):
        if "nombre_completo" in indice and not {"nombre", "apellidos"} <= indice.keys():
            nombre, apellidos = _separar_completo(fila[indice["nombre_completo"]])
        else:
            nombre, apellidos = fila[indice["nombre"]], fila[indice["apellidos"]]
        if not nombre and not apellidos:
            continue
        if not nombre or not apellidos:
            avisos.append(f"Fila {n}: falta el nombre o los apellidos.")
        email = fila[indice["email"]].lower() if "email" in indice else ""
        usuario = fila[indice["usuario_git"]].lstrip("@") if "usuario_git" in indice else ""
        alumnos.append(
            {
                "nombre": nombre,
                "apellidos": apellidos,
                "email": email or None,
                "usuario_git": usuario or None,
                "carpeta_esperada": carpeta_esperada(nombre, apellidos),
            }
        )
    vistas: dict[str, list[str]] = {}
    for a in alumnos:
        vistas.setdefault(a["carpeta_esperada"], []).append(f"{a['nombre']} {a['apellidos']}")
    for carpeta, quienes in vistas.items():
        if len(quienes) > 1:
            avisos.append(f"Carpeta «{carpeta}» repetida: {', '.join(quienes)}. Solo se podrán identificar por usuario de GitHub.")
    return alumnos, avisos


def _clave(a) -> tuple:
    if a["email"]:
        return ("email", a["email"].lower())
    return ("nombre", " ".join(palabras(a["nombre"])), " ".join(palabras(a["apellidos"])))


def aplicar_importacion(conn, curso_id: int, alumnos: list[dict]) -> dict:
    """Altas nuevas, actualiza existentes y marca como inactivos a los que ya no aparecen.
    Nunca borra alumnos ni notas."""
    existentes = conn.execute("SELECT * FROM alumno WHERE curso_id = ?", (curso_id,)).fetchall()
    por_clave = {}
    for e in existentes:
        por_clave[_clave(dict(e))] = e
        por_clave[("nombre", " ".join(palabras(e["nombre"])), " ".join(palabras(e["apellidos"])))] = e
    vistos, nuevos, actualizados = set(), 0, 0
    for a in alumnos:
        previo = por_clave.get(_clave(a)) or por_clave.get(
            ("nombre", " ".join(palabras(a["nombre"])), " ".join(palabras(a["apellidos"])))
        )
        if previo:
            conn.execute(
                "UPDATE alumno SET nombre=?, apellidos=?, email=COALESCE(?, email), "
                "usuario_git=COALESCE(?, usuario_git), activo=1 WHERE id=?",
                (a["nombre"], a["apellidos"], a["email"], a["usuario_git"], previo["id"]),
            )
            vistos.add(previo["id"])
            actualizados += 1
        else:
            cur = conn.execute(
                "INSERT INTO alumno (curso_id, nombre, apellidos, email, usuario_git, carpeta_esperada, variantes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (curso_id, a["nombre"], a["apellidos"], a["email"], a["usuario_git"], a["carpeta_esperada"], json.dumps([])),
            )
            vistos.add(cur.lastrowid)
            nuevos += 1
    bajas = [e["id"] for e in existentes if e["id"] not in vistos and e["activo"]]
    for i in bajas:
        conn.execute("UPDATE alumno SET activo = 0 WHERE id = ?", (i,))
    return {"nuevos": nuevos, "actualizados": actualizados, "bajas": len(bajas)}

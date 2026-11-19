"""Estado y nota de cada alumno en cada actividad, y exportación a CSV."""

from __future__ import annotations

import csv
import io

from . import calificacion as cal
from .db import cargar_json
from .sincronizar import actividad_dict

ETIQUETAS = {
    "no_presentado": "No presentado",
    "pendiente": "Pendiente de corregir",
    "corregida": "Corregida",
    "suspenso_estructura": "Suspenso por estructura",
}


def criterios(conn, actividad_id: int) -> list[dict]:
    filas = conn.execute("SELECT * FROM criterio WHERE actividad_id = ? ORDER BY orden", (actividad_id,)).fetchall()
    return [{**dict(f), "checks": cargar_json(f["checks"], [])} for f in filas]


def entregas_alumno(conn, actividad_id: int, alumno_id: int) -> list:
    return conn.execute(
        "SELECT * FROM entrega WHERE actividad_id = ? AND alumno_id = ? ORDER BY actualizada DESC",
        (actividad_id, alumno_id),
    ).fetchall()


def resultados(conn, entrega_id: int) -> dict[str, dict]:
    filas = conn.execute("SELECT * FROM resultado WHERE entrega_id = ?", (entrega_id,)).fetchall()
    return {f["check_id"]: dict(f) for f in filas}


def estado_alumno(conn, actividad, alumno_id: int) -> dict:
    act = actividad if isinstance(actividad, dict) else actividad_dict(actividad)
    entregas = entregas_alumno(conn, act["id"], alumno_id)
    rev = conn.execute(
        "SELECT * FROM revision WHERE actividad_id = ? AND alumno_id = ?", (act["id"], alumno_id)
    ).fetchone()
    crits = criterios(conn, act["id"])
    niveles = {
        f["criterio_id"]: f["nivel"]
        for f in conn.execute(
            "SELECT criterio_id, nivel FROM calificacion WHERE actividad_id = ? AND alumno_id = ?", (act["id"], alumno_id)
        )
    }
    if not entregas:
        return {
            "estado": "no_presentado",
            "nota": cal.dos_decimales(0),
            "entregas": [],
            "principal": None,
            "resultados": {},
            "suspenso": False,
            "niveles": niveles,
            "criterios": crits,
            "revision": rev,
        }
    principal = entregas[0]
    if rev and rev["entrega_principal"]:
        principal = next((e for e in entregas if e["id"] == rev["entrega_principal"]), principal)
    res = resultados(conn, principal["id"])
    puerta = act.get("check_puerta")
    suspenso = bool(puerta and res.get(puerta, {}).get("estado") == "fallo")
    if rev and rev["puerta_manual"] is not None:
        suspenso = bool(rev["puerta_manual"])
    nota = cal.nota_por_formula(niveles, [(c["id"], c["peso"]) for c in crits], act["factor"])
    nota = cal.aplicar_tope(nota, suspenso, act["tope_estructura"])
    if nota is None:
        estado = "pendiente"
    elif suspenso:
        estado = "suspenso_estructura"
    else:
        estado = "corregida"
    return {
        "estado": estado,
        "nota": nota,
        "entregas": entregas,
        "principal": principal,
        "resultados": res,
        "suspenso": suspenso,
        "niveles": niveles,
        "criterios": crits,
        "revision": rev,
    }


def _escribir(filas: list[list]) -> str:
    salida = io.StringIO()
    # Punto y coma y coma decimal: es lo que espera Excel en español.
    csv.writer(salida, delimiter=";", lineterminator="\r\n").writerows(filas)
    return "﻿" + salida.getvalue()


def exportar_actividad(conn, actividad_id: int) -> str:
    act = actividad_dict(conn.execute("SELECT * FROM actividad WHERE id = ?", (actividad_id,)).fetchone())
    crits = criterios(conn, actividad_id)
    alumnos = conn.execute(
        "SELECT * FROM alumno WHERE curso_id = ? AND activo = 1 ORDER BY apellidos, nombre", (act["curso_id"],)
    ).fetchall()
    filas = [["Apellidos", "Nombre", "Email", "Usuario GitHub", *[c["nombre"] for c in crits], "Nota", "Estado"]]
    for a in alumnos:
        e = estado_alumno(conn, act, a["id"])
        niveles = [e["niveles"].get(c["id"]) or "" for c in crits]
        filas.append(
            [a["apellidos"], a["nombre"], a["email"] or "", a["usuario_git"] or "", *niveles, cal.formato_nota(e["nota"]), ETIQUETAS[e["estado"]]]
        )
    return _escribir(filas)


def notas_globales(conn, curso_id: int) -> tuple[list, list[dict]]:
    actividades = [
        actividad_dict(f)
        for f in conn.execute("SELECT * FROM actividad WHERE curso_id = ? AND activa = 1 ORDER BY id", (curso_id,))
    ]
    alumnos = conn.execute(
        "SELECT * FROM alumno WHERE curso_id = ? AND activo = 1 ORDER BY apellidos, nombre", (curso_id,)
    ).fetchall()
    tabla = []
    for a in alumnos:
        notas = [estado_alumno(conn, act, a["id"])["nota"] for act in actividades]
        glob = cal.nota_global([(n, act["peso_global"]) for n, act in zip(notas, actividades)])
        tabla.append({"alumno": a, "notas": notas, "global": glob})
    return actividades, tabla


def exportar_global(conn, curso_id: int) -> str:
    actividades, tabla = notas_globales(conn, curso_id)
    filas = [["Apellidos", "Nombre", "Email", *[a["nombre"] for a in actividades], "Nota global"]]
    for t in tabla:
        a = t["alumno"]
        filas.append(
            [a["apellidos"], a["nombre"], a["email"] or "", *[cal.formato_nota(n) for n in t["notas"]], cal.formato_nota(t["global"])]
        )
    return _escribir(filas)

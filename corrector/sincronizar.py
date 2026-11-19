"""Sincronización: lee las PR del repo del profesor, las asigna a actividad y alumno y
ejecuta las comprobaciones automáticas."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone

from . import comprobaciones as cmp
from .db import ahora_iso, cargar_json, cfg_set
from .github_api import ErrorGitHub
from .nombres import coincidencia_carpeta


def actividad_dict(fila) -> dict:
    a = dict(fila)
    a["carpetas_raiz"] = cargar_json(a["carpetas_raiz"], [])
    a["comprobaciones"] = cargar_json(a["comprobaciones"], {})
    return a


def alumno_dict(fila) -> dict:
    a = dict(fila)
    a["variantes"] = cargar_json(a["variantes"], [])
    return a


def agrupar_archivos(archivos: list, raices: set[str]) -> dict:
    """{carpeta_actividad: Counter((raiz, carpeta_alumno))} para rutas raiz/alumno/actividad/…"""
    grupos: dict[str, Counter] = {}
    for f in archivos:
        partes = f["filename"].split("/")
        if len(partes) < 4:
            continue
        raiz = next((r for r in raices if r.casefold() == partes[0].casefold()), None)
        if raiz is None:
            continue
        grupos.setdefault(partes[2], Counter())[(partes[0], partes[1])] += 1
    return grupos


def identificar(alumnos: list[dict], login: str, carpeta: str | None) -> tuple[dict | None, list[str], bool]:
    """Devuelve (alumno, avisos, aprendido) donde aprendido indica que hay que guardar su usuario."""
    avisos: list[str] = []
    login_cf = (login or "").casefold()
    por_usuario = [a for a in alumnos if a.get("usuario_git") and a["usuario_git"].casefold() == login_cf]
    if len(por_usuario) == 1:
        a = por_usuario[0]
        if carpeta and coincidencia_carpeta(carpeta, a["nombre"], a["apellidos"], a["carpeta_esperada"], a["variantes"]) is None:
            avisos.append(f"El usuario {login} es de {a['nombre']} {a['apellidos']}, pero la carpeta «{carpeta}» no le corresponde.")
        return a, avisos, False
    if len(por_usuario) > 1:
        avisos.append(f"El usuario {login} está asignado a varios alumnos.")
        return None, avisos, False
    if not carpeta:
        return None, ["No se encuentra la carpeta del alumno."], False
    coincidencias = []
    for a in alumnos:
        tipo = coincidencia_carpeta(carpeta, a["nombre"], a["apellidos"], a["carpeta_esperada"], a["variantes"])
        if tipo:
            coincidencias.append((tipo, a))
    exactas = [a for t, a in coincidencias if t == "exacta"]
    elegido = None
    if len(exactas) == 1:
        elegido = exactas[0]
    elif not exactas and len(coincidencias) == 1:
        elegido = coincidencias[0][1]
        avisos.append(f"Identificado por parecido de la carpeta «{carpeta}».")
    elif len(coincidencias) > 1:
        avisos.append(f"La carpeta «{carpeta}» encaja con varios alumnos.")
    else:
        avisos.append(f"La carpeta «{carpeta}» y el usuario {login} no encajan con ningún alumno de la lista.")
    if elegido is None:
        return None, avisos, False
    if elegido.get("usuario_git"):
        avisos.append(f"La carpeta es de {elegido['nombre']} {elegido['apellidos']}, cuyo usuario registrado es {elegido['usuario_git']}, no {login}.")
        return elegido, avisos, False
    return elegido, avisos, True


def _pasada_fecha(fecha_limite: str | None, ahora: datetime) -> bool:
    if not fecha_limite:
        return False
    try:
        limite = datetime.fromisoformat(fecha_limite)
    except ValueError:
        return False
    if limite.tzinfo is None:
        limite = limite.astimezone()  # hora local del PC del profesor
    return ahora >= limite


def sincronizar_curso(conn, cliente, repo: str, rama_base: str, curso_id: int, ahora: datetime | None = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    actividades = [actividad_dict(f) for f in conn.execute("SELECT * FROM actividad WHERE curso_id = ? AND activa = 1", (curso_id,))]
    alumnos = [alumno_dict(f) for f in conn.execute("SELECT * FROM alumno WHERE curso_id = ? AND activo = 1", (curso_id,))]
    raices = {r for a in actividades for r in a["carpetas_raiz"]} or {"entregas", "submissions"}
    por_carpeta = {a["carpeta"].casefold(): a for a in actividades}

    resumen = {"prs": 0, "entregas": 0, "sin_identificar": 0, "carpetas_sin_actividad": [], "errores": []}
    desconocidas: Counter = Counter()

    prs = cliente.pulls(repo)
    resumen["prs"] = len(prs)
    for pr in prs:
        try:
            archivos = cliente.archivos_pr(repo, pr["number"])
        except ErrorGitHub as e:
            resumen["errores"].append(f"PR #{pr['number']}: {e}")
            continue
        for carpeta_act, contador in agrupar_archivos(archivos, raices).items():
            act = por_carpeta.get(carpeta_act.casefold())
            if act is None:
                desconocidas[carpeta_act] += 1
                continue
            (raiz, carpeta_alumno), _ = contador.most_common(1)[0]
            _procesar(conn, cliente, repo, rama_base, pr, archivos, act, raiz, carpeta_alumno, carpeta_act, alumnos, ahora, resumen)

    resumen["carpetas_sin_actividad"] = sorted(desconocidas)
    cfg_set(conn, f"carpetas_sin_actividad:{curso_id}", resumen["carpetas_sin_actividad"])
    cfg_set(conn, f"ultima_sincronizacion:{curso_id}", ahora_iso())
    return resumen


def _procesar(conn, cliente, repo, rama_base, pr, archivos, act, raiz, carpeta_alumno, carpeta_act, alumnos, ahora, resumen):
    login = (pr.get("user") or {}).get("login", "")
    previa = conn.execute(
        "SELECT * FROM entrega WHERE actividad_id = ? AND pr_numero = ?", (act["id"], pr["number"])
    ).fetchone()

    avisos: list[str] = []
    if previa is not None and previa["asignacion_manual"]:
        alumno = next((a for a in alumnos if a["id"] == previa["alumno_id"]), None)
    else:
        alumno, avisos, aprendido = identificar(alumnos, login, carpeta_alumno)
        if alumno and aprendido and not any((a.get("usuario_git") or "").casefold() == login.casefold() for a in alumnos):
            conn.execute("UPDATE alumno SET usuario_git = ? WHERE id = ?", (login, alumno["id"]))
            alumno["usuario_git"] = login

    head = pr.get("head") or {}
    head_sha = head.get("sha")
    sha_congelado = previa["sha_congelado"] if previa else None
    cambios = previa["cambios_tras_fecha"] if previa else 0
    if _pasada_fecha(act.get("fecha_limite"), ahora):
        if sha_congelado is None:
            sha_congelado = head_sha
        elif sha_congelado != head_sha:
            cambios = 1
    if cambios:
        avisos.append(f"La PR ha cambiado después de la fecha límite (commit congelado {sha_congelado[:7]}, actual {head_sha[:7]}).")

    estado_pr = "fusionada" if pr.get("merged_at") else pr.get("state")
    valores = {
        "alumno_id": alumno["id"] if alumno else None,
        "pr_url": pr.get("html_url"),
        "pr_titulo": pr.get("title"),
        "pr_estado": estado_pr,
        "autor": login,
        "head_repo": (head.get("repo") or {}).get("full_name"),
        "head_ref": head.get("ref"),
        "head_sha": head_sha,
        "sha_congelado": sha_congelado,
        "cambios_tras_fecha": cambios,
        "raiz": raiz,
        "carpeta_detectada": carpeta_alumno,
        "carpeta_actividad": carpeta_act,
        "creada": pr.get("created_at"),
        "actualizada": pr.get("updated_at"),
        "sincronizada": ahora_iso(),
        "avisos": json.dumps(avisos, ensure_ascii=False),
    }
    if previa is None:
        columnas = ", ".join(["actividad_id", "pr_numero", *valores])
        huecos = ", ".join("?" * (len(valores) + 2))
        cur = conn.execute(f"INSERT INTO entrega ({columnas}) VALUES ({huecos})", (act["id"], pr["number"], *valores.values()))
        entrega_id = cur.lastrowid
    else:
        asignaciones = ", ".join(f"{k} = ?" for k in valores)
        conn.execute(f"UPDATE entrega SET {asignaciones} WHERE id = ?", (*valores.values(), previa["id"]))
        entrega_id = previa["id"]

    ctx = cmp.Contexto(
        cliente=cliente,
        repo=repo,
        rama_base=rama_base,
        pr=pr,
        archivos=archivos,
        actividad=act,
        raiz=raiz,
        carpeta_alumno=carpeta_alumno,
        alumno=alumno,
        carpeta_actividad=carpeta_act,
    )
    conn.execute("DELETE FROM resultado WHERE entrega_id = ?", (entrega_id,))
    for check in act["comprobaciones"]:
        if check not in cmp.CATALOGO:
            continue
        estado, detalle = cmp.ejecutar(check, ctx)
        conn.execute(
            "INSERT INTO resultado (entrega_id, check_id, estado, detalle) VALUES (?, ?, ?, ?)",
            (entrega_id, check, estado, detalle),
        )
    resumen["entregas"] += 1
    if alumno is None:
        resumen["sin_identificar"] += 1


def actividades_en_repo(cliente, repo: str, carpeta: str, ref: str | None = None) -> list[dict]:
    """Enunciados publicados por el profesor en su repo (archivos o subcarpetas de `carpeta`)."""
    try:
        contenido = cliente.contenido(repo, carpeta.strip("/"), ref)
    except ErrorGitHub:
        return []
    if not isinstance(contenido, list):
        return []
    return [
        {"ruta": c["path"], "nombre": c["name"], "tipo": c["type"], "url": c.get("html_url")}
        for c in contenido
        if not c["name"].startswith(".")
    ]

"""Interfaz web local (solo 127.0.0.1) del corrector."""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from urllib.parse import quote

import markdown as md
from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from . import calificacion as cal
from . import comprobaciones as cmp
from . import informes, token_github
from .alumnos_import import (
    CAMPOS,
    ErrorImportacion,
    adivinar_mapeo,
    aplicar_importacion,
    construir_alumnos,
    leer_tabla,
)
from .boveda import Boveda, ContrasenaIncorrecta, FicheroNoValido
from .db import ESQUEMA, auditar, cargar_json, cfg_get, cfg_set
from .github_api import ClienteGitHub, ErrorGitHub
from .rubrica import ErrorRubrica, leer_rubrica_docx, leer_rubrica_texto
from .sincronizar import actividad_dict, actividades_en_repo, alumno_dict, sincronizar_curso

HOSTS_PERMITIDOS = {"127.0.0.1", "localhost"}
INACTIVIDAD_SEG = 30 * 60
MAX_SUBIDA = 5 * 1024 * 1024
EXT_IMAGEN = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp")
EXT_TEXTO = (".txt", ".log", ".csv")
EXT_MD = (".md", ".markdown")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https://raw.githubusercontent.com https://github.com "
    "https://user-images.githubusercontent.com https://private-user-images.githubusercontent.com "
    "https://avatars.githubusercontent.com; "
    "frame-src 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'"
)


def crear_app(ruta_datos: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=secrets.token_bytes(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        MAX_CONTENT_LENGTH=MAX_SUBIDA,
        BOVEDA=Boveda(ruta_datos or ruta_por_defecto()),
        LLAVE_SESION=None,
        ULTIMA_ACTIVIDAD=time.time(),
        CLIENTE=None,
        IMPORTACIONES={},
    )

    # -- utilidades -------------------------------------------------------
    def boveda() -> Boveda:
        return app.config["BOVEDA"]

    def conn():
        return boveda().conn

    def bloquear():
        boveda().cerrar()
        app.config["LLAVE_SESION"] = None
        app.config["CLIENTE"] = None
        app.config["IMPORTACIONES"].clear()
        session.clear()

    def cliente(nuevo: bool = False) -> ClienteGitHub:
        if nuevo or app.config["CLIENTE"] is None:
            app.config["CLIENTE"] = ClienteGitHub(token_github.leer(conn()))
        return app.config["CLIENTE"]

    def curso_actual():
        cid = cfg_get(conn(), "curso_actual")
        if cid is None:
            return None
        return conn().execute("SELECT * FROM curso WHERE id = ?", (cid,)).fetchone()

    def requiere_curso():
        c = curso_actual()
        if c is None:
            flash("Crea o selecciona primero un curso.", "aviso")
            abort(redirect(url_for("cursos")))
        return c

    def actividad_o_404(actividad_id: int):
        fila = conn().execute("SELECT * FROM actividad WHERE id = ?", (actividad_id,)).fetchone()
        if fila is None:
            abort(404)
        return actividad_dict(fila)

    def repo_config():
        return cfg_get(conn(), "repo"), cfg_get(conn(), "rama_base", "main")

    # -- seguridad ----------------------------------------------------------
    @app.before_request
    def proteger():
        host = (request.host or "").rsplit(":", 1)[0].strip("[]")
        if host not in HOSTS_PERMITIDOS:
            abort(400)
        if request.endpoint in ("static",):
            return None
        ahora = time.time()
        if boveda().abierta and ahora - app.config["ULTIMA_ACTIVIDAD"] > INACTIVIDAD_SEG:
            bloquear()
            flash("Sesión cerrada por inactividad.", "aviso")
        app.config["ULTIMA_ACTIVIDAD"] = ahora
        if request.method == "POST":
            enviado = request.form.get("_csrf", "")
            if not enviado or not secrets.compare_digest(enviado, session.get("csrf", "")):
                abort(400, "Formulario caducado. Recarga la página.")
        if request.endpoint == "desbloquear":
            return None
        autenticado = (
            boveda().abierta
            and app.config["LLAVE_SESION"] is not None
            and secrets.compare_digest(session.get("llave", ""), app.config["LLAVE_SESION"])
        )
        if not autenticado:
            return redirect(url_for("desbloquear"))
        g.curso = curso_actual()
        return None

    @app.after_request
    def cabeceras(resp: Response):
        if boveda().hay_cambios():
            boveda().guardar()
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.teardown_request
    def deshacer(exc):
        if exc is not None and boveda().abierta:
            boveda().conn.rollback()

    @app.context_processor
    def globales():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return {
            "csrf": session["csrf"],
            "curso": getattr(g, "curso", None),
            "formato_nota": cal.formato_nota,
            "ETIQUETAS": informes.ETIQUETAS,
            "CATALOGO": cmp.CATALOGO,
        }

    # -- acceso ---------------------------------------------------------------
    @app.route("/desbloquear", methods=["GET", "POST"])
    def desbloquear():
        b = boveda()
        primera_vez = not b.existe()
        if request.method == "POST":
            contrasena = request.form.get("contrasena", "")
            try:
                if primera_vez:
                    if contrasena != request.form.get("repetir", ""):
                        raise ValueError("Las contraseñas no coinciden.")
                    b.crear(contrasena, ESQUEMA)
                    auditar(b.conn, "Bóveda creada")
                elif b.abierta:
                    if not b.verificar(contrasena):
                        raise ContrasenaIncorrecta()
                else:
                    b.abrir(contrasena, ESQUEMA)
            except ContrasenaIncorrecta:
                time.sleep(1)
                flash("Contraseña incorrecta.", "error")
                return render_template("desbloquear.html", primera_vez=primera_vez)
            except (ValueError, FicheroNoValido) as e:
                flash(str(e), "error")
                return render_template("desbloquear.html", primera_vez=primera_vez)
            session.clear()
            app.config["LLAVE_SESION"] = secrets.token_urlsafe(32)
            session["llave"] = app.config["LLAVE_SESION"]
            session["csrf"] = secrets.token_urlsafe(32)
            auditar(b.conn, "Sesión iniciada")
            return redirect(url_for("panel"))
        return render_template("desbloquear.html", primera_vez=primera_vez)

    @app.post("/bloquear")
    def salir():
        auditar(conn(), "Sesión cerrada")
        bloquear()
        flash("Datos cerrados y cifrados.", "ok")
        return redirect(url_for("desbloquear"))

    # -- panel ------------------------------------------------------------------
    @app.get("/")
    def panel():
        c = curso_actual()
        if c is None:
            return redirect(url_for("cursos"))
        repo, _ = repo_config()
        acts = [actividad_dict(f) for f in conn().execute("SELECT * FROM actividad WHERE curso_id = ? ORDER BY id", (c["id"],))]
        alumnos = conn().execute("SELECT id FROM alumno WHERE curso_id = ? AND activo = 1", (c["id"],)).fetchall()
        filas = []
        for a in acts:
            cuenta = {k: 0 for k in informes.ETIQUETAS}
            for al in alumnos:
                cuenta[informes.estado_alumno(conn(), a, al["id"])["estado"]] += 1
            sin_id = conn().execute(
                "SELECT COUNT(*) FROM entrega WHERE actividad_id = ? AND alumno_id IS NULL", (a["id"],)
            ).fetchone()[0]
            filas.append({"act": a, "cuenta": cuenta, "sin_identificar": sin_id})
        return render_template(
            "panel.html",
            filas=filas,
            n_alumnos=len(alumnos),
            repo=repo,
            ultima=cfg_get(conn(), f"ultima_sincronizacion:{c['id']}"),
            desconocidas=cfg_get(conn(), f"carpetas_sin_actividad:{c['id']}", []),
        )

    @app.post("/sincronizar")
    def sincronizar():
        c = requiere_curso()
        repo, rama = repo_config()
        if not repo:
            flash("Configura primero el repositorio del profesor.", "aviso")
            return redirect(url_for("configuracion"))
        try:
            r = sincronizar_curso(conn(), cliente(nuevo=True), repo, rama, c["id"])
        except ErrorGitHub as e:
            conn().rollback()
            flash(str(e), "error")
            return redirect(request.form.get("volver") or url_for("panel"))
        auditar(conn(), f"Sincronización: {r['prs']} PR, {r['entregas']} entregas")
        flash(f"{r['prs']} PR leídas, {r['entregas']} entregas actualizadas, {r['sin_identificar']} sin identificar.", "ok")
        for e in r["errores"]:
            flash(e, "error")
        return redirect(request.form.get("volver") or url_for("panel"))

    # -- configuración ------------------------------------------------------------
    @app.route("/configuracion", methods=["GET", "POST"])
    def configuracion():
        if request.method == "POST":
            accion = request.form.get("accion")
            if accion == "repo":
                repo = request.form.get("repo", "").strip()
                repo = re.sub(r"^https?://github\.com/", "", repo).strip("/").removesuffix(".git")
                if repo and not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
                    flash("El repositorio debe tener la forma usuario/nombre.", "error")
                else:
                    cfg_set(conn(), "repo", repo or None)
                    cfg_set(conn(), "rama_base", request.form.get("rama_base", "main").strip() or "main")
                    cfg_set(conn(), "carpeta_enunciados", request.form.get("carpeta_enunciados", "").strip().strip("/"))
                    auditar(conn(), f"Repositorio configurado: {repo}")
                    flash("Repositorio guardado.", "ok")
            elif accion == "token":
                token = request.form.get("token", "").strip()
                if token:
                    donde = token_github.guardar(conn(), token)
                    app.config["CLIENTE"] = None
                    auditar(conn(), "Token de GitHub actualizado")
                    flash(
                        "Token guardado en el llavero del sistema." if donde == "llavero" else "Token guardado en los datos cifrados (no hay llavero del sistema).",
                        "ok",
                    )
            elif accion == "borrar_token":
                token_github.borrar(conn())
                app.config["CLIENTE"] = None
                auditar(conn(), "Token de GitHub borrado")
                flash("Token borrado.", "ok")
            elif accion == "probar":
                repo, _ = repo_config()
                try:
                    cl = cliente(nuevo=True)
                    info = cl.repo(repo) if repo else None
                    quien = cl.usuario()["login"] if token_github.leer(conn()) else "sin token"
                    flash(
                        f"Conexión correcta ({quien}). Repo: {info['full_name'] if info else '—'}. Consultas restantes esta hora: {cl.restantes}.",
                        "ok",
                    )
                except ErrorGitHub as e:
                    flash(f"No funciona: {e}", "error")
            elif accion == "contrasena":
                try:
                    if request.form.get("nueva") != request.form.get("repetir"):
                        raise ValueError("Las contraseñas nuevas no coinciden.")
                    boveda().cambiar_contrasena(request.form.get("actual", ""), request.form.get("nueva", ""))
                    auditar(conn(), "Contraseña maestra cambiada")
                    flash("Contraseña cambiada.", "ok")
                except ContrasenaIncorrecta:
                    flash("La contraseña actual no es correcta.", "error")
                except ValueError as e:
                    flash(str(e), "error")
            return redirect(url_for("configuracion"))
        return render_template(
            "configuracion.html",
            repo=cfg_get(conn(), "repo", ""),
            rama_base=cfg_get(conn(), "rama_base", "main"),
            carpeta_enunciados=cfg_get(conn(), "carpeta_enunciados", ""),
            token_en=token_github.ubicacion(conn()),
            ruta=boveda().ruta,
            auditoria=conn().execute("SELECT * FROM auditoria ORDER BY id DESC LIMIT 40").fetchall(),
        )

    # -- cursos -------------------------------------------------------------------
    @app.route("/cursos", methods=["GET", "POST"])
    def cursos():
        if request.method == "POST":
            asignatura = request.form.get("asignatura", "").strip()
            anio = request.form.get("anio", "").strip()
            if not asignatura or not anio:
                flash("Indica asignatura y curso académico.", "error")
            else:
                cur = conn().execute("INSERT INTO curso (asignatura, anio) VALUES (?, ?)", (asignatura, anio))
                nuevo = cur.lastrowid
                origen = request.form.get("copiar_de")
                if origen:
                    copiar_actividades(int(origen), nuevo)
                cfg_set(conn(), "curso_actual", nuevo)
                auditar(conn(), f"Curso creado: {asignatura} {anio}")
                flash("Curso creado. Ahora importa la lista de alumnos.", "ok")
                return redirect(url_for("alumnos"))
            return redirect(url_for("cursos"))
        lista = conn().execute(
            "SELECT c.*, (SELECT COUNT(*) FROM alumno a WHERE a.curso_id = c.id AND a.activo = 1) AS n_alumnos, "
            "(SELECT COUNT(*) FROM actividad x WHERE x.curso_id = c.id) AS n_actividades FROM curso c ORDER BY anio DESC, id DESC"
        ).fetchall()
        return render_template("cursos.html", cursos=lista, actual=cfg_get(conn(), "curso_actual"))

    def copiar_actividades(origen: int, destino: int):
        for a in conn().execute("SELECT * FROM actividad WHERE curso_id = ?", (origen,)).fetchall():
            cur = conn().execute(
                "INSERT INTO actividad (curso_id, nombre, carpeta, enunciado, nivel_max, factor, tope_estructura, peso_global, "
                "carpetas_raiz, comprobaciones, check_puerta, activa) SELECT ?, nombre, carpeta, enunciado, nivel_max, factor, "
                "tope_estructura, peso_global, carpetas_raiz, comprobaciones, check_puerta, activa FROM actividad WHERE id = ?",
                (destino, a["id"]),
            )
            conn().execute(
                "INSERT INTO criterio (actividad_id, orden, nombre, peso, checks) SELECT ?, orden, nombre, peso, checks "
                "FROM criterio WHERE actividad_id = ?",
                (cur.lastrowid, a["id"]),
            )

    @app.post("/cursos/<int:curso_id>/<accion>")
    def curso_accion(curso_id: int, accion: str):
        c = conn().execute("SELECT * FROM curso WHERE id = ?", (curso_id,)).fetchone()
        if c is None:
            abort(404)
        if accion == "seleccionar":
            cfg_set(conn(), "curso_actual", curso_id)
        elif accion == "archivar":
            conn().execute("UPDATE curso SET archivado = 1 - archivado WHERE id = ?", (curso_id,))
            auditar(conn(), f"Curso {c['asignatura']} {c['anio']} archivado/desarchivado")
        elif accion == "borrar":
            if request.form.get("confirmar") != c["anio"]:
                flash(f"Para borrar escribe el curso académico exacto ({c['anio']}).", "error")
            else:
                conn().execute("DELETE FROM curso WHERE id = ?", (curso_id,))
                if cfg_get(conn(), "curso_actual") == curso_id:
                    cfg_set(conn(), "curso_actual", None)
                auditar(conn(), f"Curso {c['asignatura']} {c['anio']} borrado con sus alumnos y notas")
                flash("Curso borrado con todos sus alumnos y notas.", "ok")
        else:
            abort(404)
        return redirect(url_for("cursos"))

    # -- alumnos ------------------------------------------------------------------
    @app.get("/alumnos")
    def alumnos():
        c = requiere_curso()
        lista = conn().execute("SELECT * FROM alumno WHERE curso_id = ? ORDER BY activo DESC, apellidos, nombre", (c["id"],)).fetchall()
        return render_template("alumnos.html", alumnos=[alumno_dict(a) for a in lista])

    @app.post("/alumnos/<int:alumno_id>")
    def alumno_editar(alumno_id: int):
        c = requiere_curso()
        a = conn().execute("SELECT * FROM alumno WHERE id = ? AND curso_id = ?", (alumno_id, c["id"])).fetchone()
        if a is None:
            abort(404)
        variantes = [v.strip() for v in request.form.get("variantes", "").split(",") if v.strip()]
        conn().execute(
            "UPDATE alumno SET usuario_git = ?, carpeta_esperada = ?, variantes = ?, activo = ? WHERE id = ?",
            (
                request.form.get("usuario_git", "").strip().lstrip("@") or None,
                request.form.get("carpeta_esperada", "").strip() or a["carpeta_esperada"],
                json.dumps(variantes, ensure_ascii=False),
                1 if request.form.get("activo") else 0,
                alumno_id,
            ),
        )
        flash(f"{a['nombre']} {a['apellidos']} actualizado.", "ok")
        return redirect(url_for("alumnos") + f"#al-{alumno_id}")

    @app.route("/alumnos/importar", methods=["GET", "POST"])
    def importar():
        c = requiere_curso()
        pendientes = app.config["IMPORTACIONES"]
        if request.method == "GET":
            return render_template("importar.html", etapa="subir")
        etapa = request.form.get("etapa")
        if etapa == "subir":
            f = request.files.get("fichero")
            if not f or not f.filename:
                flash("Elige un fichero.", "error")
                return redirect(url_for("importar"))
            try:
                cabecera, datos = leer_tabla(f.filename, f.read())
            except ErrorImportacion as e:
                flash(str(e), "error")
                return redirect(url_for("importar"))
            clave = secrets.token_urlsafe(16)
            pendientes.clear()
            pendientes[clave] = (cabecera, datos)
            previo = cargar_json(c["mapeo_columnas"], None) or cfg_get(conn(), "ultimo_mapeo")
            mapeo = adivinar_mapeo(cabecera, previo)
            return render_template("importar.html", etapa="mapear", clave=clave, cabecera=cabecera, datos=datos[:5], mapeo=mapeo, campos=CAMPOS, n=len(datos))
        clave = request.form.get("clave", "")
        if clave not in pendientes:
            flash("La importación ha caducado. Vuelve a subir el fichero.", "error")
            return redirect(url_for("importar"))
        cabecera, datos = pendientes[clave]
        mapeo = {campo: request.form.get(campo) for campo in CAMPOS if request.form.get(campo)}
        try:
            lista, avisos = construir_alumnos(cabecera, datos, mapeo)
        except ErrorImportacion as e:
            flash(str(e), "error")
            return render_template("importar.html", etapa="mapear", clave=clave, cabecera=cabecera, datos=datos[:5], mapeo=mapeo, campos=CAMPOS, n=len(datos))
        if etapa == "vista":
            return render_template("importar.html", etapa="vista", clave=clave, alumnos=lista, avisos=avisos, mapeo=mapeo, campos=CAMPOS)
        if etapa == "confirmar":
            r = aplicar_importacion(conn(), c["id"], lista)
            conn().execute("UPDATE curso SET mapeo_columnas = ? WHERE id = ?", (json.dumps(mapeo, ensure_ascii=False), c["id"]))
            cfg_set(conn(), "ultimo_mapeo", mapeo)
            pendientes.clear()
            auditar(conn(), f"Lista importada: {r['nuevos']} nuevos, {r['actualizados']} actualizados, {r['bajas']} bajas")
            flash(f"{r['nuevos']} alumnos nuevos, {r['actualizados']} actualizados, {r['bajas']} marcados como baja.", "ok")
            return redirect(url_for("alumnos"))
        abort(400)

    # -- actividades -----------------------------------------------------------------
    @app.get("/actividades")
    def actividades():
        c = requiere_curso()
        acts = [actividad_dict(f) for f in conn().execute("SELECT * FROM actividad WHERE curso_id = ? ORDER BY id", (c["id"],))]
        repo, rama = repo_config()
        carpeta = cfg_get(conn(), "carpeta_enunciados", "")
        candidatos, error = [], None
        if repo and request.args.get("buscar"):
            try:
                usados = {a["enunciado"] for a in acts if a["enunciado"]}
                candidatos = [x for x in actividades_en_repo(cliente(), repo, carpeta, rama) if x["ruta"] not in usados]
                if not candidatos:
                    error = f"No hay enunciados nuevos en «{carpeta or '/'}» del repositorio."
            except ErrorGitHub as e:
                error = str(e)
        return render_template(
            "actividades.html",
            actividades=acts,
            candidatos=candidatos,
            error=error,
            carpeta_enunciados=carpeta,
            desconocidas=cfg_get(conn(), f"carpetas_sin_actividad:{c['id']}", []),
        )

    @app.post("/actividades/nueva")
    def actividad_nueva():
        c = requiere_curso()
        nombre = request.form.get("nombre", "").strip()
        carpeta = request.form.get("carpeta", "").strip()
        plantilla = request.form.get("plantilla")
        comprobaciones = {"carpeta": {}, "pr_desde_fork": {}, "pr_destino": {}, "pr_titulo_descripcion": {}, "fuera_de_carpeta": {}}
        if plantilla == "aec-git":
            comprobaciones = cmp.PLANTILLA_AEC_GIT["comprobaciones"]
            carpeta = carpeta or cmp.PLANTILLA_AEC_GIT["carpeta"]
            nombre = nombre or "AEC Git"
        if not nombre or not carpeta:
            flash("Indica nombre y carpeta de entrega de la actividad.", "error")
            return redirect(url_for("actividades"))
        cur = conn().execute(
            "INSERT INTO actividad (curso_id, nombre, carpeta, enunciado, comprobaciones) VALUES (?, ?, ?, ?, ?)",
            (c["id"], nombre, carpeta, request.form.get("enunciado") or None, json.dumps(comprobaciones, ensure_ascii=False)),
        )
        auditar(conn(), f"Actividad creada: {nombre}")
        flash("Actividad creada. Importa la rúbrica y revisa las comprobaciones.", "ok")
        return redirect(url_for("actividad", actividad_id=cur.lastrowid))

    @app.route("/actividades/<int:actividad_id>", methods=["GET", "POST"])
    def actividad(actividad_id: int):
        act = actividad_o_404(actividad_id)
        if request.method == "POST":
            accion = request.form.get("accion")
            if accion == "general":
                guardar_general(act)
            elif accion == "comprobaciones":
                guardar_comprobaciones(act)
            elif accion == "criterios":
                try:
                    filas = leer_rubrica_texto(request.form.get("criterios", ""))
                    reemplazar_criterios(act["id"], [(n, p, [c for c in ch if c in cmp.CATALOGO]) for n, p, ch in filas])
                    flash("Criterios guardados.", "ok")
                except ErrorRubrica as e:
                    flash(str(e), "error")
            elif accion == "rubrica":
                f = request.files.get("fichero")
                try:
                    if not f or not f.filename.lower().endswith(".docx"):
                        raise ErrorRubrica("Sube la rúbrica en formato .docx.")
                    filas = leer_rubrica_docx(f.read())
                    disponibles = act["comprobaciones"].keys()
                    reemplazar_criterios(act["id"], [(n, p, cmp.checks_para_criterio(n, disponibles)) for n, p in filas])
                    auditar(conn(), f"Rúbrica importada en {act['nombre']}")
                    flash(f"{len(filas)} criterios importados. Revisa la asociación con las comprobaciones.", "ok")
                except ErrorRubrica as e:
                    flash(str(e), "error")
            elif accion == "borrar":
                if request.form.get("confirmar") != act["nombre"]:
                    flash("Para borrar escribe el nombre exacto de la actividad.", "error")
                else:
                    conn().execute("DELETE FROM actividad WHERE id = ?", (act["id"],))
                    auditar(conn(), f"Actividad borrada: {act['nombre']}")
                    flash("Actividad borrada con sus entregas y notas.", "ok")
                    return redirect(url_for("actividades"))
            return redirect(url_for("actividad", actividad_id=actividad_id))
        crits = informes.criterios(conn(), actividad_id)
        texto = "\n".join(f"{c['nombre']}; {str(c['peso']).rstrip('0').rstrip('.')}; {', '.join(c['checks'])}" for c in crits)
        return render_template(
            "actividad.html",
            act=act,
            criterios=crits,
            texto_criterios=texto,
            suma=cal.suma_pesos(c["peso"] for c in crits),
        )

    def guardar_general(act):
        def numero(campo, defecto):
            try:
                return float(request.form.get(campo, "").replace(",", "."))
            except ValueError:
                return defecto

        raices = [r.strip().strip("/") for r in request.form.get("carpetas_raiz", "").split(",") if r.strip()]
        fecha = request.form.get("fecha_limite", "").strip() or None
        nivel_max = int(numero("nivel_max", act["nivel_max"]))
        conn().execute(
            "UPDATE actividad SET nombre = ?, carpeta = ?, fecha_limite = ?, nivel_max = ?, factor = ?, tope_estructura = ?, "
            "peso_global = ?, carpetas_raiz = ?, check_puerta = ?, activa = ? WHERE id = ?",
            (
                request.form.get("nombre", act["nombre"]).strip() or act["nombre"],
                request.form.get("carpeta", act["carpeta"]).strip() or act["carpeta"],
                fecha,
                max(nivel_max, 2),
                numero("factor", act["factor"]),
                numero("tope_estructura", act["tope_estructura"]),
                numero("peso_global", act["peso_global"]),
                json.dumps(raices or act["carpetas_raiz"], ensure_ascii=False),
                request.form.get("check_puerta") or None,
                1 if request.form.get("activa") else 0,
                act["id"],
            ),
        )
        flash("Datos de la actividad guardados.", "ok")

    def guardar_comprobaciones(act):
        nuevas = {}
        for check, info in cmp.CATALOGO.items():
            if not request.form.get(f"usar_{check}"):
                continue
            params = {}
            for p in info["params"]:
                valor = request.form.get(f"{check}__{p}", "").strip()
                if not valor:
                    continue
                if p in ("min", "max"):
                    try:
                        params[p] = int(valor)
                    except ValueError:
                        continue
                else:
                    params[p] = [v.strip() for v in valor.split(",") if v.strip()]
            nuevas[check] = params
        conn().execute("UPDATE actividad SET comprobaciones = ? WHERE id = ?", (json.dumps(nuevas, ensure_ascii=False), act["id"]))
        flash("Comprobaciones guardadas. Se aplicarán en la próxima sincronización.", "ok")

    def reemplazar_criterios(actividad_id: int, filas):
        """Sustituye la rúbrica. Conserva las notas de los criterios que mantienen el nombre."""
        previos = {c["nombre"]: c["id"] for c in conn().execute("SELECT id, nombre FROM criterio WHERE actividad_id = ?", (actividad_id,))}
        mantener = set()
        for orden, (nombre, peso, checks) in enumerate(filas):
            if nombre in previos:
                conn().execute(
                    "UPDATE criterio SET orden = ?, peso = ?, checks = ? WHERE id = ?",
                    (orden, peso, json.dumps(checks), previos[nombre]),
                )
                mantener.add(previos[nombre])
            else:
                conn().execute(
                    "INSERT INTO criterio (actividad_id, orden, nombre, peso, checks) VALUES (?, ?, ?, ?, ?)",
                    (actividad_id, orden, nombre, peso, json.dumps(checks)),
                )
        for nombre, cid in previos.items():
            if cid not in mantener:
                conn().execute("DELETE FROM criterio WHERE id = ?", (cid,))

    # -- entregas y corrección ----------------------------------------------------------
    @app.get("/actividades/<int:actividad_id>/entregas")
    def entregas(actividad_id: int):
        act = actividad_o_404(actividad_id)
        alumnos_c = conn().execute(
            "SELECT * FROM alumno WHERE curso_id = ? AND activo = 1 ORDER BY apellidos, nombre", (act["curso_id"],)
        ).fetchall()
        filas = []
        for a in alumnos_c:
            e = informes.estado_alumno(conn(), act, a["id"])
            estados = [r["estado"] for r in e["resultados"].values()]
            filas.append({"alumno": a, "e": e, "ok": estados.count("ok"), "aviso": estados.count("aviso"), "fallo": estados.count("fallo")})
        sin_id = conn().execute(
            "SELECT * FROM entrega WHERE actividad_id = ? AND alumno_id IS NULL ORDER BY pr_numero", (actividad_id,)
        ).fetchall()
        return render_template(
            "entregas.html",
            act=act,
            filas=filas,
            sin_identificar=[{**dict(s), "avisos": cargar_json(s["avisos"], [])} for s in sin_id],
            alumnos=alumnos_c,
        )

    @app.post("/entregas/<int:entrega_id>/asignar")
    def asignar(entrega_id: int):
        e = conn().execute("SELECT * FROM entrega WHERE id = ?", (entrega_id,)).fetchone()
        if e is None:
            abort(404)
        alumno_id = request.form.get("alumno_id", type=int)
        if alumno_id:
            conn().execute("UPDATE entrega SET alumno_id = ?, asignacion_manual = 1 WHERE id = ?", (alumno_id, entrega_id))
            al = conn().execute("SELECT * FROM alumno WHERE id = ?", (alumno_id,)).fetchone()
            if al and not al["usuario_git"] and e["autor"]:
                conn().execute("UPDATE alumno SET usuario_git = ? WHERE id = ?", (e["autor"], alumno_id))
            auditar(conn(), f"PR #{e['pr_numero']} asignada manualmente")
            flash("Entrega asignada. Sincroniza para recalcular las comprobaciones con este alumno.", "ok")
        else:
            conn().execute("UPDATE entrega SET alumno_id = NULL, asignacion_manual = 0 WHERE id = ?", (entrega_id,))
        return redirect(request.form.get("volver") or url_for("entregas", actividad_id=e["actividad_id"]))

    @app.route("/actividades/<int:actividad_id>/alumnos/<int:alumno_id>", methods=["GET", "POST"])
    def revisar(actividad_id: int, alumno_id: int):
        act = actividad_o_404(actividad_id)
        al = conn().execute("SELECT * FROM alumno WHERE id = ? AND curso_id = ?", (alumno_id, act["curso_id"])).fetchone()
        if al is None:
            abort(404)
        if request.method == "POST":
            guardar_revision(act, al)
            siguiente = request.form.get("siguiente")
            if siguiente:
                return redirect(url_for("revisar", actividad_id=actividad_id, alumno_id=int(siguiente)))
            return redirect(url_for("revisar", actividad_id=actividad_id, alumno_id=alumno_id))
        e = informes.estado_alumno(conn(), act, alumno_id)
        sugeridos = {
            c["id"]: cal.nivel_sugerido([e["resultados"][k]["estado"] for k in c["checks"] if k in e["resultados"]], act["nivel_max"])
            for c in e["criterios"]
        }
        comentarios = {
            f["criterio_id"]: f["comentario"]
            for f in conn().execute(
                "SELECT criterio_id, comentario FROM calificacion WHERE actividad_id = ? AND alumno_id = ?", (actividad_id, alumno_id)
            )
        }
        orden = [
            r["id"]
            for r in conn().execute("SELECT id FROM alumno WHERE curso_id = ? AND activo = 1 ORDER BY apellidos, nombre", (act["curso_id"],))
        ]
        pos = orden.index(alumno_id) if alumno_id in orden else -1
        anterior = orden[pos - 1] if pos > 0 else None
        siguiente = orden[pos + 1] if 0 <= pos < len(orden) - 1 else None
        archivos, vista, error_archivos = [], None, None
        p = e["principal"]
        if p is not None and p["head_repo"]:
            sha = p["sha_congelado"] or p["head_sha"]
            prefijo = f"{p['raiz']}/{p['carpeta_detectada']}/{p['carpeta_actividad']}/"
            try:
                archivos = [
                    {"ruta": x["path"], "nombre": x["path"][len(prefijo):], "url": f"https://github.com/{p['head_repo']}/blob/{sha}/{quote(x['path'])}"}
                    for x in cliente().arbol(p["head_repo"], sha)
                    if x["type"] == "blob" and x["path"].startswith(prefijo)
                ]
            except ErrorGitHub as ex:
                error_archivos = f"No se pudieron leer los archivos: {ex}"
            ver = request.args.get("ver")
            if ver is None and archivos:
                preferido = next((a for a in archivos if a["ruta"].lower().endswith(EXT_MD + EXT_TEXTO)), None)
                ver = preferido["ruta"] if preferido else None
            if ver and any(a["ruta"] == ver for a in archivos):
                vista = vista_archivo(p["head_repo"], sha, ver)
        return render_template(
            "revision.html",
            act=act,
            al=al,
            e=e,
            sugeridos=sugeridos,
            comentarios=comentarios,
            anterior=anterior,
            siguiente=siguiente,
            archivos=archivos,
            vista=vista,
            error_archivos=error_archivos,
            avisos_entrega=cargar_json(p["avisos"], []) if p is not None else [],
        )

    def vista_archivo(head_repo: str, sha: str, ruta: str) -> dict:
        crudo = f"https://raw.githubusercontent.com/{head_repo}/{sha}/"
        url = crudo + quote(ruta)
        baja = ruta.lower()
        if baja.endswith(EXT_IMAGEN):
            return {"tipo": "imagen", "ruta": ruta, "url": url}
        if baja.endswith(EXT_MD + EXT_TEXTO):
            try:
                texto = cliente().texto_archivo(head_repo, ruta, sha)
            except ErrorGitHub as ex:
                return {"tipo": "error", "ruta": ruta, "mensaje": str(ex)}
            if baja.endswith(EXT_TEXTO):
                return {"tipo": "texto", "ruta": ruta, "texto": texto}
            base = crudo + quote(ruta.rsplit("/", 1)[0] + "/")
            return {"tipo": "markdown", "ruta": ruta, "html": documento_markdown(texto, base)}
        return {"tipo": "otro", "ruta": ruta, "url": f"https://github.com/{head_repo}/blob/{sha}/{quote(ruta)}"}

    # -- notas y exportación ---------------------------------------------------------------
    @app.get("/notas")
    def notas():
        c = requiere_curso()
        acts, tabla = informes.notas_globales(conn(), c["id"])
        return render_template("notas.html", actividades=acts, tabla=tabla)

    @app.get("/exportar/actividad/<int:actividad_id>.csv")
    def exportar_actividad(actividad_id: int):
        act = actividad_o_404(actividad_id)
        auditar(conn(), f"Notas exportadas: {act['nombre']}")
        return descarga(informes.exportar_actividad(conn(), actividad_id), f"notas-{act['carpeta']}.csv")

    @app.get("/exportar/global.csv")
    def exportar_global():
        c = requiere_curso()
        auditar(conn(), "Notas globales exportadas")
        return descarga(informes.exportar_global(conn(), c["id"]), f"notas-globales-{c['anio']}.csv")

    def descarga(texto: str, nombre: str) -> Response:
        nombre = re.sub(r"[^\w.-]", "_", nombre)
        return Response(
            texto.encode("utf-8"),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
        )

    def guardar_revision(act, al):
        for c in informes.criterios(conn(), act["id"]):
            nivel = request.form.get(f"nivel_{c['id']}", type=int)
            if nivel is not None and not 1 <= nivel <= act["nivel_max"]:
                nivel = None
            comentario = request.form.get(f"comentario_{c['id']}", "").strip() or None
            conn().execute(
                "INSERT INTO calificacion (actividad_id, alumno_id, criterio_id, nivel, comentario) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(actividad_id, alumno_id, criterio_id) DO UPDATE SET nivel = excluded.nivel, comentario = excluded.comentario",
                (act["id"], al["id"], c["id"], nivel, comentario),
            )
        puerta = request.form.get("puerta_manual", "")
        puerta_val = {"": None, "1": 1, "0": 0}.get(puerta)
        principal = request.form.get("entrega_principal", type=int)
        conn().execute(
            "INSERT INTO revision (actividad_id, alumno_id, entrega_principal, puerta_manual, comentario) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(actividad_id, alumno_id) DO UPDATE SET entrega_principal = excluded.entrega_principal, "
            "puerta_manual = excluded.puerta_manual, comentario = excluded.comentario",
            (act["id"], al["id"], principal, puerta_val, request.form.get("comentario", "").strip() or None),
        )
        auditar(conn(), f"Corrección guardada: {act['nombre']} / alumno {al['id']}")
        flash("Corrección guardada.", "ok")

    @app.errorhandler(413)
    def demasiado_grande(_):
        flash("El fichero es demasiado grande (máximo 5 MB).", "error")
        return redirect(request.referrer or url_for("panel"))

    return app


def documento_markdown(texto: str, base_url: str) -> str:
    """HTML del informe del alumno. Se muestra en un iframe aislado (sandbox sin scripts),
    así que aunque el alumno meta HTML o JavaScript no puede acceder a la app."""
    cuerpo = md.markdown(texto, extensions=["fenced_code", "tables"])

    def absoluta(m):
        attr, url = m.group(1), m.group(2)
        if re.match(r"^(https?:|data:|#|mailto:)", url, re.I) or url.startswith("/"):
            return m.group(0)
        return f'{attr}="{base_url}{url}"'

    cuerpo = re.sub(r'(src|href)="([^"]*)"', absoluta, cuerpo)
    estilo = (
        "body{font:15px/1.6 system-ui,sans-serif;margin:16px;color:#17202b;background:#fff}"
        "img{max-width:100%;height:auto;border:1px solid #d8dde5;margin:6px 0}"
        "pre{background:#f1f4f8;padding:10px;overflow:auto}code{background:#f1f4f8}"
        "table{border-collapse:collapse}td,th{border:1px solid #d8dde5;padding:4px 8px}"
    )
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{estilo}</style></head><body>{cuerpo}</body></html>"


def ruta_por_defecto() -> str:
    if os.environ.get("CORRECTOR_DATOS"):
        return os.environ["CORRECTOR_DATOS"]
    return os.path.join(os.path.expanduser("~"), ".corrector-aec", "datos.enc")

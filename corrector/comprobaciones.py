"""Catálogo de comprobaciones automáticas.

Cada actividad elige qué comprobaciones usa y con qué parámetros. Cada comprobación
devuelve (estado, detalle) con estado en: 'ok', 'aviso', 'fallo' o 'na' (no aplica).
'aviso' significa que el profesor debe mirarlo: la app no decide sola.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

from .github_api import ErrorGitHub, NoEncontrado
from .nombres import coincidencia_carpeta, comparar_mensaje, formato_valido


@dataclass
class Contexto:
    cliente: object
    repo: str  # repo del profesor, owner/nombre
    rama_base: str
    pr: dict
    archivos: list
    actividad: dict  # carpeta, carpetas_raiz, comprobaciones
    raiz: str | None
    carpeta_alumno: str | None
    alumno: dict | None = None
    carpeta_actividad: str | None = None  # nombre real en la PR (puede diferir en mayúsculas)
    _detalles: dict = field(default_factory=dict)

    @property
    def numero(self) -> int:
        return self.pr["number"]

    @property
    def head_repo(self) -> str | None:
        repo = (self.pr.get("head") or {}).get("repo")
        return repo["full_name"] if repo else None

    @property
    def rama_principal_fork(self) -> str:
        repo = (self.pr.get("head") or {}).get("repo") or {}
        return repo.get("default_branch") or "main"

    @property
    def prefijo(self) -> str | None:
        if not (self.raiz and self.carpeta_alumno):
            return None
        return f"{self.raiz}/{self.carpeta_alumno}/{self.carpeta_actividad or self.actividad['carpeta']}/"

    @cached_property
    def commits(self) -> list:
        return self.cliente.commits_pr(self.repo, self.numero)

    def detalle_commit(self, sha: str) -> dict:
        if sha not in self._detalles:
            fuente = self.head_repo or self.repo
            try:
                self._detalles[sha] = self.cliente.commit(fuente, sha)
            except NoEncontrado:
                self._detalles[sha] = self.cliente.commit(self.repo, sha)
        return self._detalles[sha]

    def toca_actividad(self, sha: str) -> bool:
        pref = self.prefijo
        if pref is None:
            return True
        return any(f["filename"].startswith(pref) for f in self.detalle_commit(sha).get("files", []))

    def param(self, check: str, nombre: str, defecto=None):
        return (self.actividad.get("comprobaciones", {}).get(check) or {}).get(nombre, defecto)


def _lista(valor) -> list[str]:
    if isinstance(valor, str):
        return [v.strip() for v in valor.split(",") if v.strip()]
    return list(valor or [])


# --- comprobaciones ------------------------------------------------------------

def pr_desde_fork(ctx: Contexto):
    repo = (ctx.pr.get("head") or {}).get("repo")
    if not repo:
        return "fallo", "El repositorio de origen de la PR ya no existe (fork borrado)."
    if not repo.get("fork"):
        return "fallo", f"La PR sale de {repo['full_name']}, que no es un fork."
    info = ctx.cliente.repo(repo["full_name"])
    padre = (info.get("parent") or {}).get("full_name", "")
    if padre.lower() == ctx.repo.lower():
        return "ok", f"Fork {repo['full_name']} del repositorio del profesor."
    return "aviso", f"{repo['full_name']} es un fork de {padre or 'otro repositorio'}, no de {ctx.repo}."


def carpeta(ctx: Contexto):
    act = ctx.actividad
    if not ctx.raiz or not ctx.carpeta_alumno:
        return "fallo", f"La PR no tiene archivos en <raíz>/nombre.apellido/{act['carpeta']}/."
    avisos = []
    raices = act.get("carpetas_raiz", [])
    if ctx.raiz not in raices:
        return "fallo", f"Carpeta raíz «{ctx.raiz}»; se esperaba una de: {', '.join(raices)}."
    real = ctx.carpeta_actividad or act["carpeta"]
    if real != act["carpeta"]:
        avisos.append(f"La carpeta de la actividad se llama «{real}» en lugar de «{act['carpeta']}».")
    if not formato_valido(ctx.carpeta_alumno):
        avisos.append(f"«{ctx.carpeta_alumno}» no sigue el formato nombre.apellido (minúsculas, sin tildes).")
    al = ctx.alumno
    if al is None:
        avisos.append("Alumno sin identificar: no se puede comprobar el nombre de la carpeta.")
    else:
        tipo = coincidencia_carpeta(ctx.carpeta_alumno, al["nombre"], al["apellidos"], al["carpeta_esperada"], al.get("variantes", []))
        if tipo is None:
            return "fallo", f"«{ctx.carpeta_alumno}» no corresponde a {al['nombre']} {al['apellidos']} (esperada «{al['carpeta_esperada']}»)."
        if tipo == "aproximada":
            avisos.append(f"«{ctx.carpeta_alumno}» se parece a la esperada «{al['carpeta_esperada']}» pero no es igual.")
    if avisos:
        return "aviso", " ".join(avisos)
    return "ok", f"{ctx.prefijo}"


def archivo_inicial(ctx: Contexto):
    mensajes = _lista(ctx.param("archivo_inicial", "mensajes", []))
    candidatos = []
    for c in ctx.commits:
        tipo = comparar_mensaje(c["commit"]["message"], mensajes)
        if tipo:
            candidatos.append((c, tipo))
    if not candidatos:
        return "fallo", f"Ningún commit con el mensaje {' / '.join(mensajes)}."
    c, tipo = candidatos[0]
    avisos = []
    if tipo == "mayusculas":
        avisos.append(f"El mensaje «{c['commit']['message'].splitlines()[0]}» difiere en mayúsculas o tildes.")
    det = ctx.detalle_commit(c["sha"])
    pref = ctx.prefijo or ""
    nuevos = [f for f in det.get("files", []) if f.get("status") == "added" and f["filename"].startswith(pref)]
    if not nuevos:
        avisos.append("El commit no añade ningún archivo en la carpeta de la actividad.")
    elif any(f.get("additions", 0) > 0 for f in nuevos):
        avisos.append("El archivo creado no estaba vacío.")
    if ctx.head_repo:
        try:
            cmp = ctx.cliente.comparar(ctx.head_repo, c["sha"], ctx.rama_principal_fork)
            if cmp.get("behind_by", 0) > 0:
                avisos.append(f"El commit no está en la rama {ctx.rama_principal_fork} del fork.")
        except ErrorGitHub:
            avisos.append("No se pudo comprobar si el commit está en la rama principal del fork.")
    if avisos:
        return "aviso", " ".join(avisos)
    return "ok", f"{c['sha'][:7]} «{c['commit']['message'].splitlines()[0]}» añade {nuevos[0]['filename'].rsplit('/', 1)[-1]}."


def _ramas_existentes(ctx: Contexto, ramas: list[str]) -> list[str]:
    if not ctx.head_repo:
        return []
    return [r for r in ramas if ctx.cliente.rama(ctx.head_repo, r) is not None]


def rama_nombre(ctx: Contexto):
    ramas = _lista(ctx.param("rama_nombre", "ramas", []))
    ref = (ctx.pr.get("head") or {}).get("ref", "")
    if ref in ramas:
        return "ok", f"La PR sale de la rama «{ref}»."
    existentes = _ramas_existentes(ctx, ramas)
    if existentes:
        return "aviso", f"La PR sale de «{ref}», pero la rama «{existentes[0]}» existe en el fork."
    parecidas = [r for r in ramas if r.casefold() == ref.casefold()]
    if parecidas:
        return "aviso", f"La rama «{ref}» difiere en mayúsculas de «{parecidas[0]}»."
    return "fallo", f"La PR sale de «{ref}» y no existe ninguna rama {' / '.join(ramas)} en el fork."


def num_commits(ctx: Contexto):
    minimo = int(ctx.param("num_commits", "min", 2))
    maximo = int(ctx.param("num_commits", "max", 5))
    iniciales = _lista(ctx.param("archivo_inicial", "mensajes", []))
    contados = []
    for c in ctx.commits:
        if len(c.get("parents", [])) > 1:
            continue
        if iniciales and comparar_mensaje(c["commit"]["message"], iniciales):
            continue
        if not ctx.toca_actividad(c["sha"]):
            continue
        contados.append(c["commit"]["message"].splitlines()[0] if c["commit"]["message"] else "(sin mensaje)")
    n = len(contados)
    lista = "; ".join(f"«{m}»" for m in contados) or "ninguno"
    estado = "ok" if minimo <= n <= maximo else "fallo"
    return estado, f"{n} commits de trabajo (se piden {minimo}-{maximo}): {lista}"


def rama_integrada(ctx: Contexto):
    ramas = _lista(ctx.param("rama_integrada", "ramas", None) or ctx.param("rama_nombre", "ramas", []))
    if not ctx.head_repo:
        return "fallo", "El fork ya no existe."
    principal = ctx.rama_principal_fork
    existentes = _ramas_existentes(ctx, ramas)
    if not existentes:
        ref = (ctx.pr.get("head") or {}).get("ref", "")
        if ref == principal:
            return "aviso", f"No existe la rama de trabajo en el fork (¿borrada tras el merge?); la PR sale de {principal}."
        return "fallo", f"No existe ninguna rama {' / '.join(ramas)} en el fork."
    rama = existentes[0]
    cmp = ctx.cliente.comparar(ctx.head_repo, rama, principal)
    if cmp.get("behind_by", 1) == 0:
        tipo = "con commit de merge" if cmp.get("ahead_by", 0) > 0 else "fast-forward"
        return "ok", f"{principal} contiene todos los commits de {rama} ({tipo})."
    return "fallo", f"{principal} no contiene {cmp.get('behind_by')} commits de {rama}: no se hizo el merge o no se subió."


def pr_destino(ctx: Contexto):
    base = ctx.pr.get("base") or {}
    repo = (base.get("repo") or {}).get("full_name", "")
    if repo.lower() != ctx.repo.lower():
        return "fallo", f"La PR apunta a {repo}."
    if base.get("ref") != ctx.rama_base:
        return "aviso", f"La PR apunta a la rama «{base.get('ref')}» en lugar de «{ctx.rama_base}»."
    return "ok", f"Hacia {repo}:{ctx.rama_base}."


def pr_titulo_descripcion(ctx: Contexto):
    titulo = (ctx.pr.get("title") or "").strip()
    cuerpo = (ctx.pr.get("body") or "").strip()
    if not titulo:
        return "fallo", "La PR no tiene título."
    if not cuerpo:
        return "aviso", f"Título «{titulo}», sin descripción."
    return "ok", f"Título «{titulo}» y descripción de {len(cuerpo)} caracteres."


def commits_web(ctx: Contexto):
    web = [c for c in ctx.commits if ((c.get("committer") or {}).get("login") == "web-flow")]
    if web:
        return "aviso", f"{len(web)} de {len(ctx.commits)} commits se hicieron desde la web de GitHub, no desde la terminal."
    return "ok", "Todos los commits se hicieron fuera de la web de GitHub."


def fuera_de_carpeta(ctx: Contexto):
    if not ctx.raiz or not ctx.carpeta_alumno:
        return "na", ""
    propia = f"{ctx.raiz}/{ctx.carpeta_alumno}/"
    ajenos = [f["filename"] for f in ctx.archivos if not f["filename"].startswith(propia)]
    if ajenos:
        muestra = ", ".join(ajenos[:5]) + ("…" if len(ajenos) > 5 else "")
        return "aviso", f"La PR modifica {len(ajenos)} archivos fuera de su carpeta: {muestra}"
    return "ok", "Solo modifica su propia carpeta."


CATALOGO: dict[str, dict] = {
    "pr_desde_fork": {"titulo": "La PR viene de un fork del repo del profesor", "fn": pr_desde_fork, "params": {}},
    "carpeta": {"titulo": "Estructura <raíz>/nombre.apellido/<actividad>", "fn": carpeta, "params": {}},
    "archivo_inicial": {
        "titulo": "Commit inicial con mensaje exacto y archivo vacío",
        "fn": archivo_inicial,
        "params": {"mensajes": "Mensajes aceptados (separados por comas)"},
    },
    "rama_nombre": {
        "titulo": "Rama de trabajo con el nombre exacto",
        "fn": rama_nombre,
        "params": {"ramas": "Nombres aceptados (separados por comas)"},
    },
    "num_commits": {
        "titulo": "Número de commits de trabajo en rango",
        "fn": num_commits,
        "params": {"min": "Mínimo", "max": "Máximo"},
    },
    "rama_integrada": {
        "titulo": "La rama está integrada (merge) en la principal del fork",
        "fn": rama_integrada,
        "params": {"ramas": "Ramas (vacío = las de «rama de trabajo»)"},
    },
    "pr_destino": {"titulo": "La PR apunta al repo y rama del profesor", "fn": pr_destino, "params": {}},
    "pr_titulo_descripcion": {"titulo": "La PR tiene título y descripción", "fn": pr_titulo_descripcion, "params": {}},
    "commits_web": {"titulo": "Commits hechos desde la terminal (no desde la web)", "fn": commits_web, "params": {}},
    "fuera_de_carpeta": {"titulo": "La PR no toca carpetas ajenas", "fn": fuera_de_carpeta, "params": {}},
}


def ejecutar(nombre: str, ctx: Contexto) -> tuple[str, str]:
    try:
        return CATALOGO[nombre]["fn"](ctx)
    except ErrorGitHub as e:
        return "aviso", f"No se pudo comprobar: {e}"


# Configuración de partida para la AEC de Git (español e inglés aceptados).
PLANTILLA_AEC_GIT = {
    "carpeta": "AEC-GIT",
    "comprobaciones": {
        "pr_desde_fork": {},
        "carpeta": {},
        "archivo_inicial": {"mensajes": ["docs: nuevo archivo", "docs: new file"]},
        "rama_nombre": {"ramas": ["docs/modificaciones", "docs/modifications"]},
        "num_commits": {"min": 2, "max": 5},
        "rama_integrada": {},
        "pr_destino": {},
        "pr_titulo_descripcion": {},
        "commits_web": {},
        "fuera_de_carpeta": {},
    },
}

# Palabras clave para asociar criterios de una rúbrica a comprobaciones (el primero que encaja gana).
ASOCIACION_CRITERIOS = [
    ("fork", ["pr_desde_fork"]),
    ("estructura", ["carpeta"]),
    ("primer commit", ["archivo_inicial"]),
    ("rama", ["rama_nombre"]),
    ("commit", ["num_commits"]),
    ("merge", ["rama_integrada"]),
    ("pull", ["pr_destino", "pr_titulo_descripcion"]),
    ("autonom", ["commits_web"]),
    ("trazab", ["commits_web"]),
]


def checks_para_criterio(nombre: str, disponibles) -> list[str]:
    n = nombre.lower()
    for clave, checks in ASOCIACION_CRITERIOS:
        if clave in n:
            return [c for c in checks if c in disponibles]
    return []

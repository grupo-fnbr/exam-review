"""GitHub simulado para las pruebas: un repo del profesor y varias PR de alumnos."""

from corrector.github_api import NoEncontrado

REPO = "profe/igps"


def _pr(numero, login, ref, titulo="Entrega AEC-GIT", cuerpo="Mi entrega", fork=True, base_ref="main"):
    return {
        "number": numero,
        "html_url": f"https://github.com/{REPO}/pull/{numero}",
        "title": titulo,
        "body": cuerpo,
        "state": "open",
        "merged_at": None,
        "user": {"login": login},
        "created_at": "2026-11-01T10:00:00Z",
        "updated_at": "2026-11-02T10:00:00Z",
        "head": {
            "ref": ref,
            "sha": f"sha-{numero}-head",
            "repo": {"full_name": f"{login}/igps", "fork": fork, "default_branch": "main"},
        },
        "base": {"ref": base_ref, "repo": {"full_name": REPO}},
    }


def _commit(sha, mensaje, archivos, web=False, padres=1):
    return {
        "sha": sha,
        "commit": {"message": mensaje},
        "committer": {"login": "web-flow" if web else None},
        "parents": [{"sha": "p"}] * padres,
        "_files": archivos,
    }


class GitHubFalso:
    def __init__(self):
        self.restantes = 5000
        J = "entregas/juan.perez/AEC-GIT/"
        M = "entregas/Maria.Nunez/AEC-GIT/"
        self.prs = [
            _pr(1, "jperez", "docs/modificaciones"),
            _pr(2, "mnunez", "main", cuerpo=""),
            _pr(3, "desconocido", "docs/modificaciones"),
            _pr(4, "jperez", "main", titulo="AEC 2"),
        ]
        self.archivos = {
            1: [{"filename": J + "README.md"}, {"filename": J + "capturas/paso1.png"}],
            2: [{"filename": M + "informe.txt"}, {"filename": "README.md"}],
            3: [{"filename": "entregas/pepe.grillo/AEC-GIT/README.txt"}],
            4: [{"filename": "entregas/juan.perez/AEC-2/plan.md"}],
        }
        self.commits = {
            1: [
                _commit("c1", "docs: nuevo archivo", [{"filename": J + "README.md", "status": "added", "additions": 0}]),
                _commit("c2", "Añade capturas de los pasos 1 a 3", [{"filename": J + "capturas/paso1.png", "status": "added", "additions": 0}]),
                _commit("c3", "Describe el proceso", [{"filename": J + "README.md", "status": "modified", "additions": 20}]),
                _commit("c4", "Conclusiones", [{"filename": J + "README.md", "status": "modified", "additions": 5}]),
            ],
            2: [
                _commit("m1", '"Docs: nuevo archivo"', [{"filename": M + "informe.txt", "status": "added", "additions": 3}], web=True),
                _commit("m2", "cambios", [{"filename": M + "informe.txt", "status": "modified", "additions": 3}], web=True),
            ],
            3: [_commit("d1", "docs: nuevo archivo", [{"filename": "entregas/pepe.grillo/AEC-GIT/README.txt", "status": "added", "additions": 0}])],
            4: [_commit("e1", "plan", [{"filename": "entregas/juan.perez/AEC-2/plan.md", "status": "added", "additions": 1}])],
        }
        self.ramas = {"jperez/igps": {"main", "docs/modificaciones"}, "mnunez/igps": {"main"}, "desconocido/igps": {"main", "docs/modificaciones"}}
        self.textos = {(J + "README.md"): "# Informe\n\n![paso 1](capturas/paso1.png)\n\n<script>alert(1)</script>"}

    def usuario(self):
        return {"login": "profe"}

    def repo(self, completo):
        return {"full_name": completo, "parent": {"full_name": REPO}}

    def pulls(self, completo):
        return self.prs

    def archivos_pr(self, completo, numero):
        return self.archivos[numero]

    def commits_pr(self, completo, numero):
        return self.commits[numero]

    def commit(self, completo, sha):
        for lista in self.commits.values():
            for c in lista:
                if c["sha"] == sha:
                    return {"sha": sha, "files": c["_files"]}
        raise NoEncontrado(sha)

    def rama(self, completo, nombre):
        return {"name": nombre} if nombre in self.ramas.get(completo, set()) else None

    def comparar(self, completo, base, cabeza):
        return {"behind_by": 0, "ahead_by": 0, "status": "identical"}

    def contenido(self, completo, ruta, ref=None):
        if ruta == "actividades":
            return [
                {"path": "actividades/git-aec.md", "name": "git-aec.md", "type": "file", "html_url": "u1"},
                {"path": "actividades/scrum.md", "name": "scrum.md", "type": "file", "html_url": "u2"},
            ]
        raise NoEncontrado(ruta)

    def texto_archivo(self, completo, ruta, ref):
        return self.textos[ruta]

    def arbol(self, completo, sha):
        if completo == "jperez/igps":
            return [{"path": f["filename"], "type": "blob"} for f in self.archivos[1]]
        return []

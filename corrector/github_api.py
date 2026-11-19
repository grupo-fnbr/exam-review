"""Cliente mínimo de solo lectura para la API REST de GitHub."""

from __future__ import annotations

import base64
from urllib.parse import quote

import requests

API = "https://api.github.com"


class ErrorGitHub(Exception):
    pass


class NoEncontrado(ErrorGitHub):
    pass


class ClienteGitHub:
    def __init__(self, token: str | None = None, sesion: requests.Session | None = None, timeout: int = 20):
        self.sesion = sesion or requests.Session()
        self.sesion.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "corrector-aec",
            }
        )
        if token:
            self.sesion.headers["Authorization"] = f"Bearer {token}"
        self.timeout = timeout
        self._cache: dict = {}
        self.restantes: int | None = None

    # -- bajo nivel ---------------------------------------------------------
    def _respuesta(self, url: str, params=None):
        try:
            r = self.sesion.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise ErrorGitHub(f"No se pudo conectar con GitHub: {e.__class__.__name__}") from None
        if "X-RateLimit-Remaining" in r.headers:
            try:
                self.restantes = int(r.headers["X-RateLimit-Remaining"])
            except ValueError:
                pass
        if r.status_code == 404:
            raise NoEncontrado(url)
        if r.status_code == 401:
            raise ErrorGitHub("GitHub rechaza el token (401). Revisa que no haya caducado.")
        if r.status_code == 403 and self.restantes == 0:
            raise ErrorGitHub("Se ha agotado el límite de consultas de GitHub. Espera una hora o configura un token.")
        if r.status_code >= 400:
            raise ErrorGitHub(f"GitHub respondió {r.status_code} en {url}")
        return r

    def get(self, ruta: str, params=None):
        clave = (ruta, tuple(sorted((params or {}).items())))
        if clave not in self._cache:
            self._cache[clave] = self._respuesta(API + ruta, params).json()
        return self._cache[clave]

    def paginado(self, ruta: str, params=None) -> list:
        clave = ("pag", ruta, tuple(sorted((params or {}).items())))
        if clave in self._cache:
            return self._cache[clave]
        p = dict(params or {})
        p.setdefault("per_page", 100)
        url, resultado = API + ruta, []
        while url:
            r = self._respuesta(url, p)
            resultado.extend(r.json())
            url = r.links.get("next", {}).get("url")
            p = None  # la URL "next" ya lleva los parámetros
        self._cache[clave] = resultado
        return resultado

    # -- alto nivel ---------------------------------------------------------
    def usuario(self):
        return self.get("/user")

    def repo(self, completo: str):
        return self.get(f"/repos/{completo}")

    def pulls(self, completo: str) -> list:
        return self.paginado(f"/repos/{completo}/pulls", {"state": "all", "sort": "created", "direction": "asc"})

    def archivos_pr(self, completo: str, numero: int) -> list:
        return self.paginado(f"/repos/{completo}/pulls/{numero}/files")

    def commits_pr(self, completo: str, numero: int) -> list:
        return self.paginado(f"/repos/{completo}/pulls/{numero}/commits")

    def commit(self, completo: str, sha: str):
        return self.get(f"/repos/{completo}/commits/{sha}")

    def rama(self, completo: str, nombre: str):
        try:
            return self.get(f"/repos/{completo}/branches/{quote(nombre, safe='')}")
        except NoEncontrado:
            return None

    def comparar(self, completo: str, base: str, cabeza: str):
        return self.get(f"/repos/{completo}/compare/{quote(base, safe='')}...{quote(cabeza, safe='')}")

    def contenido(self, completo: str, ruta: str, ref: str | None = None):
        params = {"ref": ref} if ref else None
        return self.get(f"/repos/{completo}/contents/{quote(ruta)}", params)

    def texto_archivo(self, completo: str, ruta: str, ref: str) -> str:
        datos = self.contenido(completo, ruta, ref)
        if isinstance(datos, list) or datos.get("encoding") != "base64":
            raise ErrorGitHub("No es un archivo de texto descargable.")
        return base64.b64decode(datos["content"]).decode("utf-8", errors="replace")

    def arbol(self, completo: str, sha: str) -> list:
        return self.get(f"/repos/{completo}/git/trees/{sha}", {"recursive": "1"}).get("tree", [])

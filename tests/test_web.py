import io
import re

import pytest

from corrector import web
from github_falso import GitHubFalso
from utiles import CSV_CAMPUS, rubrica_docx


@pytest.fixture
def cliente_web(tmp_path, monkeypatch):
    falso = GitHubFalso()
    monkeypatch.setattr(web, "ClienteGitHub", lambda token=None: falso)
    app = web.crear_app(str(tmp_path / "datos.enc"))
    app.testing = True
    return app.test_client()


def csrf(cliente, ruta="/desbloquear"):
    html = cliente.get(ruta).get_data(as_text=True)
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)


def entrar(c):
    t = csrf(c)
    r = c.post("/desbloquear", data={"_csrf": t, "contrasena": "contraseña-larga", "repetir": "contraseña-larga"})
    assert r.status_code == 302
    return csrf(c, "/configuracion")


def test_protecciones(cliente_web):
    c = cliente_web
    assert c.get("/", headers={"Host": "malicioso.example"}).status_code == 400
    assert c.get("/notas").status_code == 302  # sin abrir la bóveda
    t = entrar(c)
    assert c.post("/cursos", data={"asignatura": "X", "anio": "1"}).status_code == 400  # sin token CSRF
    r = c.get("/configuracion")
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert c.post("/bloquear", data={"_csrf": t}).status_code == 302
    assert c.get("/notas").status_code == 302


def test_flujo_completo(cliente_web):
    c = cliente_web
    t = entrar(c)
    c.post("/configuracion", data={"_csrf": t, "accion": "repo", "repo": "https://github.com/profe/igps", "rama_base": "main", "carpeta_enunciados": "actividades"})
    c.post("/cursos", data={"_csrf": t, "asignatura": "IGPS", "anio": "2026-27"})
    r = c.post("/alumnos/importar", data={"_csrf": t, "etapa": "subir", "fichero": (io.BytesIO(CSV_CAMPUS), "lista.csv")}, content_type="multipart/form-data")
    clave = re.search(r'name="clave" value="([^"]+)"', r.get_data(as_text=True)).group(1)
    mapeo = {"nombre": "Nombre", "apellidos": "Apellido(s)", "email": "Dirección de correo"}
    r = c.post("/alumnos/importar", data={"_csrf": t, "clave": clave, "etapa": "vista", **mapeo})
    assert "maria.nunez" in r.get_data(as_text=True)
    c.post("/alumnos/importar", data={"_csrf": t, "clave": clave, "etapa": "confirmar", **mapeo})

    html = c.get("/actividades?buscar=1").get_data(as_text=True)
    assert "git-aec.md" in html and "scrum.md" in html
    r = c.post("/actividades/nueva", data={"_csrf": t, "nombre": "AEC Git", "carpeta": "AEC-GIT", "plantilla": "aec-git", "enunciado": "actividades/git-aec.md"})
    url_act = r.headers["Location"]
    c.post(url_act, data={"_csrf": t, "accion": "rubrica", "fichero": (io.BytesIO(rubrica_docx()), "rubrica.docx")}, content_type="multipart/form-data")
    assert "100.0 %" in c.get(url_act).get_data(as_text=True)

    c.post("/sincronizar", data={"_csrf": t})
    html = c.get("/actividades/1/entregas").get_data(as_text=True)
    assert "Entregas sin identificar (1)" in html and "pepe.grillo" in html
    assert "No presentado" in html

    # Corrección de Juan (alumno 1): ve su informe en un iframe aislado
    html = c.get("/actividades/1/alumnos/1").get_data(as_text=True)
    assert 'sandbox=""' in html and "raw.githubusercontent.com/jperez/igps/sha-1-head/entregas/juan.perez/AEC-GIT/capturas/paso1.png" in html
    assert "<script>alert(1)</script>" not in html  # escapado dentro de srcdoc
    datos = {"_csrf": t, "entrega_principal": "1", "puerta_manual": ""}
    for i in range(1, 10):
        datos[f"nivel_{i}"] = "3"
    datos["nivel_8"] = "2"
    c.post("/actividades/1/alumnos/1", data=datos)
    assert "7,25" in c.get("/actividades/1/alumnos/1").get_data(as_text=True)

    csv = c.get("/exportar/actividad/1.csv").get_data(as_text=True)
    assert "Pérez Gómez;Juan" in csv and "7,25;Corregida" in csv
    assert "López;Ana" in csv and "0,00;No presentado" in csv
    glob = c.get("/exportar/global.csv").get_data(as_text=True)
    assert "Pérez Gómez;Juan;juan.perez@alumnos.example;7,25;7,25" in glob
    assert "Registro de actividad" in c.get("/configuracion").get_data(as_text=True)

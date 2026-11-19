import json
from datetime import datetime, timezone

import pytest

from corrector import comprobaciones as cmp
from corrector import informes
from corrector.alumnos_import import adivinar_mapeo, aplicar_importacion, construir_alumnos, leer_tabla
from corrector.boveda import Boveda
from corrector.db import ESQUEMA, cfg_get
from corrector.rubrica import leer_rubrica_docx
from corrector.sincronizar import sincronizar_curso
from github_falso import REPO, GitHubFalso
from utiles import CSV_CAMPUS, rubrica_docx


@pytest.fixture
def entorno(tmp_path):
    b = Boveda(str(tmp_path / "d.enc"))
    b.crear("contraseña-larga", ESQUEMA)
    c = b.conn
    c.execute("INSERT INTO curso (asignatura, anio) VALUES ('IGPS', '2026-27')")
    cab, datos = leer_tabla("lista.csv", CSV_CAMPUS)
    aplicar_importacion(c, 1, construir_alumnos(cab, datos, adivinar_mapeo(cab))[0])
    c.execute(
        "INSERT INTO actividad (curso_id, nombre, carpeta, comprobaciones, fecha_limite) VALUES (1, 'AEC Git', 'AEC-GIT', ?, ?)",
        (json.dumps(cmp.PLANTILLA_AEC_GIT["comprobaciones"]), "2026-11-10T23:59:00+01:00"),
    )
    for orden, (nombre, peso) in enumerate(leer_rubrica_docx(rubrica_docx())):
        c.execute(
            "INSERT INTO criterio (actividad_id, orden, nombre, peso, checks) VALUES (1, ?, ?, ?, ?)",
            (orden, nombre, peso, json.dumps(cmp.checks_para_criterio(nombre, cmp.CATALOGO))),
        )
    return c


def alumno(c, nombre):
    return c.execute("SELECT * FROM alumno WHERE nombre = ?", (nombre,)).fetchone()


def resultados_de(c, nombre):
    act = c.execute("SELECT * FROM actividad WHERE id = 1").fetchone()
    return informes.estado_alumno(c, act, alumno(c, nombre)["id"])


def sincronizar(c, gh=None, ahora=None):
    return sincronizar_curso(c, gh or GitHubFalso(), REPO, "main", 1, ahora or datetime(2026, 11, 5, tzinfo=timezone.utc))


def test_entrega_correcta(entorno):
    r = sincronizar(entorno)
    assert r["prs"] == 4 and r["entregas"] == 3 and r["sin_identificar"] == 1
    assert r["carpetas_sin_actividad"] == ["AEC-2"]
    e = resultados_de(entorno, "Juan")
    estados = {k: v["estado"] for k, v in e["resultados"].items()}
    assert estados == {
        "pr_desde_fork": "ok",
        "carpeta": "ok",
        "archivo_inicial": "ok",
        "rama_nombre": "ok",
        "num_commits": "ok",
        "rama_integrada": "ok",
        "pr_destino": "ok",
        "pr_titulo_descripcion": "ok",
        "commits_web": "ok",
        "fuera_de_carpeta": "ok",
    }
    assert "3 commits de trabajo" in e["resultados"]["num_commits"]["detalle"]
    assert e["estado"] == "pendiente" and e["nota"] is None
    # El usuario de GitHub se aprende a partir de la carpeta
    assert alumno(entorno, "Juan")["usuario_git"] == "jperez"


def test_entrega_con_problemas(entorno):
    sincronizar(entorno)
    e = resultados_de(entorno, "María José")
    estados = {k: v["estado"] for k, v in e["resultados"].items()}
    assert estados["carpeta"] == "aviso"  # Maria.Nunez: parecida, no exacta
    assert estados["archivo_inicial"] == "aviso"  # mayúsculas + archivo no vacío
    assert estados["rama_nombre"] == "fallo"
    assert estados["num_commits"] == "fallo"  # solo 1 commit de trabajo
    assert estados["rama_integrada"] == "aviso"  # PR desde main y sin rama: ¿borrada tras el merge?
    assert estados["pr_titulo_descripcion"] == "aviso"
    assert estados["commits_web"] == "aviso"
    assert estados["fuera_de_carpeta"] == "aviso"
    assert not e["suspenso"]  # un aviso no suspende: decide el profesor


def test_no_presentado_es_cero(entorno):
    sincronizar(entorno)
    e = resultados_de(entorno, "Ana")
    assert e["estado"] == "no_presentado" and str(e["nota"]) == "0.00"


def test_sin_identificar(entorno):
    sincronizar(entorno)
    fila = entorno.execute("SELECT * FROM entrega WHERE alumno_id IS NULL").fetchone()
    assert fila["pr_numero"] == 3 and fila["carpeta_detectada"] == "pepe.grillo"


def test_nota_y_tope_por_estructura(entorno):
    sincronizar(entorno)
    juan = alumno(entorno, "Juan")
    crits = informes.criterios(entorno, 1)
    for c in crits:
        entorno.execute("INSERT INTO calificacion (actividad_id, alumno_id, criterio_id, nivel) VALUES (1, ?, ?, 4)", (juan["id"], c["id"]))
    e = resultados_de(entorno, "Juan")
    assert e["estado"] == "corregida" and str(e["nota"]) == "10.00"
    entorno.execute("INSERT INTO revision (actividad_id, alumno_id, puerta_manual) VALUES (1, ?, 1)", (juan["id"],))
    e = resultados_de(entorno, "Juan")
    assert e["estado"] == "suspenso_estructura" and str(e["nota"]) == "4.90"


def test_congelado_tras_fecha_limite(entorno):
    gh = GitHubFalso()
    despues = datetime(2026, 11, 20, tzinfo=timezone.utc)
    sincronizar(entorno, gh, despues)
    fila = entorno.execute("SELECT * FROM entrega WHERE pr_numero = 1").fetchone()
    assert fila["sha_congelado"] == "sha-1-head" and not fila["cambios_tras_fecha"]
    gh.prs[0]["head"]["sha"] = "sha-1-nuevo"
    sincronizar(entorno, gh, despues)
    fila = entorno.execute("SELECT * FROM entrega WHERE pr_numero = 1").fetchone()
    assert fila["cambios_tras_fecha"] == 1 and fila["sha_congelado"] == "sha-1-head"


def test_exportaciones(entorno):
    sincronizar(entorno)
    csv = informes.exportar_actividad(entorno, 1)
    lineas = csv.lstrip("﻿").splitlines()
    assert lineas[0].startswith("Apellidos;Nombre;Email;Usuario GitHub;Fork y clonación")
    assert any(l.startswith("López;Ana") and l.endswith("0,00;No presentado") for l in lineas)
    glob = informes.exportar_global(entorno, 1).lstrip("﻿").splitlines()
    assert glob[0] == "Apellidos;Nombre;Email;AEC Git;Nota global"
    assert cfg_get(entorno, "carpetas_sin_actividad:1") == ["AEC-2"]

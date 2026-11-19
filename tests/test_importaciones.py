import io

from openpyxl import Workbook

from corrector.alumnos_import import adivinar_mapeo, aplicar_importacion, construir_alumnos, leer_tabla
from corrector.boveda import Boveda
from corrector.comprobaciones import checks_para_criterio, CATALOGO
from corrector.db import ESQUEMA
from corrector.rubrica import leer_rubrica_docx, leer_rubrica_texto
from utiles import CSV_CAMPUS, RUBRICA, rubrica_docx


def test_rubrica_docx():
    criterios = leer_rubrica_docx(rubrica_docx())
    assert [n for n, _ in criterios] == [n for n, _ in RUBRICA]
    assert sum(p for _, p in criterios) == 100
    asociados = {n: checks_para_criterio(n, CATALOGO) for n, _ in criterios}
    assert asociados["Fork y clonación del repositorio"] == ["pr_desde_fork"]
    assert asociados["Primer commit y subida inicial"] == ["archivo_inicial"]
    assert asociados["Commits y gestión de cambios"] == ["num_commits"]
    assert asociados["Merge y sincronización remota"] == ["rama_integrada"]
    assert asociados["Documentación del proceso"] == []


def test_rubrica_texto():
    assert leer_rubrica_texto("Fork; 10; pr_desde_fork\nDocumentación; 7,5\n") == [
        ("Fork", 10.0, ["pr_desde_fork"]),
        ("Documentación", 7.5, []),
    ]


def test_csv_del_campus():
    cab, datos = leer_tabla("lista.csv", CSV_CAMPUS)
    mapeo = adivinar_mapeo(cab)
    assert mapeo == {"nombre": "Nombre", "apellidos": "Apellido(s)", "email": "Dirección de correo"}
    alumnos, avisos = construir_alumnos(cab, datos, mapeo)
    assert [a["carpeta_esperada"] for a in alumnos] == ["juan.perez", "maria.nunez", "ana.lopez"]
    assert avisos == []


def test_excel_nombre_completo():
    wb = Workbook()
    ws = wb.active
    ws.append(["Alumno", "GitHub"])
    ws.append(["Pérez Gómez, Juan", "@jperez"])
    salida = io.BytesIO()
    wb.save(salida)
    cab, datos = leer_tabla("lista.xlsx", salida.getvalue())
    alumnos, _ = construir_alumnos(cab, datos, adivinar_mapeo(cab))
    assert alumnos[0]["nombre"] == "Juan" and alumnos[0]["apellidos"] == "Pérez Gómez"
    assert alumnos[0]["usuario_git"] == "jperez"


def test_reimportar_marca_bajas_sin_borrar(tmp_path):
    b = Boveda(str(tmp_path / "d.enc"))
    b.crear("contraseña-larga", ESQUEMA)
    b.conn.execute("INSERT INTO curso (asignatura, anio) VALUES ('IGPS', '2026-27')")
    cab, datos = leer_tabla("lista.csv", CSV_CAMPUS)
    alumnos, _ = construir_alumnos(cab, datos, adivinar_mapeo(cab))
    assert aplicar_importacion(b.conn, 1, alumnos) == {"nuevos": 3, "actualizados": 0, "bajas": 0}
    r = aplicar_importacion(b.conn, 1, alumnos[:2])
    assert r == {"nuevos": 0, "actualizados": 2, "bajas": 1}
    assert b.conn.execute("SELECT COUNT(*) FROM alumno").fetchone()[0] == 3
    assert b.conn.execute("SELECT activo FROM alumno WHERE nombre = 'Ana'").fetchone()[0] == 0

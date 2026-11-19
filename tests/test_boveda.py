import pytest

from corrector.boveda import Boveda, ContrasenaIncorrecta
from corrector.db import ESQUEMA


def test_cifrado_y_reapertura(tmp_path):
    ruta = str(tmp_path / "datos.enc")
    b = Boveda(ruta)
    b.crear("contraseña-larga", ESQUEMA)
    b.conn.execute("INSERT INTO curso (asignatura, anio) VALUES ('IGPS', '2026-27')")
    b.conn.execute("INSERT INTO alumno (curso_id, nombre, apellidos, carpeta_esperada) VALUES (1, 'Lucía', 'Secreta', 'lucia.secreta')")
    b.cerrar()

    crudo = open(ruta, "rb").read()
    assert b"Secreta" not in crudo and b"SQLite" not in crudo

    with pytest.raises(ContrasenaIncorrecta):
        Boveda(ruta).abrir("otra-contraseña")

    b2 = Boveda(ruta)
    b2.abrir("contraseña-larga", ESQUEMA)
    assert b2.conn.execute("SELECT apellidos FROM alumno").fetchone()[0] == "Secreta"
    assert b2.verificar("contraseña-larga") and not b2.verificar("x")


def test_contrasena_corta(tmp_path):
    with pytest.raises(ValueError):
        Boveda(str(tmp_path / "d.enc")).crear("corta", ESQUEMA)


def test_cambiar_contrasena(tmp_path):
    ruta = str(tmp_path / "d.enc")
    b = Boveda(ruta)
    b.crear("primera-clave", ESQUEMA)
    b.cambiar_contrasena("primera-clave", "segunda-clave")
    b.cerrar()
    with pytest.raises(ContrasenaIncorrecta):
        Boveda(ruta).abrir("primera-clave")
    Boveda(ruta).abrir("segunda-clave")

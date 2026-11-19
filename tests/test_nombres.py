from corrector.nombres import (
    carpeta_esperada,
    coincidencia_carpeta,
    comparar_mensaje,
    formato_valido,
    normalizar_mensaje,
)


def test_carpeta_esperada():
    assert carpeta_esperada("Juan", "Pérez Gómez") == "juan.perez"
    assert carpeta_esperada("María José", "Núñez García") == "maria.nunez"
    assert carpeta_esperada("Íñigo", "de la Fuente") == "inigo.fuente"


def test_coincidencias():
    args = ("María José", "Núñez García", "maria.nunez", [])
    assert coincidencia_carpeta("maria.nunez", *args) == "exacta"
    assert coincidencia_carpeta("María.Núñez", *args) == "aproximada"
    assert coincidencia_carpeta("maria.garcia", *args) == "aproximada"
    assert coincidencia_carpeta("maria.jose.nunez", *args) == "aproximada"
    assert coincidencia_carpeta("juan.perez", *args) is None
    assert coincidencia_carpeta("mj.nunez", "María José", "Núñez García", "maria.nunez", ["mj.nunez"]) == "exacta"


def test_formato():
    assert formato_valido("juan.perez")
    assert not formato_valido("Juan.Perez")
    assert not formato_valido("juanperez")


def test_mensajes():
    assert normalizar_mensaje('"docs: nuevo archivo"\n\ncuerpo') == "docs: nuevo archivo"
    assert comparar_mensaje("docs:  nuevo archivo", ["docs: nuevo archivo"]) == "exacto"
    assert comparar_mensaje("“docs: new file”", ["docs: nuevo archivo", "docs: new file"]) == "exacto"
    assert comparar_mensaje("Docs: Nuevo archivo", ["docs: nuevo archivo"]) == "mayusculas"
    assert comparar_mensaje("primer commit", ["docs: nuevo archivo"]) is None

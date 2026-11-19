from decimal import Decimal

from corrector import calificacion as cal

PESOS = [10, 10, 10, 15, 15, 10, 15, 10, 5]
CRIT = list(enumerate(PESOS))


def niveles(*v):
    return dict(enumerate(v))


def test_pesos_suman_100():
    assert cal.suma_pesos(PESOS) == 100


def test_formula_del_profesor():
    # Todo 3 salvo Documentación (índice 7) en 2: (3*0,90 + 2*0,10) * 2,5 = 7,25
    n = niveles(3, 3, 3, 3, 3, 3, 3, 2, 3)
    assert cal.nota_por_formula(n, CRIT, 2.5) == Decimal("7.25")


def test_extremos():
    assert cal.nota_por_formula(niveles(*[4] * 9), CRIT, 2.5) == Decimal("10.00")
    assert cal.nota_por_formula(niveles(*[1] * 9), CRIT, 2.5) == Decimal("2.50")


def test_igual_que_la_hoja():
    v = [4, 3, 2, 4, 1, 3, 4, 2, 3]
    hoja = (v[0] * 0.1 + v[1] * 0.1 + v[2] * 0.1 + v[3] * 0.15 + v[4] * 0.15 + v[5] * 0.1 + v[6] * 0.15 + v[7] * 0.1 + v[8] * 0.05) * 2.5
    assert cal.nota_por_formula(niveles(*v), CRIT, 2.5) == cal.dos_decimales(round(hoja, 6))


def test_falta_un_nivel():
    n = niveles(*[4] * 9)
    n[3] = None
    assert cal.nota_por_formula(n, CRIT, 2.5) is None


def test_tope_estructura():
    assert cal.aplicar_tope(Decimal("9.25"), True, 4.9) == Decimal("4.90")
    assert cal.aplicar_tope(Decimal("3.10"), True, 4.9) == Decimal("3.10")
    assert cal.aplicar_tope(Decimal("9.25"), False, 4.9) == Decimal("9.25")


def test_global():
    assert cal.nota_global([(Decimal("8"), 1), (Decimal("6"), 1)]) == Decimal("7.00")
    assert cal.nota_global([(Decimal("8"), 3), (Decimal("4"), 1)]) == Decimal("7.00")
    assert cal.nota_global([(Decimal("8"), 1), (None, 1)]) is None


def test_nivel_sugerido():
    assert cal.nivel_sugerido(["ok", "ok"], 4) == 4
    assert cal.nivel_sugerido(["fallo"], 4) == 1
    assert cal.nivel_sugerido(["ok", "fallo"], 4) == 3  # 1 + 0,5*3 = 2,5 -> 3
    assert cal.nivel_sugerido(["na"], 4) is None


def test_formato():
    assert cal.formato_nota(Decimal("7.25")) == "7,25"
    assert cal.formato_nota(Decimal("0")) == "0,00"

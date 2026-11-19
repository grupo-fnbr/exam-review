"""Cálculo de notas.

Fórmula del profesor (hoja de cálculo):
    =((C6*0,1)+(D6*0,1)+(E6*0,1)+(F6*0,15)+(G6*0,15)+(H6*0,1)+(I6*0,15)+(J6*0,1)+(K6*0,05))*2,5
Es decir: nota = Σ(nivel × peso) × factor, con niveles 1-4, pesos que suman 100 % y
factor 2,5 (= 10 / nivel máximo). Resultado sobre 10 con dos decimales.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
VALOR_ESTADO = {"ok": Decimal(1), "aviso": Decimal("0.5"), "fallo": Decimal(0)}


def dos_decimales(valor) -> Decimal:
    return Decimal(str(valor)).quantize(CENT, rounding=ROUND_HALF_UP)


def suma_pesos(pesos) -> Decimal:
    return sum((Decimal(str(p)) for p in pesos), Decimal(0))


def nota_por_formula(niveles: dict, criterios: list[tuple[int, float]], factor) -> Decimal | None:
    """criterios: [(id, peso_en_%)]; niveles: {id: nivel}. None si falta algún nivel."""
    if not criterios:
        return None
    if any(niveles.get(cid) is None for cid, _ in criterios):
        return None
    total = sum(
        (Decimal(int(niveles[cid])) * Decimal(str(peso)) / Decimal(100) for cid, peso in criterios),
        Decimal(0),
    )
    return dos_decimales(total * Decimal(str(factor)))


def aplicar_tope(nota: Decimal | None, suspenso: bool, tope) -> Decimal | None:
    if nota is None or not suspenso:
        return nota
    tope = dos_decimales(tope)
    return min(nota, tope)


def nota_global(pares: list[tuple[Decimal | None, float]]) -> Decimal | None:
    """Media ponderada de las notas de cada actividad. None si falta alguna."""
    if not pares or any(n is None for n, _ in pares):
        return None
    total_peso = suma_pesos(p for _, p in pares)
    if total_peso == 0:
        return None
    total = sum((Decimal(n) * Decimal(str(p)) for n, p in pares), Decimal(0))
    return dos_decimales(total / total_peso)


def nivel_sugerido(estados: list[str], nivel_max: int) -> int | None:
    """Nivel propuesto a partir de las comprobaciones automáticas de un criterio."""
    valores = [VALOR_ESTADO[e] for e in estados if e in VALOR_ESTADO]
    if not valores:
        return None
    proporcion = sum(valores, Decimal(0)) / len(valores)
    nivel = Decimal(1) + proporcion * (nivel_max - 1)
    return int(nivel.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def formato_nota(nota: Decimal | None) -> str:
    """Nota con coma decimal, como en las hojas de cálculo en español."""
    if nota is None:
        return ""
    return f"{nota:.2f}".replace(".", ",")

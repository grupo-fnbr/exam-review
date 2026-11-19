import io

from docx import Document

RUBRICA = [
    ("Fork y clonación del repositorio", "10%"),
    ("Estructura de carpetas", "10%"),
    ("Primer commit y subida inicial", "10%"),
    ("Creación y gestión de ramas", "15%"),
    ("Commits y gestión de cambios", "15%"),
    ("Merge y sincronización remota", "10%"),
    ("Creación de Pull Request", "15%"),
    ("Documentación del proceso", "10%"),
    ("Autonomía y trazabilidad", "5%"),
]


def rubrica_docx() -> bytes:
    doc = Document()
    doc.add_paragraph("La actividad se evaluará sobre 100 puntos.")
    tabla = doc.add_table(rows=1, cols=6)
    for celda, texto in zip(tabla.rows[0].cells, ["Criterio", "Peso", "Excelente (4)", "Notable (3)", "Suficiente (2)", "Insuficiente (1)"]):
        celda.text = texto
    for nombre, peso in RUBRICA:
        fila = tabla.add_row().cells
        fila[0].text, fila[1].text = nombre, peso
        for c in fila[2:]:
            c.text = "descripción"
    salida = io.BytesIO()
    doc.save(salida)
    return salida.getvalue()


CSV_CAMPUS = (
    "Nombre;Apellido(s);Dirección de correo\n"
    "Juan;Pérez Gómez;juan.perez@alumnos.example\n"
    "María José;Núñez García;mj.nunez@alumnos.example\n"
    "Ana;López;ana.lopez@alumnos.example\n"
).encode("cp1252")

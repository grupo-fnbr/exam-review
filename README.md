# Corrector AEC

Aplicación local para revisar y calificar las actividades de evaluación continua de
*Introducción a la Gestión de Proyectos de Software* que los alumnos entregan por
pull request al repositorio de GitHub del profesor.

- Se ejecuta **solo en el ordenador del profesor** (escucha en `127.0.0.1`).
- Todos los datos (alumnos, notas, comentarios) se guardan **cifrados** con una contraseña maestra.
- El token de GitHub va al llavero del sistema (Keychain / Administrador de credenciales / Secret Service).
- Varias actividades por curso, un curso por año académico.

## Instalación

Requiere Python 3.11 o posterior.

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate        # En Windows: .venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

## Uso

```bash
python -m corrector
```

Se abre el navegador en `http://127.0.0.1:5050`. La primera vez pide crear la contraseña
maestra (mínimo 10 caracteres). **Si se olvida, los datos no se pueden recuperar.**

Opciones: `--puerto 5050`, `--datos ruta/datos.enc`, `--sin-navegador`.
Por defecto los datos están en `~/.corrector-aec/datos.enc`.

### Flujo de trabajo

1. **Configuración**: repositorio del profesor (`usuario/nombre`), rama principal, carpeta de
   enunciados y, recomendado, un token de GitHub de solo lectura (sin token GitHub solo permite
   60 consultas por hora).
2. **Cursos**: crear el curso académico (p. ej. `2026-27`); se pueden copiar las actividades y
   rúbricas del año anterior.
3. **Alumnos → Importar lista**: CSV o Excel del campus. Se asignan las columnas (se recuerdan para
   el año siguiente) y se calcula la carpeta esperada `nombre.apellido`. Reimportar añade altas y marca
   bajas sin borrar notas.
4. **Actividades**: crear desde un enunciado detectado en el repo, desde una carpeta con entregas sin
   actividad o a mano. Importar la rúbrica `.docx` (tabla con columnas *Criterio* y *Peso*) y revisar
   las comprobaciones automáticas.
5. **Sincronizar**: lee todas las PR, asigna cada una a actividad (por la carpeta que modifica) y a
   alumno (por usuario de GitHub o por carpeta) y ejecuta las comprobaciones.
6. **Corregir**: por alumno se ven las comprobaciones, el informe y las capturas, y se pone el nivel
   de cada criterio (la app sugiere uno a partir de las comprobaciones).
7. **Exportar**: CSV por actividad y CSV de notas globales (separador `;` y coma decimal para Excel).

## Cálculo de la nota

```
nota = Σ(nivel × peso) × factor
```

Niveles 1-4, pesos en % que suman 100 y factor 2,5: nota sobre 10 con dos decimales.
Si falla la comprobación de estructura (o el profesor lo marca), la nota se limita a 4,9.
Sin entrega: 0. La nota global es la media ponderada de las actividades (peso configurable).
Todo ello es configurable por actividad.

## Comprobaciones disponibles

| Clave | Qué comprueba |
|---|---|
| `pr_desde_fork` | La PR sale de un fork del repo del profesor |
| `carpeta` | Ruta `<raíz>/nombre.apellido/<actividad>` y que la carpeta corresponde al alumno |
| `archivo_inicial` | Commit con el mensaje exacto que añade un archivo vacío, presente en la rama principal del fork |
| `rama_nombre` | La PR sale de la rama con el nombre exacto (o la rama existe en el fork) |
| `num_commits` | Nº de commits de trabajo en la carpeta de la actividad (sin el inicial ni merges) |
| `rama_integrada` | La rama principal del fork contiene la rama de trabajo (merge o fast-forward) |
| `pr_destino` | La PR apunta al repo y rama del profesor |
| `pr_titulo_descripcion` | La PR tiene título y descripción |
| `commits_web` | Commits hechos desde la web de GitHub en lugar de la terminal |
| `fuera_de_carpeta` | La PR modifica archivos fuera de la carpeta del alumno |

Cada comprobación da `ok`, `aviso` (lo decide el profesor) o `fallo`. La plantilla *AEC Git* acepta
los nombres en español e inglés (`entregas`/`submissions`, `docs/modificaciones`/`docs/modifications`,
`docs: nuevo archivo`/`docs: new file`).

## Seguridad

- Base de datos SQLite en memoria; en disco solo el fichero cifrado con AES-256-GCM (clave derivada con scrypt).
- Se cierra y cifra tras 30 minutos de inactividad o con «Cerrar y cifrar».
- Solo acepta conexiones de `127.0.0.1`/`localhost`; protección CSRF en todos los formularios y CSP estricta.
- Los informes de los alumnos se muestran en un iframe aislado sin scripts.
- Los comentarios y notas nunca se publican en GitHub: el repo del profesor es público.
- Registro de actividad en *Configuración*.

## Pruebas

```bash
pip install -r requirements-dev.txt
```

```bash
python -m pytest
```

## Pendiente

- Fijar las columnas con un ejemplo real del fichero de alumnos del campus.
- El diseño (diagramas y decisiones) está en `docs/decisiones.md`.

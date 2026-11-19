# Decisiones de diseño

| Tema | Decisión |
|---|---|
| Plataforma | GitHub. Repositorio del profesor público. |
| Ejecución | Aplicación local en el PC del profesor, un único usuario. |
| Identificación | Lista de alumnos importada por curso; cruce por usuario de GitHub y, si no, por la carpeta `nombre.apellido`. El usuario se aprende en la primera entrega. |
| Idioma del enunciado | Se aceptan los nombres en español y en inglés. |
| Informe | Formato libre (.md, .txt, imágenes, .docx, .pdf…). |
| Nota | `Σ(nivel × peso) × 2,5`, sobre 10 con dos decimales. |
| Carpeta incorrecta | Nota con tope 4,9 y marca «suspenso por estructura». |
| No presentado | 0. |
| Actividades | Varias por curso; cada una con su carpeta, rúbrica y comprobaciones. Se detectan los enunciados publicados en el repo del profesor. |
| Rúbricas | Las importa el profesor desde su PC (.docx); no se suben al repo. |
| Nota global | Se exporta cada actividad por separado y una global (media ponderada, peso configurable). |

## Puntos técnicos

- El merge del paso 5 suele ser *fast-forward*: no hay commit de merge. Se comprueba que la rama
  principal del fork contiene el último commit de la rama de trabajo.
- La PR incluye el commit inicial; no se cuenta en el rango de 2-5 commits.
- Como todas las actividades llegan al mismo repo, una PR puede arrastrar commits de actividades
  anteriores: se asigna por la carpeta que modifica y solo se cuentan los commits que tocan esa carpeta.
- Tras la fecha límite se congela el commit de cada PR; si cambia después, se avisa.

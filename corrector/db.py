"""Esquema y utilidades de la base de datos (siempre dentro de la bóveda cifrada)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

ESQUEMA = """
CREATE TABLE IF NOT EXISTS config (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE TABLE IF NOT EXISTS curso (
    id INTEGER PRIMARY KEY,
    asignatura TEXT NOT NULL,
    anio TEXT NOT NULL,
    archivado INTEGER NOT NULL DEFAULT 0,
    mapeo_columnas TEXT
);

CREATE TABLE IF NOT EXISTS alumno (
    id INTEGER PRIMARY KEY,
    curso_id INTEGER NOT NULL REFERENCES curso(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    apellidos TEXT NOT NULL,
    email TEXT,
    usuario_git TEXT,
    carpeta_esperada TEXT NOT NULL,
    variantes TEXT NOT NULL DEFAULT '[]',
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS actividad (
    id INTEGER PRIMARY KEY,
    curso_id INTEGER NOT NULL REFERENCES curso(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    carpeta TEXT NOT NULL,
    enunciado TEXT,
    fecha_limite TEXT,
    nivel_max INTEGER NOT NULL DEFAULT 4,
    factor REAL NOT NULL DEFAULT 2.5,
    tope_estructura REAL NOT NULL DEFAULT 4.9,
    peso_global REAL NOT NULL DEFAULT 1,
    carpetas_raiz TEXT NOT NULL DEFAULT '["entregas", "submissions"]',
    comprobaciones TEXT NOT NULL DEFAULT '{}',
    check_puerta TEXT DEFAULT 'carpeta',
    activa INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS criterio (
    id INTEGER PRIMARY KEY,
    actividad_id INTEGER NOT NULL REFERENCES actividad(id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    peso REAL NOT NULL,
    checks TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS entrega (
    id INTEGER PRIMARY KEY,
    actividad_id INTEGER NOT NULL REFERENCES actividad(id) ON DELETE CASCADE,
    alumno_id INTEGER REFERENCES alumno(id) ON DELETE SET NULL,
    asignacion_manual INTEGER NOT NULL DEFAULT 0,
    pr_numero INTEGER NOT NULL,
    pr_url TEXT,
    pr_titulo TEXT,
    pr_estado TEXT,
    autor TEXT,
    head_repo TEXT,
    head_ref TEXT,
    head_sha TEXT,
    sha_congelado TEXT,
    cambios_tras_fecha INTEGER NOT NULL DEFAULT 0,
    raiz TEXT,
    carpeta_detectada TEXT,
    carpeta_actividad TEXT,
    creada TEXT,
    actualizada TEXT,
    sincronizada TEXT,
    avisos TEXT NOT NULL DEFAULT '[]',
    UNIQUE (actividad_id, pr_numero)
);

CREATE TABLE IF NOT EXISTS resultado (
    id INTEGER PRIMARY KEY,
    entrega_id INTEGER NOT NULL REFERENCES entrega(id) ON DELETE CASCADE,
    check_id TEXT NOT NULL,
    estado TEXT NOT NULL,
    detalle TEXT
);

CREATE TABLE IF NOT EXISTS revision (
    actividad_id INTEGER NOT NULL REFERENCES actividad(id) ON DELETE CASCADE,
    alumno_id INTEGER NOT NULL REFERENCES alumno(id) ON DELETE CASCADE,
    entrega_principal INTEGER,
    puerta_manual INTEGER,
    comentario TEXT,
    PRIMARY KEY (actividad_id, alumno_id)
);

CREATE TABLE IF NOT EXISTS calificacion (
    actividad_id INTEGER NOT NULL REFERENCES actividad(id) ON DELETE CASCADE,
    alumno_id INTEGER NOT NULL REFERENCES alumno(id) ON DELETE CASCADE,
    criterio_id INTEGER NOT NULL REFERENCES criterio(id) ON DELETE CASCADE,
    nivel INTEGER,
    comentario TEXT,
    PRIMARY KEY (actividad_id, alumno_id, criterio_id)
);

CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY,
    momento TEXT NOT NULL,
    accion TEXT NOT NULL
);
"""


def ahora_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def cfg_get(conn: sqlite3.Connection, clave: str, defecto=None):
    fila = conn.execute("SELECT valor FROM config WHERE clave = ?", (clave,)).fetchone()
    if fila is None or fila["valor"] is None:
        return defecto
    return json.loads(fila["valor"])


def cfg_set(conn: sqlite3.Connection, clave: str, valor) -> None:
    if valor is None:
        conn.execute("DELETE FROM config WHERE clave = ?", (clave,))
    else:
        conn.execute(
            "INSERT INTO config (clave, valor) VALUES (?, ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
            (clave, json.dumps(valor)),
        )


def auditar(conn: sqlite3.Connection, accion: str) -> None:
    conn.execute("INSERT INTO auditoria (momento, accion) VALUES (?, ?)", (ahora_iso(), accion))


def cargar_json(texto, defecto):
    if not texto:
        return defecto
    try:
        return json.loads(texto)
    except (TypeError, ValueError):
        return defecto

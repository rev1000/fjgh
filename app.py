#!/usr/bin/env python3
"""GESTIONABLE V3 — Life OS · Warp/Weirdcore aesthetic"""
import os, json, random, string
from datetime import datetime, timedelta, date
from functools import wraps
from contextlib import contextmanager

from flask import Flask, request, jsonify, send_from_directory, g
from flask_cors import CORS
import jwt
import bcrypt

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

SECRET_KEY = os.environ.get("SECRET_KEY", "gestionable-v3-warp-2026")
TOKEN_HOURS = 72
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
USE_PG = DATABASE_URL.startswith("postgres")
SQLITE_PATH = os.environ.get("DATABASE_PATH", "/tmp/gestionable_v3.db")

ESTADOS = ["Backlog", "Pendiente", "En curso", "Pausado", "Completado", "Cancelado", "Eliminado"]
KANBAN_COLS = ["Backlog", "Pendiente", "En curso", "Pausado", "Completado", "Cancelado"]  # Eliminado nunca en board; tras reset Done/Cancel ocultos vía archivado
AREAS_DEFAULT = [
    ("Salud", "#22c55e"), ("Arte", "#ec4899"), ("Familia", "#f59e0b"),
    ("Academico", "#3b82f6"), ("Emprendimiento", "#a855f7"), ("Laboral", "#64748b"),
]
DEFAULT_FORMULA = {"u": 8, "i": 5, "e": 2, "m": 1}  # P = 8U+5I-2E-M


def gen_id(table):
    """cuatro primeras letras + _log_ + 7 dígitos irrepetibles"""
    prefix = (table[:4] if len(table) >= 4 else table.ljust(4, "x")).lower()
    return f"{prefix}_log_{random.randint(1000000, 9999999)}"


def gen_move_id():
    return f"move_log_{random.randint(1000000, 9999999)}"


# ─── DB ───
def _pg():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


def _sqlite():
    import sqlite3
    c = sqlite3.connect(SQLITE_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


@contextmanager
def db_conn():
    conn = _pg() if USE_PG else _sqlite()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def q(sql, params=None, one=False, write=False):
    params = params or ()
    if USE_PG:
        # Escape literal % (e.g. LIKE patterns) before converting ? → %s for psycopg2
        sql = sql.replace("%", "%%").replace("?", "%s")
    with db_conn() as conn:
        if USE_PG:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            cur = conn.cursor()
        cur.execute(sql, params)
        if write:
            if USE_PG:
                try:
                    r = cur.fetchone()
                    return dict(r) if r else None
                except Exception:
                    return None
            return cur.lastrowid
        rows = cur.fetchall()
        rows = [dict(r) for r in rows]
        return (rows[0] if rows else None) if one else rows


def qw(sql, params=None):
    return q(sql, params, write=True)


def init_db():
    if USE_PG:
        ddl = [
            """CREATE TABLE IF NOT EXISTS usuarios (
                id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
                nombre TEXT, role TEXT DEFAULT 'user', created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS areas (
                id TEXT PRIMARY KEY, nombre TEXT UNIQUE NOT NULL, cod_color TEXT DEFAULT '#a855f7')""",
            """CREATE TABLE IF NOT EXISTS formula_prioridad (
                id TEXT PRIMARY KEY, usuario_id TEXT, coef_u REAL DEFAULT 8, coef_i REAL DEFAULT 5,
                coef_e REAL DEFAULT 2, coef_m REAL DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS gestionables (
                id TEXT PRIMARY KEY, usuario_id TEXT NOT NULL, tipo TEXT NOT NULL,
                titulo TEXT NOT NULL, descripcion TEXT DEFAULT '',
                area_id TEXT, created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS tareas (
                gestionable_id TEXT PRIMARY KEY, estado TEXT DEFAULT 'Backlog',
                impacto INT DEFAULT 5, esfuerzo INT DEFAULT 5, miedo INT DEFAULT 3, urgencia INT DEFAULT 5,
                fecha_inicio TIMESTAMP, fecha_fin TIMESTAMP, prerequisito_id TEXT)""",
            """CREATE TABLE IF NOT EXISTS actividades (
                gestionable_id TEXT PRIMARY KEY, estado TEXT DEFAULT 'Pendiente',
                impacto INT DEFAULT 5, esfuerzo INT DEFAULT 5, miedo INT DEFAULT 3, urgencia INT DEFAULT 5)""",
            """CREATE TABLE IF NOT EXISTS proyectos (
                gestionable_id TEXT PRIMARY KEY, objetivo TEXT DEFAULT '', progreso REAL DEFAULT 0,
                deadline DATE)""",
            """CREATE TABLE IF NOT EXISTS proyecto_tareas (
                id TEXT PRIMARY KEY, proyecto_id TEXT NOT NULL, tarea_id TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS habitos (
                gestionable_id TEXT PRIMARY KEY, frecuencia TEXT DEFAULT 'diario', horario TEXT DEFAULT '',
                activo INT DEFAULT 1, racha INT DEFAULT 0, mejor_racha INT DEFAULT 0,
                duracion_min INT DEFAULT 10, estado_dia TEXT DEFAULT 'Pendiente')""",
            """CREATE TABLE IF NOT EXISTS habito_logs (
                id TEXT PRIMARY KEY, habito_id TEXT NOT NULL, usuario_id TEXT NOT NULL, fecha DATE NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS eventos (
                gestionable_id TEXT PRIMARY KEY, fecha_inicio TIMESTAMP, fecha_fin TIMESTAMP, ubicacion TEXT DEFAULT '')""",
            """CREATE TABLE IF NOT EXISTS movimientos (
                id TEXT PRIMARY KEY, usuario_id TEXT NOT NULL, tipo TEXT, detalle TEXT,
                ref_id TEXT, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS burndown_config (
                id TEXT PRIMARY KEY, usuario_id TEXT UNIQUE, fecha_inicio DATE, fecha_fin DATE,
                total_tareas INT DEFAULT 0, pct_cumplimiento REAL DEFAULT 0,
                tareas_json TEXT DEFAULT '[]')""",
            """CREATE TABLE IF NOT EXISTS logs_entidad (
                id TEXT PRIMARY KEY, usuario_id TEXT NOT NULL, entidad_tipo TEXT, entidad_id TEXT,
                accion TEXT, detalle TEXT, created_at TIMESTAMP DEFAULT NOW())""",
        ]
    else:
        ddl = [
            """CREATE TABLE IF NOT EXISTS usuarios (
                id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
                nombre TEXT, role TEXT DEFAULT 'user', created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS areas (
                id TEXT PRIMARY KEY, nombre TEXT UNIQUE NOT NULL, cod_color TEXT DEFAULT '#a855f7')""",
            """CREATE TABLE IF NOT EXISTS formula_prioridad (
                id TEXT PRIMARY KEY, usuario_id TEXT, coef_u REAL DEFAULT 8, coef_i REAL DEFAULT 5,
                coef_e REAL DEFAULT 2, coef_m REAL DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS gestionables (
                id TEXT PRIMARY KEY, usuario_id TEXT NOT NULL, tipo TEXT NOT NULL,
                titulo TEXT NOT NULL, descripcion TEXT DEFAULT '',
                area_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS tareas (
                gestionable_id TEXT PRIMARY KEY, estado TEXT DEFAULT 'Backlog',
                impacto INT DEFAULT 5, esfuerzo INT DEFAULT 5, miedo INT DEFAULT 3, urgencia INT DEFAULT 5,
                fecha_inicio TEXT, fecha_fin TEXT, prerequisito_id TEXT)""",
            """CREATE TABLE IF NOT EXISTS actividades (
                gestionable_id TEXT PRIMARY KEY, estado TEXT DEFAULT 'Pendiente',
                impacto INT DEFAULT 5, esfuerzo INT DEFAULT 5, miedo INT DEFAULT 3, urgencia INT DEFAULT 5)""",
            """CREATE TABLE IF NOT EXISTS proyectos (
                gestionable_id TEXT PRIMARY KEY, objetivo TEXT DEFAULT '', progreso REAL DEFAULT 0, deadline TEXT)""",
            """CREATE TABLE IF NOT EXISTS proyecto_tareas (
                id TEXT PRIMARY KEY, proyecto_id TEXT NOT NULL, tarea_id TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS habitos (
                gestionable_id TEXT PRIMARY KEY, frecuencia TEXT DEFAULT 'diario', horario TEXT DEFAULT '',
                activo INT DEFAULT 1, racha INT DEFAULT 0, mejor_racha INT DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS habito_logs (
                id TEXT PRIMARY KEY, habito_id TEXT NOT NULL, usuario_id TEXT NOT NULL, fecha TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS eventos (
                gestionable_id TEXT PRIMARY KEY, fecha_inicio TEXT, fecha_fin TEXT, ubicacion TEXT DEFAULT '')""",
            """CREATE TABLE IF NOT EXISTS movimientos (
                id TEXT PRIMARY KEY, usuario_id TEXT NOT NULL, tipo TEXT, detalle TEXT,
                ref_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS burndown_config (
                id TEXT PRIMARY KEY, usuario_id TEXT UNIQUE, fecha_inicio TEXT, fecha_fin TEXT,
                total_tareas INT DEFAULT 0, pct_cumplimiento REAL DEFAULT 0, tareas_json TEXT DEFAULT '[]')""",
            """CREATE TABLE IF NOT EXISTS logs_entidad (
                id TEXT PRIMARY KEY, usuario_id TEXT NOT NULL, entidad_tipo TEXT, entidad_id TEXT,
                accion TEXT, detalle TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
        ]
    with db_conn() as conn:
        cur = conn.cursor()
        for s in ddl:
            cur.execute(s)
        # areas globales
        for nom, col in AREAS_DEFAULT:
            aid = gen_id("areas")
            try:
                if USE_PG:
                    cur.execute("INSERT INTO areas (id,nombre,cod_color) VALUES (%s,%s,%s) ON CONFLICT (nombre) DO NOTHING", (aid, nom, col))
                else:
                    cur.execute("INSERT OR IGNORE INTO areas (id,nombre,cod_color) VALUES (?,?,?)", (aid, nom, col))
            except Exception:
                pass
        # seed users
        for email, pw, nombre, role in [
            ("admin@gestionable.app", b"admin123", "Admin", "admin"),
            ("user@gestionable.app", b"user123", "Usuario Demo", "user"),
        ]:
            h = bcrypt.hashpw(pw, bcrypt.gensalt()).decode()
            uid = gen_id("usua")
            try:
                if USE_PG:
                    cur.execute(
                        "INSERT INTO usuarios (id,email,password_hash,nombre,role) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (email) DO NOTHING",
                        (uid, email, h, nombre, role),
                    )
                else:
                    cur.execute(
                        "INSERT OR IGNORE INTO usuarios (id,email,password_hash,nombre,role) VALUES (?,?,?,?,?)",
                        (uid, email, h, nombre, role),
                    )
            except Exception:
                pass
    try:
        with db_conn() as conn:
            cur = conn.cursor()
            if USE_PG:
                cur.execute("ALTER TABLE tareas ADD COLUMN IF NOT EXISTS prerequisito_id TEXT")
                cur.execute("ALTER TABLE habitos ADD COLUMN IF NOT EXISTS duracion_min INT DEFAULT 10")
                cur.execute("ALTER TABLE habitos ADD COLUMN IF NOT EXISTS estado_dia TEXT DEFAULT 'Pendiente'")
                cur.execute("ALTER TABLE habitos ADD COLUMN IF NOT EXISTS last_reset DATE")
            else:
                for col, defn in [
                    ("prerequisito_id", "TEXT"),
                    ("duracion_min", "INTEGER DEFAULT 10"),
                    ("estado_dia", "TEXT DEFAULT 'Pendiente'"),
                    ("last_reset", "TEXT"),
                ]:
                    try:
                        if col == "prerequisito_id":
                            cur.execute(f"ALTER TABLE tareas ADD COLUMN {col} {defn}")
                        else:
                            cur.execute(f"ALTER TABLE habitos ADD COLUMN {col} {defn}")
                    except Exception:
                        pass
    except Exception as e:
        print("migrate", e)
    seed_demo_data()
    print("DB V3 ready. PG=", USE_PG)


def seed_demo_data():
    """Tareas precargadas ilustrativas del espectro funcional"""
    user = q("SELECT id FROM usuarios WHERE email=?", ("user@gestionable.app",), one=True)
    if not user:
        return
    uid = user["id"]
    existing = q("SELECT COUNT(*) as c FROM gestionables WHERE usuario_id=?", (uid,), one=True)
    if existing and existing.get("c", 0) > 0:
        return
    areas = {a["nombre"]: a["id"] for a in q("SELECT * FROM areas")}
    samples = [
        ("Cambiar dirección fiscal", "Trámite rápido alto impacto", "Salud", 9, 2, 3, 6, "Pendiente"),
        ("Curso Coursera especialización", "Proyecto estratégico largo", "Academico", 9, 7, 6, 7, "Backlog"),
        ("Visitar museo", "Ocio cultural", "Arte", 8, 2, 3, 4, "Pendiente"),
        ("Hacer calendario físico", "Organización", "Laboral", 7, 3, 2, 5, "En curso"),
        ("Requisitos título", "Académico urgente", "Academico", 7, 3, 5, 6, "Pendiente"),
        ("Postular a trabajos", "Empleo", "Laboral", 5, 2, 6, 8, "Backlog"),
        ("Ordenar workspace", "Mantenimiento", "Laboral", 4, 2, 3, 3, "Pausado"),
        ("Diseño de tetera", "Creativo bajo ROI", "Arte", 3, 5, 2, 2, "Backlog"),
        ("Proyecto canal YouTube", "Emprendimiento alto esfuerzo", "Emprendimiento", 8, 7, 7, 7, "En curso"),
        ("Reunión familiar domingo", "Familia", "Familia", 6, 2, 1, 4, "Pendiente"),
    ]
    for titulo, desc, area, I, E, M, U, estado in samples:
        gid = gen_id("tare")
        qw("INSERT INTO gestionables (id,usuario_id,tipo,titulo,descripcion,area_id) VALUES (?,?,?,?,?,?)",
           (gid, uid, "tarea", titulo, desc, areas.get(area)))
        qw("INSERT INTO tareas (gestionable_id,estado,impacto,esfuerzo,miedo,urgencia) VALUES (?,?,?,?,?,?)",
           (gid, estado, I, E, M, U))
    # Hábitos del PDF horario ideal
    PDF_HABITS = [
        ("Git Push Diario", "Laboral", "diario", "10:20", 10),
        ("Dental floss + mouthwash (mañana)", "Salud", "diario", "06:30", 3),
        ("Dental floss + mouthwash (noche)", "Salud", "diario", "20:00", 3),
        ("Mindfulness / Meditación Balance", "Salud", "diario", "10:40", 10),
        ("Agua al despertar (2 vasos)", "Salud", "diario", "06:10", 2),
        ("Barridita o Trapeadita", "Familia", "diario", "06:40", 10),
        ("Revisar lista priorizada (Matriz)", "Laboral", "diario", "07:30", 10),
        ("Lectura técnica", "Academico", "3x", "17:00", 20),
        ("1 clase curso online", "Academico", "2x", "14:30", 30),
        ("Practicar inglés (Ewa/Elevate)", "Academico", "5x", "19:30", 20),
        ("Un dibujo / dibujo rápido", "Arte", "3x", "17:00", 15),
        ("Lectura artística", "Arte", "2x", "19:30", 20),
        ("1 canción guitarra", "Arte", "2x", "17:15", 15),
        ("Una postulación calidad", "Laboral", "3x", "08:30", 25),
        ("Un diagrama UML", "Laboral", "1x", "11:30", 20),
        ("Aprender 5 palabras inglés", "Academico", "5x", "19:40", 10),
        ("Trucos speaking", "Academico", "5x", "19:50", 10),
        ("Prueba materiales arte / mandala", "Arte", "1x", "17:00", 20),
        ("Caligrafía", "Arte", "1x", "17:20", 15),
        ("Escribir pensamientos", "Salud", "2x", "21:00", 10),
        ("1 capítulo lectura", "Arte", "2x", "19:30", 20),
        ("Disfrutar pertenencias 15 min", "Familia", "1x", "20:30", 15),
        ("1 baile peruano", "Arte", "1x", "17:00", 15),
        ("Vinilo/CD/DVD físico", "Arte", "1x", "20:30", 30),
        ("Audiolibro Headway", "Academico", "1x", "18:00", 25),
        ("Escribir libro 25 min", "Arte", "1x", "14:30", 25),
        ("Organizar fotos álbumes", "Familia", "1x", "16:30", 20),
        ("Pintar mandala", "Arte", "1x", "15:00", 20),
        ("Gym o Bici malecón", "Salud", "3x", "18:00", 40),
        ("Registrar peso", "Salud", "diario", "06:15", 2),
        ("Agradecimiento", "Salud", "diario", "06:12", 2),
    ]
    for titulo, area, freq, horario, dur in PDF_HABITS:
        hid = gen_id("habi")
        qw("INSERT INTO gestionables (id,usuario_id,tipo,titulo,descripcion,area_id) VALUES (?,?,?,?,?,?)",
           (hid, uid, "habito", titulo, f"freq:{freq}", areas.get(area)))
        try:
            qw("INSERT INTO habitos (gestionable_id,frecuencia,horario,activo,racha,mejor_racha,duracion_min,estado_dia) VALUES (?,?,?,?,?,?,?,?)",
               (hid, freq, horario, 1, 0, 0, dur, "Pendiente"))
        except Exception:
            qw("INSERT INTO habitos (gestionable_id,frecuencia,horario,activo,racha,mejor_racha) VALUES (?,?,?,?,?,?)",
               (hid, freq, horario, 1, 0, 0))
    # demo proyecto
    pid = gen_id("proy")
    qw("INSERT INTO gestionables (id,usuario_id,tipo,titulo,descripcion,area_id) VALUES (?,?,?,?,?,?)",
       (pid, uid, "proyecto", "Lanzar portfolio", "Sitio personal", areas.get("Emprendimiento")))
    qw("INSERT INTO proyectos (gestionable_id,objetivo,progreso,deadline) VALUES (?,?,?,?)",
       (pid, "Publicar v1", 30, (date.today() + timedelta(days=30)).isoformat()))
    # demo evento
    eid = gen_id("even")
    qw("INSERT INTO gestionables (id,usuario_id,tipo,titulo,descripcion,area_id) VALUES (?,?,?,?,?,?)",
       (eid, uid, "evento", "Review semanal", "Revisión de prioridades", areas.get("Laboral")))
    qw("INSERT INTO eventos (gestionable_id,fecha_inicio,fecha_fin,ubicacion) VALUES (?,?,?,?)",
       (eid, datetime.now().isoformat()[:16], (datetime.now() + timedelta(hours=1)).isoformat()[:16], "Casa"))
    # formula default
    fid = gen_id("form")
    qw("INSERT INTO formula_prioridad (id,usuario_id,coef_u,coef_i,coef_e,coef_m) VALUES (?,?,?,?,?,?)",
       (fid, uid, 8, 5, 2, 1))


# ─── Auth helpers ───
def token_required(f):
    @wraps(f)
    def dec(*a, **k):
        tok = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not tok:
            return jsonify({"error": "Token requerido"}), 401
        try:
            data = jwt.decode(tok, SECRET_KEY, algorithms=["HS256"])
            g.user_id = data["user_id"]
            g.role = data["role"]
        except Exception:
            return jsonify({"error": "Token inválido"}), 401
        return f(*a, **k)
    return dec


def admin_required(f):
    @wraps(f)
    @token_required
    def dec(*a, **k):
        if g.role != "admin":
            return jsonify({"error": "Admin requerido"}), 403
        return f(*a, **k)
    return dec


def log_mov(uid, tipo, detalle, ref_id=None):
    mid = gen_move_id()
    # ensure unique
    for _ in range(5):
        try:
            qw("INSERT INTO movimientos (id,usuario_id,tipo,detalle,ref_id) VALUES (?,?,?,?,?)",
               (mid, uid, tipo, detalle, ref_id))
            break
        except Exception:
            mid = gen_move_id()
    return mid


def get_formula(uid):
    f = q("SELECT * FROM formula_prioridad WHERE usuario_id=?", (uid,), one=True)
    if not f:
        return DEFAULT_FORMULA
    return {"u": f["coef_u"], "i": f["coef_i"], "e": f["coef_e"], "m": f["coef_m"]}


def calc_p(t, formula=None):
    f = formula or DEFAULT_FORMULA
    return f["u"] * (t.get("urgencia") or 5) + f["i"] * (t.get("impacto") or 5) - f["e"] * (t.get("esfuerzo") or 5) - f["m"] * (t.get("miedo") or 3)


# ─── AUTH ───
@app.route("/api/auth/register", methods=["POST"])
def register():
    d = request.json or {}
    email = (d.get("email") or "").strip().lower()
    password = d.get("password") or ""
    nombre = d.get("nombre") or email.split("@")[0]
    if not email or len(password) < 6:
        return jsonify({"error": "Email y password (>=6)"}), 400
    h = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    uid = gen_id("usua")
    try:
        qw("INSERT INTO usuarios (id,email,password_hash,nombre,role) VALUES (?,?,?,?,?)",
           (uid, email, h, nombre, "user"))
        fid = gen_id("form")
        qw("INSERT INTO formula_prioridad (id,usuario_id,coef_u,coef_i,coef_e,coef_m) VALUES (?,?,8,5,2,1)", (fid, uid))
        return jsonify({"id": uid}), 201
    except Exception as e:
        return jsonify({"error": "Email existe", "d": str(e)}), 409


@app.route("/api/auth/login", methods=["POST"])
def login():
    d = request.json or {}
    row = q("SELECT * FROM usuarios WHERE email=?", ((d.get("email") or "").strip().lower(),), one=True)
    if not row or not bcrypt.checkpw((d.get("password") or "").encode(), row["password_hash"].encode()):
        return jsonify({"error": "Credenciales inválidas"}), 401
    tok = jwt.encode(
        {"user_id": row["id"], "role": row["role"], "exp": datetime.utcnow() + timedelta(hours=TOKEN_HOURS)},
        SECRET_KEY, algorithm="HS256",
    )
    return jsonify({"token": tok, "user": {"id": row["id"], "email": row["email"], "nombre": row["nombre"], "role": row["role"]}})


@app.route("/api/auth/me", methods=["GET"])
@token_required
def me():
    return jsonify(q("SELECT id,email,nombre,role,created_at FROM usuarios WHERE id=?", (g.user_id,), one=True) or {})


# ─── AREAS (globales) ───
@app.route("/api/areas", methods=["GET"])
@token_required
def list_areas():
    return jsonify(q("SELECT * FROM areas ORDER BY nombre"))


# ─── FORMULA ───
@app.route("/api/formula", methods=["GET"])
@token_required
def get_formula_api():
    f = get_formula(g.user_id)
    return jsonify({"coef_u": f["u"], "coef_i": f["i"], "coef_e": f["e"], "coef_m": f["m"],
                    "texto": f"P = {f['u']}×U + {f['i']}×I − {f['e']}×E − {f['m']}×M"})


@app.route("/api/formula", methods=["POST"])
@token_required
def set_formula():
    d = request.json or {}
    existing = q("SELECT id FROM formula_prioridad WHERE usuario_id=?", (g.user_id,), one=True)
    vals = (float(d.get("coef_u", 8)), float(d.get("coef_i", 5)), float(d.get("coef_e", 2)), float(d.get("coef_m", 1)))
    if existing:
        qw("UPDATE formula_prioridad SET coef_u=?,coef_i=?,coef_e=?,coef_m=? WHERE usuario_id=?",
           (*vals, g.user_id))
    else:
        qw("INSERT INTO formula_prioridad (id,usuario_id,coef_u,coef_i,coef_e,coef_m) VALUES (?,?,?,?,?,?)",
           (gen_id("form"), g.user_id, *vals))
    return jsonify({"ok": True})


# ─── TAREAS / MATRIZ / KANBAN ───
def fetch_tareas(uid):
    rows = q("""SELECT g.id, g.titulo, g.descripcion, g.area_id, g.created_at, g.updated_at,
                       t.estado, t.impacto, t.esfuerzo, t.miedo, t.urgencia, t.fecha_inicio, t.fecha_fin, t.prerequisito_id,
                       a.nombre as area_nombre, a.cod_color as area_color
                FROM gestionables g
                JOIN tareas t ON g.id = t.gestionable_id
                LEFT JOIN areas a ON g.area_id = a.id
                WHERE g.usuario_id=? AND g.tipo='tarea'""", (uid,))
    f = get_formula(uid)
    for r in rows:
        r["prioridad"] = calc_p(r, f)
    rows.sort(key=lambda x: x["prioridad"], reverse=True)
    return rows


@app.route("/api/matriz", methods=["GET"])
@token_required
def matriz():
    items = [x for x in fetch_tareas(g.user_id) if x.get("estado") not in ("Cancelado", "Eliminado")]
    for i, it in enumerate(items, 1):
        it["rank"] = i
    f = get_formula(g.user_id)
    return jsonify({
        "formula": f"P = {f['u']}×U + {f['i']}×I − {f['e']}×E − {f['m']}×M",
        "coefs": f,
        "items": items,
    })


@app.route("/api/tareas", methods=["GET"])
@token_required
def list_tareas():
    return jsonify(fetch_tareas(g.user_id))


@app.route("/api/tareas", methods=["POST"])
@token_required
def create_tarea():
    d = request.json or {}
    gid = gen_id("tare")
    qw("INSERT INTO gestionables (id,usuario_id,tipo,titulo,descripcion,area_id) VALUES (?,?,?,?,?,?)",
       (gid, g.user_id, "tarea", d.get("titulo") or "Sin título", d.get("descripcion", ""), d.get("area_id")))
    qw("INSERT INTO tareas (gestionable_id,estado,impacto,esfuerzo,miedo,urgencia,fecha_inicio,fecha_fin,prerequisito_id) VALUES (?,?,?,?,?,?,?,?,?)",
       (gid, d.get("estado", "Backlog"), int(d.get("impacto", 5)), int(d.get("esfuerzo", 5)),
        int(d.get("miedo", 3)), int(d.get("urgencia", 5)), d.get("fecha_inicio"), d.get("fecha_fin"), d.get("prerequisito_id")))
    log_mov(g.user_id, "create", f"Tarea: {d.get('titulo')}", gid)
    return jsonify({"id": gid}), 201


@app.route("/api/tareas/<tid>", methods=["PATCH"])
@token_required
def update_tarea(tid):
    d = request.json or {}
    row = q("SELECT g.*, t.estado FROM gestionables g JOIN tareas t ON g.id=t.gestionable_id WHERE g.id=? AND g.usuario_id=?",
            (tid, g.user_id), one=True)
    if not row:
        return jsonify({"error": "No encontrada"}), 404
    if "titulo" in d or "descripcion" in d or "area_id" in d:
        qw("UPDATE gestionables SET titulo=COALESCE(?,titulo), descripcion=COALESCE(?,descripcion), area_id=COALESCE(?,area_id), updated_at="+
           ("NOW()" if USE_PG else "CURRENT_TIMESTAMP")+" WHERE id=?",
           (d.get("titulo"), d.get("descripcion"), d.get("area_id"), tid))
    fields = []
    vals = []
    for k in ("estado", "impacto", "esfuerzo", "miedo", "urgencia", "fecha_inicio", "fecha_fin", "prerequisito_id"):
        if k in d:
            fields.append(f"{k}=?")
            vals.append(d[k])
    if fields:
        vals.append(tid)
        qw(f"UPDATE tareas SET {','.join(fields)} WHERE gestionable_id=?", tuple(vals))
    if "estado" in d and d["estado"] != row.get("estado"):
        log_mov(g.user_id, "move", f"{row['titulo']}: {row.get('estado')} → {d['estado']}", tid)
    else:
        log_mov(g.user_id, "edit", f"Editada: {d.get('titulo', row['titulo'])}", tid)
    return jsonify({"ok": True})


@app.route("/api/tareas/<tid>", methods=["DELETE"])
@token_required
def delete_tarea(tid):
    qw("DELETE FROM tareas WHERE gestionable_id=?", (tid,))
    qw("DELETE FROM gestionables WHERE id=? AND usuario_id=?", (tid, g.user_id))
    log_mov(g.user_id, "delete", f"Tarea {tid}", tid)
    return jsonify({"ok": True})


@app.route("/api/kanban", methods=["GET"])
@token_required
def kanban():
    rows = fetch_tareas(g.user_id)
    board = {e: [] for e in KANBAN_COLS}
    for r in rows:
        st = r.get("estado") or "Backlog"
        if st == "Eliminado":
            continue
        # bloqueo backlog si prerequisito no completado
        r["bloqueada"] = False
        if r.get("prerequisito_id"):
            pre = q("SELECT estado FROM tareas WHERE gestionable_id=?", (r["prerequisito_id"],), one=True)
            if not pre or pre.get("estado") != "Completado":
                r["bloqueada"] = True
        if st in board:
            board[st].append(r)
    return jsonify({"estados": KANBAN_COLS, "board": board})


def _do_move(tid, estado):
    row = q("SELECT g.titulo, t.estado, t.prerequisito_id FROM gestionables g JOIN tareas t ON g.id=t.gestionable_id WHERE g.id=? AND g.usuario_id=?",
            (tid, g.user_id), one=True)
    if not row:
        return jsonify({"error": "No encontrada"}), 404
    if estado not in ESTADOS:
        return jsonify({"error": "Estado inválido"}), 400
    if estado == "Backlog" and row.get("prerequisito_id"):
        pre = q("SELECT estado FROM tareas WHERE gestionable_id=?", (row["prerequisito_id"],), one=True)
        if not pre or pre.get("estado") != "Completado":
            return jsonify({"error": "Prerequisito no completado: no puede pasar a Backlog"}), 400
    qw("UPDATE tareas SET estado=? WHERE gestionable_id=?", (estado, tid))
    mid = log_mov(g.user_id, "move", f"{row['titulo']}: {row.get('estado')} → {estado}", tid)
    # sync burndown if Completado
    if estado == "Completado":
        cfg = q("SELECT * FROM burndown_config WHERE usuario_id=?", (g.user_id,), one=True)
        if cfg and cfg.get("tareas_json"):
            try:
                data = json.loads(cfg["tareas_json"])
                comp = set(data.get("completadas") or [])
                comp.add(tid)
                data["completadas"] = list(comp)
                data["no_completadas"] = [i for i in (data.get("todas") or []) if i not in comp]
                total = len(data.get("todas") or []) or 1
                pct = round(100 * len(comp) / total, 1)
                qw("UPDATE burndown_config SET tareas_json=?, pct_cumplimiento=? WHERE usuario_id=?",
                   (json.dumps(data), pct, g.user_id))
            except Exception:
                pass
    return jsonify({"ok": True, "move_id": mid})


# fix duplicate - redefine properly
@app.route("/api/kanban/move", methods=["POST"])
@token_required
def kanban_move():
    d = request.json or {}
    return _do_move(d.get("tarea_id"), d.get("estado"))


# ─── BURNDOWN ───

def _ensure_weekly_burndown(uid):
    """Lunes 00:00 → Sábado 20:00. Tareas en estado Pendiente. Peso = prioridad calculada."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    saturday = monday + timedelta(days=5)
    cfg = q("SELECT * FROM burndown_config WHERE usuario_id=?", (uid,), one=True)
    need = True
    if cfg and cfg.get("fecha_inicio"):
        if str(cfg["fecha_inicio"])[:10] == monday.isoformat():
            need = False
    tasks = fetch_tareas(uid)
    pendientes = [x for x in tasks if x.get("estado") == "Pendiente"]
    formula = get_formula(uid)
    ids = [x["id"] for x in pendientes]
    pesos = {x["id"]: calc_p(x, formula) for x in pendientes}
    total_peso = sum(pesos.values()) or 0
    if need:
        payload = json.dumps({
            "todas": ids, "completadas": [], "no_completadas": ids,
            "pesos": pesos, "total_peso": total_peso,
            "hora_fin": "20:00", "auto_semana": True,
        })
        if cfg:
            qw("UPDATE burndown_config SET fecha_inicio=?,fecha_fin=?,total_tareas=?,pct_cumplimiento=?,tareas_json=? WHERE usuario_id=?",
               (monday.isoformat(), saturday.isoformat(), len(ids), 0, payload, uid))
        else:
            qw("INSERT INTO burndown_config (id,usuario_id,fecha_inicio,fecha_fin,total_tareas,pct_cumplimiento,tareas_json) VALUES (?,?,?,?,?,?,?)",
               (gen_id("burn"), uid, monday.isoformat(), saturday.isoformat(), len(ids), 0, payload))
    return q("SELECT * FROM burndown_config WHERE usuario_id=?", (uid,), one=True)


@app.route("/api/burndown", methods=["GET"])
@token_required
def get_burndown():
    cfg = _ensure_weekly_burndown(g.user_id)
    tasks = fetch_tareas(g.user_id)
    formula = get_formula(g.user_id)
    data = {}
    if cfg and cfg.get("tareas_json"):
        try:
            data = json.loads(cfg["tareas_json"])
        except Exception:
            data = {}
    # refresh pending weights from current Pendiente + already completed in sprint list
    todas_ids = list(data.get("todas") or [])
    # include current pendientes not in list
    for x in tasks:
        if x.get("estado") == "Pendiente" and x["id"] not in todas_ids:
            todas_ids.append(x["id"])
    pesos = {}
    for tid in todas_ids:
        tr = next((x for x in tasks if x["id"] == tid), None)
        if tr:
            pesos[tid] = calc_p(tr, formula)
        else:
            pesos[tid] = (data.get("pesos") or {}).get(tid, 1)
    completadas = []
    for tid in todas_ids:
        tr = next((x for x in tasks if x["id"] == tid), None)
        if tr and tr.get("estado") == "Completado":
            completadas.append(tid)
        elif tid in (data.get("completadas") or []):
            if not tr or tr.get("estado") == "Completado":
                completadas.append(tid)
    no_comp = [i for i in todas_ids if i not in completadas]
    total_peso = sum(pesos.values()) or 1
    peso_done = sum(pesos.get(i, 0) for i in completadas)
    pct = round(100 * peso_done / total_peso, 1)
    # ideal line Mon-Sat
    monday = date.today() - timedelta(days=date.today().weekday())
    labels, ideal, remaining = [], [], []
    # remaining weight over days from moves
    moves = q("""SELECT created_at, ref_id FROM movimientos
                 WHERE usuario_id=? AND tipo='move' AND detalle LIKE '%Completado%'
                 ORDER BY created_at""", (g.user_id,))
    # build daily remaining from start total_peso
    day_done = {}
    for m in (moves or []):
        d0 = str(m.get("created_at") or "")[:10]
        rid = m.get("ref_id")
        if rid in pesos:
            day_done[d0] = day_done.get(d0, 0) + pesos[rid]
    rem = total_peso
    for i in range(6):  # Mon-Sat
        d0 = (monday + timedelta(days=i)).isoformat()
        labels.append(d0)
        ideal.append(round(total_peso * (1 - (i + 1) / 6), 1))
        rem = rem - day_done.get(d0, 0)
        remaining.append(max(0, round(rem, 1)))
    items = []
    for tid in todas_ids:
        tr = next((x for x in tasks if x["id"] == tid), None)
        items.append({
            "id": tid,
            "titulo": tr["titulo"] if tr else tid,
            "peso": pesos.get(tid, 0),
            "estado": tr.get("estado") if tr else "?",
            "done": tid in completadas,
        })
    return jsonify({
        "config": cfg,
        "fecha_inicio": str(cfg["fecha_inicio"])[:10] if cfg else None,
        "fecha_fin": str(cfg["fecha_fin"])[:10] if cfg else None,
        "hora_fin": "20:00",
        "total_tareas": len(todas_ids),
        "total_peso": round(total_peso, 1),
        "peso_completado": round(peso_done, 1),
        "pct": pct,
        "labels": labels,
        "ideal": ideal,
        "remaining": remaining,
        "items": items,
    })


@app.route("/api/burndown", methods=["POST"])
@token_required
def set_burndown():
    d = request.json or {}
    fi, ff = d.get("fecha_inicio"), d.get("fecha_fin")
    data = get_burndown()
    # re-fetch without recursive issues
    tasks = fetch_tareas(g.user_id)
    ids = [t["id"] for t in tasks if t.get("estado") in ("Pendiente", "En curso", "Backlog", "Pausado", "Completado")]
    done_ids = [t["id"] for t in tasks if t.get("estado") == "Completado"]
    total = len(ids)
    pct = round(100 * len(done_ids) / total, 1) if total else 0
    payload = json.dumps({"todas": ids, "completadas": done_ids, "no_completadas": [i for i in ids if i not in done_ids]})
    existing = q("SELECT id FROM burndown_config WHERE usuario_id=?", (g.user_id,), one=True)
    if existing:
        qw("UPDATE burndown_config SET fecha_inicio=?,fecha_fin=?,total_tareas=?,pct_cumplimiento=?,tareas_json=? WHERE usuario_id=?",
           (fi, ff, total, pct, payload, g.user_id))
    else:
        qw("INSERT INTO burndown_config (id,usuario_id,fecha_inicio,fecha_fin,total_tareas,pct_cumplimiento,tareas_json) VALUES (?,?,?,?,?,?,?)",
           (gen_id("burn"), g.user_id, fi, ff, total, pct, payload))
    return jsonify({"ok": True, "pct": pct, "total": total})


# ─── HÁBITOS ───
@app.route("/api/habitos", methods=["GET"])
@token_required
def list_habitos():
    rows = q("""SELECT g.id, g.titulo, g.descripcion, g.area_id, a.nombre as area_nombre, a.cod_color as area_color,
                       h.frecuencia, h.horario, h.activo, h.racha, h.mejor_racha, h.duracion_min, h.estado_dia, g.created_at
                FROM gestionables g JOIN habitos h ON g.id=h.gestionable_id
                LEFT JOIN areas a ON g.area_id=a.id
                WHERE g.usuario_id=? AND g.tipo='habito' ORDER BY a.nombre, g.titulo""", (g.user_id,))
    today = date.today().isoformat()
    month_start = date.today().replace(day=1).isoformat()
    for h in rows:
        logs = q("SELECT fecha FROM habito_logs WHERE habito_id=? AND usuario_id=? AND fecha>=?",
                 (h["id"], g.user_id, month_start))
        h["logs_mes"] = [str(x["fecha"])[:10] for x in logs]
        h["hecho_hoy"] = today in h["logs_mes"]
    # group by area
    by_area = {}
    for h in rows:
        key = h.get("area_nombre") or "Sin área"
        by_area.setdefault(key, {"color": h.get("area_color"), "items": []})
        by_area[key]["items"].append(h)
    return jsonify({"lista": rows, "por_area": by_area})


@app.route("/api/habitos", methods=["POST"])
@token_required
def create_habito():
    d = request.json or {}
    gid = gen_id("habi")
    qw("INSERT INTO gestionables (id,usuario_id,tipo,titulo,descripcion,area_id) VALUES (?,?,?,?,?,?)",
       (gid, g.user_id, "habito", d.get("titulo") or "Hábito", d.get("descripcion", ""), d.get("area_id")))
    try:
        qw("INSERT INTO habitos (gestionable_id,frecuencia,horario,activo,racha,mejor_racha,duracion_min,estado_dia) VALUES (?,?,?,?,?,?,?,?)",
           (gid, d.get("frecuencia", "diario"), d.get("horario", "07:00"), int(d.get("activo", 1)), 0, 0, int(d.get("duracion_min", 10)), "Pendiente"))
    except Exception:
        qw("INSERT INTO habitos (gestionable_id,frecuencia,horario,activo,racha,mejor_racha) VALUES (?,?,?,?,?,?)",
           (gid, d.get("frecuencia", "diario"), d.get("horario", "07:00"), int(d.get("activo", 1)), 0, 0))
    log_mov(g.user_id, "create", f"Hábito: {d.get('titulo')}", gid)
    return jsonify({"id": gid}), 201


@app.route("/api/habitos/<hid>", methods=["PATCH"])
@token_required
def update_habito(hid):
    d = request.json or {}
    if any(k in d for k in ("titulo", "descripcion", "area_id")):
        qw("UPDATE gestionables SET titulo=COALESCE(?,titulo), descripcion=COALESCE(?,descripcion), area_id=COALESCE(?,area_id) WHERE id=? AND usuario_id=?",
           (d.get("titulo"), d.get("descripcion"), d.get("area_id"), hid, g.user_id))
    for k in ("frecuencia", "horario", "activo"):
        if k in d:
            qw(f"UPDATE habitos SET {k}=? WHERE gestionable_id=?", (d[k], hid))
    return jsonify({"ok": True})


@app.route("/api/habitos/<hid>/check", methods=["POST"])
@token_required
def check_habito(hid):
    h = q("SELECT h.*, g.titulo FROM habitos h JOIN gestionables g ON h.gestionable_id=g.id WHERE g.id=? AND g.usuario_id=?",
          (hid, g.user_id), one=True)
    if not h:
        return jsonify({"error": "No encontrado"}), 404
    today = date.today().isoformat()
    exists = q("SELECT id FROM habito_logs WHERE habito_id=? AND usuario_id=? AND fecha=?", (hid, g.user_id, today), one=True)
    if exists:
        return jsonify({"error": "Ya marcado hoy"}), 409
    lid = gen_id("habi")
    qw("INSERT INTO habito_logs (id,habito_id,usuario_id,fecha) VALUES (?,?,?,?)", (lid, hid, g.user_id, today))
    racha = (h.get("racha") or 0) + 1
    mejor = max(racha, h.get("mejor_racha") or 0)
    qw("UPDATE habitos SET racha=?, mejor_racha=? WHERE gestionable_id=?", (racha, mejor, hid))
    log_mov(g.user_id, "habito_check", f"{h['titulo']} racha {racha}", hid)
    return jsonify({"racha": racha, "mejor_racha": mejor})


@app.route("/api/habitos/<hid>", methods=["DELETE"])
@token_required
def del_habito(hid):
    qw("DELETE FROM habito_logs WHERE habito_id=?", (hid,))
    qw("DELETE FROM habitos WHERE gestionable_id=?", (hid,))
    qw("DELETE FROM gestionables WHERE id=? AND usuario_id=?", (hid, g.user_id))
    return jsonify({"ok": True})


# ─── PROYECTOS (subtareas = tareas reales) ───
@app.route("/api/proyectos", methods=["GET"])
@token_required
def list_proyectos():
    projs = q("""SELECT g.id, g.titulo, g.descripcion, g.area_id, a.nombre as area_nombre, a.cod_color as area_color,
                        p.objetivo, p.progreso, p.deadline, g.created_at
                 FROM gestionables g JOIN proyectos p ON g.id=p.gestionable_id
                 LEFT JOIN areas a ON g.area_id=a.id
                 WHERE g.usuario_id=? AND g.tipo='proyecto'""", (g.user_id,))
    for p in projs:
        links = q("SELECT tarea_id FROM proyecto_tareas WHERE proyecto_id=?", (p["id"],))
        tareas = []
        for l in links:
            t = q("""SELECT g.id, g.titulo, t.estado, t.impacto, t.esfuerzo, t.miedo, t.urgencia
                     FROM gestionables g JOIN tareas t ON g.id=t.gestionable_id WHERE g.id=?""", (l["tarea_id"],), one=True)
            if t:
                t["prioridad"] = calc_p(t, get_formula(g.user_id))
                tareas.append(t)
        p["tareas"] = tareas
        if tareas:
            done = sum(1 for t in tareas if t.get("estado") == "Completado")
            p["progreso"] = round(100 * done / len(tareas), 1)
    return jsonify(projs)


@app.route("/api/proyectos", methods=["POST"])
@token_required
def create_proyecto():
    d = request.json or {}
    gid = gen_id("proy")
    qw("INSERT INTO gestionables (id,usuario_id,tipo,titulo,descripcion,area_id) VALUES (?,?,?,?,?,?)",
       (gid, g.user_id, "proyecto", d.get("titulo") or "Proyecto", d.get("descripcion", ""), d.get("area_id")))
    qw("INSERT INTO proyectos (gestionable_id,objetivo,progreso,deadline) VALUES (?,?,?,?)",
       (gid, d.get("objetivo", ""), 0, d.get("deadline")))
    log_mov(g.user_id, "create", f"Proyecto: {d.get('titulo')}", gid)
    return jsonify({"id": gid}), 201


@app.route("/api/proyectos/<pid>/tareas", methods=["POST"])
@token_required
def add_proyecto_tarea(pid):
    """Crea una TAREA real y la vincula al proyecto.
    Prerequisito por defecto = tarea anterior del proyecto (salvo sin_prereq o lista)."""
    p = q("SELECT id FROM gestionables WHERE id=? AND usuario_id=? AND tipo='proyecto'", (pid, g.user_id), one=True)
    if not p:
        return jsonify({"error": "Proyecto no encontrado"}), 404
    d = request.json or {}
    tid = gen_id("tare")
    # default prereq: last task in this project
    prereq = d.get("prerequisito_id")
    if d.get("sin_prerequisito"):
        prereq = None
    elif d.get("prerequisitos"):  # multiple: store first as main, rest ignored for now or join
        plist = d["prerequisitos"]
        prereq = plist[0] if plist else None
    elif prereq is None:
        prev = q("SELECT tarea_id FROM proyecto_tareas WHERE proyecto_id=? ORDER BY id DESC LIMIT 1", (pid,), one=True)
        if prev:
            prereq = prev["tarea_id"]
    qw("INSERT INTO gestionables (id,usuario_id,tipo,titulo,descripcion,area_id) VALUES (?,?,?,?,?,?)",
       (tid, g.user_id, "tarea", d.get("titulo") or "Subtarea", d.get("descripcion", ""), d.get("area_id")))
    try:
        qw("INSERT INTO tareas (gestionable_id,estado,impacto,esfuerzo,miedo,urgencia,fecha_inicio,fecha_fin,prerequisito_id) VALUES (?,?,?,?,?,?,?,?,?)",
           (tid, d.get("estado", "Pendiente"), int(d.get("impacto", 5)), int(d.get("esfuerzo", 5)),
            int(d.get("miedo", 3)), int(d.get("urgencia", 5)), d.get("fecha_inicio"), d.get("fecha_fin"), prereq))
    except Exception:
        qw("INSERT INTO tareas (gestionable_id,estado,impacto,esfuerzo,miedo,urgencia,fecha_inicio,fecha_fin) VALUES (?,?,?,?,?,?,?,?)",
           (tid, d.get("estado", "Pendiente"), int(d.get("impacto", 5)), int(d.get("esfuerzo", 5)),
            int(d.get("miedo", 3)), int(d.get("urgencia", 5)), d.get("fecha_inicio"), d.get("fecha_fin")))
    link = gen_id("prta")
    qw("INSERT INTO proyecto_tareas (id,proyecto_id,tarea_id) VALUES (?,?,?)", (link, pid, tid))
    log_mov(g.user_id, "create", f"Subtarea proyecto: {d.get('titulo')}", tid)
    return jsonify({"id": tid, "prerequisito_id": prereq}), 201


@app.route("/api/proyectos/<pid>", methods=["PATCH"])
@token_required
def update_proyecto(pid):
    d = request.json or {}
    if any(k in d for k in ("titulo", "descripcion", "area_id")):
        qw("UPDATE gestionables SET titulo=COALESCE(?,titulo), descripcion=COALESCE(?,descripcion), area_id=COALESCE(?,area_id) WHERE id=? AND usuario_id=?",
           (d.get("titulo"), d.get("descripcion"), d.get("area_id"), pid, g.user_id))
    for k in ("objetivo", "deadline", "progreso"):
        if k in d:
            qw(f"UPDATE proyectos SET {k}=? WHERE gestionable_id=?", (d[k], pid))
    return jsonify({"ok": True})


@app.route("/api/proyectos/<pid>", methods=["DELETE"])
@token_required
def del_proyecto(pid):
    qw("DELETE FROM proyecto_tareas WHERE proyecto_id=?", (pid,))
    qw("DELETE FROM proyectos WHERE gestionable_id=?", (pid,))
    qw("DELETE FROM gestionables WHERE id=? AND usuario_id=?", (pid, g.user_id))
    return jsonify({"ok": True})


# ─── EVENTOS ───
@app.route("/api/eventos", methods=["GET"])
@token_required
def list_eventos():
    return jsonify(q("""SELECT g.id, g.titulo, g.descripcion, g.area_id, a.nombre as area_nombre, a.cod_color as area_color,
                               e.fecha_inicio, e.fecha_fin, e.ubicacion
                        FROM gestionables g JOIN eventos e ON g.id=e.gestionable_id
                        LEFT JOIN areas a ON g.area_id=a.id
                        WHERE g.usuario_id=? AND g.tipo='evento' ORDER BY e.fecha_inicio""", (g.user_id,)))


@app.route("/api/eventos", methods=["POST"])
@token_required
def create_evento():
    d = request.json or {}
    gid = gen_id("even")
    qw("INSERT INTO gestionables (id,usuario_id,tipo,titulo,descripcion,area_id) VALUES (?,?,?,?,?,?)",
       (gid, g.user_id, "evento", d.get("titulo") or "Evento", d.get("descripcion", ""), d.get("area_id")))
    qw("INSERT INTO eventos (gestionable_id,fecha_inicio,fecha_fin,ubicacion) VALUES (?,?,?,?)",
       (gid, d.get("fecha_inicio"), d.get("fecha_fin"), d.get("ubicacion", "")))
    log_mov(g.user_id, "create", f"Evento: {d.get('titulo')}", gid)
    return jsonify({"id": gid}), 201


@app.route("/api/eventos/<eid>", methods=["PATCH"])
@token_required
def update_evento(eid):
    d = request.json or {}
    if any(k in d for k in ("titulo", "descripcion", "area_id")):
        qw("UPDATE gestionables SET titulo=COALESCE(?,titulo), descripcion=COALESCE(?,descripcion), area_id=COALESCE(?,area_id) WHERE id=? AND usuario_id=?",
           (d.get("titulo"), d.get("descripcion"), d.get("area_id"), eid, g.user_id))
    for k in ("fecha_inicio", "fecha_fin", "ubicacion"):
        if k in d:
            qw(f"UPDATE eventos SET {k}=? WHERE gestionable_id=?", (d[k], eid))
    return jsonify({"ok": True})


@app.route("/api/eventos/<eid>", methods=["DELETE"])
@token_required
def del_evento(eid):
    qw("DELETE FROM eventos WHERE gestionable_id=?", (eid,))
    qw("DELETE FROM gestionables WHERE id=? AND usuario_id=?", (eid, g.user_id))
    return jsonify({"ok": True})


@app.route("/api/calendario", methods=["GET"])
@token_required
def calendario():
    """Mensual: fechas con eventos resaltadas"""
    month = request.args.get("month")  # YYYY-MM
    if not month:
        month = date.today().strftime("%Y-%m")
    evs = q("""SELECT g.id, g.titulo, e.fecha_inicio, e.fecha_fin, e.ubicacion, 'evento' as tipo
               FROM gestionables g JOIN eventos e ON g.id=e.gestionable_id
               WHERE g.usuario_id=? AND CAST(e.fecha_inicio AS TEXT) LIKE ?""",
            (g.user_id, month + "%"))
    # also deadlines
    pros = q("""SELECT g.id, g.titulo, p.deadline as fecha_inicio, NULL as fecha_fin, '' as ubicacion, 'deadline' as tipo
                FROM gestionables g JOIN proyectos p ON g.id=p.gestionable_id
                WHERE g.usuario_id=? AND CAST(p.deadline AS TEXT) LIKE ?""",
             (g.user_id, month + "%"))
    items = []
    days = set()
    for x in (evs or []) + (pros or []):
        f = str(x.get("fecha_inicio") or "")[:10]
        if f:
            days.add(f)
            x["fecha"] = f
            items.append(x)
    return jsonify({"month": month, "days": sorted(days), "items": items})


# ─── HOY / STATS ───
@app.route("/api/hoy", methods=["GET"])
@token_required
def stats_hoy():
    today = date.today().isoformat()
    moves = q("""SELECT created_at FROM movimientos
                 WHERE usuario_id=? AND tipo='move' AND detalle LIKE '%Completado%'
                 AND CAST(created_at AS TEXT) LIKE ?""", (g.user_id, today + "%"))
    hoy = len(moves or [])
    series = q("""SELECT SUBSTR(CAST(created_at AS TEXT),1,10) as d, COUNT(*) as c
                  FROM movimientos
                  WHERE usuario_id=? AND tipo='move' AND detalle LIKE '%Completado%'
                  GROUP BY SUBSTR(CAST(created_at AS TEXT),1,10) ORDER BY d""", (g.user_id,))
    vals = [s["c"] for s in (series or [])]
    avg = round(sum(vals) / len(vals), 1) if vals else 0
    tareas = fetch_tareas(g.user_id)
    # esfuerzo total de completadas hoy (aprox: tareas en Completado)
    completadas = [t for t in tareas if t.get("estado") == "Completado"]
    esfuerzo_total = sum(int(t.get("esfuerzo") or 0) for t in completadas)
    # por area
    por_area = {}
    for t in completadas:
        a = t.get("area_nombre") or "Sin área"
        por_area[a] = por_area.get(a, 0) + 1
    # por estado
    por_estado = {}
    for t in tareas:
        st = t.get("estado") or "Backlog"
        por_estado[st] = por_estado.get(st, 0) + 1
    # proyectos progreso
    projs = q("""SELECT g.titulo, p.progreso, p.deadline FROM gestionables g
                 JOIN proyectos p ON g.id=p.gestionable_id WHERE g.usuario_id=?""", (g.user_id,))
    # habitos rachas
    habs = q("""SELECT g.titulo, h.racha, h.mejor_racha FROM gestionables g
                JOIN habitos h ON g.id=h.gestionable_id WHERE g.usuario_id=? ORDER BY h.racha DESC""", (g.user_id,))
    return jsonify({
        "hoy": hoy, "promedio": avg, "serie": series or [],
        "esfuerzo_total": esfuerzo_total,
        "por_area": [{"area": k, "c": v} for k, v in por_area.items()],
        "por_estado": [{"estado": k, "c": v} for k, v in por_estado.items()],
        "proyectos": projs or [],
        "habitos_rachas": habs or [],
    })


# ─── ADMIN ───
@app.route("/api/admin/tables", methods=["GET"])
@admin_required
def admin_tables():
    return jsonify(["usuarios", "areas", "gestionables", "tareas", "habitos", "habito_logs",
                    "proyectos", "proyecto_tareas", "eventos", "movimientos", "burndown_config", "formula_prioridad"])


@app.route("/api/admin/table/<tabla>", methods=["GET"])
@admin_required
def admin_table(tabla):
    allowed = ["usuarios", "areas", "gestionables", "tareas", "habitos", "habito_logs",
               "proyectos", "proyecto_tareas", "eventos", "movimientos", "burndown_config", "formula_prioridad", "logs_entidad"]
    if tabla not in allowed:
        return jsonify({"error": "No permitida"}), 400
    rows = q(f"SELECT * FROM {tabla} LIMIT 300")
    cols = list(rows[0].keys()) if rows else []
    return jsonify({"tabla": tabla, "columns": cols, "rows": rows})


@app.route("/api/admin/table/<tabla>/<rid>", methods=["DELETE"])
@admin_required
def admin_del(tabla, rid):
    allowed = ["areas", "gestionables", "tareas", "habitos", "eventos", "movimientos", "proyectos"]
    if tabla not in allowed:
        return jsonify({"error": "No"}), 400
    qw(f"DELETE FROM {tabla} WHERE id=?", (rid,))
    return jsonify({"ok": True})


@app.route("/api/admin/users", methods=["GET"])
@admin_required
def admin_users():
    return jsonify(q("SELECT id,email,nombre,role,created_at FROM usuarios"))


@app.route("/api/admin/movimientos", methods=["GET"])
@admin_required
def admin_movs():
    return jsonify(q("""SELECT m.*, u.email FROM movimientos m LEFT JOIN usuarios u ON m.usuario_id=u.id
                        ORDER BY m.created_at DESC LIMIT 200"""))



# ─── SOFT DELETE / RESET DIARIO / CONVERT ───
@app.route("/api/tareas/<tid>/eliminar", methods=["POST"])
@token_required
def soft_delete_tarea(tid):
    row = q("SELECT g.titulo FROM gestionables g JOIN tareas t ON g.id=t.gestionable_id WHERE g.id=? AND g.usuario_id=?",
            (tid, g.user_id), one=True)
    if not row:
        return jsonify({"error": "No encontrada"}), 404
    qw("UPDATE tareas SET estado=? WHERE gestionable_id=?", ("Eliminado", tid))
    mid = log_mov(g.user_id, "soft_delete", f"Eliminada (soft): {row['titulo']}", tid)
    return jsonify({"ok": True, "move_id": mid})


@app.route("/api/reset-diario", methods=["POST"])
@token_required
def reset_diario():
    """Completado/Cancelado → quedan archivados (ya no en kanban).
    Pendiente → Backlog. Completado y Cancelado no se borran de BD."""
    # Pendiente → Backlog
    tareas = q("""SELECT t.gestionable_id, t.estado, g.titulo FROM tareas t
                  JOIN gestionables g ON g.id=t.gestionable_id
                  WHERE g.usuario_id=? AND t.estado IN ('Pendiente','Completado','Cancelado')""",
               (g.user_id,))
    n_back, n_arch = 0, 0
    for trow in tareas:
        if trow["estado"] == "Pendiente":
            qw("UPDATE tareas SET estado='Backlog' WHERE gestionable_id=?", (trow["gestionable_id"],))
            n_back += 1
        else:
            # Completado/Cancelado: ya fuera de kanban; marcar log archivo
            n_arch += 1
    log_mov(g.user_id, "reset_diario", f"Pendiente→Backlog:{n_back} archivados:{n_arch}")
    return jsonify({"ok": True, "pendiente_a_backlog": n_back, "archivados": n_arch})


@app.route("/api/gestionables/<gid>/convertir", methods=["POST"])
@token_required
def convertir_gestionable(gid):
    """Convierte un gestionable a otro tipo (tarea|habito|proyecto|evento)."""
    d = request.json or {}
    nuevo = d.get("tipo")
    if nuevo not in ("tarea", "habito", "proyecto", "evento"):
        return jsonify({"error": "tipo inválido"}), 400
    g0 = q("SELECT * FROM gestionables WHERE id=? AND usuario_id=?", (gid, g.user_id), one=True)
    if not g0:
        return jsonify({"error": "No encontrado"}), 404
    old = g0["tipo"]
    if old == nuevo:
        return jsonify({"ok": True, "id": gid})
    # remove old specific row
    table_map = {"tarea": "tareas", "habito": "habitos", "proyecto": "proyectos", "evento": "eventos", "actividad": "actividades"}
    if old in table_map:
        try:
            qw(f"DELETE FROM {table_map[old]} WHERE gestionable_id=?", (gid,))
        except Exception:
            pass
    qw("UPDATE gestionables SET tipo=? WHERE id=?", (nuevo, gid))
    if nuevo == "tarea":
        qw("INSERT INTO tareas (gestionable_id,estado,impacto,esfuerzo,miedo,urgencia) VALUES (?,?,?,?,?,?)",
           (gid, d.get("estado", "Backlog"), int(d.get("impacto", 5)), int(d.get("esfuerzo", 5)),
            int(d.get("miedo", 3)), int(d.get("urgencia", 5))))
    elif nuevo == "habito":
        qw("INSERT INTO habitos (gestionable_id,frecuencia,horario,activo,racha,mejor_racha) VALUES (?,?,?,?,?,?)",
           (gid, d.get("frecuencia", "diario"), d.get("horario", "07:00"), 1, 0, 0))
    elif nuevo == "proyecto":
        qw("INSERT INTO proyectos (gestionable_id,objetivo,progreso,deadline) VALUES (?,?,?,?)",
           (gid, d.get("objetivo", ""), 0, d.get("deadline")))
    elif nuevo == "evento":
        qw("INSERT INTO eventos (gestionable_id,fecha_inicio,fecha_fin,ubicacion) VALUES (?,?,?,?)",
           (gid, d.get("fecha_inicio"), d.get("fecha_fin"), d.get("ubicacion", "")))
    log_mov(g.user_id, "convert", f"{g0['titulo']}: {old} → {nuevo}", gid)
    return jsonify({"ok": True, "id": gid, "tipo": nuevo})




# ─── HOME + HÁBITOS KANBAN + RESET 6AM ───
@app.route("/api/home", methods=["GET"])
@token_required
def home_summary():
    tasks = fetch_tareas(g.user_id)
    pendientes = [x for x in tasks if x.get("estado") in ("Pendiente", "Backlog", "En curso")]
    pendientes = sorted(pendientes, key=lambda x: -x.get("prioridad", 0))[:12]
    # reset habits if needed
    _maybe_reset_habitos(g.user_id)
    habs = q("""SELECT g.id, g.titulo, g.area_id, a.nombre as area_nombre, a.cod_color as area_color,
                       h.frecuencia, h.horario, h.duracion_min, h.estado_dia, h.racha, h.mejor_racha
                FROM gestionables g JOIN habitos h ON g.id=h.gestionable_id
                LEFT JOIN areas a ON g.area_id=a.id
                WHERE g.usuario_id=? AND g.tipo='habito' AND h.activo=1""", (g.user_id,))
    hab_pend = [h for h in (habs or []) if (h.get("estado_dia") or "Pendiente") != "Completado"]
    return jsonify({
        "saludo": _saludo(),
        "tareas_pendientes": pendientes,
        "habitos_pendientes": hab_pend,
        "total_tareas": len(pendientes),
        "total_habitos_pend": len(hab_pend),
        "racha_max": max([h.get("racha") or 0 for h in (habs or [])], default=0),
    })


def _saludo():
    h = datetime.now().hour
    if h < 12:
        return "Buenos días. Un día productivo empieza ahora."
    if h < 18:
        return "Buenas tardes. Sigue el momentum."
    return "Buenas noches. Cierra el día con intención."


def _maybe_reset_habitos(uid):
    """A las 6am (o primer acceso del día) todos los hábitos activos → Pendiente."""
    today = date.today().isoformat()
    rows = q("SELECT gestionable_id, last_reset FROM habitos h JOIN gestionables g ON g.id=h.gestionable_id WHERE g.usuario_id=?", (uid,))
    for r in (rows or []):
        lr = str(r.get("last_reset") or "")[:10]
        if lr != today:
            try:
                qw("UPDATE habitos SET estado_dia='Pendiente', last_reset=? WHERE gestionable_id=?", (today, r["gestionable_id"]))
            except Exception:
                qw("UPDATE habitos SET estado_dia='Pendiente' WHERE gestionable_id=?", (r["gestionable_id"],))


@app.route("/api/habitos/kanban", methods=["GET"])
@token_required
def habitos_kanban():
    _maybe_reset_habitos(g.user_id)
    rows = q("""SELECT g.id, g.titulo, g.descripcion, g.area_id, a.nombre as area_nombre, a.cod_color as area_color,
                       h.frecuencia, h.horario, h.duracion_min, h.estado_dia, h.racha, h.mejor_racha, h.activo
                FROM gestionables g JOIN habitos h ON g.id=h.gestionable_id
                LEFT JOIN areas a ON g.area_id=a.id
                WHERE g.usuario_id=? AND g.tipo='habito' AND h.activo=1""", (g.user_id,))
    board = {"Pendiente": [], "En curso": [], "Completado": []}
    for r in (rows or []):
        st = r.get("estado_dia") or "Pendiente"
        if st not in board:
            st = "Pendiente"
        board[st].append(r)
    return jsonify({"estados": ["Pendiente", "En curso", "Completado"], "board": board})


@app.route("/api/habitos/<hid>/estado", methods=["POST"])
@token_required
def habito_estado(hid):
    d = request.json or {}
    estado = d.get("estado", "Pendiente")
    if estado not in ("Pendiente", "En curso", "Completado"):
        return jsonify({"error": "estado inválido"}), 400
    h = q("SELECT h.*, g.titulo FROM habitos h JOIN gestionables g ON h.gestionable_id=g.id WHERE g.id=? AND g.usuario_id=?",
          (hid, g.user_id), one=True)
    if not h:
        return jsonify({"error": "No encontrado"}), 404
    qw("UPDATE habitos SET estado_dia=? WHERE gestionable_id=?", (estado, hid))
    racha = h.get("racha") or 0
    mejor = h.get("mejor_racha") or 0
    if estado == "Completado" and (h.get("estado_dia") or "") != "Completado":
        today = date.today().isoformat()
        exists = q("SELECT id FROM habito_logs WHERE habito_id=? AND usuario_id=? AND fecha=?", (hid, g.user_id, today), one=True)
        if not exists:
            lid = gen_id("habi")
            qw("INSERT INTO habito_logs (id,habito_id,usuario_id,fecha) VALUES (?,?,?,?)", (lid, hid, g.user_id, today))
            racha = racha + 1
            mejor = max(racha, mejor)
            qw("UPDATE habitos SET racha=?, mejor_racha=? WHERE gestionable_id=?", (racha, mejor, hid))
        log_mov(g.user_id, "habito_check", f"{h['titulo']} → Completado racha {racha}", hid)
    return jsonify({"ok": True, "racha": racha, "mejor_racha": mejor, "estado": estado})


@app.route("/api/habitos/<hid>/horario", methods=["POST"])
@token_required
def habito_horario(hid):
    d = request.json or {}
    horario = d.get("horario")
    dur = d.get("duracion_min")
    if horario is not None:
        qw("UPDATE habitos SET horario=? WHERE gestionable_id=?", (horario, hid))
    if dur is not None:
        try:
            qw("UPDATE habitos SET duracion_min=? WHERE gestionable_id=?", (int(dur), hid))
        except Exception:
            pass
    return jsonify({"ok": True})




@app.route("/api/habitos/seed-pdf", methods=["POST"])
@token_required
def seed_pdf_habits():
    """Carga hábitos del horario ideal si el usuario tiene pocos."""
    n = q("SELECT COUNT(*) as c FROM gestionables WHERE usuario_id=? AND tipo='habito'", (g.user_id,), one=True)
    if n and n.get("c", 0) >= 10:
        return jsonify({"ok": True, "msg": "ya tiene hábitos", "count": n["c"]})
    areas = {a["nombre"]: a["id"] for a in q("SELECT * FROM areas")}
    PDF_HABITS = [
        ("Git Push Diario", "Laboral", "diario", "10:20", 10),
        ("Dental floss + mouthwash (mañana)", "Salud", "diario", "06:30", 3),
        ("Dental floss + mouthwash (noche)", "Salud", "diario", "20:00", 3),
        ("Mindfulness / Meditación Balance", "Salud", "diario", "10:40", 10),
        ("Agua al despertar (2 vasos)", "Salud", "diario", "06:10", 2),
        ("Barridita o Trapeadita", "Familia", "diario", "06:40", 10),
        ("Revisar lista priorizada (Matriz)", "Laboral", "diario", "07:30", 10),
        ("Lectura técnica", "Academico", "3x", "17:00", 20),
        ("Practicar inglés (Ewa/Elevate)", "Academico", "5x", "19:30", 20),
        ("Un dibujo / dibujo rápido", "Arte", "3x", "17:00", 15),
        ("Lectura artística", "Arte", "2x", "19:30", 20),
        ("Una postulación calidad", "Laboral", "3x", "08:30", 25),
        ("Aprender 5 palabras inglés", "Academico", "5x", "19:40", 10),
        ("Gym o Bici malecón", "Salud", "3x", "18:00", 40),
        ("Registrar peso", "Salud", "diario", "06:15", 2),
        ("Agradecimiento", "Salud", "diario", "06:12", 2),
        ("Escribir pensamientos", "Salud", "2x", "21:00", 10),
        ("1 capítulo lectura", "Arte", "2x", "19:30", 20),
    ]
    created = 0
    for titulo, area, freq, horario, dur in PDF_HABITS:
        exists = q("SELECT g.id FROM gestionables g WHERE g.usuario_id=? AND g.tipo='habito' AND g.titulo=?", (g.user_id, titulo), one=True)
        if exists:
            continue
        hid = gen_id("habi")
        qw("INSERT INTO gestionables (id,usuario_id,tipo,titulo,descripcion,area_id) VALUES (?,?,?,?,?,?)",
           (hid, g.user_id, "habito", titulo, f"freq:{freq}", areas.get(area)))
        try:
            qw("INSERT INTO habitos (gestionable_id,frecuencia,horario,activo,racha,mejor_racha,duracion_min,estado_dia) VALUES (?,?,?,?,?,?,?,?)",
               (hid, freq, horario, 1, 0, 0, dur, "Pendiente"))
        except Exception:
            qw("INSERT INTO habitos (gestionable_id,frecuencia,horario,activo,racha,mejor_racha) VALUES (?,?,?,?,?,?)",
               (hid, freq, horario, 1, 0, 0))
        created += 1
    return jsonify({"ok": True, "created": created})


# ─── STATIC ───
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/<path:path>")
def static_proxy(path):
    return send_from_directory("static", path)


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"GESTIONABLE V3 :{port} PG={USE_PG}")
    app.run(host="0.0.0.0", port=port, debug=False)

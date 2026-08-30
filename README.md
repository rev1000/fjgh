# GESTIONABLE

Flujo: **Matriz → Kanban → Burndown → Hábitos → Proyectos → Eventos**

## Render + PostgreSQL

1. En Render: **New → PostgreSQL** (Free) → crea la DB
2. Copia la **Internal Database URL**
3. En tu Web Service → Environment → añade:
   - `DATABASE_URL` = la URL de Postgres (empieza por `postgres://` o `postgresql://`)
   - `SECRET_KEY` = cualquier string largo aleatorio
4. Build: `pip install -r requirements.txt`
5. Start: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4`

Sin `DATABASE_URL` usa SQLite (datos se pierden al reiniciar).

## Credenciales demo
- user@gestionable.app / user123
- admin@gestionable.app / admin123

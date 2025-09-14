# docs/DEPLOY.md
## Driver & URL hardening
- We standardise on **psycopg v3**. `app/db.py` normalises your `DATABASE_URL` to `postgresql+psycopg://` and asserts the active driver on startup.
- If a build ever loads `psycopg2`, startup fails fast with a clear error in logs.

## Dependencies
Use `requirements.txt` provided (no `psycopg2*` packages). Render will install `psycopg[binary]` automatically.

## Healthcheck (Render)
Set the service healthcheck to `GET /diag/db-test`. A failing preflight prevents bad revisions from going live.

## Migrations
- Guardrail DDL runs on every boot to ensure `clients.package_type`.
- For formal schema, run Alembic:
  - Local: `alembic upgrade head` (ensure `DATABASE_URL` is exported).
  - Render: use a one-off job or build command to run `alembic upgrade head` after install.

## Verification (Windows CMD)
- Seed demo: `curl -s -i -X POST "https://<host>/diag/seed-demo?wa=2773XXXXXXX&name=Test&t1=09:00&t2=07:00" -H "Content-Type: application/json" --data "{}"`
- Health: `curl -s -i "https://<host>/diag/db-test"`
- Weekly: `curl -s -i -X POST "https://<host>/tasks/run-reminders?weekly=1&src=manual" -H "Content-Type: application/json" --data "{}"`

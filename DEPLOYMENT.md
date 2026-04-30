# Deployment

## Production Checklist

1. Create a PostgreSQL database with your host.
2. Set environment variables:

   ```env
   SECRET_KEY=use-a-long-random-secret
   DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:PORT/DB_NAME
   SESSION_COOKIE_SECURE=1
   ADMIN_EMAILS=you@example.com
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Run database migrations:

   ```bash
   flask --app run.py db upgrade
   flask --app run.py init-db
   ```

5. Start with Gunicorn:

   ```bash
   gunicorn "run:app"
   ```

## Render

This repo includes `render.yaml`. On Render, create a Blueprint from the repo and Render will provision the web service and PostgreSQL database.

After first deploy, run this once from the Render shell:

```bash
flask --app run.py db upgrade
flask --app run.py init-db
```

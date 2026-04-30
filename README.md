# Social Forum

A Glenville State themed Reddit-style forum built with Flask and PostgreSQL. Users can register, sign in, create posts, upload images, comment, and vote on posts or comments.

## Features

- User registration and login
- Password hashing with Werkzeug
- Post creation, detail pages, and feed sorting
- Communities for organizing posts
- User profiles with post karma and comment karma
- Upvotes and downvotes
- Edit and delete controls for your own posts and comments
- Image uploads on posts
- Sorting by hot, new, top, and most commented
- Search across posts and communities
- Better search with author, post type, and image filters
- Save/bookmark posts
- Avatar initials and community icons
- User settings with bio, display name, email, password, and avatar color
- User-created communities
- Notifications for comments and replies
- Direct messages
- Events calendar
- Rich post composer with post types, image preview, and character count
- Threaded comment replies
- Join/leave communities and filter to joined communities
- Admin dashboard and moderation controls
- Moderation queue with post/comment reports
- Pin and lock posts
- Feed pagination
- Demo data seeding for a populated test app
- Nested content model for posts, comments, and votes
- One vote per user per post/comment
- PostgreSQL-ready schema through SQLAlchemy
- Clean responsive HTML/CSS frontend

## Setup

## Beginner Local Demo

Use SQLite while you are building locally:

```bash
cd /Users/callum/Documents/Codex/2026-04-29/i-am-building-a-social-forum
source .venv/bin/activate
DATABASE_URL=sqlite:///dev_glenville_demo.db SECRET_KEY=dev flask --app run.py run --port 5007
```

Demo accounts:

```text
admin / password123
ross / password123
maya / password123
jordan / password123
```

## PostgreSQL Setup

1. Create a PostgreSQL database and user:

   ```sql
   CREATE DATABASE social_forum;
   CREATE USER forum_user WITH PASSWORD 'forum_password';
   GRANT ALL PRIVILEGES ON DATABASE social_forum TO forum_user;
   ```

2. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Configure environment:

   ```bash
   cp .env.example .env
   ```

5. Initialize the database tables:

   ```bash
   flask --app run.py db upgrade
   flask --app run.py init-db
   ```

   You can also inspect the raw PostgreSQL schema in `schema.sql`.

   If you are using the beginner SQLite setup and need to rebuild the practice database after changing models, run:

   ```bash
   DATABASE_URL=sqlite:///dev.db SECRET_KEY=dev flask --app run.py reset-db
   ```

6. Run the app:

   ```bash
   flask --app run.py run
   ```

Open `http://127.0.0.1:5000`.

## Migrations

After changing models:

```bash
flask --app run.py db migrate -m "describe_change"
flask --app run.py db upgrade
```

To create the initial schema on a new database:

```bash
flask --app run.py db upgrade
flask --app run.py init-db
```

## Demo Data

Populate a fresh database:

```bash
flask --app run.py seed-demo
```

## Deployment

Production uses:

- PostgreSQL via `DATABASE_URL`
- Gunicorn via `Procfile`
- Flask-Migrate/Alembic migrations
- secure-cookie settings via `SESSION_COOKIE_SECURE=1`

See `DEPLOYMENT.md` and `SECURITY.md`.

## Project Structure

```text
app/
  __init__.py
  auth.py
  forum.py
  models.py
  static/styles.css
  templates/
config.py
run.py
requirements.txt
```

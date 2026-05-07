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
- Community moderator roles
- Moderation queue with post/comment reports
- Pin and lock posts
- Feed pagination
- Demo data seeding for a populated test app
- Nested content model for posts, comments, and votes
- One vote per user per post/comment
- PostgreSQL-ready schema through SQLAlchemy
- Clean responsive HTML/CSS frontend



## Local Setup

```bash
cd /Users/callum/Documents/Codex/2026-04-29/Glenville_Forum
source .venv/bin/activate
pip install -r requirements.txt
```

Create your local PostgreSQL database if it does not already exist:

```bash
createdb -h localhost glenville_forum
```

Apply migrations and seed demo data:

```bash
DATABASE_URL=postgresql+psycopg2://localhost:5432/glenville_forum SECRET_KEY=dev flask --app run.py db upgrade
DATABASE_URL=postgresql+psycopg2://localhost:5432/glenville_forum SECRET_KEY=dev flask --app run.py seed-demo
```

Run the app locally:

```bash
DATABASE_URL=postgresql+psycopg2://localhost:5432/glenville_forum SECRET_KEY=dev flask --app run.py run --port 5010
```

## Testing

Run the automated test suite before pushing changes:

```bash
source .venv/bin/activate
python -m pytest -q
```

## Deployment Notes

For Render, Railway, Heroku-style platforms, use these settings:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn "run:app"`
- Health check path: `/healthz`
- Required environment variables: `SECRET_KEY`, `DATABASE_URL`, `SESSION_COOKIE_SECURE=1`
- Release/migration command: `flask --app run.py db upgrade`

Use PostgreSQL in production. Do not use the development Flask server for a public deployment.

## Security Checklist

- Use a long random `SECRET_KEY`.
- Set `SESSION_COOKIE_SECURE=1` on HTTPS hosting.
- Keep `.env` out of Git.
- Run `flask --app run.py db upgrade` after every migration.
- Run `python -m pytest -q` before pushing.
- Keep uploads limited to PNG, JPG, GIF, or WEBP images.

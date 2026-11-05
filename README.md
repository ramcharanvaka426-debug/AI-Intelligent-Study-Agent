# Studyroom: AI Intelligent Study Agent

A multi-user study workspace with an academic tutor, PDF summarizer, personalized weekly planner, multiple-choice quiz generator, and student dashboard. The frontend is React + Vite; the API is FastAPI with Pydantic and SQLite. Student accounts use Werkzeug password hashing, signed sessions, CSRF tokens, and per-user ownership checks. Groq powers tutor answers, summaries, and note-grounded quizzes when `GROQ_API_KEY` is configured.

## Project structure

```text
.
├── backend/
│   ├── app/
│   │   ├── ai.py          # Groq integrations and local fallbacks
│   │   ├── database.py    # SQLite schema and additive migrations
│   │   ├── main.py        # FastAPI, auth, and study API routes
│   │   └── schemas.py     # Validated request models
│   └── tests/
├── src/
│   ├── App.jsx            # Account screens and study workspace
│   ├── main.jsx
│   └── styles.css
├── Dockerfile
├── render.yaml
├── requirements.txt
└── package.json
```

## Run locally

Use Python 3.11+ and Node.js 20.19+ (or 22.12+). Open two terminals in the repository root.

### 1. Start the API

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp -n .env.example .env
python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Set `SESSION_SECRET` in `.env` to a random value for a stable local session key. If omitted in development, the API generates an ephemeral key and logs a warning; existing sessions will expire when the process restarts.

### 2. Start the web app

In the second terminal:

```bash
npm install
npm run dev -- --host 0.0.0.0
```

Open port `5173`. Vite forwards `/api` requests to FastAPI on port `8000`. The API docs are available at `/docs`.

### 3. Configure AI (optional)

Set `GROQ_API_KEY` in your local `.env` or environment to enable provider-powered tutor answers, summaries, and quizzes. Without a key, the existing local fallback behavior remains available. Do not commit credentials; `.env` is ignored by git.

## Features

- **Student accounts:** Register and log in with a private account; logout clears the session.
- **AI tutor:** Ask questions in a selected subject and get step-by-step explanations. Conversations are saved per student.
- **PDF summarizer and library:** Extract and summarize PDFs; saved text and original files are private to the uploader.
- **Study planner:** Generate personal study sessions, add exam reminders, and mark daily sessions complete.
- **Quiz generator:** Generate four-option questions from a topic or the student's PDF notes, then save quiz scores.
- **Student dashboard:** Show the student's quiz count and average, materials, recent AI conversations, tasks, exams, and study activity.

## Database migration and legacy records

The application reuses the existing SQLite database. Startup migrations add `user_id` columns to personal data tables, add `total_questions` to quiz scores, and create `users`, `study_history`, and `ai_chat_history`. The existing subjects table is migrated to allow each account its own subjects. Existing rows are preserved and remain unassigned (`user_id IS NULL`); legacy scores keep their saved percentage and have a `NULL` question count. They are never automatically shown to the first student who registers. New accounts start with an empty workspace.

Back up the persistent database before deploying this version. SQLite's online backup API can create a consistent backup:

```bash
python -c "import sqlite3; source=sqlite3.connect('study_agent.db'); backup=sqlite3.connect('study_agent.backup.db'); source.backup(backup); backup.close(); source.close()"
```

For Render, download/backup the database from the existing persistent disk before the first deployment. Do not remove or replace that disk.

## Production and Render

Build and run the unified service with Docker:

```bash
docker build -t studyroom .
docker run --rm -p 8000:8000 \
  -e APP_ENV=production \
  -e SESSION_SECRET=replace-with-a-long-random-secret \
  -e GROQ_API_KEY=your-key \
  studyroom
```

FastAPI serves the production frontend and API from the same origin. `SESSION_SECRET` is required in production. Configure `STUDY_AGENT_DB_PATH` to a persistent writable database path; the existing Render Blueprint uses `/var/data/study_agent.db` on its persistent disk. SQLite on the disk is suitable for a single application instance. Migrate to PostgreSQL before scaling to multiple instances.

To deploy, connect the existing repository to Render and deploy its `render.yaml` Blueprint. The Blueprint uses the current Docker deployment and persistent disk, sets production mode, and generates a `SESSION_SECRET`. Set `GROQ_API_KEY` in the Render dashboard if AI provider features are needed. The default `GROQ_MODEL` is `openai/gpt-oss-20b`.

## Security behavior

- Passwords are stored as Werkzeug scrypt hashes; email uniqueness is case-insensitive.
- Session cookies are HTTP-only, same-site, expire after 12 hours, and are HTTPS-only in production. Each login is tracked in the database so logout revokes the session immediately, including if an old cookie is replayed.
- Mutating API requests require the session-bound `X-CSRF-Token` returned by `/api/auth/csrf`.
- Protected routes use the user ID from the signed server session, never a request-body `user_id`.
- Dashboard queries, study records, quiz scores, chat history, uploaded files, and file operations are scoped to that user. Cross-account object access returns `404`.

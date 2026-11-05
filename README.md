# Studyroom: AI Intelligent Study Agent

A personal study workspace with an academic tutor, PDF summarizer, personalized weekly planner, multiple-choice quiz generator, and progress dashboard. The frontend is React + Vite; the API is FastAPI with Pydantic and SQLite. OpenAI powers tutor answers, both summary lengths, and note-grounded quizzes. Configure an API key to use AI features; the API returns a clear configuration error rather than presenting template text as an AI response.

## Project Structure

```text
.
├── backend/
│   ├── .env             # Local OpenAI settings (ignored by git)
│   └── app/
│       ├── ai.py          # OpenAI integrations and local fallbacks
│       ├── database.py    # SQLite schema and sample data
│       ├── main.py        # FastAPI routes
│       └── schemas.py     # Pydantic request models
├── src/
│   ├── App.jsx            # Study workspace and feature views
│   ├── main.jsx
│   └── styles.css
├── index.html
├── .env.example
├── package.json
├── requirements.txt
└── vite.config.js
```

## Run in GitHub Codespaces

Use a Codespace with Python 3.11+ and Node.js 20.19+ (or 22.12+). Open two terminals in the repository root.

### 1. Start the API

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

In the **Ports** tab, make port `8000` available if you want to open the API docs directly. The interactive docs are at `/docs` on that forwarded port.

### 2. Start the web app

In the second terminal:

```bash
npm install
npm run dev -- --host 0.0.0.0
```

Open forwarded port `5173` in the browser. Vite forwards `/api` requests to the FastAPI server on port `8000`, so keep both terminals running.

### 3. Configure OpenAI

AI tutor, PDF summaries, and quiz generation require an OpenAI API key. Add `OPENAI_API_KEY` as a Codespaces secret under **GitHub repository Settings → Secrets and variables → Codespaces**, then restart the Codespace so the secret is available to its terminals.

The project creates `backend/.env` with a blank key and the default model. In the Codespaces Explorer, open `backend/.env` and privately replace the empty `OPENAI_API_KEY=` value with your key. Do not paste the key into chat or a terminal command. `backend/.env` is ignored by git. Keep `.env.example` as a placeholder-only template.

After saving `backend/.env`, restart the FastAPI server so `python-dotenv` loads the values.

PDF uploads accept PDFs up to 50 MB and 200 pages; long documents are summarized in bounded chunks to avoid model context limits. PDFs with fewer than 50 characters of selectable text are automatically processed with RapidOCR. Extracted text and both summaries are stored in the local SQLite database so the notes can be selected later as quiz source material. The original PDF file is also retained.

## Features

- **AI tutor:** Ask questions in a selected subject and get step-by-step explanations.
- **PDF summarizer:** Generate short and detailed summaries from uploaded notes and download either as a text file.
- **Study planner:** Schedule subjects toward an exam date, save exam reminders, and mark daily sessions complete.
- **Quiz generator:** Generate four-option questions from a topic or saved PDF notes, see explanations, and save scored results.
- **Student dashboard:** Track subjects, tasks, upcoming exams, assessment scores, and learning progress.

The API creates `study_agent.db` in the repository root on first run and seeds it with sample tasks, exams, and scores for demonstration. Uploaded note text, exam reminders, task completion, study plans, and saved quiz scores are persisted in SQLite.

## Production deployment

Build and run the unified service with Docker:

```bash
docker build -t studyroom .
docker run --rm -p 8000:8000 \
  -e GROQ_API_KEY=your-key \
  -e GROQ_MODEL=openai/gpt-oss-20b \
  studyroom
```

FastAPI serves the production frontend and API from the same origin. Set `PORT` to override the default port `8000`. Set `STUDY_AGENT_DB_PATH` to a persistent writable SQLite file path when deploying; Render is configured to use `/var/data/study_agent.db` on its persistent disk. SQLite is intended for a single application instance.

To deploy on Render, connect the repository and create a Blueprint from `render.yaml`. Set the required `GROQ_API_KEY` environment variable in the Render dashboard; `GROQ_MODEL` defaults to `openai/gpt-oss-20b`.

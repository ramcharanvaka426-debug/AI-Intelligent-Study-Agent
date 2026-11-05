from contextlib import asynccontextmanager
from datetime import date, timedelta
from functools import lru_cache
import hmac
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import quote

import pymupdf
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from werkzeug.security import check_password_hash, generate_password_hash

from . import ai
from .database import connect, initialize_database
from .schemas import (
    ExamCreate,
    LoginRequest,
    PlannerRequest,
    QuizRequest,
    QuizScoreCreate,
    RegisterRequest,
    TaskCreate,
    TaskUpdate,
    TutorRequest,
)

logger = logging.getLogger(__name__)
MAX_PDF_SIZE = 50 * 1024 * 1024
MAX_PDF_PAGES = 200
MIN_TEXT_LENGTH_FOR_OCR = 50
SESSION_MAX_AGE = 12 * 60 * 60


@lru_cache(maxsize=1)
def _get_ocr_engine():
    try:
        from rapidocr import RapidOCR
    except ImportError as error:
        logger.exception("RapidOCR is unavailable")
        raise HTTPException(
            status_code=503,
            detail="OCR is unavailable. Install the backend requirements and try again.",
        ) from error

    try:
        return RapidOCR()
    except Exception as error:
        logger.exception("Could not initialize RapidOCR")
        raise HTTPException(
            status_code=503,
            detail="OCR could not be initialized. Check the backend installation and try again.",
        ) from error


def _ocr_pdf(document) -> list[str]:
    engine = _get_ocr_engine()
    extracted_pages = []
    try:
        for page in document:
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            result = engine(pixmap.tobytes("png"))
            page_text = "\n".join(text.strip() for text in result.txts or [] if text.strip())
            extracted_pages.append(page_text)
    except Exception as error:
        logger.exception("OCR failed while processing a PDF")
        raise HTTPException(
            status_code=503,
            detail="OCR failed while processing this PDF. Check the backend logs and try again.",
        ) from error
    return extracted_pages


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


allowed_origins = [origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()]
codespace_name = os.getenv("CODESPACE_NAME")
forwarding_domain = os.getenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
if codespace_name and forwarding_domain:
    allowed_origins.append(f"https://{codespace_name}-5173.{forwarding_domain}")

app = FastAPI(title="Intelligent Study Agent API", version="1.0.0", lifespan=lifespan)
is_production = os.getenv("APP_ENV", "").lower() == "production" or os.getenv("RENDER") == "true"
session_secret = os.getenv("SESSION_SECRET")
if is_production and (not session_secret or len(session_secret) < 32):
    raise RuntimeError("SESSION_SECRET must contain at least 32 characters in production.")
if not session_secret:
    session_secret = secrets.token_urlsafe(32)
    logger.warning("SESSION_SECRET is not set; using an ephemeral development key.")

app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    session_cookie="study_session",
    max_age=SESSION_MAX_AGE,
    same_site="lax",
    https_only=is_production,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def disable_private_caching(request: Request, call_next):
    response = await call_next(request)
    if (
        request.url.path.startswith("/api/")
        or request.url.path == "/"
        or not request.url.path.startswith("/assets/")
    ):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


FRONTEND_DIST = Path(
    os.getenv("FRONTEND_DIST_DIR", Path(__file__).resolve().parents[2] / "dist")
).resolve()
FRONTEND_INDEX = FRONTEND_DIST / "index.html"
FRONTEND_ASSETS = FRONTEND_DIST / "assets"
if FRONTEND_ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS), name="frontend-assets")
else:
    logger.warning("Frontend assets are not built at %s", FRONTEND_DIST)


def _dict_rows(rows):
    return [dict(row) for row in rows]


def authenticated_user_id(request: Request) -> int:
    user_id = request.session.get("user_id")
    session_id = request.session.get("session_id")
    if not isinstance(user_id, int) or not isinstance(session_id, str):
        request.session.clear()
        raise HTTPException(status_code=401, detail="Please log in to continue.")
    with connect() as db:
        active_session = db.execute(
            "SELECT 1 FROM auth_sessions "
            "WHERE session_id = ? AND user_id = ? AND expires_at > ?",
            (session_id, user_id, int(time.time())),
        ).fetchone()
    if active_session is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Please log in to continue.")
    return user_id


def require_csrf(request: Request) -> None:
    expected = request.session.get("csrf_token")
    provided = request.headers.get("x-csrf-token", "")
    if not isinstance(expected, str) or not provided or not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=403, detail="Your session expired. Refresh the page and try again.")


def _record_activity(db, user_id: int, activity: str) -> None:
    db.execute(
        "INSERT INTO study_history (user_id, activity) VALUES (?, ?)",
        (user_id, activity[:240]),
    )


def _ai_failure(feature: str, error: Exception) -> HTTPException:
    status_code = getattr(error, "status_code", None)
    error_type = type(error).__name__
    logger.error("%s failed (%s, HTTP %s)", feature, error_type, status_code or "n/a")

    if status_code == 401 or error_type == "AuthenticationError":
        detail = "Groq authentication failed. Check that GROQ_API_KEY is valid and active."
    elif status_code == 403 or error_type == "PermissionDeniedError":
        detail = "Groq denied access. Check API permissions and model access."
    elif status_code == 429 and getattr(error, "code", None) == "insufficient_quota":
        detail = "Groq API quota is exhausted. Check billing and project usage limits."
    elif status_code == 429 or error_type == "RateLimitError":
        detail = "Groq API rate limit reached. Wait briefly and try again."
    elif status_code == 400 or error_type == "BadRequestError":
        detail = "Groq rejected the request. Check the selected model and API request parameters."
    elif status_code is None:
        detail = "Could not connect to Groq. Check network access and backend logs."
    else:
        detail = f"{feature} failed. Check the Groq model, API permissions, and backend logs."
    return HTTPException(status_code=502, detail=detail)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/auth/csrf")
def csrf_token(request: Request):
    token = request.session.get("csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return {"csrf_token": token}


@app.post("/api/auth/register", status_code=201)
def register(
    payload: RegisterRequest,
    _: None = Depends(require_csrf),
):
    password_hash = generate_password_hash(payload.password, method="scrypt")
    try:
        with connect() as db:
            db.execute(
                "INSERT INTO users (full_name, email, password_hash) VALUES (?, ?, ?)",
                (payload.full_name, payload.email, password_hash),
            )
    except sqlite3.IntegrityError as error:
        if "users.email" in str(error).lower() or "unique constraint" in str(error).lower():
            raise HTTPException(status_code=409, detail="An account with that email already exists.") from error
        raise
    return {"message": "Your account has been created. Please log in."}


@app.post("/api/auth/login")
def login(
    payload: LoginRequest,
    request: Request,
    _: None = Depends(require_csrf),
):
    with connect() as db:
        user = db.execute(
            "SELECT id, full_name, email, password_hash FROM users WHERE email = ? COLLATE NOCASE",
            (payload.email,),
        ).fetchone()
    if user is None or not check_password_hash(user["password_hash"], payload.password):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")

    session_id = secrets.token_urlsafe(32)
    with connect() as db:
        db.execute(
            "DELETE FROM auth_sessions WHERE expires_at <= ?", (int(time.time()),)
        )
        db.execute(
            "INSERT INTO auth_sessions (session_id, user_id, expires_at) VALUES (?, ?, ?)",
            (session_id, user["id"], int(time.time()) + SESSION_MAX_AGE),
        )
    request.session.clear()
    request.session.update(
        {
            "user_id": user["id"],
            "session_id": session_id,
            "csrf_token": secrets.token_urlsafe(32),
        }
    )
    return {
        "user": {"id": user["id"], "full_name": user["full_name"], "email": user["email"]},
        "csrf_token": request.session["csrf_token"],
    }


@app.get("/api/auth/me")
def current_user(user_id: int = Depends(authenticated_user_id)):
    with connect() as db:
        user = db.execute(
            "SELECT id, full_name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if user is None:
        raise HTTPException(status_code=401, detail="Please log in to continue.")
    return {"user": dict(user)}


@app.post("/api/auth/logout")
def logout(
    request: Request,
    user_id: int = Depends(authenticated_user_id),
    _: None = Depends(require_csrf),
):
    with connect() as db:
        db.execute(
            "DELETE FROM auth_sessions WHERE session_id = ? AND user_id = ?",
            (request.session["session_id"], user_id),
        )
    request.session.clear()
    return {"message": "You have been logged out."}


@app.get("/api/dashboard")
def dashboard(user_id: int = Depends(authenticated_user_id)):
    with connect() as db:
        tasks = _dict_rows(db.execute(
            "SELECT id, title, due_date, category, completed FROM tasks "
            "WHERE user_id = ? ORDER BY completed, due_date",
            (user_id,),
        ).fetchall())
        exams = _dict_rows(db.execute(
            "SELECT id, course, title, exam_date FROM exams "
            "WHERE user_id = ? AND exam_date >= ? ORDER BY exam_date LIMIT 4",
            (user_id, date.today().isoformat()),
        ).fetchall())
        scores = _dict_rows(db.execute(
            "SELECT id, course, score, label, recorded_at, total_questions FROM scores "
            "WHERE user_id = ? ORDER BY id DESC LIMIT 6",
            (user_id,),
        ).fetchall())
        all_scores = db.execute(
            "SELECT COUNT(*) AS total, AVG(score) AS average FROM scores WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        total_tasks = db.execute(
            "SELECT COUNT(*) FROM tasks WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        completed = db.execute(
            "SELECT COUNT(*) FROM tasks WHERE user_id = ? AND completed = 1", (user_id,)
        ).fetchone()[0]
        total_subjects = db.execute(
            "SELECT COUNT(*) FROM subjects WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        total_materials = db.execute(
            "SELECT COUNT(*) FROM materials WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        chats = _dict_rows(db.execute(
            "SELECT id, user_message, ai_response, created_at FROM ai_chat_history "
            "WHERE user_id = ? ORDER BY id DESC LIMIT 5",
            (user_id,),
        ).fetchall())
        activities = _dict_rows(db.execute(
            "SELECT id, activity, created_at FROM study_history "
            "WHERE user_id = ? ORDER BY id DESC LIMIT 6",
            (user_id,),
        ).fetchall())
    return {
        "tasks": tasks,
        "exams": exams,
        "scores": scores,
        "recent_conversations": chats,
        "study_activity": activities,
        "stats": {
            "total_subjects": total_subjects,
            "tasks_completed": completed,
            "tasks_total": total_tasks,
            "average_score": round(all_scores["average"] or 0),
            "quizzes_completed": all_scores["total"],
            "total_materials": total_materials,
        },
    }


@app.post("/api/tasks", status_code=201)
def create_task(
    payload: TaskCreate,
    user_id: int = Depends(authenticated_user_id),
    _: None = Depends(require_csrf),
):
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO tasks (title, due_date, category, user_id) VALUES (?, ?, ?, ?)",
            (payload.title.strip(), payload.due_date.isoformat(), payload.category, user_id),
        )
        task = db.execute(
            "SELECT id, title, due_date, category, completed FROM tasks WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        _record_activity(db, user_id, f"Added task: {payload.title.strip()}")
    return dict(task)


@app.post("/api/exams", status_code=201)
def create_exam(
    payload: ExamCreate,
    user_id: int = Depends(authenticated_user_id),
    _: None = Depends(require_csrf),
):
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO exams (course, title, exam_date, user_id) VALUES (?, ?, ?, ?)",
            (payload.course.strip(), payload.title.strip(), payload.exam_date.isoformat(), user_id),
        )
        exam = db.execute(
            "SELECT id, course, title, exam_date FROM exams WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        _record_activity(db, user_id, f"Added exam: {payload.title.strip()}")
    return dict(exam)


@app.patch("/api/tasks/{task_id}")
def update_task(
    task_id: int,
    payload: TaskUpdate,
    user_id: int = Depends(authenticated_user_id),
    _: None = Depends(require_csrf),
):
    with connect() as db:
        cursor = db.execute(
            "UPDATE tasks SET completed = ? WHERE id = ? AND user_id = ?",
            (int(payload.completed), task_id, user_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")
        task = db.execute(
            "SELECT id, title, due_date, category, completed FROM tasks "
            "WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
        _record_activity(db, user_id, "Completed a study task" if payload.completed else "Reopened a study task")
    return dict(task)


@app.post("/api/tutor")
def tutor(
    payload: TutorRequest,
    user_id: int = Depends(authenticated_user_id),
    _: None = Depends(require_csrf),
):
    try:
        result = {
            "answer": ai.tutor_answer(payload.question, payload.course),
            "key_takeaways": [],
            "powered_by_ai": True,
        }
    except ai.AIConfigurationError:
        result = ai.standalone_tutor_response(payload.question, payload.course)
    except ai.AIProviderUnavailableError as error:
        result = ai.fallback_tutor_response(payload.question, payload.course, error.reason)
    except Exception as error:
        raise _ai_failure("Tutor request", error) from error
    with connect() as db:
        db.execute(
            "INSERT INTO ai_chat_history (user_id, user_message, ai_response) VALUES (?, ?, ?)",
            (user_id, payload.question, result["answer"]),
        )
        _record_activity(db, user_id, f"Asked the AI tutor about {payload.course}")
    return result


@app.post("/api/summarize")
def summarize(
    file: UploadFile = File(...),
    user_id: int = Depends(authenticated_user_id),
    _: None = Depends(require_csrf),
):
    if Path(file.filename or "").suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")
    content = file.file.read(MAX_PDF_SIZE + 1)
    if len(content) > MAX_PDF_SIZE:
        raise HTTPException(status_code=413, detail="PDFs must be 50 MB or smaller.")
    document = None
    try:
        document = pymupdf.open(stream=content, filetype="pdf")
        if document.page_count > MAX_PDF_PAGES:
            raise HTTPException(status_code=413, detail="PDFs are limited to 200 pages.")
        page_texts = [page.get_text() for page in document]
        extracted = "\n".join(page_texts)
        if len(extracted.strip()) < MIN_TEXT_LENGTH_FOR_OCR:
            ocr_page_texts = _ocr_pdf(document)
            extracted = "\n".join(
                ocr_text or page_text
                for ocr_text, page_text in zip(ocr_page_texts, page_texts)
            )
        pages = document.page_count
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=400, detail="The uploaded file could not be read as a PDF.") from error
    finally:
        if document is not None:
            document.close()
    if not extracted.strip():
        raise HTTPException(status_code=422, detail="No readable text could be extracted from this PDF.")
    powered_by_ai = True
    try:
        summaries = ai.summarize_text(extracted)
    except Exception as error:
        logger.warning("Using local PDF summary fallback (%s, HTTP %s)", type(error).__name__, getattr(error, "status_code", "n/a"))
        summaries = ai.fallback_summarize_text(extracted)
        powered_by_ai = False
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO materials "
            "(filename, page_count, text_content, short_summary, detailed_summary, pdf_content, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                file.filename or "study-notes.pdf",
                pages,
                extracted,
                summaries["short_summary"],
                summaries["detailed_summary"],
                content,
                user_id,
            ),
        )
        material_id = cursor.lastrowid
        _record_activity(db, user_id, f"Uploaded study material: {file.filename or 'study-notes.pdf'}")
    return {"material_id": material_id, "filename": file.filename, "pages": pages, "powered_by_ai": powered_by_ai, **summaries}


@app.get("/api/materials")
def get_materials(user_id: int = Depends(authenticated_user_id)):
    with connect() as db:
        materials = _dict_rows(db.execute(
            "SELECT id, filename, page_count, created_at, pdf_content IS NOT NULL AS original_available "
            "FROM materials WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall())
    return {"materials": materials}


@app.get("/api/materials/{material_id}/file")
def get_material_file(
    material_id: int,
    download: bool = False,
    user_id: int = Depends(authenticated_user_id),
):
    with connect() as db:
        material = db.execute(
            "SELECT filename, text_content, pdf_content FROM materials WHERE id = ? AND user_id = ?",
            (material_id, user_id),
        ).fetchone()
    if material is None:
        raise HTTPException(status_code=404, detail="Study material not found.")

    original = material["pdf_content"]
    if original is None:
        filename = f"{Path(material['filename']).stem}-notes.txt"
        content = material["text_content"].encode("utf-8")
        media_type = "text/plain; charset=utf-8"
    else:
        filename = Path(material["filename"].replace("\\", "/")).name or "study-material.pdf"
        content = bytes(original)
        media_type = "application/pdf"
    disposition = "attachment" if download else "inline"
    headers = {"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}"}
    return Response(content=content, media_type=media_type, headers=headers)


@app.delete("/api/materials/{material_id}")
def delete_material(
    material_id: int,
    user_id: int = Depends(authenticated_user_id),
    _: None = Depends(require_csrf),
):
    with connect() as db:
        cursor = db.execute(
            "DELETE FROM materials WHERE id = ? AND user_id = ?", (material_id, user_id)
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Study material not found.")
        _record_activity(db, user_id, "Deleted a study material")
    return {"deleted": material_id}


@app.get("/api/subjects")
def get_subjects(user_id: int = Depends(authenticated_user_id)):
    with connect() as db:
        subjects = [row["name"] for row in db.execute(
            "SELECT name FROM subjects WHERE user_id = ? ORDER BY name COLLATE NOCASE",
            (user_id,),
        ).fetchall()]
    return {"subjects": subjects}


@app.post("/api/planner/generate")
def generate_planner(
    payload: PlannerRequest,
    user_id: int = Depends(authenticated_user_id),
    _: None = Depends(require_csrf),
):
    unique_subjects = {}
    for subject in payload.subjects:
        normalized = subject.strip()
        if normalized:
            unique_subjects.setdefault(normalized.casefold(), normalized)
    subjects = list(unique_subjects.values())
    if not subjects:
        raise HTTPException(status_code=422, detail="Add at least one subject.")
    today = date.today()
    if payload.exam_date and payload.exam_date < today:
        raise HTTPException(status_code=422, detail="The exam date must be today or later.")
    days_to_schedule = min(7, (payload.exam_date - today).days + 1) if payload.exam_date else 7
    sessions = []
    for day_offset in range(days_to_schedule):
        study_date = today + timedelta(days=day_offset)
        subject = subjects[day_offset % len(subjects)]
        sessions.append({
            "study_date": study_date.isoformat(),
            "subject": subject,
            "activity": "Practice questions" if day_offset % 2 else "Review notes & active recall",
            "duration": f"{payload.hours_per_day} hr" if payload.hours_per_day == 1 else f"{payload.hours_per_day} hrs",
            "completed": 0,
        })
    with connect() as db:
        db.execute("DELETE FROM subjects WHERE user_id = ?", (user_id,))
        db.executemany(
            "INSERT INTO subjects (name, user_id) VALUES (?, ?)",
            ((subject, user_id) for subject in subjects),
        )
        db.execute("DELETE FROM study_sessions WHERE user_id = ?", (user_id,))
        db.executemany(
            "INSERT INTO study_sessions "
            "(study_date, subject, activity, duration, completed, user_id) "
            "VALUES (:study_date, :subject, :activity, :duration, :completed, :user_id)",
            [dict(session, user_id=user_id) for session in sessions],
        )
        sessions = _dict_rows(db.execute(
            "SELECT id, study_date, subject, activity, duration, completed "
            "FROM study_sessions WHERE user_id = ? ORDER BY study_date, id",
            (user_id,),
        ).fetchall())
        _record_activity(db, user_id, "Generated a weekly study plan")
    return {"sessions": sessions, "subjects": subjects, "exam_date": payload.exam_date}


@app.get("/api/planner")
def get_planner(user_id: int = Depends(authenticated_user_id)):
    with connect() as db:
        sessions = _dict_rows(db.execute(
            "SELECT id, study_date, subject, activity, duration, completed "
            "FROM study_sessions WHERE user_id = ? ORDER BY study_date, id",
            (user_id,),
        ).fetchall())
    return {"sessions": sessions}


@app.patch("/api/planner/{session_id}")
def update_study_session(
    session_id: int,
    payload: TaskUpdate,
    user_id: int = Depends(authenticated_user_id),
    _: None = Depends(require_csrf),
):
    with connect() as db:
        cursor = db.execute(
            "UPDATE study_sessions SET completed = ? WHERE id = ? AND user_id = ?",
            (int(payload.completed), session_id, user_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Study session not found")
        session = db.execute(
            "SELECT id, study_date, subject, activity, duration, completed "
            "FROM study_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
        _record_activity(db, user_id, "Completed a planned study session" if payload.completed else "Reopened a planned study session")
    return dict(session)


@app.post("/api/quizzes/generate")
def quiz(
    payload: QuizRequest,
    user_id: int = Depends(authenticated_user_id),
    _: None = Depends(require_csrf),
):
    notes = None
    topic = payload.topic
    if payload.material_id is not None:
        with connect() as db:
            material = db.execute(
                "SELECT filename, text_content FROM materials WHERE id = ? AND user_id = ?",
                (payload.material_id, user_id),
            ).fetchone()
        if material is None:
            raise HTTPException(status_code=404, detail="Uploaded study material not found. Upload the PDF again to continue.")
        notes = material["text_content"]
        topic = topic or Path(material["filename"]).stem
    if not topic:
        raise HTTPException(status_code=422, detail="Provide a topic or select uploaded study notes.")
    try:
        questions = ai.generate_quiz(topic, payload.count, notes)
        powered_by_ai = True
    except Exception as error:
        logger.warning("Using local quiz fallback (%s, HTTP %s)", type(error).__name__, getattr(error, "status_code", "n/a"))
        questions = ai.fallback_generate_quiz(topic, payload.count, notes)
        powered_by_ai = False
    with connect() as db:
        _record_activity(db, user_id, f"Generated a practice quiz about {topic}")
    return {"topic": topic, "material_id": payload.material_id, "questions": questions, "powered_by_ai": powered_by_ai}


@app.post("/api/quiz-scores", status_code=201)
def save_quiz_score(
    payload: QuizScoreCreate,
    user_id: int = Depends(authenticated_user_id),
    _: None = Depends(require_csrf),
):
    if payload.correct > payload.total:
        raise HTTPException(status_code=422, detail="Correct answers cannot exceed the number of questions.")
    percentage = round(payload.correct * 100 / payload.total)
    label = f"Quiz result: {payload.correct}/{payload.total} correct"
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO scores (course, score, label, total_questions, user_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (payload.topic, percentage, label, payload.total, user_id),
        )
        result = db.execute(
            "SELECT id, course, score, label, recorded_at, total_questions FROM scores "
            "WHERE id = ? AND user_id = ?",
            (cursor.lastrowid, user_id),
        ).fetchone()
        _record_activity(db, user_id, f"Completed a {payload.topic} quiz with {percentage}%")
    return dict(result)


@app.get("/api/chat-history")
def get_chat_history(user_id: int = Depends(authenticated_user_id)):
    with connect() as db:
        conversations = _dict_rows(db.execute(
            "SELECT id, user_message, ai_response, created_at FROM ai_chat_history "
            "WHERE user_id = ? ORDER BY id DESC LIMIT 50",
            (user_id,),
        ).fetchall())
    return {"conversations": list(reversed(conversations))}


@app.get("/api/study-history")
def get_study_history(user_id: int = Depends(authenticated_user_id)):
    with connect() as db:
        activities = _dict_rows(db.execute(
            "SELECT id, activity, created_at FROM study_history "
            "WHERE user_id = ? ORDER BY id DESC LIMIT 100",
            (user_id,),
        ).fetchall())
    return {"activities": activities}


@app.get("/", include_in_schema=False)
def frontend_index():
    if not FRONTEND_INDEX.is_file():
        raise HTTPException(status_code=404, detail="The production frontend has not been built.")
    return FileResponse(FRONTEND_INDEX)


@app.get("/{path:path}", include_in_schema=False)
def frontend_page(path: str):
    if path == "api" or path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found.")
    if not FRONTEND_INDEX.is_file():
        raise HTTPException(status_code=404, detail="The production frontend has not been built.")

    requested_file = (FRONTEND_DIST / path).resolve()
    if FRONTEND_DIST in requested_file.parents and requested_file.is_file():
        return FileResponse(requested_file)
    return FileResponse(FRONTEND_INDEX)

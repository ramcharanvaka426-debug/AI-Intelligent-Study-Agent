from contextlib import asynccontextmanager
from datetime import date, timedelta
from functools import lru_cache
import logging
import os
from pathlib import Path
from urllib.parse import quote

import pymupdf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import ai
from .database import connect, initialize_database
from .schemas import ExamCreate, PlannerRequest, QuizRequest, QuizScoreCreate, TaskCreate, TaskUpdate, TutorRequest

logger = logging.getLogger(__name__)
MAX_PDF_SIZE = 50 * 1024 * 1024
MAX_PDF_PAGES = 200
MIN_TEXT_LENGTH_FOR_OCR = 50


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get("/api/dashboard")
def dashboard():
    with connect() as db:
        tasks = _dict_rows(db.execute("SELECT * FROM tasks ORDER BY completed, due_date").fetchall())
        exams = _dict_rows(db.execute("SELECT * FROM exams WHERE exam_date >= ? ORDER BY exam_date LIMIT 4", (date.today().isoformat(),)).fetchall())
        scores = _dict_rows(db.execute("SELECT * FROM scores ORDER BY id DESC LIMIT 6").fetchall())
        total_tasks = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        completed = db.execute("SELECT COUNT(*) FROM tasks WHERE completed = 1").fetchone()[0]
        total_subjects = db.execute("SELECT COUNT(DISTINCT name) FROM subjects").fetchone()[0]
    average_score = round(sum(item["score"] for item in scores) / len(scores)) if scores else 0
    return {
        "tasks": tasks,
        "exams": exams,
        "scores": scores,
        "stats": {"total_subjects": total_subjects, "tasks_completed": completed, "tasks_total": total_tasks, "average_score": average_score},
    }


@app.post("/api/tasks", status_code=201)
def create_task(payload: TaskCreate):
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO tasks (title, due_date, category) VALUES (?, ?, ?)",
            (payload.title.strip(), payload.due_date, payload.category),
        )
        task = db.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(task)


@app.post("/api/exams", status_code=201)
def create_exam(payload: ExamCreate):
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO exams (course, title, exam_date) VALUES (?, ?, ?)",
            (payload.course.strip(), payload.title.strip(), payload.exam_date.isoformat()),
        )
        exam = db.execute("SELECT * FROM exams WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(exam)


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, payload: TaskUpdate):
    with connect() as db:
        cursor = db.execute("UPDATE tasks SET completed = ? WHERE id = ?", (int(payload.completed), task_id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")
        task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(task)


@app.post("/api/tutor")
def tutor(payload: TutorRequest):
    try:
        return {
            "answer": ai.tutor_answer(payload.question, payload.course),
            "key_takeaways": [],
            "powered_by_ai": True,
        }
    except ai.AIConfigurationError:
        return ai.standalone_tutor_response(payload.question, payload.course)
    except ai.AIProviderUnavailableError as error:
        return ai.fallback_tutor_response(payload.question, payload.course, error.reason)
    except Exception as error:
        raise _ai_failure("Tutor request", error) from error


@app.post("/api/summarize")
def summarize(file: UploadFile = File(...)):
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
            "(filename, page_count, text_content, short_summary, detailed_summary, pdf_content) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                file.filename or "study-notes.pdf",
                pages,
                extracted,
                summaries["short_summary"],
                summaries["detailed_summary"],
                content,
            ),
        )
        material_id = cursor.lastrowid
    return {"material_id": material_id, "filename": file.filename, "pages": pages, "powered_by_ai": powered_by_ai, **summaries}


@app.get("/api/materials")
def get_materials():
    with connect() as db:
        materials = _dict_rows(db.execute(
            "SELECT id, filename, page_count, created_at, pdf_content IS NOT NULL AS original_available "
            "FROM materials ORDER BY id DESC"
        ).fetchall())
    return {"materials": materials}


@app.get("/api/materials/{material_id}/file")
def get_material_file(material_id: int, download: bool = False):
    with connect() as db:
        material = db.execute(
            "SELECT filename, text_content, pdf_content FROM materials WHERE id = ?",
            (material_id,),
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
def delete_material(material_id: int):
    with connect() as db:
        cursor = db.execute("DELETE FROM materials WHERE id = ?", (material_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Study material not found.")
    return {"deleted": material_id}


@app.get("/api/subjects")
def get_subjects():
    with connect() as db:
        subjects = [row["name"] for row in db.execute("SELECT name FROM subjects ORDER BY name COLLATE NOCASE").fetchall()]
    return {"subjects": subjects}


@app.post("/api/planner/generate")
def generate_planner(payload: PlannerRequest):
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
        db.execute("DELETE FROM subjects")
        db.executemany("INSERT INTO subjects (name) VALUES (?)", ((subject,) for subject in subjects))
        db.execute("DELETE FROM study_sessions")
        db.executemany(
            "INSERT INTO study_sessions (study_date, subject, activity, duration, completed) VALUES (:study_date, :subject, :activity, :duration, :completed)",
            sessions,
        )
        sessions = _dict_rows(db.execute("SELECT * FROM study_sessions ORDER BY study_date, id").fetchall())
    return {"sessions": sessions, "subjects": subjects, "exam_date": payload.exam_date}


@app.get("/api/planner")
def get_planner():
    with connect() as db:
        sessions = _dict_rows(db.execute("SELECT * FROM study_sessions ORDER BY study_date, id").fetchall())
    return {"sessions": sessions}


@app.patch("/api/planner/{session_id}")
def update_study_session(session_id: int, payload: TaskUpdate):
    with connect() as db:
        cursor = db.execute("UPDATE study_sessions SET completed = ? WHERE id = ?", (int(payload.completed), session_id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Study session not found")
        session = db.execute("SELECT * FROM study_sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(session)


@app.post("/api/quizzes/generate")
def quiz(payload: QuizRequest):
    notes = None
    topic = payload.topic
    if payload.material_id is not None:
        with connect() as db:
            material = db.execute("SELECT filename, text_content FROM materials WHERE id = ?", (payload.material_id,)).fetchone()
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
    return {"topic": topic, "material_id": payload.material_id, "questions": questions, "powered_by_ai": powered_by_ai}


@app.post("/api/quiz-scores", status_code=201)
def save_quiz_score(payload: QuizScoreCreate):
    if payload.correct > payload.total:
        raise HTTPException(status_code=422, detail="Correct answers cannot exceed the number of questions.")
    percentage = round(payload.correct * 100 / payload.total)
    label = f"Quiz result: {payload.correct}/{payload.total} correct"
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO scores (course, score, label) VALUES (?, ?, ?)",
            (payload.topic, percentage, label),
        )
        result = db.execute("SELECT * FROM scores WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(result)


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

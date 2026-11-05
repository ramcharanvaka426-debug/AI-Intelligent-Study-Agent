import sqlite3
from datetime import date, timedelta
import os
from pathlib import Path

DB_PATH = Path(
    os.getenv("STUDY_AGENT_DB_PATH", Path(__file__).resolve().parents[2] / "study_agent.db")
).expanduser()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due_date TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Study',
                completed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS exams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course TEXT NOT NULL,
                title TEXT NOT NULL,
                exam_date TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course TEXT NOT NULL,
                score INTEGER NOT NULL,
                label TEXT NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                study_date TEXT NOT NULL,
                subject TEXT NOT NULL,
                activity TEXT NOT NULL,
                duration TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                page_count INTEGER NOT NULL,
                text_content TEXT NOT NULL,
                short_summary TEXT NOT NULL DEFAULT '',
                detailed_summary TEXT NOT NULL DEFAULT '',
                pdf_content BLOB,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE
            );
            """
        )
        session_columns = {row[1] for row in db.execute("PRAGMA table_info(study_sessions)")}
        if "completed" not in session_columns:
            db.execute("ALTER TABLE study_sessions ADD COLUMN completed INTEGER NOT NULL DEFAULT 0")
        material_columns = {row[1] for row in db.execute("PRAGMA table_info(materials)")}
        if "short_summary" not in material_columns:
            db.execute("ALTER TABLE materials ADD COLUMN short_summary TEXT NOT NULL DEFAULT ''")
        if "detailed_summary" not in material_columns:
            db.execute("ALTER TABLE materials ADD COLUMN detailed_summary TEXT NOT NULL DEFAULT ''")
        if "pdf_content" not in material_columns:
            db.execute("ALTER TABLE materials ADD COLUMN pdf_content BLOB")
        if db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0:
            today = date.today()
            db.executemany(
                "INSERT INTO tasks (title, due_date, category, completed) VALUES (?, ?, ?, ?)",
                [
                    ("Review lecture notes", today.isoformat(), "Biology", 0),
                    ("Finish problem set 4", (today + timedelta(days=1)).isoformat(), "Calculus", 0),
                    ("Read chapter 8", (today + timedelta(days=2)).isoformat(), "History", 0),
                    ("Make flashcards for key terms", (today + timedelta(days=2)).isoformat(), "Biology", 0),
                    ("Rework missed questions", (today + timedelta(days=3)).isoformat(), "Calculus", 0),
                    ("Outline essay sources", (today + timedelta(days=4)).isoformat(), "History", 0),
                    ("Review lab diagrams", (today - timedelta(days=1)).isoformat(), "Biology", 1),
                    ("Submit reading response", (today - timedelta(days=2)).isoformat(), "History", 1),
                ],
            )
        if db.execute("SELECT COUNT(*) FROM exams").fetchone()[0] == 0:
            today = date.today()
            db.executemany(
                "INSERT INTO exams (course, title, exam_date) VALUES (?, ?, ?)",
                [
                    ("Calculus II", "Midterm examination", (today + timedelta(days=6)).isoformat()),
                    ("Cell Biology", "Unit assessment", (today + timedelta(days=12)).isoformat()),
                ],
            )
        if db.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO scores (course, score, label) VALUES (?, ?, ?)",
                [("Biology", 88, "Cell structure quiz"), ("Calculus", 76, "Integration set"), ("History", 94, "Source analysis")],
            )
        db.execute(
            "INSERT OR IGNORE INTO subjects (name) "
            "SELECT DISTINCT TRIM(category) FROM tasks "
            "WHERE TRIM(category) <> '' AND category <> 'Study'"
        )
        for table, column in (
            ("exams", "course"),
            ("scores", "course"),
            ("study_sessions", "subject"),
        ):
            db.execute(
                f"INSERT OR IGNORE INTO subjects (name) "
                f"SELECT DISTINCT TRIM({column}) FROM {table} WHERE TRIM({column}) <> ''"
            )

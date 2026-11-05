from contextlib import contextmanager
import sqlite3
import os
from pathlib import Path
from typing import Iterator

DB_PATH = Path(
    os.getenv("STUDY_AGENT_DB_PATH", Path(__file__).resolve().parents[2] / "study_agent.db")
).expanduser()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS auth_sessions (
                session_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS study_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                activity TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS ai_chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                user_message TEXT NOT NULL,
                ai_response TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due_date TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Study',
                completed INTEGER NOT NULL DEFAULT 0,
                user_id INTEGER REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS exams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course TEXT NOT NULL,
                title TEXT NOT NULL,
                exam_date TEXT NOT NULL,
                user_id INTEGER REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course TEXT NOT NULL,
                score INTEGER NOT NULL,
                label TEXT NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                total_questions INTEGER,
                user_id INTEGER REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                study_date TEXT NOT NULL,
                subject TEXT NOT NULL,
                activity TEXT NOT NULL,
                duration TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                user_id INTEGER REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                page_count INTEGER NOT NULL,
                text_content TEXT NOT NULL,
                short_summary TEXT NOT NULL DEFAULT '',
                detailed_summary TEXT NOT NULL DEFAULT '',
                pdf_content BLOB,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE,
                user_id INTEGER REFERENCES users(id),
                UNIQUE(user_id, name)
            );
            """
        )
        for table in ("tasks", "exams", "scores", "study_sessions", "materials"):
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            if "user_id" not in columns:
                db.execute(
                    f"ALTER TABLE {table} ADD COLUMN user_id INTEGER REFERENCES users(id)"
                )
            if table == "scores" and "total_questions" not in columns:
                db.execute("ALTER TABLE scores ADD COLUMN total_questions INTEGER")

        subject_columns = {row[1] for row in db.execute("PRAGMA table_info(subjects)")}
        global_name_unique = any(
            [column[2] for column in db.execute(f"PRAGMA index_info({index[1]})")] == ["name"]
            for index in db.execute("PRAGMA index_list(subjects)")
            if index[2]
        )
        if "user_id" not in subject_columns or global_name_unique:
            db.execute(
                """
                CREATE TABLE subjects_migrated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE,
                    user_id INTEGER REFERENCES users(id),
                    UNIQUE(user_id, name)
                )
                """
            )
            if "user_id" in subject_columns:
                db.execute(
                    "INSERT INTO subjects_migrated (id, name, user_id) "
                    "SELECT id, name, user_id FROM subjects"
                )
            else:
                db.execute(
                    "INSERT INTO subjects_migrated (id, name) SELECT id, name FROM subjects"
                )
            db.execute("DROP TABLE subjects")
            db.execute("ALTER TABLE subjects_migrated RENAME TO subjects")

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
        for index_sql in (
            "CREATE INDEX IF NOT EXISTS idx_tasks_user_due ON tasks(user_id, due_date)",
            "CREATE INDEX IF NOT EXISTS idx_exams_user_date ON exams(user_id, exam_date)",
            "CREATE INDEX IF NOT EXISTS idx_scores_user_id ON scores(user_id, id)",
            "CREATE INDEX IF NOT EXISTS idx_study_sessions_user_date ON study_sessions(user_id, study_date)",
            "CREATE INDEX IF NOT EXISTS idx_materials_user_id ON materials(user_id, id)",
            "CREATE INDEX IF NOT EXISTS idx_study_history_user_created ON study_history(user_id, id)",
            "CREATE INDEX IF NOT EXISTS idx_ai_chat_user_created ON ai_chat_history(user_id, id)",
            "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id)",
        ):
            db.execute(index_sql)

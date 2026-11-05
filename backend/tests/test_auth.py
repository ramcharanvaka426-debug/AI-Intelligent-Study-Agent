from contextlib import closing
from datetime import date
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

import pymupdf
from starlette.middleware.sessions import SessionMiddleware, b64encode
from itsdangerous import TimestampSigner
from fastapi.testclient import TestClient
from werkzeug.security import check_password_hash

from backend.app import database, main


def create_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "Cell biology studies living cells and their structure, function, and interactions. "
        "This paragraph contains enough selectable text for the study material upload test.",
    )
    content = document.tobytes()
    document.close()
    return content


class MultiUserAuthTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database_path = Path(self.directory.name) / "study_agent.db"
        self.database_patch = patch.object(database, "DB_PATH", self.database_path)
        self.database_patch.start()
        self.addCleanup(self.database_patch.stop)
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)

    @staticmethod
    def csrf(client):
        response = client.get("/api/auth/csrf")
        if response.status_code != 200:
            raise AssertionError(response.text)
        return response.json()["csrf_token"]

    @classmethod
    def request(cls, client, method, path, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        headers["X-CSRF-Token"] = cls.csrf(client)
        return client.request(method, path, headers=headers, **kwargs)

    @classmethod
    def register_and_login(cls, client, name, email):
        response = cls.request(
            client,
            "POST",
            "/api/auth/register",
            json={
                "full_name": name,
                "email": email,
                "password": "secure-study-password",
                "confirm_password": "secure-study-password",
            },
        )
        if response.status_code != 201:
            raise AssertionError(response.text)
        response = cls.request(
            client,
            "POST",
            "/api/auth/login",
            json={"email": email, "password": "secure-study-password"},
        )
        if response.status_code != 200:
            raise AssertionError(response.text)
        return response.json()["user"]["id"]

    def new_client(self):
        return TestClient(main.app)

    def test_registration_password_hash_and_duplicate_email(self):
        response = self.request(
            self.client,
            "POST",
            "/api/auth/register",
            json={
                "full_name": "  Alex   Student ",
                "email": "Alex@Example.com",
                "password": "secure-study-password",
                "confirm_password": "secure-study-password",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["message"], "Your account has been created. Please log in.")
        with closing(sqlite3.connect(self.database_path)) as db, db:
            full_name, email, password_hash = db.execute(
                "SELECT full_name, email, password_hash FROM users"
            ).fetchone()
        self.assertEqual(full_name, "Alex Student")
        self.assertEqual(email, "alex@example.com")
        self.assertNotEqual(password_hash, "secure-study-password")
        self.assertTrue(check_password_hash(password_hash, "secure-study-password"))

        wrong_password = self.request(
            self.client,
            "POST",
            "/api/auth/login",
            json={"email": "alex@example.com", "password": "incorrect-password"},
        )
        self.assertEqual(wrong_password.status_code, 401)

        duplicate = self.request(
            self.client,
            "POST",
            "/api/auth/register",
            json={
                "full_name": "Another Student",
                "email": "ALEX@example.com",
                "password": "secure-study-password",
                "confirm_password": "secure-study-password",
            },
        )
        self.assertEqual(duplicate.status_code, 409)

        invalid = self.request(
            self.client,
            "POST",
            "/api/auth/register",
            json={
                "full_name": "Student",
                "email": "not-an-email",
                "password": "short",
                "confirm_password": "different",
            },
        )
        self.assertEqual(invalid.status_code, 422)

    def test_user_records_and_private_material_are_isolated(self):
        client_a = self.new_client()
        client_b = self.new_client()
        user_a = self.register_and_login(client_a, "Student A", "a@example.com")
        self.register_and_login(client_b, "Student B", "b@example.com")

        task = self.request(
            client_a,
            "POST",
            "/api/tasks",
            json={
                "title": "Review cell biology",
                "due_date": date.today().isoformat(),
                "category": "Biology",
                "user_id": 999999,
            },
        )
        self.assertEqual(task.status_code, 201, task.text)
        task_id = task.json()["id"]

        exam = self.request(
            client_a,
            "POST",
            "/api/exams",
            json={
                "course": "Biology",
                "title": "Cell assessment",
                "exam_date": date.today().isoformat(),
            },
        )
        self.assertEqual(exam.status_code, 201, exam.text)

        plan = self.request(
            client_a,
            "POST",
            "/api/planner/generate",
            json={"subjects": ["Biology", "Chemistry"], "hours_per_day": 2},
        )
        self.assertEqual(plan.status_code, 200, plan.text)
        session_id = plan.json()["sessions"][0]["id"]

        with patch.object(
            main.ai,
            "tutor_answer",
            side_effect=main.ai.AIConfigurationError("Groq API key is not configured."),
        ):
            tutor = self.request(
                client_a,
                "POST",
                "/api/tutor",
                json={"question": "Explain cell biology", "course": "Biology"},
            )
        self.assertEqual(tutor.status_code, 200, tutor.text)

        with patch.object(
            main.ai,
            "generate_quiz",
            side_effect=main.ai.AIConfigurationError("Groq API key is not configured."),
        ):
            quiz = self.request(
                client_a,
                "POST",
                "/api/quizzes/generate",
                json={"topic": "Cell biology", "count": 3},
            )
        self.assertEqual(quiz.status_code, 200, quiz.text)
        score = self.request(
            client_a,
            "POST",
            "/api/quiz-scores",
            json={"topic": "Cell biology", "correct": 2, "total": 3},
        )
        self.assertEqual(score.status_code, 201, score.text)
        self.assertEqual(score.json()["total_questions"], 3)

        with patch.object(
            main.ai,
            "summarize_text",
            side_effect=main.ai.AIConfigurationError("Groq API key is not configured."),
        ):
            upload = self.request(
                client_a,
                "POST",
                "/api/summarize",
                files={"file": ("biology.pdf", create_pdf(), "application/pdf")},
            )
        self.assertEqual(upload.status_code, 200, upload.text)
        material_id = upload.json()["material_id"]

        own_file = client_a.get(f"/api/materials/{material_id}/file")
        self.assertEqual(own_file.status_code, 200)
        self.assertEqual(own_file.headers["content-type"], "application/pdf")
        self.assertEqual(own_file.content[:5], b"%PDF-")
        with patch.object(
            main.ai,
            "generate_quiz",
            side_effect=main.ai.AIConfigurationError("Groq API key is not configured."),
        ):
            quiz_from_notes = self.request(
                client_a,
                "POST",
                "/api/quizzes/generate",
                json={"material_id": material_id, "count": 3},
            )
        self.assertEqual(quiz_from_notes.status_code, 200, quiz_from_notes.text)

        dashboard_a = client_a.get("/api/dashboard").json()
        self.assertEqual([item["id"] for item in dashboard_a["tasks"]], [task_id])
        self.assertEqual([item["id"] for item in dashboard_a["exams"]], [exam.json()["id"]])
        self.assertEqual(dashboard_a["stats"]["quizzes_completed"], 1)
        self.assertEqual(dashboard_a["stats"]["average_score"], 67)
        self.assertEqual(dashboard_a["stats"]["total_materials"], 1)
        self.assertEqual(dashboard_a["scores"][0]["total_questions"], 3)
        self.assertEqual(len(dashboard_a["recent_conversations"]), 1)
        self.assertTrue(dashboard_a["study_activity"])
        self.assertEqual(client_a.get("/api/chat-history").json()["conversations"][0]["user_message"], "Explain cell biology")
        self.assertGreaterEqual(
            len(client_a.get("/api/study-history").json()["activities"]), 5
        )
        completed_task = self.request(
            client_a,
            "PATCH",
            f"/api/tasks/{task_id}",
            json={"completed": True},
        )
        self.assertEqual(completed_task.status_code, 200)
        completed_session = self.request(
            client_a,
            "PATCH",
            f"/api/planner/{session_id}",
            json={"completed": True},
        )
        self.assertEqual(completed_session.status_code, 200)

        dashboard_b = client_b.get("/api/dashboard").json()
        self.assertEqual(dashboard_b["tasks"], [])
        self.assertEqual(dashboard_b["exams"], [])
        self.assertEqual(dashboard_b["scores"], [])
        self.assertEqual(dashboard_b["stats"]["quizzes_completed"], 0)
        self.assertEqual(dashboard_b["stats"]["total_materials"], 0)
        self.assertEqual(dashboard_b["recent_conversations"], [])
        self.assertEqual(client_b.get("/api/materials").json()["materials"], [])
        self.assertEqual(client_b.get("/api/chat-history").json()["conversations"], [])
        self.assertEqual(client_b.get("/api/planner").json()["sessions"], [])
        self.assertEqual(client_b.get("/api/subjects").json()["subjects"], [])

        self.assertEqual(client_b.get(f"/api/materials/{material_id}/file").status_code, 404)
        self.assertEqual(self.request(client_b, "DELETE", f"/api/materials/{material_id}").status_code, 404)
        self.assertEqual(
            self.request(client_b, "PATCH", f"/api/tasks/{task_id}", json={"completed": True}).status_code,
            404,
        )
        self.assertEqual(
            self.request(client_b, "PATCH", f"/api/planner/{session_id}", json={"completed": True}).status_code,
            404,
        )
        self.assertEqual(
            self.request(
                client_b,
                "POST",
                "/api/quizzes/generate",
                json={"material_id": material_id, "count": 3},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.request(client_b, "GET", f"/api/materials/{material_id}/file").status_code,
            404,
        )
        self.assertEqual(
            self.request(client_a, "DELETE", f"/api/materials/{material_id}").status_code,
            200,
        )
        with closing(sqlite3.connect(self.database_path)) as db, db:
            task_owner = db.execute("SELECT user_id FROM tasks WHERE id = ?", (task_id,)).fetchone()[0]
        self.assertEqual(task_owner, user_a)

    def test_protected_routes_require_login_csrf_and_logout_clears_session(self):
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        user_id = self.register_and_login(self.client, "Student", "student@example.com")
        self.assertGreater(user_id, 0)
        dashboard = self.client.get("/api/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("no-store", dashboard.headers["cache-control"])

        no_csrf = self.client.post(
            "/api/tasks",
            json={"title": "A valid task", "due_date": date.today().isoformat(), "category": "Study"},
        )
        self.assertEqual(no_csrf.status_code, 403)

        cookie_name = "study_session"
        self.assertIn(cookie_name, self.client.cookies)
        login = self.request(
            self.client,
            "POST",
            "/api/auth/login",
            json={"email": "student@example.com", "password": "secure-study-password"},
        )
        self.assertEqual(login.status_code, 200)
        set_cookie = login.headers["set-cookie"].lower()
        self.assertIn("httponly", set_cookie)
        self.assertIn("samesite=lax", set_cookie)
        self.assertIn("max-age=43200", set_cookie)
        original_cookie = self.client.cookies.get(cookie_name)
        self.assertEqual(self.request(self.client, "POST", "/api/auth/logout").status_code, 200)
        self.assertNotIn(cookie_name, self.client.cookies)
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/").headers["cache-control"], "no-store")
        replay_client = self.new_client()
        self.assertEqual(
            replay_client.get(
                "/api/auth/me",
                headers={"Cookie": f"{cookie_name}={original_cookie}"},
            ).status_code,
            401,
        )

    def test_expired_session_cookie_is_rejected(self):
        self.register_and_login(self.client, "Student", "expired@example.com")
        with closing(sqlite3.connect(self.database_path)) as db:
            session_id = db.execute(
                "SELECT session_id FROM auth_sessions WHERE user_id = 1"
            ).fetchone()[0]
        middleware = next(item for item in main.app.user_middleware if item.cls is SessionMiddleware)
        old_signer = TimestampSigner(middleware.kwargs["secret_key"])
        session_data = json.dumps(
            {"user_id": 1, "csrf_token": "expired-token", "session_id": session_id}
        ).encode("utf-8")
        with patch("itsdangerous.timed.time.time", return_value=time.time() - 13 * 60 * 60):
            expired_cookie = old_signer.sign(b64encode(session_data)).decode("utf-8")
        expired_client = self.new_client()
        expired_response = expired_client.get(
            "/api/auth/me",
            headers={"Cookie": f"study_session={expired_cookie}"},
        )
        self.assertEqual(expired_response.status_code, 401)
        self.assertEqual(
            expired_client.get(
                "/api/dashboard",
                headers={"Cookie": f"study_session={expired_cookie}"},
            ).status_code,
            401,
        )

    def test_legacy_rows_are_preserved_but_not_visible_to_new_accounts(self):
        path = Path(self.directory.name) / "legacy.db"
        with patch.object(database, "DB_PATH", path):
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript(
                    """
                    CREATE TABLE tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                        due_date TEXT NOT NULL, category TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE TABLE exams (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, course TEXT NOT NULL,
                        title TEXT NOT NULL, exam_date TEXT NOT NULL
                    );
                    CREATE TABLE scores (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, course TEXT NOT NULL,
                        score INTEGER NOT NULL, label TEXT NOT NULL,
                        recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE study_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, study_date TEXT NOT NULL,
                        subject TEXT NOT NULL, activity TEXT NOT NULL, duration TEXT NOT NULL
                    );
                    CREATE TABLE materials (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL,
                        page_count INTEGER NOT NULL, text_content TEXT NOT NULL
                    );
                    CREATE TABLE subjects (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL COLLATE NOCASE UNIQUE
                    );
                    INSERT INTO tasks (title, due_date, category) VALUES ('Old shared task', '2026-11-06', 'Biology');
                    INSERT INTO exams (course, title, exam_date) VALUES ('Biology', 'Old exam', '2026-11-07');
                    INSERT INTO scores (course, score, label) VALUES ('Biology', 90, 'Old shared score');
                    INSERT INTO study_sessions (study_date, subject, activity, duration)
                        VALUES ('2026-11-06', 'Biology', 'Old activity', '1 hr');
                    INSERT INTO materials (filename, page_count, text_content)
                        VALUES ('old.pdf', 1, 'Old notes');
                    INSERT INTO subjects (name) VALUES ('Biology');
                    """
                )
            database.initialize_database()
            database.initialize_database()
            with closing(sqlite3.connect(path)) as db, db:
                for table in ("tasks", "exams", "scores", "study_sessions", "materials", "subjects"):
                    self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1)
                for table in ("tasks", "exams", "scores", "study_sessions", "materials", "subjects"):
                    self.assertIsNone(db.execute(f"SELECT user_id FROM {table}").fetchone()[0])
                self.assertIsNone(db.execute("SELECT total_questions FROM scores").fetchone()[0])
                self.assertEqual(
                    db.execute("SELECT title FROM tasks").fetchone()[0], "Old shared task"
                )
                self.assertEqual(
                    db.execute("SELECT title FROM exams").fetchone()[0], "Old exam"
                )
                self.assertEqual(
                    db.execute("SELECT label FROM scores").fetchone()[0], "Old shared score"
                )
                self.assertEqual(
                    db.execute("SELECT activity FROM study_sessions").fetchone()[0], "Old activity"
                )
                self.assertEqual(
                    db.execute("SELECT text_content FROM materials").fetchone()[0], "Old notes"
                )
                self.assertEqual(
                    db.execute("SELECT name FROM subjects").fetchone()[0], "Biology"
                )

            user_client = self.new_client()
            self.register_and_login(user_client, "New Student", "new@example.com")
            dashboard = user_client.get("/api/dashboard").json()
            self.assertEqual(dashboard["tasks"], [])
            self.assertEqual(dashboard["scores"], [])
            self.assertEqual(dashboard["stats"]["average_score"], 0)

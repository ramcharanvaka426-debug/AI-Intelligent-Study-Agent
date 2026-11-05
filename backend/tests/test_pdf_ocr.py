from contextlib import closing
from io import BytesIO
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pymupdf
from fastapi import UploadFile

from backend.app import database
from backend.app import main


def create_pdf(text: str, scanned: bool = False) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text, fontsize=14)
    if scanned:
        image = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).tobytes("png")
        scanned_document = pymupdf.open()
        scanned_page = scanned_document.new_page(width=page.rect.width, height=page.rect.height)
        scanned_page.insert_image(scanned_page.rect, stream=image)
        document.close()
        document = scanned_document
    content = document.tobytes()
    document.close()
    return content


class PdfOcrTests(unittest.TestCase):
    def setUp(self):
        self.database = sqlite3.connect(":memory:")
        self.database.row_factory = sqlite3.Row
        self.database.execute(
            "CREATE TABLE materials ("
            "id INTEGER PRIMARY KEY, filename TEXT, page_count INTEGER, text_content TEXT, "
            "short_summary TEXT, detailed_summary TEXT, pdf_content BLOB, user_id INTEGER)"
        )
        self.database.execute(
            "CREATE TABLE study_history ("
            "id INTEGER PRIMARY KEY, user_id INTEGER, activity TEXT, "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        self.database_context = patch("backend.app.main.connect", return_value=self.database)
        self.database_context.start()
        self.addCleanup(self.database_context.stop)
        self.addCleanup(self.database.close)
        self.summary_mock = Mock(
            return_value={"short_summary": "Short", "detailed_summary": "Detailed"}
        )
        self.summarize_patch = patch(
            "backend.app.main.ai.summarize_text", self.summary_mock
        )
        self.summarize_patch.start()
        self.addCleanup(self.summarize_patch.stop)

    def test_text_pdf_skips_ocr_and_is_saved(self):
        text = "This is selectable text from a regular PDF, and it is long enough to avoid OCR."
        content = create_pdf(text)
        engine = Mock()

        with patch("backend.app.main._get_ocr_engine", return_value=engine):
            result = main.summarize(
                UploadFile(filename="notes.pdf", file=BytesIO(content)),
                user_id=1,
                _=None,
            )

        engine.assert_not_called()
        self.assertEqual(result["pages"], 1)
        self.assertEqual(
            self.summary_mock.call_args.args[0].strip(),
            text,
        )
        saved = self.database.execute(
            "SELECT text_content, short_summary, detailed_summary FROM materials"
        ).fetchone()
        self.assertEqual(saved["text_content"].strip(), text)
        self.assertEqual(saved["short_summary"], "Short")
        self.assertEqual(saved["detailed_summary"], "Detailed")

    def test_scanned_pdf_uses_ocr_and_saves_extracted_text_and_summaries(self):
        content = create_pdf("A scanned page with recognizable text.", scanned=True)
        ocr_text = "OCR recovered this text from an image-only PDF. " * 2
        engine = Mock(return_value=SimpleNamespace(txts=[ocr_text]))

        with patch("backend.app.main._get_ocr_engine", return_value=engine):
            result = main.summarize(
                UploadFile(filename="scan.pdf", file=BytesIO(content)),
                user_id=1,
                _=None,
            )

        engine.assert_called_once()
        self.assertEqual(self.summary_mock.call_args.args[0], ocr_text.strip())
        self.assertEqual(result["pages"], 1)
        saved = self.database.execute(
            "SELECT text_content, short_summary, detailed_summary, pdf_content FROM materials"
        ).fetchone()
        self.assertEqual(saved["text_content"], ocr_text.strip())
        self.assertEqual(saved["short_summary"], "Short")
        self.assertEqual(saved["detailed_summary"], "Detailed")
        self.assertEqual(bytes(saved["pdf_content"]), content)

    def test_existing_database_gains_summary_columns(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "study_agent.db"
            with closing(sqlite3.connect(path)) as legacy_database, legacy_database:
                legacy_database.execute(
                    "CREATE TABLE materials ("
                    "id INTEGER PRIMARY KEY, filename TEXT NOT NULL, page_count INTEGER NOT NULL, "
                    "text_content TEXT NOT NULL, pdf_content BLOB)"
                )
            with patch.object(database, "DB_PATH", path):
                database.initialize_database()
            with closing(sqlite3.connect(path)) as migrated_database, migrated_database:
                columns = {
                    row[1]
                    for row in migrated_database.execute("PRAGMA table_info(materials)")
                }
            self.assertIn("short_summary", columns)
            self.assertIn("detailed_summary", columns)


if __name__ == "__main__":
    unittest.main()

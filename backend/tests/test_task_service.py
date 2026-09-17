import unittest
from unittest.mock import patch

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from backend.database import open_database
from backend.migrate import migrate
from backend.models import DocumentType, File, Task, TaskStatus
from backend.schemas import InitTaskRequestDTO
from backend.task_service import TaskService


class TaskServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine, sessions = open_database("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        migrate(self.engine)
        self.db = sessions()
        self.addCleanup(self.db.close)
        self.request = InitTaskRequestDTO(task_code="task-1", callback_url="https://integration.test/callback",
                                             document_link="s3://documents/input.pdf")

    def test_create_and_read(self):
        self.assertTrue(TaskService.create_task(self.request, self.db))
        self.assertTrue(TaskService.is_task_existing("task-1", self.db))
        self.assertEqual(TaskService.get_status_by_code("task-1", self.db), TaskStatus.PENDING)
        task, doc_type, callback, file = TaskService.get_task_data("task-1", self.db)
        self.db.expunge_all()
        self.assertEqual(doc_type.name, "generic")
        self.assertEqual(callback, self.request.callback_url)
        self.assertEqual(file.s3_link, self.request.document_link)
        self.assertEqual(task.file.task_id, task.id)

    def test_custom_document_type(self):
        self.db.add(DocumentType(name="invoice"))
        self.db.commit()
        request = self.request.model_copy(update={"document_type": "invoice"})
        TaskService.create_task(request, self.db)
        self.assertEqual(TaskService.get_task_data(request.task_code, self.db)[1].name, "invoice")

    def test_unknown_document_type_does_not_create_task(self):
        request = self.request.model_copy(update={"document_type": "unknown"})
        with self.assertRaisesRegex(ValueError, "DocumentType 'unknown' not found"):
            TaskService.create_task(request, self.db)
        self.assertFalse(TaskService.is_task_existing(request.task_code, self.db))

    def test_missing_task(self):
        self.assertFalse(TaskService.is_task_existing("missing", self.db))
        self.assertIsNone(TaskService.get_status_by_code("missing", self.db))
        self.assertIsNone(TaskService.get_task_data("missing", self.db))
        self.assertFalse(TaskService.update_task_status("missing", TaskStatus.DONE, self.db))

    def test_status_forms_and_completion_time(self):
        TaskService.create_task(self.request, self.db)
        for status in (TaskStatus.DONE, " done ", "ERROR", "response_sending_error", 2, 3, 4):
            with self.subTest(status=status):
                TaskService.update_task_status("task-1", TaskStatus.PROCESSING, self.db)
                self.assertIsNone(self.db.get(Task, "task-1").task_completion_time)
                self.assertTrue(TaskService.update_task_status("task-1", status, self.db))
                completed_at = self.db.get(Task, "task-1").task_completion_time
                self.assertIsNotNone(completed_at)
                TaskService.update_task_status("task-1", status, self.db)
                self.assertEqual(self.db.get(Task, "task-1").task_completion_time, completed_at)

    def test_invalid_status_does_not_modify_task(self):
        TaskService.create_task(self.request, self.db)
        for status in (-1, 5, "unknown", True, None):
            with self.subTest(status=status):
                with self.assertRaises((ValueError, TypeError)):
                    TaskService.update_task_status("task-1", status, self.db)
                self.assertEqual(TaskService.get_status_by_code("task-1", self.db), TaskStatus.PENDING)

    def test_duplicate_rolls_back_and_session_can_be_reused(self):
        TaskService.create_task(self.request, self.db)
        with self.assertRaises(IntegrityError):
            TaskService.create_task(self.request, self.db)
        self.assertTrue(self.db.is_active)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(File)), 1)
        TaskService.create_task(self.request.model_copy(update={"task_code": "task-2"}), self.db)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Task)), 2)

    def test_file_failure_rolls_back_task(self):
        invalid = self.request.model_copy(update={"document_link": None})
        with self.assertRaises(IntegrityError):
            TaskService.create_task(invalid, self.db)
        self.assertFalse(TaskService.is_task_existing("task-1", self.db))
        self.assertTrue(self.db.is_active)

    def test_missing_document_type_is_explicit(self):
        self.db.delete(self.db.scalar(select(DocumentType)))
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "DocumentType 'generic' not found"):
            TaskService.create_task(self.request, self.db)
        self.assertFalse(TaskService.is_task_existing("task-1", self.db))

    def test_read_failures_are_not_reported_as_missing(self):
        with patch.object(self.db, "scalar", side_effect=OperationalError("SELECT", {}, Exception("offline"))):
            for method in (TaskService.is_task_existing, TaskService.get_status_by_code, TaskService.get_task_data):
                with self.subTest(method=method.__name__), self.assertRaises(OperationalError):
                    method("task-1", self.db)

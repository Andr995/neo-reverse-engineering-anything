import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import zipfile
from unittest.mock import patch

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app import ExportWorker, Window, Settings
from engine import defaults


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rea-ui-test-")
        self.root = Path(self.temp.name)
        config = defaults()
        config["output"] = str(self.root / "reports")
        with patch("app.load_config", return_value=config):
            self.window = Window()
        self.window.show()

    def wait_idle(self):
        deadline = time.monotonic() + 15
        while self.window.worker or self.window.pending:
            self.app.processEvents()
            QTest.qWait(20)
            if time.monotonic() > deadline:
                self.fail("GUI worker did not settle")

    def tearDown(self):
        self.window.cancel()
        self.wait_idle()
        self.window.close()
        self.temp.cleanup()

    def test_drop_queue_report_and_zip(self):
        paths = [self.root / "uno.bin", self.root / "due.bin"]
        for path in paths:
            path.write_bytes(b"unknown format test\0")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        drop = QDropEvent(QPointF(100, 200), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        self.window.dropEvent(drop)
        self.wait_idle()
        self.assertEqual(self.window.jobs.count(), 2)
        self.assertEqual(self.window.report["status"], "partial")
        self.assertTrue(self.window.reveal.isEnabled())
        directory = Path(self.window.report["directory"])
        archive = self.root / "report.zip"
        export = ExportWorker(directory, archive)
        export.run()
        with zipfile.ZipFile(archive) as zipped:
            self.assertIn("report.json", zipped.namelist())
            self.assertEqual(json.loads(zipped.read("report.json"))["status"], "partial")

    def test_cancel_clears_pending_and_retains_current(self):
        paths = [self.root / "uno.bin", self.root / "due.bin"]
        for path in paths:
            path.write_bytes(b"\0" * (2 * 1024 * 1024))
        self.window.enqueue([str(path) for path in paths])
        self.window.cancel()
        self.wait_idle()
        self.assertFalse(self.window.pending)
        self.assertEqual(self.window.report["status"], "cancelled")
        self.assertTrue(self.window.jobs.item(1).text().startswith("Annullata"))

    def test_iso_drop_shows_project_and_export_excludes_executable(self):
        from test_ps2 import iso_fixture
        path = self.root / "disc.iso"
        iso_fixture(path)
        self.window.config.update(ps2_analyzer="", ps2_recompiler="", bt3_setup="")
        self.window.enqueue([str(path)])
        self.wait_idle()
        self.assertIn("SLUS-99999", self.window.ps2_details.toPlainText())
        self.assertFalse(self.window.port_folder.isEnabled())
        directory = Path(self.window.report["directory"])
        archive = self.root / "iso-report.zip"
        ExportWorker(directory, archive).run()
        with zipfile.ZipFile(archive) as zipped:
            self.assertIn("ps2-project.json", zipped.namelist())
            self.assertFalse(any("ps2-extracted" in name for name in zipped.namelist()))

    def test_settings_preserve_explicit_build_mode_and_tools(self):
        settings = Settings(defaults(), self.window)
        self.assertEqual(settings.values()["ps2_mode"], "recompile")
        mode = settings.fields["ps2_mode"]
        mode.setCurrentIndex(mode.findData("sources"))
        values = settings.values()
        self.assertEqual(values["ps2_mode"], "sources")
        self.assertIn("cmake", values)
        self.assertIn("raylib_source", values)
        settings.fields["executable_output"].setText(str(self.root / "giochi"))
        self.assertEqual(settings.values()["executable_output"], str(self.root / "giochi"))
        self.assertEqual(set(values), set(defaults()))
        settings.close()

    def test_running_build_shows_directory_and_compiler_output(self):
        release = threading.Event()
        directory = self.root / "reports" / "active"

        def slow_analysis(target, config, cancel, progress, on_directory):
            (directory / "native-build").mkdir(parents=True)
            (directory / "native-build/compiling.log").write_text("[45%] Building CXX object sample.cpp\n")
            on_directory(str(directory))
            progress("PS2: compilazione C++ e collegamento del runtime", 92)
            release.wait(10)
            return {"target": target, "status": "error", "error": "Fine della prova"}

        with patch("app.analyze", side_effect=slow_analysis):
            try:
                self.window.enqueue([str(self.root / "sample.iso")])
                deadline = time.monotonic() + 5
                while "sample.cpp" not in self.window.summary.toPlainText():
                    self.app.processEvents()
                    QTest.qWait(20)
                    self.assertLess(time.monotonic(), deadline)
                self.assertTrue(self.window.reveal.isEnabled())
                self.assertFalse(self.window.export.isEnabled())
                self.assertEqual(self.window.progress.maximum(), 0)
                self.assertNotIn("Pronto per", self.window.summary.toPlainText())
                with patch("app.QDesktopServices.openUrl") as open_url:
                    self.window.show_folder()
                    self.assertEqual(open_url.call_args.args[0].toLocalFile(), str(directory))
            finally:
                release.set()
                self.wait_idle()
        self.assertEqual(self.window.progress.maximum(), 100)
        self.assertFalse(self.window.analysis_timer.isActive())

    def test_show_compiled_executable_and_reject_external_path(self):
        directory = self.root / "report"
        binary = directory / "native-build/build/bin/rea-recompiled"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"test")
        report = {"target": "disc.iso", "directory": str(directory), "status": "partial", "ps2": {
            "build": {"status": "built_unverified", "executable": "native-build/build/bin/rea-recompiled"}}}
        self.window.display_report(report)
        self.assertTrue(self.window.executable_folder.isEnabled())
        with patch("app.QDesktopServices.openUrl") as open_url:
            self.window.show_executable_folder()
            self.assertEqual(open_url.call_args.args[0].toLocalFile(), str(binary.parent))
        report["ps2"]["build"]["executable"] = str(self.root / "external")
        (self.root / "external").write_bytes(b"test")
        self.window.display_report(report)
        self.assertFalse(self.window.executable_folder.isEnabled())

    def test_show_delivered_executable_prefers_selected_destination(self):
        from recompile import deliver_executable
        directory = self.root / "report"
        binary = directory / "native-build/build/bin/rea-recompiled"
        binary.parent.mkdir(parents=True)
        for name in ("rea-recompiled", "boot.elf", "disc-path.txt", "LEGGIMI.txt"):
            (binary.parent / name).write_bytes(b"test")
        delivery = deliver_executable(binary, self.root / "giochi", "game", lambda: None)
        report = {"target": "disc.iso", "directory": str(directory), "status": "partial", "ps2": {
            "build": {"status": "built_unverified", "executable": "native-build/build/bin/rea-recompiled", "delivery": delivery}}}
        self.window.display_report(report)
        with patch("app.QDesktopServices.openUrl") as open_url:
            self.window.show_executable_folder()
            self.assertEqual(open_url.call_args.args[0].toLocalFile(), delivery["directory"])
        Path(delivery["executable"]).unlink()
        self.assertEqual(self.window.compiled_executable(), binary)


if __name__ == "__main__":
    unittest.main()

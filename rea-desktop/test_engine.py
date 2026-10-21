import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from engine import Cancelled, analyze, classify, defaults, inspect_file


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rea-desktop-test-")
        self.root = Path(self.temporary.name)
        self.config = defaults()
        self.config["output"] = str(self.root / "reports")

    def tearDown(self):
        self.temporary.cleanup()

    def test_signatures_win_linux_and_managed(self):
        self.assertEqual(classify(b"\x7fELF" + bytes(100), ".exe"), "elf")
        pe = bytearray(512)
        pe[:2] = b"MZ"
        struct.pack_into("<I", pe, 0x3c, 0x80)
        pe[0x80:0x84] = b"PE\0\0"
        struct.pack_into("<H", pe, 0x80 + 20, 224)
        struct.pack_into("<H", pe, 0x80 + 24, 0x10b)
        self.assertEqual(classify(pe, ".so"), "pe")
        struct.pack_into("<I", pe, 0x80 + 24 + 92, 16)
        struct.pack_into("<II", pe, 0x80 + 24 + 96 + 14 * 8, 0x2000, 72)
        self.assertEqual(classify(pe, ".dll"), "dotnet")

    def test_truncated_pe_is_not_claimed_as_valid(self):
        self.assertEqual(classify(b"MZ", ".exe"), "malformed-pe")

    def test_portable_app_discovers_tools_and_honors_environment(self):
        package = self.root / "rea-desktop/dist/REA-Desktop"
        package.mkdir(parents=True)
        tools = self.root / ".tools"
        ghidra = tools / "ghidra_12.1.4_PUBLIC"
        jdk = tools / "jdk-21.0.12.1+1"
        launcher = "analyzeHeadless.bat" if os.name == "nt" else "analyzeHeadless"
        (ghidra / "support").mkdir(parents=True)
        (ghidra / "support" / launcher).touch()
        (jdk / "bin").mkdir(parents=True)
        for name in ("java", "javac"):
            (jdk / "bin" / (name + (".exe" if os.name == "nt" else ""))).touch()
        with patch("engine.ROOT", package), patch("engine.sys.frozen", True, create=True), patch.dict(os.environ, {}, clear=True):
            config = defaults()
            self.assertEqual(config["ghidra"], str(ghidra))
            self.assertEqual(config["java_home"], str(jdk))
            with patch.dict(os.environ, {"GHIDRA_INSTALL_DIR": "/explicit/ghidra", "JAVA_HOME": "/explicit/jdk"}):
                config = defaults()
                self.assertEqual(config["ghidra"], "/explicit/ghidra")
                self.assertEqual(config["java_home"], "/explicit/jdk")

    def test_hash_strings_and_no_execution(self):
        marker = self.root / "executed"
        target = self.root / "sample.sh"
        content = f"#!/bin/sh\ntouch '{marker}'\n".encode() + "HELLO".encode("utf-16-le")
        target.write_bytes(content)
        target.chmod(0o700)
        data = inspect_file(target, threading.Event())
        self.assertEqual(data["sha256"], hashlib.sha256(content).hexdigest())
        self.assertTrue(any(s["value"] == "HELLO" for s in data["strings"]))
        self.assertFalse(marker.exists())

    def test_unknown_format_saves_partial_report(self):
        target = self.root / "unknown.bin"
        target.write_bytes(b"unknown binary\x00")
        report = analyze(target, self.config, threading.Event())
        self.assertEqual(report["status"], "partial")
        directory = Path(report["directory"])
        self.assertTrue((directory / "report.md").is_file())
        self.assertEqual(json.loads((directory / "report.json").read_text())["status"], "partial")

    def test_cancellation_retains_report(self):
        target = self.root / "unknown.bin"
        target.write_bytes(b"abc")
        cancel = threading.Event()
        cancel.set()
        report = analyze(target, self.config, cancel)
        self.assertEqual(report["status"], "cancelled")
        self.assertTrue((Path(report["directory"]) / "report.json").is_file())

    def test_rejects_recursive_report_output(self):
        self.config["output"] = str(self.root / "nested")
        with self.assertRaises(ValueError):
            analyze(self.root, self.config, threading.Event())

    def test_missing_engine_preserves_basic_results(self):
        target = self.root / "linux-program"
        target.write_bytes(b"\x7fELF" + bytes(100))
        self.config["node"] = str(self.root / "absent-node")
        report = analyze(target, self.config, threading.Event())
        self.assertEqual(report["status"], "partial")
        self.assertIn("error", report)
        self.assertEqual(report["file"]["format"], "elf")

    def test_native_orchestration_preserves_success_and_failure(self):
        # Contract fixture only: this does NOT establish real Ghidra behavior.
        class FixtureClient:
            closed = False

            def __init__(self, *args):
                pass

            def initialize(self):
                return {"serverInfo": {"name": "fixture", "version": "0"}}

            def call(self, name, arguments):
                if name == "list_procedures":
                    value = [{"address": "0x1000", "value": "main"}, {"address": "0x2000", "value": "other"}]
                elif name == "analyze_function":
                    if arguments["procedure"] == "0x2000":
                        raise RuntimeError("fixture decompilation failure")
                    value = {"pseudocode": "int main(void) { return 42; }", "assembly": ["ret"]}
                else:
                    value = {}
                return {"normalized_result": value}

            def close(self):
                FixtureClient.closed = True
                return []

        target = self.root / "native-fixture"
        target.write_bytes(b"\x7fELF" + bytes(100))
        with patch("engine.ReaClient", FixtureClient):
            report = analyze(target, self.config, threading.Event())
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["functions_discovered"], 2)
        self.assertEqual(report["functions_decompiled"], 1)
        self.assertIn("return 42", (Path(report["directory"]) / report["functions"][0]["pseudocode_file"]).read_text())
        self.assertEqual(report["functions"][1]["error"], "fixture decompilation failure")
        self.assertTrue(FixtureClient.closed)

    @unittest.skipUnless(os.environ.get("REA_DESKTOP_INTEGRATION") == "1", "Enable real REA integration explicitly")
    def test_real_rea_javascript_session_and_cleanup(self):
        sample = self.root / "app with spaces"
        sample.mkdir()
        (sample / "package.json").write_text('{"name":"sample","version":"1.0.0","main":"index.js","type":"module"}')
        (sample / "index.js").write_text("export function add(a,b) { return a+b; }\n")
        report = analyze(sample, self.config, threading.Event())
        self.assertEqual(report["status"], "completed", report)
        evidence = json.loads((Path(report["directory"]) / "javascript.json").read_text())
        self.assertEqual(evidence["operation"], "analyze_javascript_application")
        self.assertTrue(evidence["normalized_result"]["graph"]["nodes"])
        self.assertFalse(any("Chiusura sessione" in str(v) for v in report["limitations"]))


if __name__ == "__main__":
    unittest.main()

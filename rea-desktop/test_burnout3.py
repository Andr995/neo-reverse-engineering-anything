import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import burnout3
from engine import analyze, defaults
from test_ps2 import iso_fixture, mips_elf
import threading


class BurnoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rea-burnout-")
        self.root = Path(self.temp.name)
        self.iso = self.root / "disc.iso"
        iso_fixture(self.iso, "SLUS_210.50")
        self.config = defaults()
        self.config.update(output=str(self.root / "reports"), ps2_analyzer="", ps2_recompiler="",
                           burnout3_executable="", proton_wine="", ps2_mode="existing_ports")

    def tearDown(self):
        self.temp.cleanup()

    def test_serial_alone_does_not_enable_port(self):
        report = analyze(self.iso, self.config, threading.Event())
        self.assertEqual(report["ps2"]["native_profile"]["status"], "incompatible_build")
        self.assertEqual(report["ps2"]["status"], "tools_missing")

    def test_launch_rechecks_disc_instead_of_trusting_report(self):
        with patch("burnout3.subprocess.Popen") as popen:
            with self.assertRaisesRegex(ValueError, "non corrisponde"):
                burnout3.launch(self.iso, self.config)
        popen.assert_not_called()

    def test_different_port_build_not_prepared(self):
        executable = self.root / "burnout3.exe"
        executable.write_bytes(b"not the official release")
        self.config["burnout3_executable"] = str(executable)
        result = burnout3.prepare(self.iso, {"boot_sha256": burnout3.BOOT_SHA256}, self.config)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("impronta diversa", result["reason"])

    @unittest.skipIf(os.name == "nt", "POSIX launcher quoting")
    def test_launcher_preserves_spaces_quotes_and_shell_metacharacters(self):
        executable = self.root / "fake host.exe"
        executable.write_text("import sys,json; print(json.dumps(sys.argv[1:]))\n")
        self.config.update(burnout3_executable=str(executable), proton_wine=sys.executable,
                           output=str(self.root / "reports ' $test"))
        iso = self.root / "disc ' $(touch SHOULD_NOT_EXIST).iso"
        with patch("burnout3.PORT_SHA256", hashlib.sha256(executable.read_bytes()).hexdigest()):
            profile = burnout3.prepare(iso, {"boot_sha256": burnout3.BOOT_SHA256}, self.config)
        self.assertEqual(profile["status"], "ready_to_launch")
        subprocess.run(["bash", profile["launcher"]], check=True, timeout=10)
        argv = json.loads((Path(profile["directory"]) / "burnout3.log").read_text())
        self.assertEqual(argv[argv.index("--disc") + 1], burnout3.windows_path(iso))
        self.assertFalse(list(self.root.rglob("SHOULD_NOT_EXIST")))

    def test_prepared_profile_skips_generic_translation_but_stays_unverified(self):
        with patch("burnout3.prepare", return_value={"id": "burnout3-usa", "status": "ready_to_launch",
                   "url": burnout3.URL, "execution": "test", "title": "Burnout 3"}), patch("ps2.generate_sources") as generate:
            result = analyze(self.iso, self.config, threading.Event())
        generate.assert_not_called()
        self.assertEqual(result["ps2"]["status"], "native_prepared")
        self.assertFalse(result["ps2"]["playable"])
        self.assertEqual(result["status"], "partial")


if __name__ == "__main__":
    unittest.main()

import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import ps2_runtime_fixes as fixes


class RuntimeFixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.boot = self.root / "boot.elf"
        self.boot.write_bytes(b"profile fixture")
        self.fingerprint = hashlib.sha256(self.boot.read_bytes()).hexdigest()
        self.runtime = self.root / "runtime"

    def copy_runtime(self):
        source = Path(__file__).resolve().parent.parent / "ps2recomp"
        if not all((source / name).is_file() for name in fixes.SOURCE_HASHES):
            self.skipTest("Local upstream runtime sources required")
        for name in fixes.SOURCE_HASHES:
            dest = self.runtime / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, dest)

    def test_unknown_game_does_not_patch_runtime(self):
        result = fixes.apply_runtime_fixes(self.runtime, self.boot)
        self.assertEqual(result["status"], "not_applicable")
        self.assertFalse(self.runtime.exists())

    def test_profile_records_disjoint_arenas_and_source_hashes(self):
        self.copy_runtime()
        with patch.object(fixes, "SUPPORTED_BOOT", self.fingerprint):
            result = fixes.apply_runtime_fixes(self.runtime, self.boot)
        arenas = [result[key] for key in ("guest_libc", "runtime_scratch", "callback_stacks", "main_stack")]
        previous = 0
        for low, high in arenas:
            low, high = int(low, 16), int(high, 16)
            self.assertLess(low, high)
            self.assertGreaterEqual(low, previous)
            previous = high
        self.assertLessEqual(previous, 32 * 1024 * 1024)
        for name, audit in result["changed_sources"].items():
            self.assertEqual(fixes.sha((self.runtime / name).read_bytes()), audit["after"])
            self.assertNotEqual(audit["before"], audit["after"])
        self.assertFalse(result["playable"])

    def test_unknown_runtime_revision_fails_before_any_mutation(self):
        self.copy_runtime()
        damaged = self.runtime / fixes.SYSTEM
        damaged.write_text(damaged.read_text() + "\n// Different revision\n")
        before = {name: (self.runtime / name).read_bytes() for name in fixes.SOURCE_HASHES}
        with patch.object(fixes, "SUPPORTED_BOOT", self.fingerprint), self.assertRaisesRegex(ValueError, "non verificata"):
            fixes.apply_runtime_fixes(self.runtime, self.boot)
        self.assertEqual(before, {name: (self.runtime / name).read_bytes() for name in before})


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch

import ps2_codegen_fixes as fixes


class DelayBoundaryTests(unittest.TestCase):
    def test_data_store_filter_preserves_unrelated_patches_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            boot = Path(folder) / "input.elf"
            boot.write_bytes(b"test image")
            fragment = lambda a, v: f'[[patches.instructions]]\naddress = "{a}"\nvalue = "{v}"\n\n'
            config = "[general]\n" + fragment("0x155128", "0x0") + fragment("0x17c538", "0x0") + "[performance]\na = true\n"
            self.assertEqual(fixes.restore_data_stores(config, boot)[0], config)
            with patch.object(fixes, "SUPPORTED_BOOT", hashlib.sha256(boot.read_bytes()).hexdigest()):
                updated, audit = fixes.restore_data_stores(config, boot)
                self.assertNotIn("0x155128", updated)
                self.assertIn(fragment("0x17c538", "0x0"), updated)
                self.assertTrue(updated.endswith("[performance]\na = true\n"))
                self.assertEqual(audit["restored"][0]["instruction"], "0xac50c9a4")
                self.assertEqual(fixes.restore_data_stores(updated, boot)[0], updated)
                inline = '[patches]\ninstructions = [\n { address = "0x155128", value = "0x0" }, # analyzer\n]\n'
                self.assertEqual(fixes.restore_data_stores(inline, boot)[0], '[patches]\ninstructions = [\n]\n')
                with self.assertRaisesRegex(ValueError, "non riconosciuta"):
                    fixes.restore_data_stores(fragment("0x155128", "0x1234"), boot)
                with self.assertRaisesRegex(ValueError, "duplicata"):
                    fixes.restore_data_stores(fragment("0x155128", "0") * 2, boot)

    def test_fingerprint_gate_and_unknown_translation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            boot = root / "input.elf"
            boot.write_bytes(b"unrelated executable")
            output = root / "output"
            output.mkdir()
            self.assertEqual(fixes.repair(boot, output)["status"], "not_applicable")
            translated = output / fixes.FILE
            translated.write_text("unexpected generator output")
            with patch.object(fixes, "SUPPORTED_BOOT", hashlib.sha256(boot.read_bytes()).hexdigest()):
                with self.assertRaisesRegex(ValueError, "non riconosciuta"):
                    fixes.repair(boot, output)
            self.assertEqual(translated.read_text(), "unexpected generator output")

    def test_repair_is_idempotent_and_preserves_other_code(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            boot = root / "input.elf"
            boot.write_bytes(b"test image")
            output = root / "output"
            output.mkdir()
            translated = output / fixes.FILE
            translated.write_text("prefix\n" + fixes.OLD + "\nsuffix\n")
            stores = output / fixes.STORE_FILE
            stores.write_text("".join(fixes.store_fragments(pc)[0] for pc in fixes.STORE_ADDRESSES))
            with patch.object(fixes, "SUPPORTED_BOOT", hashlib.sha256(boot.read_bytes()).hexdigest()):
                self.assertEqual(fixes.repair(boot, output)["status"], "applied")
                result = translated.read_bytes()
                self.assertEqual(fixes.repair(boot, output)["status"], "already_applied")
                self.assertEqual(translated.read_bytes(), result)
            self.assertEqual(translated.read_text(), "prefix\n" + fixes.NEW + "\nsuffix\n")
            self.assertEqual(stores.read_text(), "".join(fixes.store_fragments(pc)[1] for pc in fixes.STORE_ADDRESSES))

    def test_bad_store_does_not_leave_partial_delay_fix(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            boot = root / "input.elf"
            boot.write_bytes(b"test image")
            output = root / "output"
            output.mkdir()
            translated = output / fixes.FILE
            translated.write_text(fixes.OLD)
            (output / fixes.STORE_FILE).write_text("unknown code")
            with patch.object(fixes, "SUPPORTED_BOOT", hashlib.sha256(boot.read_bytes()).hexdigest()):
                with self.assertRaisesRegex(ValueError, "Store dati"):
                    fixes.repair(boot, output)
            self.assertEqual(translated.read_text(), fixes.OLD)

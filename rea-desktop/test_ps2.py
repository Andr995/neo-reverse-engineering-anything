"""Synthetic disc fixtures: no commercial game data or target execution."""
import hashlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from engine import analyze, defaults
from ps2 import Disc, run_tool


def mips_elf():
    data = bytearray(1024)
    data[:16] = b"\x7fELF\x01\x01\x01" + bytes(9)
    struct.pack_into("<HHIIIIIHHHHHH", data, 16, 2, 8, 1, 0x100000, 52, 512,
                     0x20924001, 52, 32, 1, 40, 5, 4)
    struct.pack_into("<IIIIIIII", data, 52, 1, 256, 0x100000, 0x100000, 12, 12, 5, 16)
    struct.pack_into("<III", data, 256, 0x2402002a, 0x03e00008, 0)
    struct.pack_into("<IIIBBH", data, 304, 1, 0x100000, 12, 0x12, 0, 1)
    data[320:326] = b"\0main\0"
    names = b"\0.text\0.symtab\0.strtab\0.shstrtab\0"
    data[336:336 + len(names)] = names
    for index, fields in enumerate((
            (1, 1, 6, 0x100000, 256, 12, 0, 0, 4, 0),
            (7, 2, 0, 0, 288, 32, 3, 1, 4, 16),
            (15, 3, 0, 0, 320, 6, 0, 0, 1, 0),
            (23, 3, 0, 0, 336, len(names), 0, 0, 1, 0)), 1):
        struct.pack_into("<10I", data, 512 + index * 40, *fields)
    return bytes(data)


def dual(value, width=4):
    return value.to_bytes(width, "little") + value.to_bytes(width, "big")


def record(name, sector, size, directory=False):
    length = 33 + len(name) + (len(name) % 2 == 0)
    result = bytearray(length)
    result[0] = length
    result[2:10] = dual(sector)
    result[10:18] = dual(size)
    result[25] = 2 if directory else 0
    result[28:32] = dual(1, 2)
    result[32] = len(name)
    result[33:33 + len(name)] = name
    return result


def iso_fixture(path, serial="SLUS_999.99", bad_name=None, bad_extent=False):
    data = bytearray(32 * 2048)
    primary = bytearray(2048)
    primary[:7] = b"\x01CD001\x01"
    primary[40:72] = b"REA SYNTHETIC PS2 TEST".ljust(32, b" ")
    primary[80:88] = dual(32)
    primary[128:132] = dual(2048, 2)
    root = record(b"\0", 20, 2048, True)
    primary[156:156 + len(root)] = root
    data[16 * 2048:17 * 2048] = primary
    data[17 * 2048:17 * 2048 + 7] = b"\xffCD001\x01"
    cnf = f"BOOT2 = cdrom0:\\{serial};1\r\nVER = 1.00\r\n".encode()
    executable = mips_elf()
    entries = root + record(b"\1", 20, 2048, True) + record(b"SYSTEM.CNF;1", 21, len(cnf))
    entries += record(bad_name or (serial + ";1").encode(), 200 if bad_extent else 22, len(executable))
    data[20 * 2048:20 * 2048 + len(entries)] = entries
    data[21 * 2048:21 * 2048 + len(cnf)] = cnf
    data[22 * 2048:22 * 2048 + len(executable)] = executable
    path.write_bytes(data)


class PS2Tests(unittest.TestCase):
    def test_callback_inference_requires_data_reference_and_return_boundary(self):
        from ps2 import callback_entries, apply_entry_hints
        data = bytearray(mips_elf())
        names = b"\0.text\0.symtab\0.strtab\0.shstrtab\0.rodata\0"
        data[336:336 + len(names)] = names
        struct.pack_into("<H", data, 48, 6)
        struct.pack_into("<I", data, 512 + 4 * 40 + 20, len(names))
        struct.pack_into("<I", data, 512 + 40 + 20, 40)
        struct.pack_into("<10I", data, 512 + 5 * 40, 33, 1, 2, 0x200000, 768, 32, 0, 0, 4, 0)
        # Return + non-NOP delay + zero/two padding NOPs; one unrelated pointer.
        struct.pack_into("<10I", data, 256, 0x03e00008, 0x2402002a, 0x24020001,
                         0x03e00008, 0x2402002a, 0, 0, 0x27bdfff0, 0x24020001, 0)
        struct.pack_into("<8I", data, 768, 0x100008, 0x10001c, 0x100020,
                         0x100009, 0x200000, 0x100008, 0, 0)
        addresses, evidence = callback_entries(data)
        self.assertEqual(addresses, {0x100008, 0x10001c})
        self.assertEqual(len(evidence), 2)
        broken = bytearray(data)
        struct.pack_into("<I", broken, 256, 0)
        self.assertEqual(callback_entries(broken)[0], {0x10001c})
        boot = self.root / "callbacks.elf"
        boot.write_bytes(data)
        fingerprint = hashlib.sha256(data).hexdigest()
        config = '[general]\ninput = "input.elf"\n'
        self.assertEqual(apply_entry_hints(config, boot, self.root)[0], config)
        with patch("ps2.CALLBACK_PROFILES", {fingerprint}):
            changed, audit = apply_entry_hints(config, boot, self.root)
        self.assertIn('"rea_observed@0x0010001C"', changed)
        self.assertEqual(audit["callback_entries"], evidence)

    def test_method_tables_require_header_pairs_and_code_addresses(self):
        from ps2 import method_entries
        data = bytearray(mips_elf())
        names = b"\0.text\0.symtab\0.strtab\0.shstrtab\0.rodata\0"
        data[336:336 + len(names)] = names
        struct.pack_into("<H", data, 48, 6)
        struct.pack_into("<I", data, 512 + 4 * 40 + 20, len(names))
        struct.pack_into("<10I", data, 512 + 5 * 40, 33, 1, 2, 0x200000, 768, 32, 0, 0, 8, 0)
        struct.pack_into("<8I", data, 768, 0, 0, 0, 0x100000, 0, 0x100004, 0, 0)
        addresses, tables = method_entries(data)
        self.assertEqual(addresses, {0x100000, 0x100004})
        self.assertEqual(len(tables), 1)
        for position, value in ((768, 1), (784, 4), (788, 0x200000), (788, 0x100001)):
            invalid = bytearray(data)
            struct.pack_into("<I", invalid, position, value)
            self.assertFalse(method_entries(invalid)[0])
        single = bytearray(data)
        struct.pack_into("<8I", single, 768, 0, 0, 0, 0x100000, 0, 0, 0, 0)
        self.assertEqual(method_entries(single)[0], {0x100000})
        struct.pack_into("<2I", single, 784, 0, 0x200000)
        self.assertFalse(method_entries(single)[0])
        struct.pack_into("<I", data, 512 + 5 * 40 + 20, 512)
        with self.assertRaises(ValueError):
            method_entries(data)

    def test_constructor_table_bounds_terminator_and_executable_targets(self):
        from ps2 import constructor_entries
        data = bytearray(mips_elf())
        struct.pack_into("<I", data, 52 + 16, 0x100)
        struct.pack_into("<4I", data, 384, 2, 0x100000, 0x100004, 0)
        self.assertEqual(constructor_entries(data, 0x100080), (0x100000, 0x100004))
        for field, value in ((384, 4097), (388, 0x200000), (388, 0x100001), (396, 1)):
            broken = bytearray(data)
            struct.pack_into("<I", broken, field, value)
            with self.assertRaises(ValueError):
                constructor_entries(broken, 0x100080)

    def test_observed_entry_hints_require_exact_boot_and_preserve_analyzer_entries(self):
        from ps2 import apply_entry_hints
        boot = self.root / "hint.elf"
        boot.write_bytes(b"test exact boot")
        fingerprint = hashlib.sha256(boot.read_bytes()).hexdigest()
        original = '[general]\nentry_points = [\n "original@0x100000",\n]\n[other]\nvalue = 7\n'
        with patch.dict("ps2.OBSERVED_ENTRY_HINTS", {fingerprint: (0x100010,)}, clear=True):
            changed, audit = apply_entry_hints(original, boot, self.root)
            self.assertIn('"rea_observed@0x00100010"', changed)
            self.assertIn('"original@0x100000"', changed)
            self.assertTrue(changed.endswith('[other]\nvalue = 7\n'))
            self.assertEqual(audit["addresses"], ["0x100010"])
            inserted, _ = apply_entry_hints('[general]\ninput = "input.elf"\n', boot, self.root)
            self.assertIn('entry_points = [', inserted)
            boot.write_bytes(b"different boot")
            unchanged, audit = apply_entry_hints(original, boot, self.root)
            self.assertEqual(unchanged, original)
            self.assertEqual(audit["addresses"], [])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rea ps2 ")
        self.root = Path(self.temp.name)
        self.path = self.root / "disc.iso"
        self.config = defaults()
        self.config.update(output=str(self.root / "reports"), ps2_analyzer="", ps2_recompiler="", bt3_setup="", ps2_mode="existing_ports")

    def tearDown(self):
        self.temp.cleanup()

    def analyze(self):
        return analyze(self.path, self.config, threading.Event())

    def test_iso_extract_hash_and_missing_tools_never_claim_playable(self):
        iso_fixture(self.path)
        result = self.analyze()
        self.assertNotIn("error", result)
        self.assertEqual(result["ps2"]["serial"], "SLUS-99999")
        self.assertEqual(result["ps2"]["status"], "tools_missing")
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["ps2"]["playable"])
        self.assertEqual(result["ps2"]["boot_sha256"], hashlib.sha256(mips_elf()).hexdigest())
        self.assertIsNone(result["file"]["entropy"])

    def test_known_serial_is_only_candidate_not_disc_validation(self):
        iso_fixture(self.path, "SLUS_216.78")
        result = self.analyze()
        self.assertFalse(result["ps2"]["native_profile"]["verified_disc"])
        self.assertEqual(result["ps2"]["native_profile"]["status"], "setup_missing")

    def test_unsafe_names_and_out_of_bounds_extents_rejected(self):
        for options in ({"bad_name": b"../ESCAPE;1"}, {"bad_extent": True}):
            with self.subTest(options=options):
                iso_fixture(self.path, **options)
                result = self.analyze()
                self.assertIn("error", result)
                self.assertEqual(result["ps2"]["status"], "error")
                self.assertFalse((self.root / "ESCAPE").exists())

    def test_directory_cycle_rejected(self):
        iso_fixture(self.path)
        data = bytearray(self.path.read_bytes())
        alias = record(b"CYCLE", 20, 2048, True)
        cursor = 20 * 2048
        while data[cursor]:
            cursor += data[cursor]
        data[cursor:cursor + len(alias)] = alias
        self.path.write_bytes(data)
        result = self.analyze()
        self.assertIn("ciclo", result["error"])

    def test_truncated_disc_and_non_ps2_disc_fail_without_success(self):
        self.path.write_bytes(b"not an iso")
        self.assertIn("error", self.analyze())
        iso_fixture(self.path)
        data = self.path.read_bytes().replace(b"BOOT2", b"BOOT1")
        self.path.write_bytes(data)
        self.assertIn("BOOT2", self.analyze()["error"])

    def test_cancellation_keeps_report(self):
        iso_fixture(self.path)
        cancel = threading.Event()
        def progress(message, percent):
            if percent == 15:
                cancel.set()
        result = analyze(self.path, self.config, cancel, progress)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["ps2"]["status"], "cancelled")
        self.assertTrue((Path(result["directory"]) / "ps2-project.json").exists())

    def test_tool_timeout(self):
        with self.assertRaises(TimeoutError):
            run_tool([sys.executable, "-c", "import time; time.sleep(10)"], self.root,
                     self.root / "timeout.log", 0.1, lambda: None)

    def test_recompiler_failure_is_reported_and_logs_preserved(self):
        iso_fixture(self.path)
        self.config.update(ps2_analyzer=sys.executable, ps2_recompiler=sys.executable)
        result = self.analyze()
        self.assertEqual(result["ps2"]["status"], "error")
        self.assertTrue((Path(result["directory"]) / "ps2-recomp/analyzer.log").exists())
        self.assertEqual(result["ps2"]["recompilation"]["status"], "error")

    def test_existing_port_setup_reports_preparation_not_gameplay(self):
        iso_fixture(self.path, "SLUS_216.78")
        suffix = ".exe" if os.name == "nt" else ""
        setup = self.root / ("Tenkaichi3Decomp-setup" + suffix)
        setup.touch()
        (self.root / ("Tenkaichi3Decomp" + suffix)).touch()
        self.config["bt3_setup"] = str(setup)
        with patch("ps2.run_tool") as runner:
            result = self.analyze()
        self.assertEqual(result["ps2"]["status"], "native_prepared")
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["ps2"]["playable"])
        self.assertEqual(runner.call_args.args[0], [setup, "--install", self.path])
        self.assertEqual(runner.call_count, 1)

    @unittest.skipUnless(os.environ.get("REA_BT3_INTEGRATION") == "1", "Requires local Tenkaichi3Decomp release")
    def test_official_setup_rejects_fake_disc_with_matching_serial(self):
        import shutil
        iso_fixture(self.path, "SLUS_216.78")
        source = Path(defaults()["bt3_setup"])
        self.assertTrue(source.is_file())
        package = self.root / "official-port"
        shutil.copytree(source.parent, package)
        self.config["bt3_setup"] = str(package / source.name)
        result = self.analyze()
        self.assertEqual(result["ps2"]["status"], "error")
        self.assertFalse(result["ps2"]["playable"])
        log = (Path(result["directory"]) / "ps2-port-setup.log").read_text()
        self.assertTrue(log.strip())
        self.assertNotIn("prepared_unverified", str(result))

    @unittest.skipUnless(os.environ.get("REA_PS2_INTEGRATION") == "1", "Requires locally built PS2Recomp")
    def test_real_mips_to_cpp_with_space_in_path(self):
        iso_fixture(self.path)
        actual = defaults()
        for key in ("ps2_analyzer", "ps2_recompiler"):
            self.assertTrue(actual[key], f"Missing {key}")
            self.config[key] = actual[key]
        result = self.analyze()
        self.assertNotIn("error", result, result.get("error"))
        self.assertEqual(result["ps2"]["status"], "sources_generated")
        sources = list((Path(result["directory"]) / "ps2-recomp/output").rglob("*.cpp"))
        self.assertTrue(sources)
        text = "\n".join(p.read_text() for p in sources)
        self.assertIn("0x2a", text.lower())
        self.assertFalse(result["ps2"]["playable"])


if __name__ == "__main__":
    unittest.main()

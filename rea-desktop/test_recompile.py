import json
import os
from pathlib import Path
import tempfile
import threading
import shutil
import subprocess
import unittest
from unittest.mock import patch

from engine import analyze, defaults
from recompile import build_ps2, LAUNCH_HEADER, prepare_launch_files, prepare_disc_modules, deliver_executable, digest
from test_ps2 import iso_fixture, mips_elf


class RecompileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rea new build '")
        self.root = Path(self.temp.name)
        self.config = defaults()
        self.config.update(output=str(self.root / "reports"), ps2_mode="recompile")

    def tearDown(self):
        self.temp.cleanup()

    def test_new_build_never_uses_known_precompiled_port(self):
        iso = self.root / "disc.iso"
        iso_fixture(iso, "SLUS_210.50")
        with patch("burnout3.prepare") as prepare, patch("ps2.generate_sources", return_value={
                "status": "sources_generated", "cpp_files": 2}), patch("recompile.build_ps2", return_value={
                "status": "build_failed", "reason": "compiler error", "limitations": []}):
            report = analyze(iso, self.config, threading.Event())
        prepare.assert_not_called()
        self.assertNotIn("native_profile", report["ps2"])
        self.assertEqual(report["ps2"]["status"], "build_failed")
        self.assertFalse(report["ps2"]["playable"])

    def test_sources_mode_never_compiles_or_runs_setup(self):
        iso = self.root / "disc.iso"
        iso_fixture(iso, "SLUS_216.78")
        self.config["ps2_mode"] = "sources"
        with patch("ps2.generate_sources", return_value={"status": "sources_generated"}), \
                patch("ps2.run_tool") as tool, patch("recompile.build_ps2") as build:
            report = analyze(iso, self.config, threading.Event())
        build.assert_not_called()
        tool.assert_not_called()
        self.assertEqual(report["ps2"]["status"], "sources_generated")

    def test_missing_build_tools_recorded_without_claiming_executable(self):
        self.config.update(cmake="", ps2_source="", raylib_source="")
        with patch("ps2.run_tool") as tool:
            result = build_ps2(self.root, self.config, lambda: None, lambda *_: None, lambda _: None)
        tool.assert_not_called()
        self.assertEqual(result["status"], "build_tools_missing")
        self.assertNotIn("executable", result)
        self.assertEqual(json.loads((self.root / "native-build/build.json").read_text()), result)

    def test_invalid_mode_fails_before_starting_tools(self):
        iso = self.root / "disc.iso"
        iso_fixture(iso)
        self.config["ps2_mode"] = "invented"
        with patch("ps2.run_tool") as tool:
            result = analyze(iso, self.config, threading.Event())
        tool.assert_not_called()
        self.assertIn("Modalità PS2", result["error"])

    @unittest.skipUnless(defaults()["cmake"], "CMake required")
    def test_cmake_error_is_retained_and_upstream_sources_untouched(self):
        source = self.root / "upstream"
        for component in ("ps2xRuntime", "ps2xIOP"):
            folder = source / component
            folder.mkdir(parents=True)
            (folder / "CMakeLists.txt").write_text('message(FATAL_ERROR "test-runtime-unavailable")\n')
        raylib = self.root / "raylib"
        (raylib / "src").mkdir(parents=True)
        (raylib / "src/raylib.h").write_text("// fixture\n")
        generated = self.root / "ps2-recomp/output"
        generated.mkdir(parents=True)
        (generated / "function.cpp").write_text("void fixture() {}\n")
        (generated.parent / "input.elf").write_bytes(b"test")
        self.config.update(ps2_source=str(source), raylib_source=str(raylib))
        result = build_ps2(self.root, self.config, lambda: None, lambda *_: None, lambda _: None)
        self.assertEqual(result["status"], "build_failed")
        self.assertNotIn("executable", result)
        self.assertIn("test-runtime-unavailable", (self.root / "native-build/configuring.log").read_text())
        self.assertEqual((source / "ps2xIOP/CMakeLists.txt").read_text(),
                         'message(FATAL_ERROR "test-runtime-unavailable")\n')
        self.assertEqual(json.loads((self.root / "native-build/build.json").read_text()), result)

    @unittest.skipUnless(os.environ.get("REA_BUILD_INTEGRATION") == "1", "Full local C++ toolchain/runtime build")
    def test_iso_to_new_executable(self):
        iso = self.root / "disc.iso"
        iso_fixture(iso)
        report = analyze(iso, self.config, threading.Event())
        build = report.get("ps2", {}).get("build", {})
        self.assertEqual(build.get("status"), "built_unverified", report)
        executable = Path(report["directory"]) / build["executable"]
        self.assertTrue(executable.is_file())
        self.assertEqual(executable.read_bytes()[:4], b"MZ\x90\x00" if os.name == "nt" else b"\x7fELF")
        self.assertFalse(build["executed"])
        self.assertFalse(report["ps2"]["playable"])

    @unittest.skipUnless(shutil.which("g++") and os.name != "nt", "Local Linux C++ compiler required")
    def test_direct_launch_paths_survive_different_cwd_and_moving_folder(self):
        bundle = self.root / "bin à spazi"
        bundle.mkdir()
        (bundle / "rea_launch.h").write_text(LAUNCH_HEADER)
        (bundle / "test.cpp").write_text('''#include "rea_launch.h"
#include <iostream>
int main(int argc, char** argv) {
    try { auto p = rea::inputs(argc, argv); std::cout << p.boot << "\\n" << p.disc; }
    catch (const std::exception& e) { std::cerr << e.what(); return 1; }
}
''')
        executable = bundle / "rea-recompiled"
        subprocess.run(["g++", "-std=c++20", str(bundle / "test.cpp"), "-o", str(executable)], check=True, capture_output=True)
        boot = self.root / "input.elf"
        boot.write_bytes(b"test boot")
        iso = self.root / "disco à.iso"
        iso.write_bytes(b"test ISO")
        prepare_launch_files(executable, boot, iso)
        first = subprocess.run([str(executable)], cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn(str(iso), first.stdout)
        moved = self.root / "spostato"
        bundle.rename(moved)
        executable = moved / executable.name
        iso.rename(moved / "disc.iso")
        second = subprocess.run([str(executable)], cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn(str(moved / "disc.iso"), second.stdout)
        (moved / "disc.iso").unlink()
        missing = subprocess.run([str(executable)], cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(missing.returncode, 1)
        self.assertIn("ISO not found", missing.stderr)

    def test_destination_preserves_existing_files_and_includes_launch_data(self):
        source = self.root / "bin"
        source.mkdir()
        executable = source / "rea-recompiled"
        executable.write_bytes(b"executable")
        executable.chmod(0o755)
        for name in ("boot.elf", "disc-path.txt", "LEGGIMI.txt", "runtime.dll"):
            (source / name).write_text(name)
        module = source / "disc-files/IOP/MODULE.IRX"
        module.parent.mkdir(parents=True)
        module.write_bytes(b"original IOP module")
        (source / "disc-files.json").write_text("[]")
        destination = self.root / "giochi à spazi"
        destination.mkdir()
        existing = destination / executable.name
        existing.write_bytes(b"do not replace")
        first = deliver_executable(executable, destination, "BURNOUT", lambda: None)
        second = deliver_executable(executable, destination, "BURNOUT", lambda: None)
        self.assertNotEqual(first["directory"], second["directory"])
        self.assertEqual(existing.read_bytes(), b"do not replace")
        self.assertEqual(Path(first["executable"]).read_bytes(), b"executable")
        self.assertTrue(os.access(first["executable"], os.X_OK))
        self.assertEqual((Path(first["directory"]) / "runtime.dll").read_text(), "runtime.dll")
        self.assertTrue((Path(first["directory"]) / "boot.elf").is_file())
        self.assertEqual((Path(first["directory"]) / "disc-files/IOP/MODULE.IRX").read_bytes(), module.read_bytes())
        self.assertTrue((Path(first["directory"]) / "disc-files.json").is_file())

    def test_extract_iop_modules_without_copying_other_disc_data(self):
        iso = self.root / "disc.iso"
        iso_fixture(iso, bad_name=b"MODULE.IRX;1")
        audit = prepare_disc_modules(self.root, iso, lambda: None)
        target = self.root / "disc-files/MODULE.IRX"
        self.assertEqual(target.read_bytes(), mips_elf())
        self.assertEqual(audit, [{"path": "MODULE.IRX", "size": len(mips_elf()), "sha256": digest(target)}])
        self.assertEqual(json.loads((self.root / "disc-files.json").read_text()), audit)
        self.assertEqual(list((self.root / "disc-files").iterdir()), [target])
        with self.assertRaises(ValueError):
            prepare_disc_modules(self.root, iso, lambda: None)
        self.assertEqual(target.read_bytes(), mips_elf())

    def test_extract_iop_rejects_host_device_names_and_unsafe_paths(self):
        iso = self.root / "disc.iso"
        for name in (b"../ESCAPE.IRX;1", b"CON.IRX;1", b"LPT1.IRX;1", b"A:BAD.IRX;1"):
            with self.subTest(name=name):
                iso_fixture(iso, bad_name=name)
                with self.assertRaises(ValueError):
                    prepare_disc_modules(self.root, iso, lambda: None)
                self.assertFalse((self.root / "disc-files").exists())
                self.assertFalse(list(self.root.glob(".rea-modules-*")))

    def test_cancel_during_extraction_removes_partial_modules(self):
        from ps2 import Disc
        iso = self.root / "disc.iso"
        iso_fixture(iso, bad_name=b"MODULE.IRX;1")
        def cancelled_after_write(disc, entry, target):
            target.write_bytes(b"partial")
            raise InterruptedError("cancelled")
        with patch.object(Disc, "extract", cancelled_after_write):
            with self.assertRaises(InterruptedError):
                prepare_disc_modules(self.root, iso, lambda: None)
        self.assertFalse((self.root / "disc-files").exists())
        self.assertFalse((self.root / "disc-files.json").exists())
        self.assertFalse(list(self.root.glob(".rea-modules-*")))

    def test_module_extraction_budget_checked_before_writing(self):
        iso = self.root / "disc.iso"
        iso_fixture(iso)
        for entries in ([{"path": "HUGE.IRX", "directory": False, "size": 64 * 1024 * 1024 + 1}],
                        [{"path": "SMALL.IRX", "directory": False, "size": 1}] * 1025):
            with patch("ps2.Disc.inventory", return_value=({}, entries)), patch("ps2.Disc.extract") as extract:
                with self.assertRaises(ValueError):
                    prepare_disc_modules(self.root, iso, lambda: None)
                extract.assert_not_called()
                self.assertFalse((self.root / "disc-files").exists())

    @unittest.skipIf(os.name == "nt", "Symlink creation may require Windows privileges")
    def test_delivery_rejects_module_symlinks_and_cleans_copy(self):
        source = self.root / "bin"
        source.mkdir()
        for name in ("rea-recompiled", "boot.elf", "disc-path.txt", "LEGGIMI.txt"):
            (source / name).write_text(name)
        modules = source / "disc-files"
        modules.mkdir()
        (modules / "LINK.IRX").symlink_to(source / "boot.elf")
        destination = self.root / "destination"
        with self.assertRaises(ValueError):
            deliver_executable(source / "rea-recompiled", destination, "game", lambda: None)
        self.assertFalse(list(destination.iterdir()))
        self.assertTrue((modules / "LINK.IRX").is_symlink())

    def test_destination_failure_cleans_only_incomplete_copy(self):
        source = self.root / "bin"
        source.mkdir()
        executable = source / "rea-recompiled"
        executable.write_bytes(b"original")
        destination = self.root / "destination"
        with self.assertRaises(OSError):
            deliver_executable(executable, destination, "game", lambda: None)
        self.assertFalse(list(destination.iterdir()))
        self.assertEqual(executable.read_bytes(), b"original")

    def test_destination_error_preserves_successful_build_status(self):
        source = self.root / "sources"
        for component in ("ps2xRuntime", "ps2xIOP"):
            (source / component).mkdir(parents=True)
            (source / component / "CMakeLists.txt").write_text("# test")
        raylib = self.root / "raylib"
        (raylib / "src").mkdir(parents=True)
        (raylib / "src/raylib.h").write_text("// test")
        generated = self.root / "ps2-recomp/output"
        generated.mkdir(parents=True)
        (generated.parent / "input.elf").write_bytes(b"boot")
        cmake = self.root / "cmake"
        cmake.write_text("test")
        destination = self.root / "not-a-directory"
        destination.write_text("preserve")
        self.config.update(cmake=str(cmake), ps2_source=str(source), raylib_source=str(raylib), executable_output=str(destination))

        def successful_compiler(command, work, *args):
            if "--build" not in command:
                (work / "build").mkdir()
                (work / "build/CMakeCache.txt").write_text("PS2X_ENABLE_FFMPEG:BOOL=ON\n")
            if "--build" in command:
                binary = work / "build/bin" / ("rea-recompiled.exe" if os.name == "nt" else "rea-recompiled")
                binary.parent.mkdir(parents=True)
                binary.write_bytes(b"compiled fixture")

        with patch("ps2.run_tool", side_effect=successful_compiler):
            result = build_ps2(self.root, self.config, lambda: None, lambda *_: None, lambda _: None, iso_path=self.root / "disc.iso")
        self.assertEqual(result["status"], "built_unverified")
        self.assertTrue(result["ffmpeg"])
        self.assertEqual(result["delivery"]["status"], "failed")
        self.assertTrue((self.root / result["executable"]).is_file())
        self.assertEqual(destination.read_text(), "preserve")
        self.assertEqual(json.loads((self.root / "native-build/build.json").read_text()), result)


if __name__ == "__main__":
    unittest.main()

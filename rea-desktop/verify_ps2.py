"""Retain a reproducible, self-owned synthetic ISO → C++ verification report."""
import argparse
import json
from pathlib import Path
import threading

from engine import analyze, defaults
from test_ps2 import iso_fixture, mips_elf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundled", action="store_true")
    parser.add_argument("--build", action="store_true", help="Build a new native executable and verify the translated fixture function")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    example = root / "examples/ps2-homebrew.iso"
    iso_fixture(example)
    (root / "examples/ps2-homebrew.elf").write_bytes(mips_elf())
    config = defaults()
    config["ps2_mode"] = "recompile" if args.build else "sources"
    config["output"] = str(root / "reports/ps2-verification")
    if args.bundled:
        runtime = root / "dist/REA-Desktop/runtime/ps2recomp"
        import os
        suffix = ".exe" if os.name == "nt" else ""
        config.update(ps2_analyzer=str(runtime / ("ps2_analyzer" + suffix)),
                      ps2_recompiler=str(runtime / ("ps2_recomp" + suffix)))
    report = analyze(example, config, threading.Event(), lambda message, _: print(message, flush=True))
    if report.get("ps2", {}).get("status") != ("built_unverified" if args.build else "sources_generated"):
        raise RuntimeError(json.dumps(report, ensure_ascii=False, indent=2))
    assert report["status"] == "partial" and not report["ps2"]["playable"]
    output = Path(report["directory"]) / "ps2-recomp/output"
    sources = list(output.rglob("*.cpp"))
    assert sources and "0x2a" in "\n".join(p.read_text().lower() for p in sources)
    if args.build:
        from ps2 import run_tool
        work = Path(report["directory"]) / "native-build"
        # Verify default paths from another working directory without running the guest.
        import subprocess
        executable = Path(report["directory"]) / report["ps2"]["build"]["executable"]
        probe = subprocess.run([str(executable), "--check-inputs"], cwd=root, capture_output=True, text=True, timeout=10)
        assert probe.returncode == 0, probe.stderr
        assert str(example.resolve()) in probe.stdout, probe.stdout
        (work / "launch-path-verification.json").write_text(json.dumps({
            "passed": True, "returncode": probe.returncode, "output": probe.stdout,
            "scope": "Default input paths only; guest not executed."}, indent=2))
        # Execute only our three-instruction fixture, not a supplied game.
        (work / "verify_fixture.cpp").write_text('''#include "ps2_runtime.h"
#include <iostream>
int main() {
  R5900Context ctx;
  if (g_ps2RecompiledFunctionTableBase != 0x100000 || !g_ps2RecompiledFunctionTable[0]) return 1;
  g_ps2RecompiledFunctionTable[0](nullptr, &ctx, nullptr);
  const auto value = getRegU32(&ctx, 2);
  std::cout << value << "\\n";
  return value == 42 ? 0 : 2;
}
''', encoding="utf-8")
        with (work / "CMakeLists.txt").open("a", encoding="utf-8") as cmake:
            cmake.write('''
add_executable(verify_fixture verify_fixture.cpp ${translated})
target_include_directories(verify_fixture PRIVATE ../ps2-recomp/output)
target_link_libraries(verify_fixture PRIVATE ps2_runtime)
''')
        run_tool([config["cmake"], "-S", ".", "-B", "build"], work, work / "verify-configure.log", 900, lambda: None)
        run_tool([config["cmake"], "--build", "build", "--target", "verify_fixture", "--config", "Release", "--parallel", "2"],
                 work, work / "verify-build.log", 900, lambda: None)
        import os
        executable = work / "build/bin" / ("verify_fixture.exe" if os.name == "nt" else "verify_fixture")
        run_tool([executable], work, work / "verify-function.log", 10, lambda: None)
        assert (work / "verify-function.log").read_text().strip() == "42"
        (work / "fixture-verification.json").write_text(json.dumps({
            "passed": True, "expected_register_v0": 42, "observed_register_v0": 42,
            "scope": "Own three-instruction fixture only; no game or hardware-equivalence claim."}, indent=2))
    print(json.dumps({"report": report["directory"], "cpp_files": len(sources),
                      "status": report["ps2"]["status"], "playable": False}, indent=2))


if __name__ == "__main__":
    main()

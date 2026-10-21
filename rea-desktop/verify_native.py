"""Integration verification on self-owned ELF/PE fixtures, without executing them."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import threading

from engine import analyze, defaults


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundled", action="store_true")
    parser.add_argument("--build-fixtures", action="store_true", help="Rebuild on Linux with GCC and GNU binutils")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if args.build_fixtures:
        examples = root / "examples"
        for platform, extra in (("linux", []), ("windows", ["-DWINDOWS_FIXTURE"])):
            obj = f"native-{platform}.o"
            subprocess.run(["gcc", "-O1", "-fno-ident", "-ffreestanding", "-fno-pie",
                            "-fno-stack-protector", "-fno-asynchronous-unwind-tables", *extra,
                            "-c", "native-fixture.c", "-o", obj], cwd=examples, check=True)
            linker_args = ["-mi386pep", "--subsystem", "console"] if platform == "windows" else []
            suffix = "exe" if platform == "windows" else "elf"
            subprocess.run(["ld", *linker_args, "--entry=entry", obj, "-o", f"native-{platform}.{suffix}"], cwd=examples, check=True)
    config = defaults()
    config["output"] = str(root / "reports" / "native-verification")
    if args.bundled:
        runtime = root / "dist/REA-Desktop/runtime"
        config["node"] = str(runtime / ("node.exe" if os.name == "nt" else "node"))
        config["rea"] = str(runtime / "rea/scripts/rea.mjs")
    env = os.environ.copy()
    env.update(GHIDRA_INSTALL_DIR=config["ghidra"], JAVA_HOME=config["java_home"])
    env["PATH"] = str(Path(config["java_home"]) / "bin") + os.pathsep + env["PATH"]
    doctor = subprocess.run([config["node"], config["rea"], "doctor", "--provider", "ghidra", "--json"],
                            env=env, capture_output=True, text=True, check=False)
    payload = json.loads(doctor.stdout)
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports/ghidra-doctor.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    assert payload["healthy"], payload["scope_checks"]
    print("Ghidra doctor: PASS", flush=True)
    for filename in ("native-linux.elf", "native-windows.exe"):
        print("Analisi:", filename, flush=True)
        report = analyze(root / "examples" / filename, config, threading.Event(),
                         lambda message, percent: print(f"  {percent}% {message}", flush=True))
        summary = {key: report.get(key) for key in ("status", "functions_discovered", "functions_decompiled", "elapsed_seconds", "directory", "error")}
        print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
        assert report["status"] == "completed", summary
        assert report["functions_decompiled"] >= 2, summary
        # PE COFF symbol names need not survive the provider's import. Resolve
        # the function using the original fixture's linker address, not a label.
        symbols = subprocess.check_output(["nm", "--defined-only", str(root / "examples" / filename)], text=True)
        expected_address = next(int(line.split()[0], 16) for line in symbols.splitlines()
                                if len(line.split()) == 3 and line.split()[2] == "calculate_score")
        score = next(f for f in report["functions"] if int(f["address"], 16) == expected_address)
        code = (Path(report["directory"]) / score["pseudocode_file"]).read_text()
        assert "42" in code or "0x2a" in code.lower(), code
        print("Pseudocodice calculate_score verificato.", flush=True)


if __name__ == "__main__":
    main()

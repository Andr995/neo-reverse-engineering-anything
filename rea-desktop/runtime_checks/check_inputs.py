"""Compile and run the real native input checks against a local build."""
from pathlib import Path
import json
import re
import shlex
import subprocess
import sys

app = Path(__file__).resolve().parents[1]
work = Path(sys.argv[1]).resolve()
checks = work / "checks"
checks.mkdir(exist_ok=True)
flags = (work / "build/runtime/ps2xRuntime/CMakeFiles/ps2_runtime.dir/flags.make").read_text()
includes = shlex.split(next(line.split("=", 1)[1] for line in flags.splitlines() if line.startswith("CXX_INCLUDES =")))
common = ["g++", "-std=c++20", "-O1", "-mavx2", "-ffunction-sections", "-fdata-sections", *includes]
video_libraries = []
cache = (work / "build/CMakeCache.txt").read_text()
if re.search(r"(?m)^PS2X_ENABLE_FFMPEG:BOOL=(ON|TRUE|1)$", cache):
    video_libraries = shlex.split(subprocess.check_output(
        ["pkg-config", "--libs", "libavcodec", "libavformat", "libavutil",
         "libswresample", "libswscale"], text=True))
sys.path.insert(0, str(app))
import ps2_input_ui
(checks / "rea_controls_fixture.h").write_text(ps2_input_ui.CPP)
commands = [
    ("controls-config", [*common, "-I" + str(checks), str(app / "runtime_checks/controls_config.cpp"), "-Wl,--gc-sections"]),
    ("keyboard-input", [*common, str(app / "runtime_checks/keyboard_input.cpp"),
                        str(work / "runtime/ps2xRuntime/src/lib/ps2_pad.cpp"), "-Wl,--gc-sections"]),
    ("pad2-input", [*common, "-I" + str(work.parent / "ps2-recomp/output"),
                   str(app / "runtime_checks/pad2_input.cpp"),
                   str(work.parent / "ps2-recomp/output/sub_003A27E0_0x3a27e0.cpp"),
                   str(work / "build/runtime/ps2xRuntime/libps2_runtime.a"),
                   str(work / "build/runtime/ps2xIOP/libps2_iop.a"),
                   str(work / "build/_deps/raylib-build/raylib/libraylib.a"),
                   "-lGL", "-lm", "-lpthread", "-ldl", "-lrt", *video_libraries,
                   *("-Wl,--wrap=" + name for name in (
                       "IsWindowReady", "IsKeyDown", "IsGamepadAvailable",
                       "IsGamepadButtonDown", "GetGamepadAxisMovement"))]),
]
audit = []
for name, command in commands:
    binary = checks / name
    command += ["-o", str(binary)]
    run = [str(binary)]
    if name == "controls-config":
        preference = checks / "test-controls.ini"
        preference.unlink(missing_ok=True)
        run.append(str(preference))
    with (checks / (name + ".log")).open("w") as log:
        subprocess.run(command, stdout=log, stderr=log, check=True)
        subprocess.run(run, stdout=log, stderr=log, check=True, timeout=20)
    audit.append({"name": name, "compile": command, "run": run, "passed": True})
    print(name, "PASS", flush=True)
(checks / "input-checks.json").write_text(json.dumps(audit, indent=2) + "\n")

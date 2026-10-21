"""Sample stacks of a newly launched child under GDB; never attach to a user process."""
from pathlib import Path
import argparse
import os
import signal
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("native_build", type=Path, help="Existing native-build directory (Linux/GDB)")
work = parser.parse_args().native_build.resolve()
exe = work / "build/bin/rea-recompiled"
if not exe.is_file():
    parser.error("Missing build/bin/rea-recompiled")
(work / "checks").mkdir(exist_ok=True)
script = work / "checks/profile-child.gdb"
script.write_text(r"""
set pagination off
set confirm off
set print thread-events off
set debuginfod enabled off
set environment REA_SKIP_CONTROLS 1
unset environment REA_DIAGNOSTICS
unset environment REA_PAD_TRACE
break main
run
delete breakpoints
python
import os, signal, threading, gdb
pid=gdb.selected_inferior().pid
def interrupt():
    try: os.kill(pid,signal.SIGINT)
    except ProcessLookupError: pass
for index in range(12):
    timer=threading.Timer(55 if index==0 else .7, interrupt)
    timer.daemon=True
    timer.start()
    gdb.execute('continue')
    timer.cancel()
    gdb.write('\\nREA_PROFILE_SAMPLE %d\\n' % index)
    gdb.execute('thread apply all bt 12')
end
kill
quit
""")
with (work / "checks/profile-child.log").open("w") as log:
    process = subprocess.Popen(["gdb", "-q", "-batch", "-x", str(script), "--args", str(exe)],
                               cwd=exe.parent, stdout=log, stderr=log, start_new_session=True)
    try:
        print(process.wait(timeout=85), flush=True)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

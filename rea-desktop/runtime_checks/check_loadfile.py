from pathlib import Path
import subprocess
import sys
app = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(app))
from ps2_sif_fixes import LOADFILE
work = Path(sys.argv[1]).resolve()
checks = work / "checks"
checks.mkdir(parents=True, exist_ok=True)
(checks / "rea_loadfile_fixture.h").write_text(LOADFILE)
exe = checks / "loadfile-rpc"
with (checks / "loadfile-rpc.log").open("w") as log:
    subprocess.run(["g++","-std=c++20","-O2","-I"+str(checks),
                    "-I"+str(work/"runtime/ps2xIOP/include"),
                    str(app/"runtime_checks/loadfile_rpc.cpp"),"-o",str(exe)],
                   check=True,stdout=log,stderr=log)
    subprocess.run([str(exe)],check=True,stdout=log,stderr=log,timeout=10)
print("LOADFILE protocol PASS")

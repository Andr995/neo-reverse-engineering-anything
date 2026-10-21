"""Compile the actual regenerated SW expressions and check the guest writes."""
from pathlib import Path
import json
import re
import subprocess
import sys

app = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(app))
from ps2_codegen_fixes import DATA_STORE_WORDS
work = Path(sys.argv[1]).resolve()
output = work.parent / "ps2-recomp/output"
changed = json.loads((work / "data-store-generation/changed.json").read_text())
sources = "\n".join((output / name).read_text() for name in changed if name.endswith(".cpp"))
destinations = [
    0x45f010,0x45ac84,0x45c9a4,0x45dca4,0x45dca8,0x45dcac,0x45dcb0,
    0x466fd8,0x467000,0x467014,0x467024,0x46e7c4,0x46e7c0,0x46e7c0,
    0x47a880,0x47a8a4,0x47a898,0x47a910,0x47aa04,0x47aa08,0x47b0c4,
    0x47b20c,0x47b7b4,0x47bcbc,0x47c1ac,0x47c1ac,0x47d55c,0x45f00c,
]
prefix = r"""
#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>
struct Context { uint32_t gpr[32]{}; uint32_t pc=0; } cpu;
auto *ctx=&cpu;
std::array<uint8_t,0x2000000> ram{};
auto *rdram=ram.data();
#define GPR_U32(c,r) ((c)->gpr[r])
#define ADD32(a,b) (uint32_t((a)+(b)))
#define WRITE32(a,b) do {uint32_t v=(b);std::memcpy(rdram+(a),&v,4);} while(0)
#define FAST_WRITE32(a,b) WRITE32(a,b)
#define ps2TraceGuestWrite(...) ((void)0)
int main() { unsigned failures=0;
"""
cases = []
for (pc, word), dest in zip(DATA_STORE_WORDS.items(), destinations, strict=True):
    expression = re.search(rf"// 0x{pc:x}: 0x{word:x}  sw[^\n]*\n(?:\s*ctx->pc =[^\n]*\n)?([^\n]+)", sources)
    if pc in (0x38a664, 0x38aa08):
        # These blocks are not part of the generated function map in this build.
        assert expression is None
        continue
    assert expression and "WRITE32" in expression[1], hex(pc)
    rs, rt, immediate = word >> 21 & 31, word >> 16 & 31, word & 65535
    immediate -= 65536 if immediate >= 32768 else 0
    expected = 0x12345678 if rt else 0
    cases.append(f"""
    cpu={{}}; ram.fill(0xa5);
    cpu.gpr[{rs}]=0x{dest-immediate:x}; cpu.gpr[{rt}]=0x{expected:x};
    /* STORE */
    uint32_t value_{pc:x}; std::memcpy(&value_{pc:x},rdram+0x{dest:x},4);
    if(value_{pc:x}!=0x{expected:x} || ram[0x{dest-1:x}]!=0xa5 || ram[0x{dest+4:x}]!=0xa5) ++failures;
""".replace("/* STORE */", expression[1].strip()))
suffix = '\nstd::cout<<"Store failures: "<<failures<<" / 26 emitted stores\\n";return failures?1:0;}\n'
for name, body, expected_code in [
    ("before", "\n".join(re.sub(r"(?m)^    (?:do \{|WRITE32\().*$", "    // removed store", case) for case in cases), 1),
    ("after", "\n".join(cases), 0),
]:
    source = work / f"checks/global-stores-{name}.cpp"
    source.write_text(prefix + body + suffix)
    binary = source.with_suffix("")
    subprocess.run(["g++", "-std=c++20", "-O1", str(source), "-o", str(binary)], check=True)
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    (work / f"checks/global-stores-{name}.log").write_text(result.stdout + result.stderr)
    assert result.returncode == expected_code, (name, result.stdout)
    print(name, result.stdout.strip())

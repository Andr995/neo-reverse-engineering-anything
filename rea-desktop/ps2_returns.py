"""Recover unregistered two-instruction return entries from executable ELF sections.

Only JR ra with NOP or DADDU in its delay slot is recognized. This does not
replace missing functions with stubs: the two original instructions are emitted.
"""
import json
from pathlib import Path
import re
import struct


def recover(boot, output, check=lambda: None):
    output = Path(output)
    data = Path(boot).read_bytes()
    if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01" or struct.unpack_from("<H", data, 18)[0] != 8:
        raise ValueError("Return entries: expected ELF32 little-endian MIPS.")
    register = (output / "register_functions.cpp").read_text(encoding="utf-8")
    def constant(name):
        match = re.search(r"\b" + name + r"\s*=\s*(0x[0-9a-fA-F]+|[0-9]+)u?;", register)
        if not match:
            raise ValueError("Return entries: unsupported generated registration table.")
        return int(match[1], 0)
    base, end = (constant("g_ps2RecompiledFunctionTable" + part) for part in ("Base", "End"))
    slots = constant("g_ps2RecompiledFunctionTableSlotCount")
    if base & 3 or end & 3 or end < base or end > 0x100000000 or end - base != slots * 4:
        raise ValueError("Return entries: invalid registration bounds.")
    known = {int(m[1]) for m in re.finditer(r"g_ps2RecompiledFunctionTable\[(\d+)u?\]\s*=", register)}
    shoff = struct.unpack_from("<I", data, 32)[0]
    entsize, count = struct.unpack_from("<HH", data, 46)
    if count and (entsize < 40 or shoff + entsize * count > len(data)):
        raise ValueError("Return entries: truncated section table.")
    entries = {}
    for index in range(count):
        check()
        _, kind, flags, address, offset, size, *_ = struct.unpack_from("<10I", data, shoff + index * entsize)
        if kind != 1 or not flags & 4:
            continue
        if offset + size > len(data) or address + size > 0x100000000:
            raise ValueError("Return entries: executable section outside ELF bounds.")
        for pos in range((-address) % 4, max(0, size - 7), 4):
            if pos % 65536 == 0:
                check()
            pc = address + pos
            if pc < base or pc >= end or (pc - base) // 4 in known:
                continue
            instruction, delay = struct.unpack_from("<II", data, offset + pos)
            daddu = delay >> 26 == 0 and delay & 63 == 45 and (delay >> 6) & 31 == 0
            if instruction == 0x03e00008 and (delay == 0 or daddu):
                entries[pc] = delay
                if len(entries) > 4096:
                    raise ValueError("Return entries: more than 4096 candidates; function-map review required.")
    lines = ['#include "ps2_runtime_macros.h"', '#include "ps2_runtime.h"', 'namespace {']
    for pc, delay in sorted(entries.items()):
        lines += [f"void return_{pc:x}(uint8_t* rdram, R5900Context* ctx, PS2Runtime* runtime) {{",
                  f"  // Original instructions at 0x{pc:x}: 03e00008 {delay:08x}",
                  "  const uint32_t target = GPR_U32(ctx, 31);",
                  f"  ctx->pc = 0x{pc + 4:x}u; ctx->branch_pc = 0x{pc:x}u; ctx->in_delay_slot = true;"]
        if delay:
            rs, rt, rd = (delay >> 21) & 31, (delay >> 16) & 31, (delay >> 11) & 31
            lines += [f"  SET_GPR_U64(ctx, {rd}, (uint64_t)GPR_U64(ctx, {rs}) + (uint64_t)GPR_U64(ctx, {rt}));"]
        lines += ["  ctx->in_delay_slot = false; ctx->pc = target;",
                  "#if defined(PS2X_STRICT_RETURN_DIAGNOSTICS) && PS2X_STRICT_RETURN_DIAGNOSTICS",
                  f'  (void)runtime->dispatchGuestBranch(rdram, ctx, target, 0x{pc:x}u, 0u, PS2Runtime::GuestBranchKind::Return, "JR $ra");',
                  "#endif", "}"]
    lines += ["struct RegisterRecoveredReturns { RegisterRecoveredReturns() {"]
    for pc in sorted(entries):
        slot = (pc - base) // 4
        lines += [f"  if (!g_ps2RecompiledFunctionTable[{slot}]) g_ps2RecompiledFunctionTable[{slot}] = return_{pc:x};"]
    lines += ["}};", "RegisterRecoveredReturns registerRecoveredReturns;", "}"]
    generated = output / "zz_rea_return_entries.cpp"
    if entries:
        generated.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif generated.exists():
        generated.unlink()
    result = {"count": len(entries), "addresses": [hex(pc) for pc in sorted(entries)],
              "scope": "Exact JR ra + NOP/DADDU only, within executable sections and existing table bounds."}
    (output.parent / "return-entries.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result

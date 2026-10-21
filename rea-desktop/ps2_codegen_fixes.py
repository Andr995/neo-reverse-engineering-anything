"""Audited corrections to translated code, scoped to the exact BOOT2 image.

The analyzer splits SLES-53506 at 0x400004, inside a branch delay slot.
PS2Recomp substitutes a synthetic NOP at that boundary. Restore the original
LW after evaluating the branch condition, for both taken and untaken paths.

The same analyzer mistakes stores of the object size to data at 0x47c198 for
self-modifying code (the ELF .data section is WAX). Restore the 26 audited SW
instructions in the native-class factory; zero sizes otherwise stall GC.
"""
import hashlib
import json
from pathlib import Path
import re
import tomllib

SUPPORTED_BOOT = "f33f153b4903a3026a29937e0e4610f6cff8ebf24005ee078e2dc1fd9b8a5242"
FILE = "sub_003FF7F8_0x3ff7f8.cpp"
STORE_FILE = "sub_0017C4D8_0x17c4d8.cpp"
STORE_ADDRESSES = tuple(range(0x17c538, 0x17c9e8 + 1, 0x30))

# The other analyzer NOPs are also SW to globals in .data [45a580,4a35f8).
# Their base registers are loaded by LUI/ADDIU in the original BOOT2.
# Keep the existing 26 factory-store repair below, and let the recompiler emit
# these original instructions itself, including the branch-likely delay slots.
DATA_STORE_WORDS = {
    0x104200: 0xaca2f010, 0x113968: 0xae00ac84, 0x155128: 0xac50c9a4,
    0x183f98: 0xac62dca4, 0x183fb0: 0xac62dca8, 0x183fc8: 0xac62dcac, 0x183fe0: 0xac62dcb0,
    0x2918f8: 0xaca06fd8, 0x293118: 0xaca07000, 0x298d70: 0xaca07014, 0x29e620: 0xaca07024,
    0x38a664: 0xac60e7c4, 0x38a710: 0xac83e7c0, 0x38aa08: 0xac60e7c0,
    0x3a3cb8: 0xac40a880, 0x3a4f0c: 0xac44a8a4, 0x3a500c: 0xae03a898,
    0x3a6e8c: 0xac64a910, 0x3a9494: 0xac40aa04, 0x3aeba4: 0xac40aa08,
    0x3b5180: 0xae02b0c4, 0x3bbd88: 0xae02000c, 0x3da540: 0xae00b7b4,
    0x3ece30: 0xaca20004, 0x3f6454: 0xac51c1ac, 0x3f6754: 0xac40c1ac,
    0x439e60: 0xae00d55c, 0x454b20: 0xac60f00c,
}


def restore_data_stores(configuration, boot):
    """Remove only audited false-positive NOP patches, before translation."""
    if hashlib.sha256(Path(boot).read_bytes()).hexdigest() != SUPPORTED_BOOT:
        return configuration, {"status": "not_applicable", "restored": []}
    removed = []
    pattern = re.compile(r"(?ms)^\[\[patches\.instructions\]\][^\n]*\n.*?(?=^\[|\Z)")

    def removable(block):
        address = int(str(block["address"]), 0)
        if address not in DATA_STORE_WORDS:
            return False
        if int(str(block["value"]), 0) != 0 or set(block) != {"address", "value"}:
            raise ValueError(f"Patch dati 0x{address:x} non riconosciuta; revisione richiesta.")
        if address in removed:
            raise ValueError(f"Patch dati duplicata: 0x{address:x}")
        removed.append(address)
        return True

    def replace(match):
        block = tomllib.loads(match.group())["patches"]["instructions"][0]
        return "" if removable(block) else match.group()

    updated = pattern.sub(replace, configuration)
    section = re.search(r"(?ms)^\[patches\][^\n]*\n.*?(?=^\[|\Z)", updated)
    if section:
        inline = re.compile(r"(?m)^[ \t]*(\{[^\n}]+\})[ \t]*,?[ \t]*(?:#[^\n]*)?\n")

        def replace_inline(match):
            block = tomllib.loads("entry = " + match.group(1))["entry"]
            if set(block) >= {"address", "value"} and removable(block):
                return ""
            return match.group()

        body = inline.sub(replace_inline, section.group())
        updated = updated[:section.start()] + body + updated[section.end():]
    # Parse again before any caller writes the modified configuration.
    parsed = tomllib.loads(updated)
    remaining = parsed.get("patches", {}).get("instructions", [])
    if any(int(str(item["address"]), 0) in DATA_STORE_WORDS for item in remaining):
        raise ValueError("Formato patch dati non riconosciuto; revisione richiesta.")
    return updated, {"status": "applied" if removed else "already_applied",
                     "restored": [{"address": hex(a), "instruction": hex(DATA_STORE_WORDS[a])}
                                  for a in removed]}

def store_fragments(pc):
    old = f"    // 0x{pc:x}: 0x0  nop\n    ctx->pc = 0x{pc:x}u;\n    // NOP\n"
    new = (f"    // REA: original 0xac45c198 SW a1,-0x3e68(v0) at 0x{pc:x}.\n"
           f"    ctx->pc = 0x{pc:x}u;\n"
           "    WRITE32(ADD32(GPR_U32(ctx, 2), 0xffffc198u), GPR_U32(ctx, 5));\n")
    return old, new

OLD = """        const bool branch_taken_0x400000 = (GPR_U64(ctx, 2) == GPR_U64(ctx, 0));
        if (branch_taken_0x400000) {"""
NEW = """        const bool branch_taken_0x400000 = (GPR_U64(ctx, 2) == GPR_U64(ctx, 0));
        // REA: original 0x8e420000 LW v0,0(s2), lost at the function boundary.
        ctx->pc = 0x400004u;
        ctx->branch_pc = 0x400000u;
        ctx->in_delay_slot = true;
        SET_GPR_S32(ctx, 2, (int32_t)READ32(GPR_U32(ctx, 18)));
        ctx->in_delay_slot = false;
        if (branch_taken_0x400000) {"""


def repair(boot, output, check=lambda: None):
    check()
    fingerprint = hashlib.sha256(Path(boot).read_bytes()).hexdigest()
    result = {"boot_sha256": fingerprint, "status": "not_applicable", "fixes": []}
    if fingerprint == SUPPORTED_BOOT:
        path = Path(output) / FILE
        source = path.read_text(encoding="utf-8")
        original = source
        before = hashlib.sha256(source.encode()).hexdigest()
        if NEW in source:
            result["status"] = "already_applied"
        else:
            if source.count(OLD) != 1:
                raise ValueError("Delay slot 0x400004: traduzione non riconosciuta; revisione richiesta.")
            source = source.replace(OLD, NEW, 1)
            result["status"] = "applied"
        result["fixes"] = [{"file": FILE, "branch": "0x400000", "delay": "0x400004",
                            "instruction": "0x8e420000", "before": before,
                            "after": hashlib.sha256(source.encode()).hexdigest()}]
        store_path = Path(output) / STORE_FILE
        stores = store_path.read_text(encoding="utf-8")
        original_stores = stores
        for pc in STORE_ADDRESSES:
            old, new = store_fragments(pc)
            if new in stores:
                continue
            if stores.count(old) != 1:
                raise ValueError(f"Store dati 0x{pc:x}: traduzione non riconosciuta; revisione richiesta.")
            stores = stores.replace(old, new, 1)
        result["fixes"].append({"file": STORE_FILE, "addresses": [hex(pc) for pc in STORE_ADDRESSES],
                                "instruction": "0xac45c198", "destination": "0x47c198",
                                "before": hashlib.sha256(original_stores.encode()).hexdigest(),
                                "after": hashlib.sha256(stores.encode()).hexdigest()})
        # Validate every expected translation before modifying either file.
        for dest, previous, updated in ((path, original, source), (store_path, original_stores, stores)):
            if previous != updated:
                dest.write_text(updated, encoding="utf-8")
                result["status"] = "applied"
    (Path(output).parent / "codegen-fixes.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result

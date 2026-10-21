from pathlib import Path
import struct
import tempfile
import unittest

from ps2_returns import recover
from test_ps2 import mips_elf


class ReturnEntriesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.boot = self.root / "input.elf"
        self.data = bytearray(mips_elf())
        self.table = '''extern const uint32_t g_ps2RecompiledFunctionTableBase = 0x100000u;
extern const uint32_t g_ps2RecompiledFunctionTableEnd = 0x100100u;
extern const uint32_t g_ps2RecompiledFunctionTableSlotCount = 64u;
PS2Runtime::RecompiledFunction g_ps2RecompiledFunctionTable[64u] = {};
'''

    def tearDown(self):
        self.temp.cleanup()

    def run_recovery(self):
        self.boot.write_bytes(self.data)
        (self.output / "register_functions.cpp").write_text(self.table)
        return recover(self.boot, self.output)

    def test_recovers_only_unregistered_exact_return_sequences(self):
        self.assertEqual(self.run_recovery()["addresses"], ["0x100004"])
        self.table += "g_ps2RecompiledFunctionTable[1] = known_function;\n"
        self.assertEqual(self.run_recovery()["count"], 0)
        self.assertFalse((self.output / "zz_rea_return_entries.cpp").exists())

    def test_nontrivial_delay_slot_is_not_replaced_with_nop(self):
        struct.pack_into("<I", self.data, 264, 0x0080102d)  # daddu v0,a0,zero
        self.assertEqual(self.run_recovery()["addresses"], ["0x100004"])
        text = (self.output / "zz_rea_return_entries.cpp").read_text()
        self.assertIn("SET_GPR_U64(ctx, 2, (uint64_t)GPR_U64(ctx, 4)", text)
        struct.pack_into("<I", self.data, 264, 0x8c820000)  # lw v0,0(a0), unsupported delay
        self.assertEqual(self.run_recovery()["count"], 0)

    def test_nonexecutable_section_and_outside_table_are_excluded(self):
        struct.pack_into("<I", self.data, 512 + 40 + 8, 2)
        self.assertEqual(self.run_recovery()["count"], 0)
        self.data = bytearray(mips_elf())
        self.table = self.table.replace("0x100100u", "0x100004u").replace("64u", "1u")
        self.assertEqual(self.run_recovery()["count"], 0)

    def test_truncated_section_rejected(self):
        self.data = self.data[:600]
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.run_recovery()


if __name__ == "__main__":
    unittest.main()

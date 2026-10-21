// Regression against the real copied IOP runtime. Uses upstream synthetic tests,
// never commercial code. The test host and ELF builder retain their upstream license.
#define main upstream_iop_tests_main
#include "../../ps2recomp/ps2xIOP/tests/iop_emulator_tests.cpp"
#undef main

int main() {
    if (upstream_iop_tests_main() != 0) return 1;
    const char options[] = {'o', 'n', 'e', 0, 't', 'w', 'o', 0};
    for (int test = 0; test < 4; ++test) {
        TestHost host(0x20000u);
        IopSubsystem iop(host);
        writeMinimalIrx(host, 0x100u);
        // Record argc, argv[0][0], argv[argc], and complete four-byte options (possibly unaligned).
        const uint32_t code[] = {
            0x3c080001, 0x35080180, 0xad040000,
            0x8ca90000, 0, 0x912a0000, 0, 0xad0a0004,
            0x00044880, 0x01254821, 0x8d2a0000, 0, 0xad0a0008,
            0x24090001, 0x1089000d, 0,
            0x8ca90004, 0, 0x892a0003, 0x992a0000, 0, 0xad0a000c,
            0x8ca90008, 0, 0x892a0003, 0x992a0000, 0, 0xad0a0010,
            0x00001021, 0x03e00008, 0,
        };
        auto* program = reinterpret_cast<ProgramHeader*>(host.guest.data() + 0x100u + sizeof(ElfHeader));
        program->filesz = sizeof(code);
        program->memsz = 0x200;
        std::memcpy(host.guest.data() + 0x200u, code, sizeof(code));
        const auto result = iop.loadModuleBuffer(0x100u, test == 0 ? nullptr : options,
                                                test == 0 ? 0 : test == 1 ? sizeof(options) : test == 2 ? 3 : 65537);
        if (test >= 2) {
            if (!expect(result.moduleId < 0, "Malformed/oversized arguments must be rejected")) return 1;
            continue;
        }
        uint32_t observed[5]{};
        if (!expect(result.startResult == 0 && result.moduleId > 0, "Fixture did not start")) return 1;
        if (!expect(iop.readMemory(0x10180, observed, sizeof(observed)), "Cannot inspect fixture output")) return 1;
        if (!expect(observed[0] == (test == 0 ? 1 : 3), "argc must count strings including module path")) return 1;
        if (!expect(observed[1] != 0, "argv[0] must contain the module path")) return 1;
        if (!expect(observed[2] == 0, "argv[argc] must be null")) return 1;
        if (test == 1 && !expect(observed[3] == 0x00656e6f && observed[4] == 0x006f7774,
                                "argv must point to individual strings")) return 1;
    }
    {
        TestHost host(0x20000u);
        IopSubsystem iop(host);
        for (int repeat = 0; repeat < 12; ++repeat) {
            writeRpcServerIrx(host, 0x100u);
            std::memcpy(host.guest.data() + 0x100u + 0x100u + 0x60u + 12u, "missing", 8);
            (void)iop.loadModuleBuffer(0x100u);
        }
        int warnings = 0, notices = 0;
        for (const auto& log : host.logs) {
            if (log.find("unhandled import missing:") != std::string::npos) {
                ++warnings;
                if (log.find("Further repetitions suppressed") != std::string::npos) ++notices;
            }
        }
        if (!expect(warnings == 5 && notices == 1, "IOP warnings must retain evidence without flooding logs")) return 1;
    }
    {
        TestHost host(0x20000u);
        IopSubsystem iop(host);
        for (int repeat = 0; repeat < 12; ++repeat) {
            writeRpcServerIrx(host, 0x100u);
            std::memcpy(host.guest.data() + 0x26cu, "stdio\0\0", 8);
            const uint32_t ordinal = 0x24000004u;
            std::memcpy(host.guest.data() + 0x278u, &ordinal, 4);
            (void)iop.loadModuleBuffer(0x100u);
        }
        int messages = 0, notices = 0;
        for (const auto& log : host.logs) {
            if (log.find("[IOP printf]") != std::string::npos) {
                ++messages;
                if (log.find("Further repetitions suppressed") != std::string::npos) ++notices;
            }
        }
        if (!expect(messages == 5 && notices == 1, "Guest printf must also be bounded")) return 1;
    }
    std::cout << "PASS: IOP entry argc/argv, no options, two options, malformed/oversized input, bounded repeated logs\n";
}

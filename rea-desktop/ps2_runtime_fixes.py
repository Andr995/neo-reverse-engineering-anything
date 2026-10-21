"""Audited, fingerprint-scoped adaptations of the copied PS2 runtime.

The upstream checkout is never patched. Unknown revisions fail before changes.
These corrections do not certify gameplay or replace guest functions with stubs.
"""
import hashlib
from pathlib import Path
import ps2_iop_fixes
import ps2_sif_fixes
import ps2_spu_fixes
import ps2_input_fixes

SUPPORTED_BOOT = "f33f153b4903a3026a29937e0e4610f6cff8ebf24005ee078e2dc1fd9b8a5242"
RUNTIME = "ps2xRuntime/src/lib/ps2_runtime.cpp"
SYSTEM = "ps2xRuntime/src/lib/Kernel/Syscalls/System.cpp"
IOP = "ps2xIOP/src/emulator/iop_emulator.cpp"
STDIO = "ps2xIOP/src/emulator/imports/iop_stdio.cpp"
STDIO_HEADER = "ps2xIOP/src/emulator/imports/iop_stdio.h"
THREAD = "ps2xRuntime/src/lib/Kernel/Syscalls/Thread.cpp"
SOURCE_HASHES = {
    **ps2_input_fixes.SOURCE_HASHES,
    **ps2_iop_fixes.SOURCE_HASHES,
    **ps2_sif_fixes.SOURCE_HASHES,
    **ps2_spu_fixes.SOURCE_HASHES,
    RUNTIME: "77cd184f2e70eacfd5ea584ec95829553e3deeead0a19c04e4b0970dd7c6c9ee",
    SYSTEM: "9d30538bd6d34577bd55946b537ec0d57524c20e660e8f1e7edb1f2eca1f3034",
    IOP: "01deb410d04f441be12adc68638846061f19759e007c36cdfcbe987796199d36",
    STDIO: "89bc5d2ef9196aadafe7c4728e2fdc6814a9169e25b282631a53976735c86f47",
    STDIO_HEADER: "4bd26cab65e0d4b5a1757ed39e692ba7929ed5668ef7fc1b0c0c880d6d893db8",
    THREAD: "e73d7f0a46d07fc0f70d5b49b6453ed64271b3ad19ffd62a6a872095491bcdf4",
}

# PS2SDK modload start_module: the byte list becomes argc/argv, with the
# module path at argv[0]. Passing byte length/raw bytes corrupts IRX startup.
IOP_ARGUMENTS = '''            std::vector<std::string> argv{module.path};
            if (argumentSize > 65536u || module.path.size() > 4096u || (argumentSize && !arguments))
                return result;
            const auto *bytes = static_cast<const char *>(arguments);
            for (uint32_t offset = 0u; offset < argumentSize;)
            {
                const auto *end = static_cast<const char *>(std::memchr(bytes + offset, 0, argumentSize - offset));
                if (!end || argv.size() >= 256u)
                    return result;
                argv.emplace_back(bytes + offset, static_cast<size_t>(end - (bytes + offset)));
                offset = static_cast<uint32_t>(end - bytes) + 1u;
            }
            const uint32_t pointersSize = static_cast<uint32_t>((argv.size() + 1u) * 4u);
            uint32_t allocationSize = pointersSize;
            for (const auto &value : argv)
                allocationSize += static_cast<uint32_t>(value.size() + 1u);
            const uint32_t args = allocate(allocationSize, 16u);
            if (!args)
                return result;
            uint32_t cursor = args + pointersSize;
            for (size_t index = 0; index < argv.size(); ++index)
            {
                write32(args + static_cast<uint32_t>(index * 4u), cursor);
                writeRam(cursor, argv[index].c_str(), argv[index].size() + 1u);
                cursor += static_cast<uint32_t>(argv[index].size() + 1u);
            }
            write32(args + static_cast<uint32_t>(argv.size() * 4u), 0u);
            if (std::getenv("REA_DIAGNOSTICS"))
            {
                std::ostringstream detail;
                detail << "[REA IOP argv] module=" << module.path << " bytes=" << argumentSize << " argc=" << argv.size();
                for (size_t index = 1; index < argv.size() && index < 16u; ++index)
                    detail << " arg" << index << "=" << std::quoted(argv[index].substr(0, 128));
                log(LogLevel::Info, detail.str());
            }
            uint32_t startResult;
            try
            {
                startResult = callFunction(module.entry, static_cast<uint32_t>(argv.size()), args, 0u, 0u, module.gp);
            }
            catch (...)
            {
                freeAllocation(args);
                throw;
            }
            freeAllocation(args);
'''

IOP_LOG = '''        std::map<std::string, unsigned> reaLogCounts;
        void log(LogLevel level, std::string_view text)
        {
            const std::string key(text.substr(0, 2048));
            auto found = reaLogCounts.find(key);
            if (found == reaLogCounts.end() && reaLogCounts.size() >= 1024u)
                return;
            auto &count = reaLogCounts[key];
            if (count < 4u)
                host.log(level, key);
            else if (count == 4u)
                host.log(level, "[REA IOP] Further repetitions suppressed: " + key);
            if (count < 5u) ++count;
        }
'''

# BOOT2 declares BSS end 0x1f84988 and stack [0x1ff0000, 0x2000000).
# Its translated libc implements sbrk itself: HLE allocations must not share
# that allocator's arena. GS temporary packets previously overwrote RW plugins.
HEAP_SYSCALLS = '''    // REA SLES-53506: disjoint libc, HLE scratch and callback arenas.
    void SetupHeap(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        const uint32_t base = (getRegU32(ctx, 4) + 15u) & ~15u;
        if (base != 0x01F84990u || getRegU32(ctx, 5) != 0xFFFFFFFFu)
            throw std::runtime_error("REA memory profile: unexpected SetupHeap arguments");
        runtime->configureGuestHeap(0x01FD0000u, 0x01FE0000u);
        setReturnU32(ctx, base);
    }

    void EndOfHeap(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        setReturnU32(ctx, 0x01FD0000u);
    }

'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def apply_runtime_fixes(runtime, boot):
    runtime = Path(runtime)
    fingerprint = sha(Path(boot).read_bytes())
    if fingerprint != SUPPORTED_BOOT:
        return {"status": "not_applicable", "boot_sha256": fingerprint}
    sources = {}
    for name, expected in SOURCE_HASHES.items():
        path = runtime / name
        if not path.is_file() or sha(path.read_bytes()) != expected:
            raise ValueError("Profilo memoria SLES-53506: revisione runtime non verificata: " + name)
        sources[name] = path.read_text(encoding="utf-8")
    sources[RUNTIME] = sources[RUNTIME].replace(
        "kGuestHeapHardLimit = 0x01F00000u", "kGuestHeapHardLimit = 0x01FE0000u"
    ).replace("m_asyncCallbackStackTop = PS2_RAM_SIZE;", "m_asyncCallbackStackTop = 0x01FF0000u;")
    start = sources[SYSTEM].index("    // 0x3D SetupHeap:")
    end = sources[SYSTEM].index("    void GetMemorySize", start)
    sources[SYSTEM] = sources[SYSTEM][:start] + HEAP_SYSCALLS + sources[SYSTEM][end:]
    start = sources[IOP].index("            uint32_t args = 0u;", sources[IOP].index("ModuleLoadResult loadImage("))
    end = sources[IOP].index("            module.resident =", start)
    sources[IOP] = "#include <cstring>\n#include <iomanip>\n#include <cstdlib>\n" + sources[IOP][:start] + IOP_ARGUMENTS + sources[IOP][end:]
    start = sources[IOP].index("        void log(LogLevel level, std::string_view text)")
    end = sources[IOP].index("        bool checkInterrupt", start)
    sources[IOP] = sources[IOP][:start] + IOP_LOG + "\n" + sources[IOP][end:]
    sources[STDIO_HEADER] = sources[STDIO_HEADER].replace("#include <cstdint>",
        "#include <cstdint>\n#include <map>\n#include <string>\n#include <string_view>").replace(
        "    private:", "    private:\n        std::map<std::string, unsigned> reaLogCounts;\n        void log(std::string_view text);")
    stdio_log = IOP_LOG.split("        void log", 1)[1]
    stdio_log = "    void IopStdio::log" + stdio_log.replace("(LogLevel level, std::string_view text)", "(std::string_view text)", 1)
    stdio_log = stdio_log.replace("host.log(level,", "m_host.log(LogLevel::Info,")
    sources[STDIO] = sources[STDIO].replace("m_host.log(LogLevel::Info, ", "log(")
    sources[STDIO] = sources[STDIO].replace("    bool IopStdio::dispatchImport", stdio_log + "\n    bool IopStdio::dispatchImport")
    ps2_iop_fixes.adapt(sources, IOP)
    ps2_sif_fixes.adapt(sources, RUNTIME, IOP)
    ps2_spu_fixes.adapt(sources, IOP)
    ps2_input_fixes.adapt(sources, RUNTIME)
    # The failed indirect branch is diagnosed on the EE execution thread.
    # Keep the snapshot opt-in, exclusive and bounded to one RAM image.
    sources[RUNTIME] = '#include <cstdio>\n#include <cstdlib>\n' + sources[RUNTIME]
    sources[RUNTIME] = sources[RUNTIME].replace('        static std::mutex s_missingFunctionLogMutex;', '''        if (rdram && ctx && std::getenv("REA_DIAGNOSTICS")) {
            for (unsigned reg = 16u; reg < 24u; ++reg)
                oss << " s" << std::dec << reg - 16u << "=0x" << std::hex << static_cast<uint32_t>(_mm_extract_epi32(ctx->r[reg], 0));
            if (const char *path = std::getenv("REA_BRANCH_RAM_SNAPSHOT"))
                if (FILE *file = std::fopen(path, "wbx")) {
                    const size_t written = std::fwrite(rdram, 1u, PS2_RAM_SIZE, file);
                    std::fclose(file);
                    oss << " snapshotBytes=" << std::dec << written;
                }
        }
        static std::mutex s_missingFunctionLogMutex;''', 1)
    sources[THREAD] = '#include <cstdio>\n#include <cstdlib>\n#include <cstring>\n' + sources[THREAD]
    sources[THREAD] = sources[THREAD].replace('        ee.sleepCurrent();', '''        // Read guest state only on its owning execution thread, before yielding.
        static unsigned reaMainSleeps = 0;
        if (std::getenv("REA_DIAGNOSTICS") && ee.currentThreadId() == 1 &&
            ++reaMainSleeps <= 3600u && reaMainSleeps % 600u == 0u)
        {
            const uint32_t sp = getRegU32(ctx, 29) & 0x1FFFFFFFu;
            std::fprintf(stderr, "[REA main-stack] sleep=%u ra=%x sp=%x", reaMainSleeps, getRegU32(ctx, 31), sp);
            for (unsigned reg = 16; reg < 24; ++reg)
                std::fprintf(stderr, " s%u=%x", reg - 16u, getRegU32(ctx, reg));
            if (sp <= 0x2000000u - 256u)
                for (unsigned offset = 0; offset < 256u; offset += 4u)
                {
                    uint32_t value;
                    std::memcpy(&value, rdram + sp + offset, sizeof(value));
                    std::fprintf(stderr, " +%x=%x", offset, value);
                }
            std::fprintf(stderr, "\\n");
            if (reaMainSleeps == 600u)
                if (const char *path = std::getenv("REA_GUEST_RAM_SNAPSHOT"))
                    if (FILE *file = std::fopen(path, "wbx"))
                    {
                        const size_t written = std::fwrite(rdram, 1u, 0x2000000u, file);
                        std::fclose(file);
                        std::fprintf(stderr, "[REA RAM snapshot] bytes=%zu\\n", written);
                    }
        }
        ee.sleepCurrent();''')
    changes = {}
    for name, source in sources.items():
        (runtime / name).write_text(source, encoding="utf-8")
        changes[name] = {"before": SOURCE_HASHES[name], "after": sha(source.encode("utf-8"))}
    return {"status": "applied", "profile": "sles-53506-memory-iop-v5", "boot_sha256": fingerprint,
            "input": "atomic host input snapshot; keyboard and gamepad combined; both analog sticks; player one",
            "pad2": "fingerprint-scoped libpad2 host adapter for socket lifecycle, state, 18-byte input, 5-byte profile and DMA buffers; no rumble or multitap",
            "spu2": "48kHz capture-buffer IRQ timing and shared 2MiB sound RAM with FIFO/normal DMA; synthesis, reverb and AutoDMA streaming incomplete",
            "sif_dma_completion": "validated data transfer followed by original deferred guest callback with GP/userdata",
            "sif_commands": "EE register arguments; directional payload DMA and original IOP command handlers",
            "iop_usb": "OHCI reset and interrupt register semantics; empty ports, no USB transfers or frame scheduling",
            "iop_memory": "256-byte sysmem pages; fixed pools with allocation, release, wait queues and status",
            "iop_start_arguments": "argc/argv with module path and bounded NUL-separated arguments",
            "iop_log_limit": "4 copies per message, then explicit suppression; 1024 distinct messages of at most 2048 bytes",
            "guest_libc": ["0x1f84990", "0x1fd0000"],
            "runtime_scratch": ["0x1fd0000", "0x1fe0000"],
            "callback_stacks": ["0x1fe0000", "0x1ff0000"],
            "main_stack": ["0x1ff0000", "0x2000000"],
            "changed_sources": changes, "playable": False}

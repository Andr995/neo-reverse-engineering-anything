"""SIF command transport for the audited SLES-53506 runtime copy.

API semantics: PS2SDK ee/kernel/src/sifcmd.c and iop/system/sifcmd/src/sifcmd.c.
The EE passes arguments 5/6 in t0/t1; IOP imports use o32 stack arguments.
"""
import ps2_iop_fixes
SUBSYSTEM_H = 'ps2xIOP/include/ps2x/iop/iop_subsystem.h'
SUBSYSTEM = 'ps2xIOP/src/iop_subsystem.cpp'
EMULATOR_H = 'ps2xIOP/src/emulator/iop_emulator.h'
RPC_H = 'ps2xIOP/src/emulator/services/iop_rpc.h'
RPC = 'ps2xIOP/src/emulator/services/iop_rpc.cpp'
TRANSPORT = 'ps2xRuntime/src/lib/ps2_iop_transport.h'
EE_SIF = 'ps2xRuntime/src/lib/Kernel/Stubs/SIF.cpp'
EE_RPC = 'ps2xRuntime/src/lib/Kernel/Syscalls/RPC.cpp'
SOURCE_HASHES = {
    SUBSYSTEM_H: "74eb35a63fb7e3af98ba3d24088a5a47e7f6fe8a5f9a50b51d057a5fe08fc608",
    SUBSYSTEM: "b8c04b4a2b35fc3121ed23e4e97a7dbd0b10e17f4f9a319105ec2534dfbb919f",
    EMULATOR_H: "a14bd2fb923632ad434f95e942b930fcc5e3a45e3bc2250d7fea7edcbe1b0f73",
    RPC_H: "bddd5dbe9cebfcb4214b0b5f09fff210e8399a5710105b3f2d4600c5bc38fae1",
    RPC: "62680a58200046de70babc31273535c51fa43a1979e0ffde5c307481dc83c969",
    TRANSPORT: "8c5e29466927af2c8f64406a6dd49c5766a51e4cf8ad248b406abb57aa5d93d7",
    EE_SIF: "35244dec8738ab81bcd6eadd8212f39c940881750a140260c8004b017005f505",
    EE_RPC: "803a94aaa5b20faef56f92400f88d706069bcf899bc6bd075c67a07dcfd6736f",
}

# Packet layout: ps2sdk/common/include/loadfile-common.h; service ABI:
# ps2sdk/iop/system/loadfile/src/loadfile.c. This route is confined to the
# hash-verified runtime profile. Unsupported operations return an error.
LOADFILE = r'''
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
template<class Runtime>
ps2x::iop::RpcResult reaLoadfileRpc(Runtime *runtime, uint8_t *ram,
                                   const ps2x::iop::RpcRequest &request) {
    using namespace ps2x::iop;
    RpcResult result{};
    if (!runtime || request.sid != 0x80000006u) return result;
    result.handled = true;
    result.signalCompletion = true;
    result.serverDispatchPolicy = ServerDispatchPolicy::Suppress;
    const auto range = [ram](GuestBuffer buffer) -> uint8_t * {
        const uint32_t segment = buffer.address & 0xe0000000u;
        const uint32_t address = buffer.address & 0x1fffffffu;
        if (!ram || (segment && segment != 0x80000000u && segment != 0xa0000000u) ||
            address < 0x10000u || address >= 0x2000000u ||
            buffer.size > 0x2000000u-address) return nullptr;
        return ram+address;
    };
    auto *out = range(request.receive);
    if (!out || request.receive.size < 4u || request.receive.size > 16u) return result;
    auto *in = range(request.send);
    const auto word = [](const uint8_t *p) { uint32_t v; std::memcpy(&v,p,4); return v; };
    std::array<int32_t,4> reply{-1,-1,0,-1};
    if (request.function == 0xffu) reply[0] = 0x30303133; // LOADFILE 3.1 wire ABI
    else if (request.function == 0u && in && request.send.size >= 260u) {
        const uint32_t size = word(in);
        const auto *end = static_cast<const uint8_t *>(std::memchr(in+8,0,252));
        if (end && end != in+8 && size <= 252u && size <= request.send.size-260u) {
            const std::string path(reinterpret_cast<const char *>(in+8), end-(in+8));
            const auto loaded = runtime->loadIopModule(path,size ? in+260 : nullptr,size);
            if (loaded.handled) { reply[0]=loaded.moduleId; reply[1]=loaded.startResult; }
        }
    } else if ((request.function == 2u || request.function == 3u) &&
               in && request.send.size >= 12u) {
        const uint32_t address=word(in), type=word(in+4);
        if(type<=2u) {
            const unsigned size=1u<<type;
            uint32_t value=request.function==2u ? word(in+8) : 0u;
            const bool ok=request.function==2u ? runtime->writeIopMemory(address,&value,size)
                                               : runtime->readIopMemory(address,&value,size);
            if(ok) reply[0]=request.function==2u ? 0 : static_cast<int32_t>(value);
        }
    } else if (request.function == 1u || request.function == 5u) {
        // ELF execution data reports failure via epc=0, not a bogus entry point.
        reply[0]=0; reply[1]=0;
    }
    // Copy only after parsing: send and receive commonly alias.
    std::memcpy(out,reply.data(),request.receive.size);
    result.resultAddress=request.receive.address;
    static const bool trace=std::getenv("REA_DIAGNOSTICS") != nullptr;
    static unsigned count=0;
    if(trace && count++<32u)
        std::fprintf(stderr,"[REA loadfile] function=%x send=%u receive=%u result=%d module-result=%d\n",
                     request.function,request.send.size,request.receive.size,reply[0],reply[1]);
    return result;
}
'''

COMMAND_IMPORTS = '''        case 6: // sceSifGetSreg
            setV0(cpu.gpr[4] < 32u ? m_sregs[cpu.gpr[4]] : 0u);
            return true;
        case 7: // sceSifSetSreg
            if (cpu.gpr[4] < 32u) m_sregs[cpu.gpr[4]] = cpu.gpr[5];
            setV0(0u);
            return true;
        case 8: // sceSifSetCmdBuffer
        case 9: // sceSifSetSysCmdBuffer
        {
            const uint32_t address = cpu.gpr[4], count = cpu.gpr[5];
            if (count > 256u || (count && (!address || !m_memory.ownsRamRange(address, count * 8u))))
            {
                setV0(0xFFFFFFFFu);
                return true;
            }
            const unsigned table = ordinal == 9 ? 1u : 0u;
            const uint32_t previous = m_commandTables[table];
            m_commandTables[table] = address;
            m_commandCounts[table] = count;
            traceCommand("table", table << 31u, address, count);
            for (auto it = m_commandGps.begin(); it != m_commandGps.end();)
                if ((it->first >> 31u) == table) it = m_commandGps.erase(it);
                else ++it;
            setV0(previous);
            return true;
        }
        case 10: // sceSifAddCmdHandler
        case 11: // sceSifRemoveCmdHandler
        {
            const uint32_t cid = cpu.gpr[4], index = cid & 0x7FFFFFFFu;
            const unsigned table = cid >> 31u;
            if (index >= m_commandCounts[table] || !m_commandTables[table])
            {
                traceCommand("registration-no-table", cid, cpu.gpr[5], cpu.gpr[6]);
                setV0(0xFFFFFFFFu);
                return true;
            }
            const uint32_t entry = m_commandTables[table] + index * 8u;
            m_memory.write32(entry, ordinal == 10 ? cpu.gpr[5] : 0u);
            m_memory.write32(entry + 4u, ordinal == 10 ? cpu.gpr[6] : 0u);
            if (ordinal == 10) m_commandGps[cid] = cpu.gpr[28];
            else m_commandGps.erase(cid);
            traceCommand("registration", cid, m_memory.read32(entry), m_memory.read32(entry + 4u));
            setV0(0u);
            return true;
        }
'''

RECEIVE_COMMAND = '''    bool IopRpcBridge::receiveCommand(uint32_t commandId, const void *packet,
                                                size_t size, IopGuestExecutor &executor)
    {
        if (!packet || size < 16u || size > 112u) return false;
        uint32_t header[4]{};
        std::memcpy(header, packet, sizeof(header));
        if ((header[0] & 0xFFu) != size || header[2] != commandId) return false;
        const unsigned table = commandId >> 31u;
        const uint32_t index = commandId & 0x7FFFFFFFu;
        if (index >= m_commandCounts[table] || !m_commandTables[table]) {
            traceCommand("receive-no-table", commandId, 0u, 0u);
            return true;
        }
        const uint32_t entry = m_commandTables[table] + index * 8u;
        const uint32_t function = m_memory.read32(entry);
        const uint32_t argument = m_memory.read32(entry + 4u);
        traceCommand("receive", commandId, function, argument);
        if (!function) return true; // DMA completes even when no receiver is registered.
        if ((function & 3u) || !m_memory.ownsRamRange(function, 4u)) return false;
        const uint32_t address = m_memory.allocate(static_cast<uint32_t>(size), 16u);
        if (!address) return false;
        struct PacketGuard { IopMemory &memory; uint32_t address;
            ~PacketGuard() { (void)memory.freeAllocation(address); } } guard{m_memory, address};
        if (!m_memory.writeRam(address, packet, size)) return false;
        const auto gp = m_commandGps.find(commandId);
        (void)executor.executeGuestFunctionWithBudget(function, address, argument, 0u, 0u,
            gp != m_commandGps.end() ? gp->second : 0u, 100000u);
        return true;
    }

'''

SEND_COMMAND = '''    void sceSifSendCmd(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        const uint32_t cid = getRegU32(ctx, 4), address = getRegU32(ctx, 5);
        const uint32_t size = getRegU32(ctx, 6) & 0xFFu;
        const uint32_t source = getRegU32(ctx, 7), destination = getRegU32(ctx, 8);
        const int32_t signedExtra = static_cast<int32_t>(getRegU32(ctx, 9));
        const uint32_t extra = signedExtra > 0 ? static_cast<uint32_t>(signedExtra) : 0u;
        setReturnU32(ctx, 0u);
        if (!runtime || !address || size < 16u || size > 112u ||
            !canAccessEeRange(rdram, address, size) || extra > 0xFFFFFFu) return;
        if (extra && (!source || !destination || !canAccessEeRange(rdram, source, extra) ||
                      !runtime->isIopMemoryRange(destination, extra))) return;
        std::array<uint8_t, 112> packet{};
        if (!readEeRange(rdram, address, packet.data(), size)) return;
        const uint32_t header[3] = {size | (extra << 8u), extra ? destination : 0u, cid};
        std::memcpy(packet.data(), header, sizeof(header));
        std::vector<uint8_t> payload(extra);
        if (extra && (!readEeRange(rdram, source, payload.data(), extra) ||
                      !runtime->writeIopMemory(destination, payload.data(), extra))) return;
        if (!writeEeRange(rdram, address, header, sizeof(header))) return;
        const bool delivered = PS2IopTransport::sendCommand(runtime, rdram, ctx, cid, packet.data(), size);
        setReturnU32(ctx, delivered ? allocateSifDmaTransferId() : 0u);
    }

'''


def adapt(sources, runtime, emulator):
    declaration = "        [[nodiscard]] bool receiveCommand(uint32_t commandId, const void *packet, size_t size);\n"
    for name in (SUBSYSTEM_H, EMULATOR_H):
        sources[name] = sources[name].replace("        void onSifTransfer(", declaration + "        void onSifTransfer(", 1)
    sources[SUBSYSTEM] += '''
namespace ps2x::iop {
bool IopSubsystem::receiveCommand(uint32_t cid, const void *packet, size_t size) {
    return m_impl->emulator.receiveCommand(cid, packet, size);
}
}
'''
    sources[emulator] += '''
namespace ps2x::iop::detail {
bool IopEmulator::receiveCommand(uint32_t cid, const void *packet, size_t size) {
    return m_impl->rpc.receiveCommand(cid, packet, size, *m_impl);
}
}
'''
    sources[RPC_H] = sources[RPC_H].replace("#include <cstddef>", "#include <array>\n#include <cstddef>")
    sources[RPC_H] = sources[RPC_H].replace("        void onSifTransfer(",
        "        [[nodiscard]] bool receiveCommand(uint32_t commandId, const void *packet, size_t size, IopGuestExecutor &executor);\n        void onSifTransfer(", 1)
    sources[RPC_H] = sources[RPC_H].replace("        uint32_t m_nextDmaId", '''        std::array<uint32_t, 2> m_commandTables{}, m_commandCounts{};
        std::array<uint32_t, 32> m_sregs{};
        std::unordered_map<uint32_t, uint32_t> m_commandGps;
        uint32_t m_commandTraceCount = 0;
        void traceCommand(const char *action, uint32_t cid, uint32_t first, uint32_t second);
        uint32_t m_nextDmaId''')
    sources[RPC] = '#include <cstdlib>\n#include <sstream>\n' + sources[RPC]
    # sceSifSetDmaIntr is the same transfer with a deferred completion callback.
    # GTFSCDVD sleeps after submitting it and relies on that callback to wake up.
    sources[RPC_H] = '#include <optional>\n' + sources[RPC_H]
    sources[RPC_H] = sources[RPC_H].replace('        void reset();', '''        struct DmaCompletion { uint32_t address, gp, argument; };
        std::optional<DmaCompletion> takeDmaCompletion() {
            auto result = m_dmaCompletion;
            m_dmaCompletion.reset();
            return result;
        }
        void reset();''', 1).replace('        uint32_t m_nextDmaId',
            '        std::optional<DmaCompletion> m_dmaCompletion;\n        uint32_t m_nextDmaId', 1)
    sources[RPC] = sources[RPC].replace('        m_servers.clear();',
        '        m_dmaCompletion.reset();\n        m_servers.clear();', 1)
    sources[RPC] = sources[RPC].replace('        case 7: // sceSifSetDma',
        '        case 32: // sceSifSetDmaIntr\n        case 7: // sceSifSetDma', 1)
    sources[RPC] = sources[RPC].replace('            setV0(dmaId);', '''            if (ordinal == 32 && cpu.gpr[6] != 0u)
                m_dmaCompletion = DmaCompletion{cpu.gpr[6], cpu.gpr[28], cpu.gpr[7]};
            setV0(dmaId);''', 1)
    sources[emulator] = sources[emulator].replace('''                return rpc.dispatchSifManImport(call.ordinal, cpu)
                           ? ImportDisposition::Handled
                           : ImportDisposition::Missing;''', '''                if (!rpc.dispatchSifManImport(call.ordinal, cpu))
                    return ImportDisposition::Missing;
                if (const auto callback = rpc.takeDmaCompletion())
                    pendingGuestCallbacks.emplace(totalCycles + 128u,
                        ScheduledGuestCallback{callback->address, callback->gp, callback->argument});
                return ImportDisposition::Handled;''', 1)
    sources[RPC] = sources[RPC].replace("        m_servers.clear();", '''        m_servers.clear();
        m_commandTables.fill(0u);
        m_commandCounts.fill(0u);
        m_sregs.fill(0u);
        m_commandTraceCount = 0;
        m_commandGps.clear();''', 1)
    start = sources[RPC].index("        case 6:\n", sources[RPC].index("bool IopRpcBridge::dispatchSifCmdImport"))
    end = sources[RPC].index("        case 14:", start)
    sources[RPC] = sources[RPC][:start] + sources[RPC][end:]
    start = sources[RPC].index("        case 12: // sceSifSendCmd")
    sources[RPC] = sources[RPC][:start] + COMMAND_IMPORTS + sources[RPC][start:]
    sources[RPC] = sources[RPC].replace("            if (!m_host.sendSifCommand(commandId, packet.data(), packetSize))", '''            traceCommand("send-to-ee", commandId, packetAddress, packetSize);
            if (!m_host.sendSifCommand(commandId, packet.data(), packetSize))''')
    start = sources[RPC].index("    void IopRpcBridge::onSifTransfer")
    sources[RPC] = sources[RPC][:start] + RECEIVE_COMMAND + sources[RPC][start:]
    sources[RPC] += '''
namespace ps2x::iop::detail {
void IopRpcBridge::traceCommand(const char *action, uint32_t cid, uint32_t first, uint32_t second) {
    if (!std::getenv("REA_DIAGNOSTICS") || m_commandTraceCount >= 64u) return;
    ++m_commandTraceCount;
    std::ostringstream out;
    out << "[REA SIF cmd] " << action << " cid=0x" << std::hex << cid
        << " first=0x" << first << " second=0x" << second;
    m_host.log(LogLevel::Info, out.str());
}
}
'''
    # Remove command callbacks as well as RPC servers when a module is unloaded.
    sources[RPC] = sources[RPC].replace("    void IopRpcBridge::removeServersInRange(uint32_t base, uint32_t size)\n    {", '''    void IopRpcBridge::removeServersInRange(uint32_t base, uint32_t size)
    {
        for (unsigned table = 0; table < 2; ++table)
            for (uint32_t i = 0; m_commandTables[table] && i < m_commandCounts[table]; ++i) {
                const uint32_t entry = m_commandTables[table] + i * 8u;
                const uint32_t function = IopMemory::physicalAddress(m_memory.read32(entry));
                if (function >= base && function - base < size) {
                    m_memory.write32(entry, 0u);
                    m_memory.write32(entry + 4u, 0u);
                    m_commandGps.erase((table << 31u) | i);
                }
            }
''', 1)
    sources[TRANSPORT] = sources[TRANSPORT].replace("public:\n", '''public:
    [[nodiscard]] static bool sendCommand(PS2Runtime *runtime, uint8_t *rdram,
        R5900Context *context, uint32_t commandId, const void *packet, size_t size);
''', 1)
    sources[runtime] = '#include "ps2_iop_transport.h"\n' + sources[runtime] + '''
bool PS2IopTransport::sendCommand(PS2Runtime *runtime, uint8_t *rdram,
    R5900Context *context, uint32_t cid, const void *packet, size_t size) {
    if (!runtime || !runtime->m_iopSubsystem) return false;
    auto scope = runtime->m_iopHost->enterCall(context, rdram);
    return runtime->m_iopSubsystem->receiveCommand(cid, packet, size);
}
'''
    start = sources[EE_SIF].index("    void sceSifSendCmd(")
    end = sources[EE_SIF].index("    namespace\n", start)
    sources[EE_SIF] = sources[EE_SIF][:start] + sources[EE_SIF][end:]
    start = sources[EE_SIF].index("    void resetSifState()")
    sources[EE_SIF] = sources[EE_SIF][:start] + SEND_COMMAND + sources[EE_SIF][start:]
    start = sources[EE_RPC].index("    void sceSifSendCmd(")
    end = sources[EE_RPC].index("    void sceRpcGetPacket(", start)
    sources[EE_RPC] = sources[EE_RPC][:start] + '''    void sceSifSendCmd(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        ps2_stubs::sceSifSendCmd(rdram, ctx, runtime);
    }

''' + sources[EE_RPC][end:]
    if '#include "../Stubs/SIF.h"' not in sources[EE_RPC]:
        sources[EE_RPC] = '#include "../Stubs/SIF.h"\n' + sources[EE_RPC]
    # Sample on the IOP execution thread only; no concurrent reads of live CPU state.
    sources[ps2_iop_fixes.KERNEL_HEADER] = sources[ps2_iop_fixes.KERNEL_HEADER].replace(
        "#include <cstddef>", "#include <string>\n#include <cstddef>").replace(
        "        void reset();", "        void reset();\n        std::string diagnosticThreads() const;")
    sources[ps2_iop_fixes.KERNEL] = '#include <sstream>\n' + sources[ps2_iop_fixes.KERNEL] + '''
namespace ps2x::iop::detail {
std::string IopKernel::diagnosticThreads() const {
    std::ostringstream out;
    for (const auto &[id, thread] : m_threads) {
        out << "[REA IOP thread] id=" << std::dec << id << " priority=" << thread.priority
            << " state=" << static_cast<unsigned>(thread.state) << " wait=" << thread.waitId
            << " entry=0x" << std::hex << thread.entry << " pc=0x" << thread.cpu.pc
            << " ra=0x" << thread.cpu.gpr[31] << " sp=0x" << thread.cpu.gpr[29]
            << " waitBits=0x" << thread.waitBits << '\\n';
    }
    return out.str();
}
}
'''
    sources[emulator] = '#include <cstdlib>\n#include <cstdio>\n' + sources[emulator]
    sources[emulator] = sources[emulator].replace("            runCpu(cpu, budget);\n            return cpu.gpr[2];", '''            runCpu(cpu, budget);
            if (std::getenv("REA_DIAGNOSTICS") && cpu.pc != kCallReturnSentinel) {
                std::ostringstream out;
                out << "[REA IOP incomplete call] entry=0x" << std::hex << address
                    << " pc=0x" << cpu.pc << " ra=0x" << cpu.gpr[31]
                    << " v0=0x" << cpu.gpr[2] << " budget=" << std::dec << budget
                    << " yielded=" << cpu.yielded << " stopped=" << cpu.stopped;
                log(LogLevel::Warning, out.str());
            }
            return cpu.gpr[2];''', 1)
    sources[emulator] = sources[emulator].replace("        void runCycles(uint64_t cycles)",
        "        uint64_t reaNextThreadTrace = 20000000u;\n        unsigned reaThreadTraces = 0;\n\n        void runCycles(uint64_t cycles)")
    sources[emulator] = sources[emulator].replace("                const uint64_t target = totalCycles + cycles;", '''                static const bool reaDiagnostics = std::getenv("REA_DIAGNOSTICS") != nullptr;
                if (reaDiagnostics && reaThreadTraces < 5u && totalCycles >= reaNextThreadTrace) {
                    ++reaThreadTraces;
                    reaNextThreadTrace = totalCycles + 50000000u;
                    host.log(LogLevel::Info, kernel.diagnosticThreads());
                    if (reaThreadTraces == 5u)
                        if (const char *path = std::getenv("REA_IOP_RAM_SNAPSHOT"))
                            if (FILE *file = std::fopen(path, "wbx")) {
                                const auto &bytes = memory.ram();
                                const size_t written = std::fwrite(bytes.data(), 1u, bytes.size(), file);
                                std::fclose(file);
                                host.log(LogLevel::Info, "[REA IOP RAM snapshot] bytes=" + std::to_string(written));
                            }
                }
                const uint64_t target = totalCycles + cycles;''', 1)

    # Bounded diagnostics for original IRX audio and DMA completion paths.
    sources[emulator] = sources[emulator].replace('            if (iequals(call.library, "sysmem")', '''            if (std::getenv("REA_DIAGNOSTICS")) {
                static unsigned audioImports = 0;
                if (audioImports < 80u && ((iequals(call.library, "libsd") && call.ordinal >= 17u) ||
                    (iequals(call.library, "intrman") && call.ordinal >= 4u && call.ordinal <= 7u))) {
                    ++audioImports;
                    std::ostringstream out;
                    out << "[REA audio import] " << call.library << ':' << call.ordinal
                        << std::hex << " a0=0x" << cpu.gpr[4] << " a1=0x" << cpu.gpr[5]
                        << " a2=0x" << cpu.gpr[6] << " a3=0x" << cpu.gpr[7];
                    log(LogLevel::Info, out.str());
                }
            }
            if (iequals(call.library, "sysmem")''', 1)
    sources[emulator] = sources[emulator].replace('                pendingDmaInterrupts[dma->irq] = totalCycles + dma->delayCycles;', '''            {
                pendingDmaInterrupts[dma->irq] = totalCycles + dma->delayCycles;
                if (std::getenv("REA_DIAGNOSTICS")) {
                    static unsigned traces = 0;
                    if (traces++ < 32u) {
                        std::ostringstream out;
                        out << "[REA audio DMA start] irq=" << dma->irq << " cycle=" << totalCycles
                            << " delay=" << dma->delayCycles;
                        log(LogLevel::Info, out.str());
                    }
                }
            }''', 1)
    sources[emulator] = sources[emulator].replace('                    (void)intrman.dispatchInterrupt(irq, *this);', '''                {
                    const bool handled = intrman.dispatchInterrupt(irq, *this);
                    if (std::getenv("REA_DIAGNOSTICS")) {
                        static unsigned traces = 0;
                        if (traces++ < 32u)
                            log(LogLevel::Info, "[REA audio DMA completion] irq=" + std::to_string(irq) +
                                " handled=" + std::to_string(handled));
                    }
                }''', 1)
    sources[emulator] = sources[emulator].replace('                    host.log(LogLevel::Info, kernel.diagnosticThreads());', '''                    host.log(LogLevel::Info, kernel.diagnosticThreads());
                    std::ostringstream registers;
                    registers << "[REA SPU registers]" << std::hex;
                    for (uint32_t a : {0x1F900198u, 0x1F90019Cu, 0x1F9001A8u, 0x1F9001B0u,
                                       0x1F900344u, 0x1F900598u, 0x1F90059Cu, 0x1F9005A8u,
                                       0x1F9005B0u, 0x1F900744u, 0x1F9007C0u,
                                       0x1F8010C0u, 0x1F8010C4u, 0x1F8010C8u,
                                       0x1F801500u, 0x1F801504u, 0x1F801508u})
                        registers << " " << a << "=" << memory.read32(a);
                    host.log(LogLevel::Info, registers.str());''', 1)
    sources[emulator] = sources[emulator].replace('                    if (reaThreadTraces == 5u)', '''                    if (reaThreadTraces == 5u)
                        if (const char *path = std::getenv("REA_EE_RAM_SNAPSHOT")) {
                            std::vector<uint8_t> bytes(32u * 1024u * 1024u);
                            if (host.readGuest(0u, bytes.data(), bytes.size()))
                                if (FILE *file = std::fopen(path, "wbx")) {
                                    const size_t written = std::fwrite(bytes.data(), 1u, bytes.size(), file);
                                    std::fclose(file);
                                    host.log(LogLevel::Info, "[REA EE RAM snapshot] bytes=" + std::to_string(written));
                                }
                        }
                    if (reaThreadTraces == 5u)''', 1)
    sources[emulator] = sources[emulator].replace('                if (const auto callback = cdvd.takeCompletionCallback())', '''                if (call.ordinal == 6u && !cpu.gpr[2] && std::getenv("REA_DIAGNOSTICS")) {
                    static unsigned failures = 0;
                    if (failures++ < 4u) {
                        std::ostringstream out;
                        out << "[REA disc read rejected] lsn=0x" << std::hex << cpu.gpr[4]
                            << " sectors=0x" << cpu.gpr[5] << " destination=0x" << cpu.gpr[6]
                            << " owned=" << memory.ownsRamRange(cpu.gpr[6], size_t(cpu.gpr[5]) * 2048u);
                        if (auto block = memory.allocationContaining(cpu.gpr[6]))
                            out << " allocation=0x" << block->address << " size=0x" << block->size;
                        log(LogLevel::Warning, out.str());
                    }
                }
                if (const auto callback = cdvd.takeCompletionCallback())''', 1)
    transport = sources[TRANSPORT]
    assert transport.count("class PS2IopTransport") == 1
    transport = transport.replace("class PS2IopTransport", LOADFILE + "\nclass PS2IopTransport")
    old = """        return runtime
                   ? runtime->handleIopRpc(rdram, context, std::move(request))"""
    assert transport.count(old) == 1
    transport = transport.replace(old, """        if (runtime && request.sid == 0x80000006u)
            return reaLoadfileRpc(runtime, rdram, request);
""" + old)
    transport = transport.replace(
        "return !runtime || runtime->canBindIopRpc(sid);",
        "return !runtime || sid == 0x80000006u || runtime->canBindIopRpc(sid);")
    sources[TRANSPORT] = transport

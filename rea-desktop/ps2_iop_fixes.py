"""IOP startup adaptations, used only inside the audited runtime profile.

Register/ABI references and limitations are recorded in VERIFICATION.md.
This implements an empty USB controller, not USB peripheral transfers.
"""

CDVD = "ps2xIOP/src/emulator/imports/iop_cdvd.cpp"
MEMORY = "ps2xIOP/src/emulator/core/iop_memory.cpp"
SYSMEM = "ps2xIOP/src/emulator/imports/iop_sysmem.cpp"
SYSCLIB = "ps2xIOP/src/emulator/imports/iop_sysclib.cpp"
KERNEL = "ps2xIOP/src/emulator/core/iop_kernel.cpp"
KERNEL_HEADER = "ps2xIOP/src/emulator/core/iop_kernel.h"
SOURCE_HASHES = {
    CDVD: "ca8f524a3b708bca4183c940ecdc244468782c0162e832f13e5ae8f088d26f07",
    MEMORY: "3952624ce32b501511a7460a7ce6d387f314d7173e8a6f4a2ed7fc1507e5f4ee",
    SYSMEM: "7d8a0e9439dc9dc733896d74fadb5800d5f9c246609316db521b9ef1edd5b44e",
    SYSCLIB: "f1888fadffdf2ef90913c9b5fc079b812fc4ef9123c566de1d1eb2a808caf974",
    KERNEL: "203c9949793be35f30583612db855544356d1ec1124b96fdf9377e4d321c1002",
    KERNEL_HEADER: "260863c946a687faf5e88c309615de4da319a3028124a97b714468dbf6df0ab5",
}

OHCI_READ = '''        // REA: OHCI 1.0, two powered ports, no attached USB devices.
        if (address == 0x1F801600u) return 0x10u;
        if (address == 0x1F801614u) return readHardware32(0x1F801610u);
        if (address == 0x1F801648u) return 0x202u; // NPS, two ports
        if (address == 0x1F801654u || address == 0x1F801658u) return 0x100u;
'''

OHCI_WRITE = '''        // REA: controller register semantics; no transfer completion is fabricated.
        if (address == 0x1F801608u && (value & 1u))
        {
            const uint32_t routing = readHardware32(0x1F801604u) & 0x100u;
            for (uint32_t reg = 0x1F801604u; reg <= 0x1F801644u; reg += 4u)
                m_hardware[reg] = 0u;
            m_hardware[0x1F801604u] = routing | 0xC0u;
            m_hardware[0x1F801610u] = 0x80000000u;
            m_hardware[0x1F801634u] = 0x27782EDFu;
            m_hardware[0x1F801644u] = 0x628u;
            return; // HCR completes synchronously in this register-only model.
        }
        if (address == 0x1F80160Cu)
        {
            m_hardware[address] &= ~(value & 0x4000007Fu); // W1C
            return;
        }
        if (address == 0x1F801610u || address == 0x1F801614u)
        {
            auto &enabled = m_hardware[0x1F801610u];
            if (address == 0x1F801610u) enabled |= value & 0xC000007Fu;
            else enabled &= ~(value & 0xC000007Fu);
            return;
        }
        if (address == 0x1F801600u || address == 0x1F801648u ||
            address == 0x1F801654u || address == 0x1F801658u)
            return;
        if (address == 0x1F801618u) value &= 0xFFFFFF00u;
'''

SYSMEM_ALLOC = '''            // IOP sysmem works in 256-byte pages, including DMA/HCCA allocations.
            if (a0 > 2u || a1 == 0u || a1 > IopMemory::HeapLimit - IopMemory::HeapBase ||
                (a0 == 2u && (a2 & 255u)))
            {
                setV0(0u);
                return true;
            }
            const uint32_t size = (a1 + 255u) & ~255u;
            if (a0 == 2u && (a2 < IopMemory::HeapBase || a2 > IopMemory::HeapLimit - size))
            {
                setV0(0u);
                return true;
            }
            uint32_t address = 0u;
            if (a0 == 2u) address = m_memory.allocate(size, 256u, a2);
            else
            {
                // Both first-fit and last-fit reuse freed pages.
                uint32_t cursor = a0 == 1u ? IopMemory::HeapLimit - size : IopMemory::HeapBase;
                for (;;)
                {
                    address = m_memory.allocate(size, 256u, cursor);
                    if (address) break;
                    if (a0 == 1u)
                    {
                        if (cursor == IopMemory::HeapBase) break;
                        cursor -= 256u;
                    }
                    else
                    {
                        if (cursor == IopMemory::HeapLimit - size) break;
                        cursor += 256u;
                    }
                }
            }
'''

FPL_FIELDS = '''        struct FixedPool
        {
            uint32_t base = 0, blockSize = 0, stride = 0, count = 0, attr = 0, option = 0;
            std::vector<uint8_t> allocated;
            std::deque<uint32_t> freeBlocks;
        };
        std::map<int, FixedPool> m_fixedPools;
        uint32_t m_nextPoolId = 1;
        uint64_t m_poolWaitSequence = 0;
'''

FPL_DISPATCH = '''    bool IopKernel::dispatchFixedPoolImport(uint16_t ordinal, IopCpuState &cpu)
    {
        if (ordinal < 4 || ordinal > 12 || ordinal == 10) return false;
        const auto result = [&](int32_t value) { cpu.gpr[2] = static_cast<uint32_t>(value); return true; };
        const auto validRam = [](uint32_t ptr, uint32_t size) {
            ptr = IopMemory::physicalAddress(ptr);
            return ptr && ptr <= IopMemory::RamSize && size <= IopMemory::RamSize - ptr;
        };
        if (ordinal == 4)
        {
            const uint32_t ptr = cpu.gpr[4];
            if (!validRam(ptr, 16u)) return result(-426);
            FixedPool pool;
            pool.attr = m_memory.read32(ptr);
            pool.option = m_memory.read32(ptr + 4u);
            pool.blockSize = m_memory.read32(ptr + 8u);
            pool.count = m_memory.read32(ptr + 12u);
            if (pool.attr & ~0x201u) return result(-401);
            if (!pool.blockSize || !pool.count || pool.blockSize > IopMemory::RamSize)
                return result(-427);
            pool.stride = (pool.blockSize + 3u) & ~3u;
            const uint64_t bytes = static_cast<uint64_t>(pool.stride) * pool.count;
            if (bytes > IopMemory::HeapLimit - IopMemory::HeapBase) return result(-400);
            const uint32_t size = (static_cast<uint32_t>(bytes) + 255u) & ~255u;
            const bool fromTop = (pool.attr & 0x200u) != 0;
            uint32_t cursor = fromTop ? IopMemory::HeapLimit - size : IopMemory::HeapBase;
            for (;;)
            {
                pool.base = m_memory.allocate(size, 256u, cursor);
                if (pool.base) break;
                if (fromTop)
                {
                    if (cursor == IopMemory::HeapBase) break;
                    cursor -= 256u;
                }
                else
                {
                    if (cursor == IopMemory::HeapLimit - size) break;
                    cursor += 256u;
                }
            }
            if (!pool.base) return result(-400);
            pool.allocated.resize(pool.count, 0u);
            for (uint32_t index = 0; index < pool.count; ++index) pool.freeBlocks.push_back(index);
            const int id = static_cast<int>(m_nextPoolId++);
            m_fixedPools.emplace(id, std::move(pool));
            return result(id);
        }
        const int id = static_cast<int>(cpu.gpr[4]);
        const auto found = m_fixedPools.find(id);
        if (found == m_fixedPools.end()) return result(-412);
        auto &pool = found->second;
        if (ordinal == 5)
        {
            for (auto &[tid, thread] : m_threads)
            {
                if (thread.state != IopThreadState::FixedPool || thread.waitId != id) continue;
                thread.state = IopThreadState::Ready;
                thread.waitId = 0;
                thread.cpu.gpr[2] = static_cast<uint32_t>(-425);
            }
            (void)m_memory.freeAllocation(pool.base);
            m_fixedPools.erase(found);
            return result(0);
        }
        if (ordinal >= 6 && ordinal <= 8)
        {
            if (!pool.freeBlocks.empty())
            {
                const uint32_t index = pool.freeBlocks.front();
                pool.freeBlocks.pop_front();
                pool.allocated[index] = 1;
                return result(pool.base + index * pool.stride);
            }
            if (ordinal != 6) return result(-400);
            if (!m_currentThread || &m_currentThread->cpu != &cpu) return result(-417);
            m_currentThread->state = IopThreadState::FixedPool;
            m_currentThread->waitId = id;
            m_currentThread->poolWaitOrder = ++m_poolWaitSequence;
            cpu.yielded = true;
            return result(0); // Replaced with a real block address on wakeup.
        }
        if (ordinal == 9)
        {
            const uint32_t ptr = IopMemory::physicalAddress(cpu.gpr[5]);
            if (ptr < pool.base || ptr - pool.base >= pool.stride * pool.count ||
                (ptr - pool.base) % pool.stride) return result(-426);
            const uint32_t index = (ptr - pool.base) / pool.stride;
            if (!pool.allocated[index]) return result(-426);
            IopThread *next = nullptr;
            for (auto &[tid, thread] : m_threads)
            {
                if (thread.state != IopThreadState::FixedPool || thread.waitId != id) continue;
                const bool byPriority = (pool.attr & 1u) != 0;
                if (!next || (byPriority && thread.priority < next->priority) ||
                    ((!byPriority || thread.priority == next->priority) && thread.poolWaitOrder < next->poolWaitOrder))
                    next = &thread;
            }
            if (next)
            {
                next->state = IopThreadState::Ready;
                next->waitId = 0;
                next->cpu.gpr[2] = ptr;
            }
            else
            {
                pool.allocated[index] = 0;
                pool.freeBlocks.push_back(index);
            }
            return result(0);
        }
        const uint32_t out = cpu.gpr[5];
        if (!validRam(out, 24u)) return result(-426);
        uint32_t waiters = 0;
        for (const auto &[tid, thread] : m_threads)
            if (thread.state == IopThreadState::FixedPool && thread.waitId == id) ++waiters;
        m_memory.write32(out, pool.attr);
        m_memory.write32(out + 4u, pool.option);
        m_memory.write32(out + 8u, pool.blockSize);
        m_memory.write32(out + 12u, pool.count);
        m_memory.write32(out + 16u, static_cast<uint32_t>(pool.freeBlocks.size()));
        m_memory.write32(out + 20u, waiters);
        return result(0);
    }

'''


def adapt(sources, emulator):
    sources[SYSCLIB] = sources[SYSCLIB].replace('''        case 8:
        case 9: // ctype table is optional for most IRXs.''', '''        case 8: // look_ctype_table: PS2SDK IOP classification, independent of host locale.
        {
            const uint32_t c = a0 & 255u;
            uint32_t flags = 0u;
            if (c >= '0' && c <= '9') flags = 4u;
            else if (c >= 'A' && c <= 'Z') flags = 1u | (c <= 'F' ? 64u : 0u);
            else if (c >= 'a' && c <= 'z') flags = 2u | (c <= 'f' ? 64u : 0u);
            else if (c >= 9u && c <= 13u) flags = 8u;
            else if (c < 32u || c == 127u) flags = 32u;
            else if (c == 32u) flags = 24u;
            else if (c < 127u) flags = 16u;
            setV0(flags);
            return true;
        }
        case 9: // get_ctype_table is not implemented.''', 1)
    sources[MEMORY] = sources[MEMORY].replace(
        "        const auto value = m_hardware.find(address);", OHCI_READ + "        const auto value = m_hardware.find(address);", 1
    ).replace("    void IopMemory::writeHardware32(uint32_t address, uint32_t value)\n    {",
              "    void IopMemory::writeHardware32(uint32_t address, uint32_t value)\n    {\n" + OHCI_WRITE)
    start = sources[SYSMEM].index("            const uint32_t address = a0 == 2u")
    end = sources[SYSMEM].index("            setV0(address);", start)
    sources[SYSMEM] = sources[SYSMEM][:start] + SYSMEM_ALLOC + sources[SYSMEM][end:]
    sources[KERNEL_HEADER] = sources[KERNEL_HEADER].replace("#include <map>", "#include <map>\n#include <deque>\n#include <vector>")
    sources[KERNEL_HEADER] = sources[KERNEL_HEADER].replace("        EventFlag,", "        EventFlag,\n        FixedPool,")
    sources[KERNEL_HEADER] = sources[KERNEL_HEADER].replace("        int waitId = 0;", "        int waitId = 0;\n        uint64_t poolWaitOrder = 0;")
    sources[KERNEL_HEADER] = sources[KERNEL_HEADER].replace("        void reset();", "        void reset();\n        [[nodiscard]] bool dispatchFixedPoolImport(uint16_t ordinal, IopCpuState &cpu);")
    sources[KERNEL_HEADER] = sources[KERNEL_HEADER].replace("        struct Semaphore", FPL_FIELDS + "\n        struct Semaphore")
    sources[KERNEL] = sources[KERNEL].replace("        m_threads.clear();", "        for (const auto &[id, pool] : m_fixedPools) (void)m_memory.freeAllocation(pool.base);\n        m_fixedPools.clear();\n        m_nextPoolId = 1;\n        m_poolWaitSequence = 0;\n        m_threads.clear();", 1)
    sources[KERNEL] = sources[KERNEL].replace("    bool IopKernel::dispatchSemaphoreImport", FPL_DISPATCH + "    bool IopKernel::dispatchSemaphoreImport")
    sources[KERNEL] = sources[KERNEL].replace("        case IopThreadState::EventFlag:", "        case IopThreadState::FixedPool:\n        case IopThreadState::EventFlag:")
    sources[KERNEL] = sources[KERNEL].replace("thread.state == IopThreadState::EventFlag ? 4u", "thread.state == IopThreadState::FixedPool ? 7u\n                                                                                       : thread.state == IopThreadState::EventFlag ? 4u")
    sources[KERNEL] = sources[KERNEL].replace("it->second.state == IopThreadState::EventFlag)", "it->second.state == IopThreadState::FixedPool ||\n                it->second.state == IopThreadState::EventFlag)")
    sources[KERNEL] = sources[KERNEL].replace("                it->second.state = IopThreadState::Ready;\n            }\n            setV0(0);", "                if (it->second.state == IopThreadState::FixedPool)\n                {\n                    it->second.cpu.gpr[2] = static_cast<uint32_t>(-418);\n                    it->second.waitId = 0;\n                }\n                it->second.state = IopThreadState::Ready;\n            }\n            setV0(0);", 1)
    sources[emulator] = sources[emulator].replace('            if (iequals(call.library, "thsemap"))', '''            if (iequals(call.library, "thfpool") && kernel.dispatchFixedPoolImport(call.ordinal, cpu))
                return ImportDisposition::Handled;
            if (iequals(call.library, "thsemap"))''')
    # A CD DMA destination is physical IOP RAM, including untouched static
    # buffers. Initialization/allocator bookkeeping is not a mapping boundary.
    sources[CDVD] = sources[CDVD].replace(
        '            if (byteCount64 > IopMemory::RamSize || !memory.ownsRamRange(destination, static_cast<size_t>(byteCount64)))',
        '''            const uint32_t physical = IopMemory::physicalAddress(destination);
            if (physical >= IopMemory::RamSize || byteCount64 > IopMemory::RamSize - physical)''', 1)
    cache_idle_schedule(sources, emulator)


def cache_idle_schedule(sources: dict[str, str], emulator: str) -> None:
    """Avoid rescanning sleeping threads at every EE checkpoint.

    Cache only an empty ready queue and its earliest delay deadline. Every
    scheduler mutation invalidates it; DMA, SPU and timer servicing still runs
    in the emulator before each scheduling decision.
    """
    sources[KERNEL_HEADER] = sources[KERNEL_HEADER].replace(
        "        IopThread *m_currentThread = nullptr;",
        """        IopThread *m_currentThread = nullptr;
        bool m_idleScheduleValid = false;
        uint64_t m_idleWakeCycle = UINT64_MAX;""")
    text = sources[KERNEL]
    # Include indirect wakeups (semaphores, event flags, fixed pools), module
    # unload, reset and externally updated timeslices, not just StartThread.
    import re
    mutations = (
        "reset", "dispatchThreadImport", "dispatchFixedPoolImport",
        "dispatchSemaphoreImport", "dispatchEventImport",
        "createInternalEventFlag", "setInternalEventFlag",
        "sleepCurrent", "delayCurrentUntil", "endTimeslice",
        "cleanupDeadThreads", "terminateThreadsInRange",
        "wakeOneSemaphore", "wakeEventWaiters",
    )
    for name in mutations:
        text, count = re.subn(
            rf"(IopKernel::{name}\([^{{]*\)\s*\{{)",
            r"\1\n        m_idleScheduleValid = false;", text)
        assert count == 1, f"Missing scheduler mutation: {name}"
    text = text.replace(
        "    IopThread *IopKernel::beginNextReady(uint64_t currentCycle)\n    {",
        """    IopThread *IopKernel::beginNextReady(uint64_t currentCycle)
    {
        if (m_idleScheduleValid && currentCycle < m_idleWakeCycle)
            return nullptr;
        m_idleScheduleValid = false;
        m_idleWakeCycle = UINT64_MAX;""")
    text = text.replace(
        "                thread.state = IopThreadState::Ready;\n        }\n\n        IopThread *next = nullptr;",
        """                thread.state = IopThreadState::Ready;
            if (thread.state == IopThreadState::Delay)
                m_idleWakeCycle = std::min(m_idleWakeCycle, thread.wakeCycle);
        }

        IopThread *next = nullptr;""")
    text = text.replace(
        "        if (next == nullptr)\n            return nullptr;",
        """        if (next == nullptr)
        {
            m_idleScheduleValid = true;
            return nullptr;
        }""")
    text = text.replace(
        "    uint64_t IopKernel::nextWakeCycle(uint64_t fallback) const\n    {",
        """    uint64_t IopKernel::nextWakeCycle(uint64_t fallback) const
    {
        if (m_idleScheduleValid)
            return std::min(fallback, m_idleWakeCycle);""")
    sources[KERNEL] = text

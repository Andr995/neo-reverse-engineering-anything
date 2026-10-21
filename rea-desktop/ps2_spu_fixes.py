"""SPU2 capture-buffer clock for the fingerprint-scoped runtime.

The capture/mix buffers advance at 48 kHz (768 IOP cycles/sample), including
when voices are silent. IRQ address comparisons latch SPDIF IRQINFO until
ATTR disables the corresponding IRQ. This is timing support, not synthesis.
Register map and capture layout checked against PCSX2 SPU2 regs.h/Mixer.cpp.
"""
MEMORY = 'ps2xIOP/src/emulator/core/iop_memory.cpp'
HEADER = 'ps2xIOP/src/emulator/core/iop_memory.h'
SOURCE_HASHES = {
    HEADER: '5a5b73ab69c4b58531111cad2743847ef00f3a8dd73004eea01ec8de4053135c',
}

CLOCK = '''
namespace ps2x::iop::detail {
    bool IopMemory::advanceSpuClock(uint64_t cycle) {
        const uint64_t samples = (cycle - m_spuCycle) / 768u;
        if (!samples) return false;
        m_spuCycle += samples * 768u;
        bool raised = false;
        for (unsigned core = 0; core < 2; ++core) {
            const uint32_t base = Spu2Base + core * 0x400u;
            const uint32_t attr = read16(base + 0x19Au);
            const uint32_t irqAddress = ((read16(base + 0x19Cu) & 15u) << 16u) |
                                         read16(base + 0x19Eu);
            const uint32_t flag = (4u << core) << 16u;
            // All capture/mix blocks in [0x400,0x2000) advance even in silence.
            // Voice decoding, reverb addresses and AutoDMA input need their own accesses.
            if ((attr & 0x40u) && irqAddress >= 0x400u && irqAddress < 0x2000u &&
                !(readHardware32(Spu2Base + 0x7C0u) & flag)) {
                const uint32_t distance = ((irqAddress & 0x1FFu) - m_spuPosition) & 0x1FFu;
                if (samples > distance) {
                    m_hardware[Spu2Base + 0x7C0u] |= flag;
                    raised = true;
                }
            }
        }
        m_spuPosition = (m_spuPosition + static_cast<uint32_t>(samples & 0x1FFu)) & 0x1FFu;
        return raised;
    }
}
'''

def adapt(sources, emulator):
    sources[HEADER] = sources[HEADER].replace('        void reset();',
        '        void reset();\n        bool advanceSpuClock(uint64_t cycle);', 1)
    sources[HEADER] = sources[HEADER].replace('        uint32_t m_heapCursor',
        '        uint64_t m_spuCycle = 0;\n        uint32_t m_spuPosition = 0;\n        uint32_t m_heapCursor', 1)
    sources[MEMORY] = sources[MEMORY].replace('        m_hardware.clear();',
        '        m_hardware.clear();\n        m_spuCycle = 0;\n        m_spuPosition = 0;', 1)
    sources[MEMORY] = sources[MEMORY].replace('        m_hardware[address] = value;', '''        // Clearing ATTR.IRQEnable acknowledges the corresponding SPU IRQ latch.
        if ((address == Spu2Base + 0x198u || address == Spu2Base + 0x598u) &&
            !(value & (0x40u << 16u)))
            m_hardware[Spu2Base + 0x7C0u] &= ~((address == Spu2Base + 0x198u ? 4u : 8u) << 16u);
        m_hardware[address] = value;''', 1)
    sources[MEMORY] += CLOCK
    sources[emulator] = sources[emulator].replace('            totalCycles = 0;',
        '            totalCycles = 0;\n            reaSpuPending = false;\n            reaNextSpuCycle = 768u;\n            reaServicingSpu = false;', 1)
    sources[emulator] = sources[emulator].replace('        bool checkInterrupt(CpuState &cpu)', '''        bool reaSpuPending = false, reaServicingSpu = false;
        uint64_t reaNextSpuCycle = 768u;
        void serviceSpuClock() {
            if (reaServicingSpu || (totalCycles < reaNextSpuCycle && !reaSpuPending)) return;
            if (totalCycles >= reaNextSpuCycle) {
                reaSpuPending = memory.advanceSpuClock(totalCycles) || reaSpuPending;
                reaNextSpuCycle = (totalCycles / 768u + 1u) * 768u;
            }
            if (!reaSpuPending) return;
            if (!(memory.read16(0x1F9007C2u) & 12u)) reaSpuPending = false;
            if (!reaSpuPending || !memory.interruptControl()) return;
            reaServicingSpu = true;
            try {
                if (intrman.dispatchInterrupt(9, *this)) reaSpuPending = false;
            } catch (...) {
                reaServicingSpu = false;
                throw;
            }
            reaServicingSpu = false;
        }

        bool checkInterrupt(CpuState &cpu)''', 1)
    sources[emulator] = sources[emulator].replace('                if (!step(cpu))',
        '                serviceSpuClock();\n                if (!step(cpu))', 1)
    sources[emulator] = sources[emulator].replace('                    timrman.serviceDue(totalCycles, *this);',
        '                    serviceSpuClock();\n                    timrman.serviceDue(totalCycles, *this);', 1)
    sources[emulator] = sources[emulator].replace('                        nextWake = timrman.nextEventCycle(nextWake);',
        '                        nextWake = std::min(nextWake, (totalCycles / 768u + 1u) * 768u);\n                        nextWake = timrman.nextEventCycle(nextWake);', 1)
    # Preserve the sound-bank bytes: previously MMIO kept only the last FIFO
    # value and DMA reported completion without transferring SPU RAM contents.
    sources[HEADER] = sources[HEADER].replace('        std::vector<uint8_t> m_ram;', '''        void checkSpuTransferIrq(uint32_t start, uint32_t halfwords);
        std::vector<uint16_t> m_spuRam = std::vector<uint16_t>(0x100000u);
        mutable uint32_t m_spuTransfer[2]{};
        bool m_spuTransferIrq = false;
        std::vector<uint8_t> m_ram;''', 1)
    sources[MEMORY] = sources[MEMORY].replace('        m_spuCycle = 0;', '''        std::fill(m_spuRam.begin(), m_spuRam.end(), uint16_t{0});
        m_spuTransfer[0] = m_spuTransfer[1] = 0;
        m_spuTransferIrq = false;
        m_spuCycle = 0;''', 1)
    # These accesses must remain a single halfword transaction, unlike generic MMIO.
    read_start = sources[MEMORY].index('    uint16_t IopMemory::read16')
    write_start = sources[MEMORY].index('    void IopMemory::write16')
    for start, writing in ((write_start, True), (read_start, False)):
        pos = sources[MEMORY].index('        if (phys', start)
        operation = '''            m_spuRam[m_spuTransfer[core]] = value;
            checkSpuTransferIrq(m_spuTransfer[core], 1u);
            m_spuTransfer[core] = (m_spuTransfer[core] + 1u) & 0xFFFFFu;
            return;''' if writing else '''            const uint16_t value = m_spuRam[m_spuTransfer[core]];
            m_spuTransfer[core] = (m_spuTransfer[core] + 1u) & 0xFFFFFu;
            return value;'''
        sources[MEMORY] = sources[MEMORY][:pos] + '''        if (phys == Spu2Base + 0x1ACu || phys == Spu2Base + 0x5ACu) {
            const unsigned core = phys == Spu2Base + 0x5ACu ? 1u : 0u;
''' + operation + '\n        }\n' + sources[MEMORY][pos:]
    sources[MEMORY] = sources[MEMORY].replace('        m_hardware[address] = value;', '''        m_hardware[address] = value;
        if (address == Spu2Base + 0x1A8u || address == Spu2Base + 0x5A8u)
            m_spuTransfer[address == Spu2Base + 0x5A8u ? 1u : 0u] =
                ((value & 15u) << 16u) | (value >> 16u);''', 1)
    sources[MEMORY] = sources[MEMORY].replace('        m_dmaStart = DmaStart{', '''        const unsigned core = secondCore ? 1u : 0u;
        const uint32_t dmaAddress = physicalAddress(readHardware32(address - 8u));
        const uint64_t bytes = transferWords * 4u;
        // Reject impossible memory ranges before copying or reporting completion.
        if (dmaAddress >= RamSize || bytes > RamSize - dmaAddress) return;
        const uint32_t count = static_cast<uint32_t>(bytes / 2u);
        const uint32_t start = m_spuTransfer[core];
        for (uint32_t i = 0; i < count; ++i) {
            auto &word = m_spuRam[(start + i) & 0xFFFFFu];
            if (value & 1u) std::memcpy(&word, m_ram.data() + dmaAddress + i * 2u, 2u);
            else std::memcpy(m_ram.data() + dmaAddress + i * 2u, &word, 2u);
        }
        if (!(value & 1u)) markOwned(dmaAddress, static_cast<size_t>(bytes));
        checkSpuTransferIrq(start, count);
        m_spuTransfer[core] = (start + count) & 0xFFFFFu;
        m_dmaStart = DmaStart{''', 1)
    sources[MEMORY] = sources[MEMORY].replace('        if (!samples) return false;', '''        const bool transferIrq = m_spuTransferIrq;
        m_spuTransferIrq = false;
        if (!samples) return transferIrq;''', 1).replace('        bool raised = false;', '        bool raised = transferIrq;', 1)
    sources[MEMORY] += '''
namespace ps2x::iop::detail {
void IopMemory::checkSpuTransferIrq(uint32_t start, uint32_t halfwords) {
    for (unsigned core = 0; core < 2; ++core) {
        const uint32_t base = Spu2Base + core * 0x400u;
        const uint32_t address = ((read16(base + 0x19Cu) & 15u) << 16u) | read16(base + 0x19Eu);
        const uint32_t distance = (address - start) & 0xFFFFFu;
        const uint32_t flag = (4u << core) << 16u;
        if ((read16(base + 0x19Au) & 0x40u) && distance && distance <= halfwords &&
            !(readHardware32(Spu2Base + 0x7C0u) & flag)) {
            m_hardware[Spu2Base + 0x7C0u] |= flag;
            m_spuTransferIrq = true;
        }
    }
}
}
'''

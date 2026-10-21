// Verify capture-buffer IRQ timing using the production IOP memory model.
#include "emulator/core/iop_memory.h"
#include <stdexcept>
#include <iostream>
using ps2x::iop::detail::IopMemory;
void check(bool ok, const char* why) { if (!ok) throw std::runtime_error(why); }
int main() {
    IopMemory m;
    constexpr unsigned base = IopMemory::Spu2Base;
    m.write16(base + 0x19c, 0); m.write16(base + 0x19e, 0x403);
    m.write16(base + 0x19a, 0xc040);
    check(!m.advanceSpuClock(3*768), "IRQ fired before address reached");
    check(m.advanceSpuClock(4*768), "Capture address failed to trigger IRQ");
    check(m.read16(base+0x7c2) == 4, "Wrong core IRQINFO bit");
    check(!m.advanceSpuClock(516*768), "Latched IRQ retriggered without acknowledgement");
    m.write16(base+0x19a, 0xc000);
    check(m.read16(base+0x7c2) == 0, "Disabling IRQ must clear its latch");
    m.write16(base+0x19a, 0xc040);
    check(!m.advanceSpuClock(1027*768), "IRQ retriggered before next wrap");
    check(m.advanceSpuClock(1028*768), "IRQ failed after acknowledgement and wrap");
    m.reset();
    m.write16(base+0x59e, 0x800); m.write16(base+0x59a, 0xc040);
    check(m.advanceSpuClock(768) && m.read16(base+0x7c2)==8, "Cross-core capture comparison");
    m.write16(base+0x19a, 0);
    check(m.read16(base+0x7c2)==8, "Core 0 acknowledgement cleared core 1");
    m.reset();
    m.write16(base+0x19e, 0x400);
    check(!m.advanceSpuClock(512*768), "Disabled IRQ fired");
    m.write16(base+0x19c, 1); m.write16(base+0x19a, 0xc040);
    check(!m.advanceSpuClock(1024*768), "Unimplemented voice/reverb address fabricated an IRQ");
    m.reset();
    check(!m.advanceSpuClock(768) && !m.read16(base+0x7c2), "Reset retained IRQ state");
    // FIFO halfwords must be stored once, and DMA must move actual sound bytes.
    const auto tsa = [&](unsigned core, unsigned word) {
        m.write16(base + core * 0x400 + 0x1a8, word >> 16);
        m.write16(base + core * 0x400 + 0x1aa, word & 0xffff);
    };
    tsa(0, 0xfffff);
    m.write16(base+0x1ac, 0x1234); m.write16(base+0x1ac, 0x5678);
    tsa(1, 0xfffff);
    check(m.read16(base+0x5ac)==0x1234 && m.read16(base+0x5ac)==0x5678,
          "FIFO halfwords lost, duplicated or failed to wrap shared SPU RAM");
    m.write32(0x1000, 0xdeadbeef); m.write32(0x1004, 0x11223344);
    tsa(1, 0x54320);
    m.write32(0x1f801500, 0x1000); m.write32(0x1f801504, 0x10002);
    m.write32(0x1f801508, 0x01000201);
    auto dma=m.takeDmaStart();
    check(dma && dma->irq==0x28, "Core1 DMA not scheduled");
    tsa(0, 0x54320);
    m.write32(0x1f8010c0, 0x2000); m.write32(0x1f8010c4, 0x10002);
    m.write32(0x1f8010c8, 0x01000200);
    dma=m.takeDmaStart();
    check(dma && dma->irq==0x24 && m.read32(0x2000)==0xdeadbeef && m.read32(0x2004)==0x11223344,
          "DMA roundtrip across both cores corrupted sound data");
    m.write32(0x1f801500, 0x1ffffc); m.write32(0x1f801504, 0x10002);
    m.write32(0x1f801508, 0x01000201);
    check(!m.takeDmaStart(), "Invalid DMA reported completion");
    m.reset(); tsa(0, 0x54320);
    check(m.read16(base+0x1ac)==0, "Reset retained sound bank bytes");
    std::cout << "PASS: 48kHz capture IRQ timing, latching, acknowledgement, wrap, core isolation, FIFO, DMA data roundtrip/bounds and reset\n";
}

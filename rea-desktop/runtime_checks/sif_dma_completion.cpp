// Synthetic IOP module: verify real DMA bytes and deferred guest completion.
#include "../../ps2recomp/ps2xIOP/tests/iop_compat_test_support.h"
#include "emulator/core/iop_memory.h"
#include "emulator/core/iop_kernel.h"
#include "emulator/core/iop_cpu.h"
#include "emulator/services/iop_rpc.h"

int main() {
    using namespace iop_test;
    using namespace ps2x::iop::detail;
    Host host;
    Irx image;
    image.words(0, {
        0x27BDFFE0, 0xAFBF001C,
        0x3C040001, 0x34840200, 0x24050001,
        0x3C060001, 0x34C60300, 0x2407002A,
        0x3C1C1234, 0x379C5678,
        0x0C004045, 0, // SetDmaIntr(descriptor, 1, callback, 42)
        0x8FBF001C, 0, 0x27BD0020, 0x03E00008, 0x00001021,
    });
    image.words(0x100, {0x41E00000, 0, 0x0101, 0x6D666973, 0x00006E61,
        0x03E00008, 0x24000020, 0, 0});
    image.words(0x200, {0x10400, 0x800, 16, 0});
    image.words(0x300, {
        0x3C080001, 0x35080420,
        0xAD040000, 0xAD1C0004, // record userdata and GP
        0x8D090008, 0, 0x25290001, 0xAD090008, // count invocations
        0x03E00008, 0,
    });
    image.words(0x400, {0xDEADBEEF, 0x11223344, 0x55667788, 0xABCDEF01});
    image.install(host);
    IopSubsystem iop(host);
    const auto loaded = iop.loadModuleBuffer(0x1000);
    require(loaded.moduleId > 0 && loaded.startResult == 0, "DMA fixture failed to load");
    require(host.word(0x800) == 0xDEADBEEF && host.word(0x80C) == 0xABCDEF01,
            "SetDmaIntr did not transfer actual bytes to EE");
    for (unsigned n = 0; n < 10; ++n) iop.runEeCycles(10000);
    uint32_t observed[3]{};
    require(iop.readMemory(0x10420, observed, sizeof(observed)), "cannot read completion");
    require(observed[0] == 42 && observed[1] == 0x12345678 && observed[2] == 1,
            "completion must execute original guest callback once with userdata and GP");
    for (unsigned n = 0; n < 10; ++n) iop.runEeCycles(10000);
    require(iop.readMemory(0x10420, observed, sizeof(observed)) && observed[2] == 1,
            "completion was delivered twice");

    // A malformed chain must neither write a prefix nor schedule its callback.
    IopMemory memory;
    IopKernel kernel(memory);
    IopRpcBridge bridge(host, memory, kernel);
    IopCpuState cpu{};
    const uint32_t descriptors[] = {0x1000, 0x900, 4, 0, 0x1000, 0x1FFFF, 4, 0};
    require(memory.writeRam(0x2000, descriptors, sizeof(descriptors)), "descriptor setup failed");
    memory.write32(0x1000, 99);
    cpu.gpr[4] = 0x2000; cpu.gpr[5] = 2; cpu.gpr[6] = 0x10300; cpu.gpr[7] = 42;
    require(bridge.dispatchSifManImport(32, cpu) && cpu.gpr[2] == 0 &&
            host.word(0x900) == 0xCCCCCCCC && !bridge.takeDmaCompletion(),
            "invalid DMA chain partially committed or scheduled completion");
    cpu.gpr[5] = 1;
    require(bridge.dispatchSifManImport(32, cpu) && cpu.gpr[2] != 0 && host.word(0x900) == 99,
            "valid DMA chain failed");
    bridge.reset();
    require(!bridge.takeDmaCompletion(), "reset retained an old completion");
    cpu.gpr[6] = 0;
    require(bridge.dispatchSifManImport(32, cpu) && cpu.gpr[2] != 0 && !bridge.takeDmaCompletion(),
            "optional null callback rejected or scheduled");
    std::cout << "PASS: DMA data, original deferred callback, GP/userdata, exactly-once and invalid-chain isolation\n";
}

// Original synthetic IRX tests the real EE -> IOP transport, no game or display.
#include "ps2_runtime.h"
#include "ps2_runtime_macros.h"
#include "Stubs/SIF.h"
#include "Syscalls/RPC.h"
#include "../../ps2recomp/ps2xIOP/tests/iop_compat_test_support.h"

extern const uint32_t g_ps2RecompiledFunctionTableBase = 0;
extern const uint32_t g_ps2RecompiledFunctionTableEnd = 4;
extern const uint32_t g_ps2RecompiledFunctionTableSlotCount = 1;
PS2Runtime::RecompiledFunction g_ps2RecompiledFunctionTable[1] = {};

int main() {
    using iop_test::require;
    iop_test::Irx image;
    image.words(0, {
        0x27BDFFE0, 0xAFBF001C, // save caller
        0x3C040001, 0x34840200, 0x24050002,
        0x0C004045, 0, // SetCmdBuffer(0x10200, 2)
        0x24040001, 0x3C050001, 0x34A50300,
        0x3C060001, 0x34C60400,
        0x3C1C1234, 0x379C5678,
        0x0C004047, 0, // AddCmdHandler(1, 0x10300, 0x10400)
        0x8FBF001C, 0, 0x27BD0020, 0x03E00008, 0x00001021,
    });
    image.words(0x100, {0x41E00000, 0, 0x0101, 0x63666973, 0x0000646D,
        0x03E00008, 0x24000008, 0x03E00008, 0x2400000A, 0, 0});
    image.words(0x300, {
        0x8C880000, 0x8C890008, 0, // packet size and cid
        0xACA80000, 0xACA90004, 0xACBC0008, // observed size, cid, saved gp
        0x8C8A0010, 0, 0xACAA000C, // packet payload
        0x8C8B0004, 0, // extra destination
        0x11600004, 0, // skip extra read if absent
        0x8D6C0000, 0, 0xACAC0010,
        0x03E00008, 0,
    });
    PS2Runtime runtime;
    require(runtime.memory().initialize(), "runtime RAM initialization failed");
    uint8_t *ram = runtime.memory().getRDRAM();
    require(ram != nullptr, "runtime RAM unavailable");
    std::memcpy(ram + 0x1000, image.bytes.data(), image.bytes.size());
    const auto loaded = runtime.loadIopModuleBuffer(0x1000);
    require(loaded.moduleId > 0 && loaded.startResult == 0, "command receiver IRX failed");
    const uint32_t destination = runtime.allocateIopMemory(16, 16);
    require(destination != 0, "IOP destination allocation failed");
    const uint32_t payload = 0xDEADBEEF;
    std::memcpy(ram + 0x4000, &payload, 4);
    std::memset(ram + destination, 0xCC, 16); // equal-numbered EE RAM must remain unchanged
    auto send = [&](bool syscall, uint32_t cid, uint32_t size, uint32_t extra) {
        R5900Context cpu;
        auto *ctx = &cpu;
        const uint32_t packet[5] = {0, 0, 0, 0x778899AA, 42};
        std::memcpy(ram + 0x3000, packet, sizeof(packet));
        SET_GPR_U32(ctx, 4, cid); SET_GPR_U32(ctx, 5, 0x3000);
        SET_GPR_U32(ctx, 6, size); SET_GPR_U32(ctx, 7, 0x4000);
        SET_GPR_U32(ctx, 8, destination); SET_GPR_U32(ctx, 9, extra);
        SET_GPR_U32(ctx, 29, 0x5000);
        std::memset(ram + 0x5010, 0xFF, 8); // stack ABI would read invalid arguments
        if (syscall) ps2_syscalls::sceSifSendCmd(ram, ctx, &runtime);
        else ps2_stubs::sceSifSendCmd(ram, ctx, &runtime);
        return getRegU32(ctx, 2);
    };
    for (bool syscall : {false, true}) {
        require(runtime.zeroIopMemory(0x10400, 20), "cannot reset receiver");
        require(send(syscall, 1, 20, 4) != 0, "valid command failed");
        uint32_t observed[5]{};
        require(runtime.readIopMemory(0x10400, observed, sizeof(observed)), "cannot read callback result");
        require(observed[0] == (20 | (4 << 8)) && observed[1] == 1 &&
                observed[2] == 0x12345678 && observed[3] == 42 && observed[4] == payload,
                "callback did not receive header, harg, gp and payload before dispatch");
        uint32_t untouched;
        std::memcpy(&untouched, ram + destination, 4);
        require(untouched == 0xCCCCCCCC, "IOP DMA corrupted equal-numbered EE address");
        require(runtime.zeroIopMemory(0x10400, 20), "cannot reset receiver");
        require(send(syscall, 1, 15, 4) == 0, "short packet accepted");
        require(send(syscall, 1, 113, 4) == 0, "oversized packet accepted");
        require(send(syscall, 1, 20, 0x1000000) == 0, "oversized extra DMA accepted");
        require(runtime.readIopMemory(0x10400, observed, sizeof(observed)) && observed[0] == 0,
                "invalid packet invoked callback");
        require(send(syscall, 2, 20, 0) != 0, "unregistered command DMA should complete");
        require(runtime.readIopMemory(0x10400, observed, sizeof(observed)) && observed[0] == 0,
                "unregistered command called another handler");
        require(send(syscall, 1, 20, 0) != 0, "command without extra payload failed");
    }
    std::cout << "PASS: EE register ABI, SIF packet dispatch, IOP DMA isolation and malformed inputs\n";
}

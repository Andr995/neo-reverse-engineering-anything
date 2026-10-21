// Link against the copied, patched runtime. No graphics or game execution.
#include "ps2_runtime.h"
#include "ps2_runtime_macros.h"
#include <iostream>
#include <stdexcept>
#include <vector>

extern const uint32_t g_ps2RecompiledFunctionTableBase = 0;
extern const uint32_t g_ps2RecompiledFunctionTableEnd = 4;
extern const uint32_t g_ps2RecompiledFunctionTableSlotCount = 1;
PS2Runtime::RecompiledFunction g_ps2RecompiledFunctionTable[1] = {};

void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}

int main() {
    PS2Runtime runtime;
    R5900Context cpu{};
    R5900Context* ctx = &cpu;
    std::vector<uint8_t> ram(PS2_RAM_SIZE);
    SET_GPR_U32(ctx, 4, 0x1f84988u);
    SET_GPR_U32(ctx, 5, 0xffffffffu);
    runtime.handleSyscall(ram.data(), ctx, 0x3du);
    require(getRegU32(ctx, 2) == 0x1f84990u, "heap start must remain above BSS");
    runtime.handleSyscall(ram.data(), ctx, 0x3eu);
    const auto libcEnd = getRegU32(ctx, 2);
    require(libcEnd > 0x1f84990u, "guest malloc must have usable space");
    require(runtime.guestHeapBase() >= libcEnd, "HLE allocations overlap guest libc");
    const auto packet = runtime.guestMalloc(128, 16);
    require(packet >= libcEnd && packet + 128 <= runtime.guestHeapLimit(), "GS scratch outside reserved arena");
    require(runtime.guestMalloc(0x10001u) == 0, "oversized HLE allocation must fail");
    runtime.guestFree(packet);
    require(runtime.guestMalloc(128, 16) == packet, "scratch allocation must be reusable");
    uint32_t previousBase = 0x1ff0000u;
    for (int i = 0; i < 4; ++i) {
        const auto top = runtime.reserveAsyncCallbackStack(0x4000u, 16u);
        require(top != 0, "callback stack reservation unexpectedly failed");
        require(top + 16 <= previousBase, "callback stacks overlap each other or the main stack");
        const auto base = top + 16 - 0x4000u;
        require(base >= runtime.guestHeapLimit(), "callback stack overlaps heap");
        previousBase = base;
    }
    require(runtime.reserveAsyncCallbackStack(0x4000u, 16u) == 0, "stack exhaustion must fail safely");
    SET_GPR_U32(ctx, 4, 0x100000u);
    bool rejected = false;
    try { runtime.handleSyscall(ram.data(), ctx, 0x3du); }
    catch (const std::runtime_error&) { rejected = true; }
    require(rejected, "unexpected memory layout must be rejected");
    std::cout << "PASS: libc, HLE scratch, callback stacks and main stack are disjoint\n";
}

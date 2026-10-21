// Link with the real patched ps2_iop library. No commercial code is embedded.
#define main upstream_iop_tests_main
#include "../../ps2recomp/ps2xIOP/tests/iop_emulator_tests.cpp"
#undef main
#include "emulator/core/iop_memory.h"
#include "emulator/core/iop_kernel.h"
#include "emulator/imports/iop_sysmem.h"
#include "emulator/imports/iop_sysclib.h"
#include <stdexcept>

using namespace ps2x::iop::detail;
static void check(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
}

int main() {
    IopMemory memory;
    constexpr uint32_t usb = 0xbf801600;
    memory.write32(usb + 0x18, 0x12345678);
    check(memory.read32(usb + 0x18) == 0x12345600, "HCCA alignment");
    memory.write32(usb + 8, 1);
    check(!(memory.read32(usb + 8) & 1), "USB reset must complete");
    check(memory.read32(usb + 0x18) == 0, "Reset clears HCCA");
    memory.write32(usb + 0x14, 0xffffffff);
    memory.write32(usb + 0x10, 0x80000002);
    memory.write32(usb + 0x10, 0x40);
    check(memory.read32(usb + 0x14) == 0x80000042, "Interrupt enable W1S/read alias");
    memory.write32(usb + 0x14, 2);
    check(memory.read32(usb + 0x10) == 0x80000040, "Interrupt disable W1C");
    memory.write32(usb + 0xc, 0xffffffff);
    check(memory.read32(usb + 0xc) == 0, "Acknowledging absent IRQ cannot create IRQ");
    check(memory.read32(usb) == 0x10 && memory.read32(usb + 0x48) == 0x202, "Controller identity");
    memory.write32(usb + 0x54, 0xffffffff);
    check(!(memory.read32(usb + 0x54) & 1), "No fabricated connected peripheral");

    TestHost host(0x20000);
    IopSysmem sysmem(host, memory);
    IopCpuState cpu{};
    IopSysclib sysclib(memory);
    for (auto [character, expected] : std::initializer_list<std::pair<uint32_t, uint32_t>>{
            {'0', 4}, {'9', 4}, {'A', 65}, {'F', 65}, {'G', 1},
            {'a', 66}, {'f', 66}, {'g', 2}, {' ', 24}, {'\t', 8},
            {'\n', 8}, {'!', 16}, {0, 32}, {127, 32}, {255, 0}}) {
        cpu.gpr[4] = character;
        check(sysclib.dispatchImport(8, cpu) && cpu.gpr[2] == expected,
              "IOP character classification must support numeric module options");
    }
    const auto alloc = [&](uint32_t mode, uint32_t size, uint32_t fixed = 0) {
        cpu.gpr[4] = mode; cpu.gpr[5] = size; cpu.gpr[6] = fixed;
        check(sysmem.dispatchImport(4, cpu), "AllocSysMemory dispatch");
        return cpu.gpr[2];
    };
    (void)memory.allocate(17, 16);
    const uint32_t first = alloc(0, 257);
    check(first && !(first & 255), "Sysmem address alignment");
    check(memory.allocationContaining(first)->size == 512, "Sysmem size rounding");
    const uint32_t last = alloc(1, 1);
    check(last == IopMemory::HeapLimit - 256, "Last-fit sysmem");
    cpu.gpr[4] = first;
    check(sysmem.dispatchImport(5, cpu) && cpu.gpr[2] == 0, "Sysmem free");
    check(alloc(0, 257) == first, "Reuse freed sysmem");
    check(!alloc(0, 0xffffffff) && !alloc(3, 16) && !alloc(2, 16, first + 1), "Reject invalid allocation");
    check(!alloc(2, 512, 0xffffff00) && !alloc(2, 512, IopMemory::HeapLimit - 256), "Reject overflowing/out-of-arena fixed allocation");

    IopKernel kernel(memory);
    const auto poolCall = [&](uint16_t op, uint32_t a, uint32_t b = 0) {
        cpu.gpr[4] = a; cpu.gpr[5] = b;
        check(kernel.dispatchFixedPoolImport(op, cpu), "FPL dispatch");
        return static_cast<int32_t>(cpu.gpr[2]);
    };
    const auto makePool = [&](uint32_t attr, uint32_t size, uint32_t count) {
        memory.write32(0x100, attr); memory.write32(0x104, 0x1234);
        memory.write32(0x108, size); memory.write32(0x10c, count);
        return poolCall(4, 0x100);
    };
    check(makePool(4, 1, 1) == -401, "Invalid attributes");
    check(makePool(0, 0, 1) == -427, "Zero block size");
    check(makePool(0, 0xffffffff, 4) < 0 && makePool(0, 0x10000, 0xffffffff) < 0, "Overflow rejection");
    for (uint32_t attr : {0u, 1u, 0x200u}) {
        const int id = makePool(attr, 5, 2);
        check(id > 0, "CreateFpl");
        const uint32_t a = poolCall(7, id), b = poolCall(7, id);
        check(a && b == a + 8, "Distinct aligned blocks");
        check(poolCall(7, id) == -400, "Exhausted polling reports no memory");
        check(poolCall(6, id) == -417, "Cannot wait outside current thread");
        check(poolCall(9, id, a + 1) == -426, "Reject interior free");
        check(poolCall(9, id, a) == 0 && poolCall(9, id, a) == -426, "Detect double free");
        check(poolCall(11, id, 0x200) == 0 && memory.read32(0x210) == 1, "Pool free status");
        check(static_cast<uint32_t>(poolCall(7, id)) == a, "Reallocate freed block");
        check(poolCall(5, id) == 0 && poolCall(7, id) == -412, "Deleted pool is invalid");
    }
    // Real scheduler transitions: blocked allocation -> free/delete/release wakeup.
    const auto createThread = [&](uint32_t priority) {
        memory.write32(0x300, 0); memory.write32(0x304, 0);
        memory.write32(0x308, 0x10000); memory.write32(0x30c, 256); memory.write32(0x310, priority);
        cpu.gpr[4] = 0x300; check(kernel.dispatchThreadImport(4, cpu, 0), "Create thread");
        const uint32_t id = cpu.gpr[2];
        cpu.gpr[4] = id; cpu.gpr[5] = 0;
        check(kernel.dispatchThreadImport(6, cpu, 0), "Start thread");
        return id;
    };
    for (const bool priorityQueue : {false, true}) {
        const int id = makePool(priorityQueue ? 1 : 0, 16, 1);
        const uint32_t block = poolCall(7, id);
        createThread(80);
        auto *older = kernel.beginNextReady(0);
        check(older != nullptr, "Old waiter ready");
        older->cpu.gpr[4] = id;
        check(kernel.dispatchFixedPoolImport(6, older->cpu) && older->cpu.yielded, "Allocation blocks");
        kernel.endTimeslice(*older, 0xffffffff);
        createThread(20);
        auto *newer = kernel.beginNextReady(0);
        check(newer && newer != older, "New waiter ready");
        newer->cpu.gpr[4] = id;
        check(kernel.dispatchFixedPoolImport(6, newer->cpu), "Second allocation blocks");
        kernel.endTimeslice(*newer, 0xffffffff);
        check(poolCall(11, id, 0x200) == 0 && memory.read32(0x214) == 2, "Count two waiters");
        check(poolCall(9, id, block) == 0, "Free to waiter");
        auto *selected = kernel.beginNextReady(0);
        check(selected == (priorityQueue ? newer : older) && selected->cpu.gpr[2] == block, "FIFO/priority wake order");
        selected->state = IopThreadState::Dormant;
        kernel.endTimeslice(*selected, 0xffffffff);
        check(poolCall(5, id) == 0, "Delete pool with waiter");
        auto *remaining = kernel.beginNextReady(0);
        check(remaining && static_cast<int32_t>(remaining->cpu.gpr[2]) == -425, "Delete wakes with error");
        remaining->state = IopThreadState::Dormant;
        kernel.endTimeslice(*remaining, 0xffffffff);
    }
    std::cout << "OHCI startup, sysmem alignment and fixed-pool checks passed\n";
}

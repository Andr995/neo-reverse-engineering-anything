// Exercise the production scheduler, including wakes after a cached idle result.
#include "emulator/core/iop_memory.h"
#include "emulator/core/iop_kernel.h"
#include <chrono>
#include <iostream>
#include <stdexcept>
using namespace ps2x::iop::detail;
static void check(bool ok) { if (!ok) throw std::runtime_error("scheduler regression"); }
int main() {
    IopMemory memory;
    IopKernel kernel(memory);
    IopCpuState cpu{};
    const auto create = [&](unsigned priority) {
        memory.write32(0x100,0); memory.write32(0x104,0);
        memory.write32(0x108,0x10000); memory.write32(0x10c,256);
        memory.write32(0x110,priority);
        cpu.gpr[4]=0x100; check(kernel.dispatchThreadImport(4,cpu,0));
        unsigned id=cpu.gpr[2]; cpu.gpr[4]=id;
        check(kernel.dispatchThreadImport(6,cpu,0)); return id;
    };
    const auto idle = [&](uint64_t cycle) {
        for (int n=0;n<20;++n) check(!kernel.beginNextReady(cycle));
    };
    idle(0); create(80);
    auto *first=kernel.beginNextReady(0); check(first);
    kernel.delayCurrentUntil(100,first->cpu);
    kernel.endTimeslice(*first,0xffffffff);
    idle(0); check(kernel.nextWakeCycle(200)==100);
    check(kernel.nextWakeCycle(50)==50); idle(99);
    check(kernel.beginNextReady(100)==first);
    kernel.sleepCurrent(first->cpu); kernel.endTimeslice(*first,0xffffffff);
    idle(101); cpu.gpr[4]=first->id;
    check(kernel.dispatchThreadImport(25,cpu,101)); // WakeupThread
    check(kernel.beginNextReady(101)==first);
    const int event=kernel.createInternalEventFlag(0,0,0);
    first->cpu.gpr[4]=event; first->cpu.gpr[5]=1; first->cpu.gpr[6]=0; first->cpu.gpr[7]=0;
    check(kernel.dispatchEventImport(10,first->cpu));
    kernel.endTimeslice(*first,0xffffffff); idle(102);
    check(kernel.setInternalEventFlag(event,1));
    check(kernel.beginNextReady(102)==first);
    memory.write32(0x200,0); memory.write32(0x204,0);
    memory.write32(0x208,0); memory.write32(0x20c,1);
    cpu.gpr[4]=0x200; check(kernel.dispatchSemaphoreImport(4,cpu));
    const unsigned sem=cpu.gpr[2]; first->cpu.gpr[4]=sem;
    check(kernel.dispatchSemaphoreImport(8,first->cpu));
    kernel.endTimeslice(*first,0xffffffff); idle(103);
    cpu.gpr[4]=sem; check(kernel.dispatchSemaphoreImport(6,cpu));
    check(kernel.beginNextReady(103)==first);
    kernel.sleepCurrent(first->cpu); kernel.endTimeslice(*first,0xffffffff);
    idle(104);
    const unsigned low=create(90), high=create(10);
    auto *chosen=kernel.beginNextReady(104); check(chosen && chosen->id==int(high));
    kernel.delayCurrentUntil(500,chosen->cpu); kernel.endTimeslice(*chosen,0xffffffff);
    chosen=kernel.beginNextReady(104); check(chosen && chosen->id==int(low));
    kernel.delayCurrentUntil(300,chosen->cpu); kernel.endTimeslice(*chosen,0xffffffff);
    idle(200); check(kernel.nextWakeCycle(1000)==300);
    kernel.terminateThreadsInRange(0x10000,4); kernel.cleanupDeadThreads();
    idle(1000); check(kernel.nextWakeCycle(2000)==2000);
    kernel.reset(); idle(0);
    // Reproduce the profiled workload: repeated EE checks with 64 IOP sleepers.
    for(int n=0;n<64;++n) {
        create(64); auto *t=kernel.beginNextReady(0); check(t);
        kernel.delayCurrentUntil(10000000,t->cpu); kernel.endTimeslice(*t,0xffffffff);
    }
    const auto start=std::chrono::steady_clock::now();
    for(uint64_t n=0;n<1000000;++n) {
        check(!kernel.beginNextReady(n)); check(kernel.nextWakeCycle(n+1)==n+1);
    }
    const auto ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
    std::cout<<"Scheduler wake/reset/priority checks passed. 1M idle decisions: "<<ms<<" ms\n";
}

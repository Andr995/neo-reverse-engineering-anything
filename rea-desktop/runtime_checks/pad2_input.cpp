// Exercise the real libpad2 adapter and cached backend without opening a window.
#include "ps2_runtime.h"
#include "ps2_runtime_macros.h"
#include "raylib.h"
#include <cassert>
#include <iostream>
#include <set>
extern const uint32_t g_ps2RecompiledFunctionTableBase = 0;
extern const uint32_t g_ps2RecompiledFunctionTableEnd = 4;
extern const uint32_t g_ps2RecompiledFunctionTableSlotCount = 1;
PS2Runtime::RecompiledFunction g_ps2RecompiledFunctionTable[1] = {};
namespace rea_pad2 {
void init(uint8_t*,R5900Context*,PS2Runtime*);
void create(uint8_t*,R5900Context*,PS2Runtime*);
void close(uint8_t*,R5900Context*,PS2Runtime*);
void state(uint8_t*,R5900Context*,PS2Runtime*);
void read(uint8_t*,R5900Context*,PS2Runtime*);
void buttonProfile(uint8_t*,R5900Context*,PS2Runtime*);
}
extern void reaPollPadInput();
extern void sub_003A27E0_0x3a27e0(uint8_t*,R5900Context*,PS2Runtime*);
static std::set<int> keys;
extern "C" bool __wrap_IsWindowReady() { return true; }
extern "C" bool __wrap_IsKeyDown(int key) { return keys.contains(key); }
extern "C" bool __wrap_IsGamepadAvailable(int) { return false; }
extern "C" bool __wrap_IsGamepadButtonDown(int,int) { return false; }
extern "C" float __wrap_GetGamepadAxisMovement(int,int) { return 0; }
int main() {
    std::vector<uint8_t> ram(PS2_RAM_SIZE,0xa5); R5900Context cpu{}; auto *ctx=&cpu;
    auto call=[&](auto function,uint32_t a0=0,uint32_t a1=0) {
        SET_GPR_U32(ctx,4,a0); SET_GPR_U32(ctx,5,a1); SET_GPR_U32(ctx,31,0x1234);
        function(ram.data(),ctx,nullptr); assert(ctx->pc==0x1234); return GPR_S32(ctx,2);
    };
    call(rea_pad2::init); assert(call(rea_pad2::state,0)==0);
    assert(call(rea_pad2::create,0,0x10001)==-1);
    assert(call(rea_pad2::create,0,0x1ffffc0)==-1);
    const int id=call(rea_pad2::create,0,0x10000); assert(id==0);
    assert(call(rea_pad2::state,id)==1);
    assert(call(rea_pad2::buttonProfile,id,0x11000)==5);
    assert(ram[0x11000]==255 && ram[0x11003]==255 && ram[0x11004]==0 && ram[0x11005]==0xa5);
    keys={KEY_X,KEY_LEFT,KEY_A,KEY_I}; reaPollPadInput();
    assert(call(rea_pad2::read,id,0x12000)==18);
    assert(ram[0x12000]==0x7f && ram[0x12001]==0xbf); // Left and Cross, active-low.
    assert(ram[0x12003]==0 && ram[0x12004]==0); // right Y / left X
    assert(ram[0x1200c]==255 && ram[0x12012]==0xa5); // Cross pressure / guard byte
    assert(std::memcmp(ram.data()+0x1001c,ram.data()+0x12000,18)==0);
    assert(std::memcmp(ram.data()+0x1009c,ram.data()+0x12000,18)==0);
    SET_GPR_U32(ctx,29,0x20000); SET_GPR_U32(ctx,6,26); ctx->pc=0x3a27e0;
    assert(call(sub_003A27E0_0x3a27e0,id,0x12000)==255); // Original translated Cross pressure decoder.
    SET_GPR_U32(ctx,6,14); ctx->pc=0x3a27e0;
    assert(call(sub_003A27E0_0x3a27e0,id,0x12000)==1); // Original translated digital decoder.
    keys.clear(); reaPollPadInput(); assert(call(rea_pad2::read,id,0x12000)==18);
    assert(ram[0x12000]==255 && ram[0x12001]==255 && ram[0x12004]==128);
    auto before=ram; assert(call(rea_pad2::read,id,0x1fffff8)==-1); assert(before==ram);
    assert(call(rea_pad2::read,id,0x60012000)==-1); // not a RAM segment
    assert(call(rea_pad2::close,id)==1); assert(call(rea_pad2::read,id,0x12000)==-1);
    assert(call(rea_pad2::create,0,0x10000)==id); // reuse a closed socket
    call(rea_pad2::init); assert(call(rea_pad2::state,id)==0);
    std::cout<<"PASS: Pad2 sockets, input, profile, pressure, DMA sides, close/reset and buffer bounds\n";
}

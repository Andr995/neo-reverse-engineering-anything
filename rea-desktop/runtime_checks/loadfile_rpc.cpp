#include "ps2x/iop/iop_types.h"
#include "rea_loadfile_fixture.h"
#include <cassert>
#include <iostream>
using namespace ps2x::iop;
struct Backend {
    unsigned calls=0;
    std::array<uint8_t,16> memory{};
    ModuleLoadResult loadIopModule(const std::string &path,const void *args,uint32_t size) {
        ++calls; assert(path=="cdrom0:\\TEST.IRX;1");
        assert(size==4 && std::memcmp(args,"abc",4)==0);
        return {true,17,2};
    }
    bool writeIopMemory(uint32_t a,const void *p,size_t n) {
        if(a>memory.size() || n>memory.size()-a) return false;
        std::memcpy(memory.data()+a,p,n); return true;
    }
    bool readIopMemory(uint32_t a,void *p,size_t n) {
        if(a>memory.size() || n>memory.size()-a) return false;
        std::memcpy(p,memory.data()+a,n); return true;
    }
};
int main() {
    Backend backend;
    std::vector<uint8_t> ram(0x2000000,0xa5);
    auto put=[&](uint32_t a,uint32_t v) { std::memcpy(ram.data()+a,&v,4); };
    auto get=[&](uint32_t a) { int32_t v; std::memcpy(&v,ram.data()+a,4); return v; };
    RpcRequest request{}; request.sid=0x80000006; request.function=0xff;
    request.send={0x10000,512}; request.receive={0x10000,8};
    auto result=reaLoadfileRpc(&backend,ram.data(),request);
    assert(result.handled && result.signalCompletion && result.resultAddress==0x10000);
    assert(get(0x10000)==0x30303133 && ram[0x10008]==0xa5);
    request.function=0;
    put(0x10000,4);
    constexpr char path[]="cdrom0:\\TEST.IRX;1";
    std::memcpy(ram.data()+0x10008,path,sizeof(path));
    std::memcpy(ram.data()+0x10104,"abc",4);
    reaLoadfileRpc(&backend,ram.data(),request);
    assert(backend.calls==1 && get(0x10000)==17 && get(0x10004)==2);
    put(0x10000,253); reaLoadfileRpc(&backend,ram.data(),request);
    assert(backend.calls==1 && get(0x10000)==-1);
    put(0x10000,0); std::memset(ram.data()+0x10008,'x',252);
    reaLoadfileRpc(&backend,ram.data(),request); assert(backend.calls==1);
    request.function=2; request.send.size=16;
    put(0x10000,3); put(0x10004,0); put(0x10008,0x123456ab);
    reaLoadfileRpc(&backend,ram.data(),request);
    assert(get(0x10000)==0 && backend.memory[3]==0xab && backend.memory[4]==0);
    request.function=3; put(0x10000,3); put(0x10004,0);
    reaLoadfileRpc(&backend,ram.data(),request); assert(get(0x10000)==0xab);
    put(0x10000,15); put(0x10004,2);
    reaLoadfileRpc(&backend,ram.data(),request); assert(get(0x10000)==-1);
    request.function=6; reaLoadfileRpc(&backend,ram.data(),request);
    assert(get(0x10000)==-1); // never fake success for unsupported buffer loads
    request.function=1; reaLoadfileRpc(&backend,ram.data(),request);
    assert(get(0x10000)==0 && get(0x10004)==0);
    request.receive={0x1fffffe,8}; auto before=ram;
    reaLoadfileRpc(&backend,ram.data(),request); assert(ram==before);
    request.receive={0x60010000,8};
    reaLoadfileRpc(&backend,ram.data(),request); assert(ram==before);
    request.sid=1; assert(!reaLoadfileRpc(&backend,ram.data(),request).handled);
    std::cout<<"LOADFILE protocol: load result/arguments, aliasing, memory access and invalid buffers PASS\n";
}

// Real CDVD service, synthetic large ISO. No commercial data required.
#define main upstream_import_main
#include "../../ps2recomp/ps2xIOP/tests/iop_import_tests.cpp"
#undef main
#include <stdexcept>
class ImageHost final : public NullHost {
public:
    std::string hostPath(HostPathKind k) const override { return k==HostPathKind::CdImage ? "fixture.iso" : ""; }
    uint64_t openHostFile(std::string_view) override { return 1; }
    bool readHostFile(uint64_t h, uint64_t off, void* dst, size_t size, size_t& read) override {
        ++reads; offset=off; read=shortRead ? size/2 : size;
        if(h!=1) return false;
        std::memset(dst,0x5a,read); return true;
    }
    unsigned reads=0; uint64_t offset=0; bool shortRead=false;
};
void check(bool value, const char* why) { if(!value) throw std::runtime_error(why); }
int main() {
    ImageHost host; IopMemory mem; IopKernel kernel(mem); IopCdvd cdvd(host,mem,kernel); IopCpuState cpu{};
    const auto read=[&](uint32_t dest, uint32_t n=4){
        cpu.gpr[4]=0x14d121; cpu.gpr[5]=n; cpu.gpr[6]=dest;
        check(cdvd.dispatchImport(6,cpu),"sceCdRead not handled"); return cpu.gpr[2];
    };
    check(!mem.ownsRamRange(0x15f600,8192),"Fixture buffer must start untouched");
    check(read(0x15f600)==1,"Valid untouched IOP RAM rejected as DMA destination");
    check(host.offset==uint64_t(0x14d121)*2048 && host.offset>0x80000000,
          "Large ISO offset truncated");
    check(mem.read32(0x15f600)==0x5a5a5a5a && mem.read32(0x1615fc)==0x5a5a5a5a,
          "Read did not transfer complete sector data");
    check(read(0xa0100000)==1,"Valid uncached RAM alias rejected");
    const auto calls=host.reads;
    check(!read(0x1ffffc) && !read(0x200000) && !read(0x1000,0xffffffff) &&
          !read(0x1f900000),"Out-of-RAM or oversized DMA accepted");
    check(host.reads==calls,"Invalid destination reached file IO");
    mem.write32(0x10000,0x12345678);host.shortRead=true;
    check(!read(0x10000) && mem.read32(0x10000)==0x12345678,"Short file read partially modified RAM");
    std::cout << "PASS: untouched/aliased IOP DMA buffer, 64-bit ISO offset, bounds and short-read isolation\n";
}

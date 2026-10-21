#include "raylib.h"
#include <array>
#include <algorithm>
#include <stdexcept>
#include <cstdio>
#include <cstdlib>
#include <cassert>
#include <iostream>
#include "rea_controls_fixture.h"
int main(int argc,char** argv) {
    assert(argc==2); const auto path=std::filesystem::path(argv[1]);
    using namespace rea_controls;
    Config c; assert(valid(c)); assert(load(path,c)); assert(c.keys[4]==KEY_X);
    c.mode=0; c.keys[4]=KEY_B; assert(save(path,c));
    Config read; assert(load(path,read)); assert(read.mode==0 && read.keys[4]==KEY_B);
    c.keys[4]=KEY_A; assert(!valid(c)); assert(!save(path,c)); // duplicate left stick key
    assert(load(path,read) && read.keys[4]==KEY_B); // invalid save preserves previous data
    {std::ofstream f(path); f<<"version=1\nmode=2\nkey.4=99999\n";}
    assert(!load(path,read)); assert(read.keys[4]==KEY_B);
    {std::ofstream f(path); f<<"version=2\n";} assert(!load(path,read));
    {std::ofstream f(path); f<<"version=1\nkey.-1=65\n";} assert(!load(path,read));
    {std::ofstream f(path); f<<"version=1\nkey.25=65\n";} assert(!load(path,read));
    {std::ofstream f(path); f<<"version=1\nmode=0oops\n";} assert(!load(path,read));
    {std::ofstream f(path); f<<"version=1\npad=4\n";} assert(!load(path,read));
    assert(save(path,Config{})); assert(load(path,read) && read.keys[4]==KEY_X);
    std::cout<<"PASS: controls preferences round trip, defaults, malformed input and duplicate mapping rejection\n";
}

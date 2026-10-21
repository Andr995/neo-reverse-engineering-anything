// Test the actual patched PSPadBackend with deterministic host input.
#include "runtime/ps2_pad.h"
#include "raylib.h"
#include <cassert>
#include <set>
#include <cstring>
#include <iostream>
extern void reaPollPadInput();
static std::set<int> keys, buttons;
static bool gamepad = false;
extern "C" bool IsWindowReady(void) { return true; }
extern "C" bool IsKeyDown(int key) { return keys.contains(key); }
extern "C" bool IsGamepadAvailable(int pad) { return gamepad && pad == 0; }
extern "C" bool IsGamepadButtonDown(int, int button) { return buttons.contains(button); }
extern "C" float GetGamepadAxisMovement(int, int axis) { return axis == GAMEPAD_AXIS_RIGHT_X ? 0.5f : 0.0f; }
int main() {
    PSPadBackend backend; uint8_t data[32]{};
    auto read = [&] { reaPollPadInput(); assert(backend.readState(0, 0, data, sizeof(data))); };
    auto mask = [&] { return uint16_t(data[2] | data[3] << 8); };
    read(); assert(mask() == 0xffff && data[6] == 128 && data[7] == 128);
    const struct { int key; uint16_t bit; } cases[] = {
        {KEY_UP, 0x10}, {KEY_RIGHT, 0x20}, {KEY_DOWN, 0x40}, {KEY_LEFT, 0x80},
        {KEY_X, 0x4000}, {KEY_SPACE, 0x4000}, {KEY_C, 0x2000}, {KEY_Z, 0x8000}, {KEY_V, 0x1000},
        {KEY_Q, 0x400}, {KEY_E, 0x800}, {KEY_ONE, 0x100}, {KEY_THREE, 0x200},
        {KEY_ENTER, 8}, {KEY_TAB, 1}, {KEY_RIGHT_SHIFT, 1}, {KEY_LEFT_CONTROL, 2}, {KEY_RIGHT_CONTROL, 4}
    };
    for (auto c : cases) { keys = {c.key}; read(); assert(mask() == uint16_t(0xffff ^ c.bit)); }
    keys = {KEY_A, KEY_W, KEY_L, KEY_K}; read();
    assert(mask() == 0xffff && data[6] == 0 && data[7] == 0 && data[4] == 255 && data[5] == 255);
    keys = {KEY_A, KEY_D, KEY_I, KEY_K}; read(); assert(data[6] == 128 && data[5] == 128);
    // The snapshot stays stable until the render thread polls again.
    keys = {KEY_X}; read(); keys.clear(); backend.readState(0, 0, data, 32); assert(mask() == 0xbfff);
    read(); assert(mask() == 0xffff);
    gamepad = true; buttons = {GAMEPAD_BUTTON_RIGHT_FACE_RIGHT}; keys = {KEY_X, KEY_A}; read();
    assert(mask() == 0x9fff && data[6] == 0 && data[4] == 191);
    assert(backend.readState(1, 0, data, 32) && mask() == 0xffff && data[6] == 128);
    assert(!backend.readState(0, 1, data, 32)); assert(!backend.readState(0, 0, nullptr, 32));
    std::memset(data, 0xa5, 32); assert(!backend.readState(0, 0, data, 31)); assert(data[0] == 0xa5);
    std::cout << "Keyboard: 18 mappings, both sticks, gamepad coexistence, snapshot and port validation passed\n";
}

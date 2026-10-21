"""Host keyboard/gamepad input sampled on the window thread; audited v5 profile."""
import ps2_input_ui

PAD = "ps2xRuntime/src/lib/ps2_pad.cpp"
STUB = "ps2xRuntime/src/lib/Kernel/Stubs/Pad.cpp"
SOURCE_HASHES = {
    PAD: "ad7767253d4e56abbfab3bb3869b38c6d10293914a0b1f6652685cc49383fd49",
    STUB: "5b940a4fa9001b0345a82cc21847ea0372f69f89f25bfa514cf6282092a37c44",
}
BACKEND = r'''#include "runtime/ps2_pad.h"
#include "ps2_host_backend.h"
#include <cstring>
#include <atomic>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>

namespace
{
    constexpr uint8_t kPadAnalogMarker = 0x73;
    constexpr uint8_t kPadStickCenter = 0x80;

    constexpr uint16_t PAD_LEFT = 0x0080u;
    constexpr uint16_t PAD_DOWN = 0x0040u;
    constexpr uint16_t PAD_RIGHT = 0x0020u;
    constexpr uint16_t PAD_UP = 0x0010u;
    constexpr uint16_t PAD_START = 0x0008u;
    constexpr uint16_t PAD_R3 = 0x0004u;
    constexpr uint16_t PAD_L3 = 0x0002u;
    constexpr uint16_t PAD_SELECT = 0x0001u;
    constexpr uint16_t PAD_SQUARE = 0x8000u;
    constexpr uint16_t PAD_CROSS = 0x4000u;
    constexpr uint16_t PAD_CIRCLE = 0x2000u;
    constexpr uint16_t PAD_TRIANGLE = 0x1000u;
    constexpr uint16_t PAD_R1 = 0x0800u;
    constexpr uint16_t PAD_L1 = 0x0400u;
    constexpr uint16_t PAD_R2 = 0x0200u;
    constexpr uint16_t PAD_L2 = 0x0100u;
}

namespace {
    // One atomic packet: readers cannot observe buttons from one frame and axes
    // from another. The guest thread never accesses GLFW/raylib input arrays.
    std::atomic<uint64_t> reaPadPacket{0x80808080FFFFull};
    uint8_t axisByte(float value) {
        if (!std::isfinite(value)) value = 0.0f;
        return static_cast<uint8_t>(std::lround((std::clamp(value, -1.0f, 1.0f) + 1.0f) * 127.5f));
    }
}
void reaPollPadInput() {
    if (!IsWindowReady()) return;
    uint8_t data[32];
    std::memset(data, 0, 32);
    data[0] = 0x01;
    data[1] = kPadAnalogMarker;
    data[2] = 0xFF;
    data[3] = 0xFF;
    data[4] = data[5] = data[6] = data[7] = kPadStickCenter;

    uint16_t btns = 0xFFFFu;
    int kGamepad = 0;
    while (kGamepad < 4 && !IsGamepadAvailable(kGamepad)) ++kGamepad;
    const bool useGamepad = kGamepad < 4;
    auto clearBit = [&btns](uint16_t mask)
    { btns &= ~mask; };

    if (useGamepad)
    {
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_LEFT_FACE_UP))
            clearBit(PAD_UP);
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_LEFT_FACE_DOWN))
            clearBit(PAD_DOWN);
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_LEFT_FACE_LEFT))
            clearBit(PAD_LEFT);
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_LEFT_FACE_RIGHT))
            clearBit(PAD_RIGHT);
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_RIGHT_FACE_DOWN))
            clearBit(PAD_CROSS);
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_RIGHT_FACE_RIGHT))
            clearBit(PAD_CIRCLE);
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_RIGHT_FACE_LEFT))
            clearBit(PAD_SQUARE);
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_RIGHT_FACE_UP))
            clearBit(PAD_TRIANGLE);
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_LEFT_TRIGGER_1))
            clearBit(PAD_L1);
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_RIGHT_TRIGGER_1))
            clearBit(PAD_R1);
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_LEFT_TRIGGER_2))
            clearBit(PAD_L2);
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_RIGHT_TRIGGER_2))
            clearBit(PAD_R2);
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_MIDDLE_RIGHT))
            clearBit(PAD_START);
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_MIDDLE_LEFT))
            clearBit(PAD_SELECT);
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_LEFT_THUMB))
            clearBit(PAD_L3);
        if (IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_RIGHT_THUMB))
            clearBit(PAD_R3);

        float lx = GetGamepadAxisMovement(kGamepad, GAMEPAD_AXIS_LEFT_X);
        float ly = GetGamepadAxisMovement(kGamepad, GAMEPAD_AXIS_LEFT_Y);
        float rx = GetGamepadAxisMovement(kGamepad, GAMEPAD_AXIS_RIGHT_X);
        float ry = GetGamepadAxisMovement(kGamepad, GAMEPAD_AXIS_RIGHT_Y);
        data[6] = axisByte(lx);
        data[7] = axisByte(ly);
        data[4] = axisByte(rx);
        data[5] = axisByte(ry);
    }
    // Same controls with or without a connected gamepad. WASD is analog,
    // arrows are the D-pad. All raylib input access stays on the window thread.
    const struct { int key; uint16_t mask; } keys[] = {
        {KEY_UP, PAD_UP}, {KEY_DOWN, PAD_DOWN}, {KEY_LEFT, PAD_LEFT}, {KEY_RIGHT, PAD_RIGHT},
        {KEY_X, PAD_CROSS}, {KEY_SPACE, PAD_CROSS}, {KEY_C, PAD_CIRCLE},
        {KEY_Z, PAD_SQUARE}, {KEY_V, PAD_TRIANGLE},
        {KEY_Q, PAD_L1}, {KEY_E, PAD_R1}, {KEY_ONE, PAD_L2}, {KEY_THREE, PAD_R2},
        {KEY_ENTER, PAD_START}, {KEY_TAB, PAD_SELECT}, {KEY_RIGHT_SHIFT, PAD_SELECT},
        {KEY_LEFT_CONTROL, PAD_L3}, {KEY_RIGHT_CONTROL, PAD_R3}
    };
    for (const auto &key : keys)
        if (IsKeyDown(key.key)) clearBit(key.mask);
    const auto keyboardAxis = [&](int negative, int positive, unsigned index) {
        const bool n = IsKeyDown(negative), p = IsKeyDown(positive);
        if (n || p) data[index] = n == p ? 128u : n ? 0u : 255u;
    };
    keyboardAxis(KEY_A, KEY_D, 6); keyboardAxis(KEY_W, KEY_S, 7);
    keyboardAxis(KEY_J, KEY_L, 4); keyboardAxis(KEY_I, KEY_K, 5);
    uint64_t packet = btns;
    for (unsigned i = 0; i < 4; ++i) packet |= uint64_t(data[4+i]) << (16u + 8u*i);
    reaPadPacket.store(packet, std::memory_order_relaxed);
    static uint64_t previous = 0x80808080FFFFull;
    static unsigned logs = 0;
    if (packet != previous && std::getenv("REA_DIAGNOSTICS") && logs++ < 64u)
        std::fprintf(stderr, "[REA pad] buttons=%04x left=%u,%u right=%u,%u\n", btns, data[6], data[7], data[4], data[5]);
    previous = packet;
}
bool PSPadBackend::readState(int port, int slot, uint8_t *data, size_t size) {
    if (!data || size < 32 || port < 0 || port > 1 || slot != 0) return false;
    // Keyboard/gamepad 0 drives player one only; player two stays neutral.
    const uint64_t packet = port == 0 ? reaPadPacket.load(std::memory_order_relaxed) : 0x80808080FFFFull;
    std::memset(data, 0, 32);
    data[0] = 0x01; data[1] = kPadAnalogMarker;
    for (unsigned i = 0; i < 6; ++i) data[2+i] = static_cast<uint8_t>(packet >> (8u*i));
    return true;
}
'''
FALLBACK_OLD = r'''        uint8_t axisToByte(float axis)
        {
            axis = std::clamp(axis, -1.0f, 1.0f);
            const float mapped = (axis + 1.0f) * 127.5f;
            return static_cast<uint8_t>(std::lround(mapped));
        }

        void setButton(PadInputState &state, uint16_t mask, bool pressed)
        {
            if (pressed)
            {
                state.buttons = static_cast<uint16_t>(state.buttons & ~mask);
            }
        }

        int findFirstGamepad()
        {
            for (int i = 0; i < 4; ++i)
            {
                if (IsGamepadAvailable(i))
                {
                    return i;
                }
            }
            return -1;
        }

        void applyGamepadState(PadInputState &state)
        {
            if (!IsWindowReady())
            {
                return;
            }

            const int gamepad = findFirstGamepad();
            if (gamepad < 0)
            {
                return;
            }

            // Raylib mapping (PS2 -> raylib buttons/axes):
            // D-Pad -> LEFT_FACE_*, Cross/Circle/Square/Triangle -> RIGHT_FACE_*
            // L1/R1 -> TRIGGER_1, L2/R2 -> TRIGGER_2, L3/R3 -> THUMB
            // Select/Start -> MIDDLE_LEFT/MIDDLE_RIGHT
            state.lx = axisToByte(GetGamepadAxisMovement(gamepad, GAMEPAD_AXIS_LEFT_X));
            state.ly = axisToByte(GetGamepadAxisMovement(gamepad, GAMEPAD_AXIS_LEFT_Y));
            state.rx = axisToByte(GetGamepadAxisMovement(gamepad, GAMEPAD_AXIS_RIGHT_X));
            state.ry = axisToByte(GetGamepadAxisMovement(gamepad, GAMEPAD_AXIS_RIGHT_Y));

            setButton(state, kPadBtnUp, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_LEFT_FACE_UP));
            setButton(state, kPadBtnDown, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_LEFT_FACE_DOWN));
            setButton(state, kPadBtnLeft, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_LEFT_FACE_LEFT));
            setButton(state, kPadBtnRight, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_LEFT_FACE_RIGHT));

            setButton(state, kPadBtnCross, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_RIGHT_FACE_DOWN));
            setButton(state, kPadBtnCircle, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_RIGHT_FACE_RIGHT));
            setButton(state, kPadBtnSquare, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_RIGHT_FACE_LEFT));
            setButton(state, kPadBtnTriangle, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_RIGHT_FACE_UP));

            setButton(state, kPadBtnL1, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_LEFT_TRIGGER_1));
            setButton(state, kPadBtnR1, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_RIGHT_TRIGGER_1));
            setButton(state, kPadBtnL2, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_LEFT_TRIGGER_2));
            setButton(state, kPadBtnR2, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_RIGHT_TRIGGER_2));

            setButton(state, kPadBtnL3, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_LEFT_THUMB));
            setButton(state, kPadBtnR3, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_RIGHT_THUMB));

            setButton(state, kPadBtnSelect, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_MIDDLE_LEFT));
            setButton(state, kPadBtnStart, IsGamepadButtonDown(gamepad, GAMEPAD_BUTTON_MIDDLE_RIGHT));
        }

        void applyKeyboardState(PadInputState &state, bool allowAnalog)
        {
            if (!IsWindowReady())
            {
                return;
            }

            // Keyboard mapping (PS2 -> keys):
            // D-Pad: arrows, Square/Cross/Circle/Triangle: Z/X/C/V
            // L1/R1: Q/E, L2/R2: 1/3, Start/Select: Enter/RightShift
            // L3/R3: LeftCtrl/RightCtrl, Analog left: WASD
            setButton(state, kPadBtnUp, IsKeyDown(KEY_UP));
            setButton(state, kPadBtnDown, IsKeyDown(KEY_DOWN));
            setButton(state, kPadBtnLeft, IsKeyDown(KEY_LEFT));
            setButton(state, kPadBtnRight, IsKeyDown(KEY_RIGHT));

            setButton(state, kPadBtnSquare, IsKeyDown(KEY_Z));
            setButton(state, kPadBtnCross, IsKeyDown(KEY_X));
            setButton(state, kPadBtnCircle, IsKeyDown(KEY_C));
            setButton(state, kPadBtnTriangle, IsKeyDown(KEY_V));

            setButton(state, kPadBtnL1, IsKeyDown(KEY_Q));
            setButton(state, kPadBtnR1, IsKeyDown(KEY_E));
            setButton(state, kPadBtnL2, IsKeyDown(KEY_ONE));
            setButton(state, kPadBtnR2, IsKeyDown(KEY_THREE));

            setButton(state, kPadBtnStart, IsKeyDown(KEY_ENTER));
            setButton(state, kPadBtnSelect, IsKeyDown(KEY_RIGHT_SHIFT));
            setButton(state, kPadBtnL3, IsKeyDown(KEY_LEFT_CONTROL));
            setButton(state, kPadBtnR3, IsKeyDown(KEY_RIGHT_CONTROL));

            if (!allowAnalog)
            {
                return;
            }

            float ax = 0.0f;
            float ay = 0.0f;
            if (IsKeyDown(KEY_D))
                ax += 1.0f;
            if (IsKeyDown(KEY_A))
                ax -= 1.0f;
            if (IsKeyDown(KEY_S))
                ay += 1.0f;
            if (IsKeyDown(KEY_W))
                ay -= 1.0f;

            if (ax != 0.0f || ay != 0.0f)
            {
                state.lx = axisToByte(ax);
                state.ly = axisToByte(ay);
            }
        }

'''
FALLBACK_NEW = r'''        void applyCachedHostState(PadInputState &state)
        {
            PSPadBackend backend;
            uint8_t data[32]{};
            if (backend.readState(0, 0, data, sizeof(data))) {
                state.buttons = static_cast<uint16_t>(data[2] | (data[3] << 8));
                state.rx = data[4]; state.ry = data[5]; state.lx = data[6]; state.ly = data[7];
            }
        }

'''
CAPTURE = r'''        // REA diagnostics: read this OpenGL texture on its owning thread.
        // No desktop/window screenshot: other windows and lock screens are excluded.
        if (const char *directory = std::getenv("REA_FRAME_DIR")) {
            const auto now = std::chrono::steady_clock::now();
            if (reaFrameCount < 120u && now >= reaNextFrame) {
                const auto path = std::filesystem::path(directory) / ("frame-" + std::to_string(reaFrameCount++) + ".png");
                reaNextFrame = now + std::chrono::seconds(5);
                std::error_code ec;
                if (std::filesystem::is_directory(path.parent_path(), ec) && !std::filesystem::exists(path, ec)) {
                    Image shot = LoadImageFromTexture(frameTex);
                    if (shot.data) {
                        ExportImage(shot, path.string().c_str());
                        UnloadImage(shot);
                    }
                }
            }
        }
'''


def configured_backend():
    source = BACKEND.replace("#include <cstring>", "#include <cstring>\n#include <array>\n#include <stdexcept>")
    point = source.index("namespace")
    source = source[:point] + ps2_input_ui.CPP + source[point:]
    first = source.index("    int kGamepad = 0;")
    last = source.index("    auto clearBit", first)
    source = source[:first] + "    const int kGamepad = rea_controls::gamepad();\n    const bool useGamepad = kGamepad >= 0;\n" + source[last:]
    buttons = ("LEFT_FACE_UP", "LEFT_FACE_DOWN", "LEFT_FACE_LEFT", "LEFT_FACE_RIGHT", "RIGHT_FACE_DOWN", "RIGHT_FACE_RIGHT", "RIGHT_FACE_LEFT", "RIGHT_FACE_UP", "LEFT_TRIGGER_1", "RIGHT_TRIGGER_1", "LEFT_TRIGGER_2", "RIGHT_TRIGGER_2", "MIDDLE_RIGHT", "MIDDLE_LEFT", "LEFT_THUMB", "RIGHT_THUMB")
    for index, name in enumerate(buttons):
        source = source.replace("IsGamepadButtonDown(kGamepad, GAMEPAD_BUTTON_" + name + ")", f"rea_controls::gamepadDown({index})")
    first = source.index("    const struct { int key; uint16_t mask; }")
    last = source.index("    uint64_t packet =", first)
    source = source[:first] + r'''    const uint16_t masks[] = { PAD_UP,PAD_DOWN,PAD_LEFT,PAD_RIGHT,PAD_CROSS,PAD_CIRCLE,PAD_SQUARE,PAD_TRIANGLE,
        PAD_L1,PAD_R1,PAD_L2,PAD_R2,PAD_START,PAD_SELECT,PAD_L3,PAD_R3 };
    for (unsigned i=0;i<16;++i) if (rea_controls::keyDown(i)) clearBit(masks[i]);
    const auto keyboardAxis = [&](unsigned negative,unsigned positive,unsigned index) {
        const bool n=rea_controls::keyDown(negative), p=rea_controls::keyDown(positive);
        if (n || p) data[index]=n==p ? 128u : n ? 0u : 255u;
    };
    keyboardAxis(18,19,6); keyboardAxis(16,17,7);
    keyboardAxis(22,23,4); keyboardAxis(20,21,5);
''' + source[last:]
    return source


def adapt(sources, runtime):
    sources[PAD] = configured_backend()
    sources[runtime] = sources[runtime].replace("void PS2Runtime::run()", PAD2 + "\nvoid PS2Runtime::run()", 1)
    sources[runtime] = sources[runtime].replace("    m_stopRequested.store(false, std::memory_order_relaxed);\n    ps2_stubs::resetSifState();", "    if (!reaConfigureControls()) return;\n    rea_pad2::install(*this);\n    m_stopRequested.store(false, std::memory_order_relaxed);\n    ps2_stubs::resetSifState();", 1)
    assert sources[STUB].count(FALLBACK_OLD) == 1
    sources[STUB] = sources[STUB].replace(FALLBACK_OLD, FALLBACK_NEW).replace(
        "                    applyGamepadState(state);\n                    applyKeyboardState(state, portState.analogMode);",
        "                    applyCachedHostState(state);")
    sources[runtime] = "#include <chrono>\nextern void reaPollPadInput();\nextern bool reaConfigureControls();\n" + sources[runtime]
    sources[runtime] = sources[runtime].replace("    uint64_t tick = 0;", "    unsigned reaFrameCount = 0;\n    auto reaNextFrame = std::chrono::steady_clock::now();\n    uint64_t tick = 0;", 1)
    sources[runtime] = sources[runtime].replace("        uint32_t presentWidth = FB_WIDTH;", "        reaPollPadInput();\n        uint32_t presentWidth = FB_WIDTH;", 1)
    sources[runtime] = sources[runtime].replace("        BeginDrawing();", CAPTURE + "\n        BeginDrawing();", 1)

PAD2 = r'''// SLES-53506 libpad2 adapter. Layout recovered from this BOOT2:
// socket table 0x1f49980, stride 0x334; DMA sides 0x80; payload +0x1c.
// Public socket parameters and active-low payload corroborated by OPL padhook.
namespace rea_pad2 {
struct Socket { bool open = false; uint32_t port = 0, dma = 0, frame = 0; };
std::array<Socket, 16> sockets{};
constexpr uint32_t table = 0x01f49980u;
uint8_t *range(uint8_t *ram, uint32_t address, uint32_t size) {
    const uint32_t segment = address & 0xe0000000u;
    if (segment != 0 && segment != 0x80000000u && segment != 0xa0000000u) return nullptr;
    const uint32_t physical = address & 0x1fffffffu;
    if (physical < 0x10000u || size > 0x2000000u - std::min(physical, 0x2000000u)) return nullptr;
    return ram + physical;
}
void word(uint8_t *dest, uint32_t value) { std::memcpy(dest, &value, 4); }
uint32_t word(const uint8_t *src) { uint32_t value; std::memcpy(&value, src, 4); return value; }
void result(R5900Context *ctx, int32_t value) {
    SET_GPR_S32(ctx, 2, value); ctx->pc = GPR_U32(ctx, 31);
}
Socket *lookup(uint32_t id) { return id < sockets.size() && sockets[id].open ? &sockets[id] : nullptr; }
constexpr std::array<uint8_t, 5> profile{0xff, 0xff, 0xff, 0xff, 0x00};
void sample(Socket &socket, uint8_t *raw) {
    PSPadBackend backend; uint8_t data[32]{};
    backend.readState(socket.port, 0, data, sizeof(data));
    std::memcpy(raw, data+2, 6);
    constexpr uint16_t pressure[] = {0x20,0x80,0x10,0x40,0x1000,0x2000,0x4000,0x8000,0x400,0x800,0x100,0x200};
    const uint16_t buttons = uint16_t(data[2] | data[3] << 8);
    for (unsigned i = 0; i < 12; ++i) raw[6+i] = buttons & pressure[i] ? 0 : 255;
}
void refresh(uint8_t *ram, Socket &socket) {
    auto *dma = range(ram, socket.dma, 256); if (!dma) return;
    uint8_t raw[18]; sample(socket, raw); ++socket.frame;
    for (unsigned side = 0; side < 2; ++side) {
        auto *p = dma + side*128;
        p[0] = socket.port == 0 ? 1 : 0; p[1] = 0; p[2] = 18; p[3] = 5;
        word(p+4, socket.port == 0 ? 1 : 0); word(p+124, socket.frame);
        std::memcpy(p+28, raw, sizeof(raw)); std::memcpy(p+46, profile.data(), profile.size());
    }
}
void init(uint8_t *ram, R5900Context *ctx, PS2Runtime *) {
    sockets = {}; std::memset(ram+table, 0, 16*0x334);
    word(ram+0x47a850, 1); result(ctx, 1);
}
void create(uint8_t *ram, R5900Context *ctx, PS2Runtime *) {
    const uint32_t params = GPR_U32(ctx,4), dma = GPR_U32(ctx,5);
    uint32_t port = 0, slot = 0;
    if (params) {
        auto *p = range(ram, params, 32); if (!p) { result(ctx,-1); return; }
        port = word(p+4); slot = word(p+8);
    }
    if (port > 1 || slot != 0 || (dma & 63u) || !range(ram,dma,256)) { result(ctx,-1); return; }
    unsigned id = 0; while (id < sockets.size() && sockets[id].open) ++id;
    if (id == sockets.size()) { result(ctx,-1); return; }
    sockets[id] = {true,port,dma,0};
    auto *entry = ram + table + id*0x334; std::memset(entry,0,0x334);
    word(entry,1); word(entry+4,1); word(entry+12,port); word(entry+16,dma);
    for (unsigned bit=0;bit<32;++bit) {
        auto *desc = entry+20+bit*16;
        word(desc,1); word(desc+4,bit<16 ? 1 : 8);
        word(desc+8,bit<16 ? bit/8 : 2+bit-16); word(desc+12,bit<16 ? bit%8 : 0);
    }
    std::memset(range(ram,dma,256),0,256); refresh(ram,sockets[id]);
    static unsigned logs = 0;
    if (std::getenv("REA_DIAGNOSTICS") && logs++ < 16)
        std::fprintf(stderr,"[REA pad2] socket=%u port=%u dma=%x\n",id,port,dma);
    result(ctx,static_cast<int32_t>(id));
}
void close(uint8_t *ram, R5900Context *ctx, PS2Runtime *) {
    const uint32_t id=GPR_U32(ctx,4); auto *s=lookup(id);
    if (!s) { result(ctx,-1); return; }
    *s={}; std::memset(ram+table+id*0x334,0,0x334); result(ctx,1);
}
void state(uint8_t *ram, R5900Context *ctx, PS2Runtime *) {
    auto *s=lookup(GPR_U32(ctx,4)); if (s) refresh(ram,*s);
    result(ctx,s && s->port==0 ? 1 : 0);
}
void read(uint8_t *ram, R5900Context *ctx, PS2Runtime *) {
    auto *s=lookup(GPR_U32(ctx,4)); auto *dest=range(ram,GPR_U32(ctx,5),18);
    if (!s || s->port!=0 || !dest) { result(ctx,-1); return; }
    sample(*s,dest); refresh(ram,*s);
    static unsigned count=0;
    static uint16_t previous=0;
    const uint16_t buttons=uint16_t(dest[0]) | uint16_t(dest[1])<<8;
    if (std::getenv("REA_DIAGNOSTICS") && buttons!=previous && count++ < 64)
        std::fprintf(stderr,"[REA pad2] read buttons=%02x%02x\n",dest[1],dest[0]);
    previous=buttons;
    result(ctx,18);
}
void buttonProfile(uint8_t *ram, R5900Context *ctx, PS2Runtime *) {
    auto *s=lookup(GPR_U32(ctx,4)); auto *dest=range(ram,GPR_U32(ctx,5),5);
    if (!s || s->port!=0 || !dest) { result(ctx,-1); return; }
    std::memcpy(dest,profile.data(),profile.size()); result(ctx,5);
}
PS2Runtime::RecompiledFunction originalButton = nullptr;
std::array<PS2Runtime::RecompiledFunction,4> originalQueries{};
template<unsigned Index>
void traceQuery(uint8_t *ram, R5900Context *ctx, PS2Runtime *rt) {
    const uint32_t object=GPR_U32(ctx,4), index=GPR_U32(ctx,5), caller=GPR_U32(ctx,31);
    originalQueries[Index](ram,ctx,rt);
    uint8_t data[32]{}; PSPadBackend backend; backend.readState(0,0,data,32);
    static unsigned count=0;
    if(!(data[3]&0x40) && (Index != 3 || index == 2) && count++<64)
        if(auto *p=range(ram,object,0x100))
            std::fprintf(stderr,"[REA pad-query] query=%u caller=%x object=%x index=%u old=%u current=%u result=%x float=%g\n",
                         Index,caller,object,index,index<28?p[14+index]:255,index<28?p[42+index]:255,GPR_U32(ctx,2),ctx->f[0]);
}
void traceButton(uint8_t *ram, R5900Context *ctx, PS2Runtime *rt) {
    const uint32_t object=GPR_U32(ctx,4), index=GPR_U32(ctx,5), button=GPR_U32(ctx,6);
    originalButton(ram,ctx,rt);
    static std::array<uint32_t,16> previous{};
    static unsigned count=0;
    if(index<previous.size())
        if(auto *p=range(ram,object+76+index*4,4)) {
            const uint32_t value=word(p);
            if(value!=previous[index] && count++<128)
                std::fprintf(stderr,"[REA pad-value] object=%x index=%u button=%u value=%08x\n",object,index,button,value);
            previous[index]=value;
        }
}
void install(PS2Runtime &rt) {
    sockets = {};
    const std::pair<uint32_t,PS2Runtime::RecompiledFunction> functions[] = {
        {0x3a2358,init}, {0x3a2398,create}, {0x3a24a0,close},
        {0x3a24f8,read}, {0x3a25d0,buttonProfile}, {0x3a26a0,state}
    };
    for (const auto &[address, function] : functions)
        if (!rt.hasFunction(address)) throw std::runtime_error("REA Pad2: missing verified library entry point");
    for (const auto &[address, function] : functions) rt.replaceFunction(address,function);
    if(std::getenv("REA_PAD_TRACE")) {
        originalButton=rt.lookupFunction(0x301be0);
        if(originalButton) rt.replaceFunction(0x301be0,traceButton);
        const std::pair<uint32_t,PS2Runtime::RecompiledFunction> queries[] = {
            {0x3017a8,traceQuery<0>},{0x3017d0,traceQuery<1>},{0x301810,traceQuery<2>},
            {0x111140,traceQuery<3>}
        };
        for(unsigned i=0;i<4;++i) {
            originalQueries[i]=rt.lookupFunction(queries[i].first);
            if(originalQueries[i]) rt.replaceFunction(queries[i].first,queries[i].second);
        }
    }
}
}
'''

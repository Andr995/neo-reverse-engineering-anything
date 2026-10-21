"""Native raylib controls dialog and validated local preferences for the v5 adapter."""
CPP = r'''
#include <filesystem>
#include <fstream>
#include <charconv>
#include <set>
#include <string>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif
namespace rea_controls {
constexpr unsigned count = 24;
constexpr int defaultKeys[count] = {
    KEY_UP,KEY_DOWN,KEY_LEFT,KEY_RIGHT,KEY_X,KEY_C,KEY_Z,KEY_V,
    KEY_Q,KEY_E,KEY_ONE,KEY_THREE,KEY_ENTER,KEY_TAB,KEY_LEFT_CONTROL,KEY_RIGHT_CONTROL,
    KEY_W,KEY_S,KEY_A,KEY_D,KEY_I,KEY_K,KEY_J,KEY_L
};
constexpr int defaultButtons[16] = {
    GAMEPAD_BUTTON_LEFT_FACE_UP,GAMEPAD_BUTTON_LEFT_FACE_DOWN,
    GAMEPAD_BUTTON_LEFT_FACE_LEFT,GAMEPAD_BUTTON_LEFT_FACE_RIGHT,
    GAMEPAD_BUTTON_RIGHT_FACE_DOWN,GAMEPAD_BUTTON_RIGHT_FACE_RIGHT,
    GAMEPAD_BUTTON_RIGHT_FACE_LEFT,GAMEPAD_BUTTON_RIGHT_FACE_UP,
    GAMEPAD_BUTTON_LEFT_TRIGGER_1,GAMEPAD_BUTTON_RIGHT_TRIGGER_1,
    GAMEPAD_BUTTON_LEFT_TRIGGER_2,GAMEPAD_BUTTON_RIGHT_TRIGGER_2,
    GAMEPAD_BUTTON_MIDDLE_RIGHT,GAMEPAD_BUTTON_MIDDLE_LEFT,
    GAMEPAD_BUTTON_LEFT_THUMB,GAMEPAD_BUTTON_RIGHT_THUMB
};
constexpr const char *labels[count] = {
    "Su","Giu","Sinistra","Destra","Croce / conferma","Cerchio","Quadrato","Triangolo",
    "L1","R1","L2","R2","Start","Select","L3","R3",
    "Stick SX: su","Stick SX: giu","Stick SX: sinistra","Stick SX: destra",
    "Stick DX: su","Stick DX: giu","Stick DX: sinistra","Stick DX: destra"
};
struct Config {
    int mode=2, pad=0; // 0 keyboard, 1 gamepad, 2 both
    std::array<int,count> keys{};
    std::array<int,16> buttons{};
    Config() { std::copy_n(defaultKeys,count,keys.begin()); std::copy_n(defaultButtons,16,buttons.begin()); }
};
Config config;
bool validKey(int k) {
    return (k>=32 && k<=96) || (k>=257 && k<=269) ||
        (k>=280 && k<=284) || (k>=290 && k<=301) ||
        (k>=320 && k<=336) || (k>=340 && k<=347);
}
bool valid(const Config &c) {
    if(c.mode<0 || c.mode>2 || c.pad<0 || c.pad>3) return false;
    std::set<int> keys,buttons;
    for(int k:c.keys) if(!validKey(k) || !keys.insert(k).second) return false;
    for(int b:c.buttons) if(b<1 || b>17 || !buttons.insert(b).second) return false;
    return true;
}
std::filesystem::path filePath() {
#ifdef _WIN32
    std::wstring path(32768,L'\0');
    const auto size=GetModuleFileNameW(nullptr,path.data(),static_cast<DWORD>(path.size()));
    if(!size || size>=path.size()) throw std::runtime_error("Cannot find executable directory");
    path.resize(size); return std::filesystem::path(path).parent_path()/"controlli.ini";
#else
    return std::filesystem::read_symlink("/proc/self/exe").parent_path()/"controlli.ini";
#endif
}
bool integer(const std::string &text,int &value) {
    const auto result=std::from_chars(text.data(),text.data()+text.size(),value);
    return result.ec==std::errc() && result.ptr==text.data()+text.size();
}
bool load(const std::filesystem::path &path,Config &out) {
    std::error_code ec;
    if(!std::filesystem::exists(path,ec)) { out=Config{}; return !ec; }
    if(std::filesystem::file_size(path,ec)>32768 || ec) return false;
    std::ifstream file(path); if(!file) return false;
    Config candidate; std::string line; bool version=false;
    while(std::getline(file,line)) {
        if(!line.empty() && line.back()=='\r') line.pop_back();
        if(line.empty() || line[0]=='#') continue;
        auto split=line.find('='); if(split==std::string::npos) return false;
        const auto name=line.substr(0,split); int value;
        if(!integer(line.substr(split+1),value)) return false;
        if(name=="version") { if(value!=1) return false; version=true; }
        else if(name=="mode") candidate.mode=value;
        else if(name=="pad") candidate.pad=value;
        else {
            const bool key=name.starts_with("key."); const bool button=name.starts_with("button.");
            int index;
            if((!key && !button) || !integer(name.substr(key?4:7),index) || index<0 || index>=int(key?count:16)) return false;
            if(key) candidate.keys[index]=value; else candidate.buttons[index]=value;
        }
    }
    if(file.bad() || !version || !valid(candidate)) return false;
    out=candidate; return true;
}
bool save(const std::filesystem::path &path,const Config &c) {
    if(!valid(c)) return false;
    auto staging=path; staging += ".tmp";
    {
        std::ofstream file(staging,std::ios::trunc); if(!file) return false;
        file<<"version=1\nmode="<<c.mode<<"\npad="<<c.pad<<'\n';
        for(unsigned i=0;i<count;++i) file<<"key."<<i<<'='<<c.keys[i]<<'\n';
        for(unsigned i=0;i<16;++i) file<<"button."<<i<<'='<<c.buttons[i]<<'\n';
        file.flush(); if(!file) return false;
    }
#ifdef _WIN32
    return MoveFileExW(staging.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)!=0;
#else
    std::error_code ec; std::filesystem::rename(staging,path,ec); return !ec;
#endif
}
std::string keyName(int k) {
    if(k>=32 && k<=96) return k==KEY_SPACE ? "Spazio" : std::string(1,char(k));
    switch(k) {
    case KEY_UP:return "Su";case KEY_DOWN:return "Giu";case KEY_LEFT:return "Sinistra";case KEY_RIGHT:return "Destra";
    case KEY_ENTER:return "Invio";case KEY_TAB:return "Tab";case KEY_BACKSPACE:return "Backspace";
    case KEY_LEFT_CONTROL:return "Ctrl SX";case KEY_RIGHT_CONTROL:return "Ctrl DX";
    case KEY_LEFT_SHIFT:return "Shift SX";case KEY_RIGHT_SHIFT:return "Shift DX";
    case KEY_LEFT_ALT:return "Alt SX";case KEY_RIGHT_ALT:return "Alt DX";
    default:return "Tasto "+std::to_string(k);
    }
}
std::string buttonName(int b) { return "Pad "+std::to_string(b); }
bool keyDown(unsigned index) {
    if(config.mode==1 || index>=count) return false;
    if(IsKeyDown(config.keys[index])) return true;
    // Familiar alternate bindings apply only while their primary is unchanged.
    if(index==4 && config.keys[4]==KEY_X && std::find(config.keys.begin(),config.keys.end(),KEY_SPACE)==config.keys.end()) return IsKeyDown(KEY_SPACE);
    if(index==13 && config.keys[13]==KEY_TAB && std::find(config.keys.begin(),config.keys.end(),KEY_RIGHT_SHIFT)==config.keys.end()) return IsKeyDown(KEY_RIGHT_SHIFT);
    return false;
}
int gamepad() { return config.mode!=0 && IsGamepadAvailable(config.pad) ? config.pad : -1; }
bool gamepadDown(unsigned index) {
    const int pad=gamepad(); return pad>=0 && index<16 && IsGamepadButtonDown(pad,config.buttons[index]);
}
bool button(Rectangle rect,const std::string &text,bool active=false,bool enabled=true) {
    const bool hover=CheckCollisionPointRec(GetMousePosition(),rect);
    DrawRectangleRec(rect, !enabled ? Color{36,42,51,255} : active ? Color{37,119,109,255} : hover ? Color{62,79,99,255} : Color{41,55,73,255});
    DrawRectangleLinesEx(rect,1,active?Color{94,217,190,255}:Color{69,87,109,255});
    DrawText(text.c_str(),int(rect.x)+8,int(rect.y)+9,16,enabled?RAYWHITE:GRAY);
    return enabled && hover && IsMouseButtonPressed(MOUSE_BUTTON_LEFT);
}
}
bool reaConfigureControls() {
    using namespace rea_controls;
    std::filesystem::path path;
    std::string status="Clicca un tasto o un pulsante Pad per cambiarlo. Esc annulla la modifica.";
    try {
        path=filePath();
        if(!load(path,config)) { config=Config{}; status="Configurazione non valida: caricati i comandi predefiniti."; }
    } catch(const std::exception&) { status="Cartella configurazione non disponibile."; }
    if(const char *skip=std::getenv("REA_SKIP_CONTROLS"); skip && std::string(skip)=="1") return true;
    const int oldWidth=GetScreenWidth(),oldHeight=GetScreenHeight();
    SetWindowSize(880,650); SetExitKey(KEY_NULL);
    int capture=-1; bool capturePad=false,accept=false,saveFailed=false;
    unsigned frames=0;
    while(!WindowShouldClose()) {
        const bool wasCapturing=capture>=0;
        if(capture>=0) {
            if(IsKeyPressed(KEY_ESCAPE)) capture=-1;
            else {
                int value=0;
                if(capturePad) { for(int b=1;b<=17;++b) if(IsGamepadButtonPressed(config.pad,b)) { value=b; break; } }
                else value=GetKeyPressed();
                if(value && (capturePad || validKey(value))) {
                    bool duplicate=false;
                    for(unsigned i=0;i<(capturePad?16:count);++i)
                        if(int(i)!=capture && (capturePad?config.buttons[i]:config.keys[i])==value) duplicate=true;
                    if(duplicate) status="Comando gia assegnato: scegli un altro tasto oppure ripristina i predefiniti.";
                    else {
                        if(capturePad) config.buttons[capture]=value; else config.keys[capture]=value;
                        status="Comando aggiornato. Le preferenze verranno salvate con Avvia."; capture=-1;
                    }
                }
            }
        }
        const bool ready=config.mode!=1 || IsGamepadAvailable(config.pad);
        BeginDrawing(); ClearBackground(Color{16,23,33,255});
        DrawText("Scegli i comandi",24,18,27,RAYWHITE);
        DrawText("Giocatore 1",705,23,19,Color{94,217,190,255});
        const char *modes[]={"Tastiera","Gamepad","Entrambi"};
        for(int i=0;i<3;++i) if(button({24.0f+i*144.0f,58,132,34},modes[i],config.mode==i)) { config.mode=i; capture=-1; }
        if(button({472,58,36,34},"<")) { config.pad=(config.pad+3)%4; capture=-1; }
        std::string name="Pad "+std::to_string(config.pad+1)+": ";
        name += IsGamepadAvailable(config.pad) ? std::string(GetGamepadName(config.pad)).substr(0,26) : "non collegato";
        DrawText(name.c_str(),520,68,15,RAYWHITE);
        if(button({818,58,36,34},">")) { config.pad=(config.pad+1)%4; capture=-1; }
        for(unsigned i=0;i<count;++i) {
            const float x=24+float(i/12)*432, y=127+float(i%12)*32;
            DrawText(labels[i],int(x),int(y)+9,16,RAYWHITE);
            if(button({x+168,y,112,29},keyName(config.keys[i]),capture==int(i)&&!capturePad)) { capture=int(i); capturePad=false; }
            if(i<16 && button({x+288,y,108,29},buttonName(config.buttons[i]),capture==int(i)&&capturePad,IsGamepadAvailable(config.pad))) { capture=int(i); capturePad=true; }
            if(i>=16) DrawText("Stick del pad",int(x)+288,int(y)+9,14,GRAY);
        }
        const std::string message=capture<0 ? status : std::string("Premi ")+(capturePad?"un pulsante del gamepad":"un tasto")+" per: "+labels[capture]+". Esc annulla.";
        DrawText(message.substr(0,100).c_str(),24,526,16,Color{94,217,190,255});
        DrawText(ready?"Gli stick del gamepad mantengono gli assi standard.":"Collega il gamepad selezionato oppure scegli Tastiera.",24,551,16,ready?GRAY:ORANGE);
        if(button({24,590,180,38},"Ripristina predefiniti")) { config=Config{}; capture=-1; }
        bool cancel=button({520,590,140,38},"Annulla");
        const bool start=button({680,590,174,38},saveFailed?"Avvia senza salvare":"Salva e avvia",false,ready) || (!wasCapturing && capture<0 && ready && IsKeyPressed(KEY_ENTER));
        if(start) {
            if(saveFailed || (!path.empty() && save(path,config))) accept=true;
            else { status="Salvataggio non riuscito. Puoi avviare senza salvare le preferenze."; saveFailed=true; }
        }
        EndDrawing();
        if(++frames==10)
            if(const char *shotPath=std::getenv("REA_CONTROLS_FRAME")) {
                std::error_code ec;
                if(!std::filesystem::exists(shotPath,ec)) {
                    Image shot=LoadImageFromScreen();
                    if(shot.data) { ExportImage(shot,shotPath); UnloadImage(shot); }
                }
            }
        if(accept || cancel || (!wasCapturing && capture<0 && IsKeyPressed(KEY_ESCAPE))) break;
    }
    SetWindowSize(oldWidth,oldHeight); SetExitKey(KEY_ESCAPE);
    return accept;
}
'''

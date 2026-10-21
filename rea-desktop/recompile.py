"""Build translated PS2 sources against an isolated copy of the real runtime.

This builds new machine code. It does not certify the recovered program's behavior.
Dependencies must be installed explicitly; configuring a project never downloads them.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import re
import tempfile


CMAKE = r'''cmake_minimum_required(VERSION 3.21)
project(REARecompiledPS2 LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_SIZEOF_VOID_P EQUAL 8 OR NOT CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|AMD64|amd64)$")
  message(FATAL_ERROR "This build adapter currently supports x86-64 hosts only")
endif()
if(MSVC)
  add_compile_options("$<$<COMPILE_LANGUAGE:CXX>:/arch:AVX2>")
else()
  add_compile_options("$<$<COMPILE_LANGUAGE:CXX>:-mavx2>")
endif()
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}/bin")
set(FETCHCONTENT_FULLY_DISCONNECTED ON CACHE BOOL "" FORCE)
set(FETCHCONTENT_SOURCE_DIR_RAYLIB "${CMAKE_CURRENT_SOURCE_DIR}/vendor/raylib" CACHE PATH "" FORCE)
set(PS2X_ENABLE_DEBUG_UI OFF CACHE BOOL "" FORCE)
set(PS2X_ENABLE_RUNNER_PCH ON CACHE BOOL "" FORCE)
set(PS2X_ENABLE_RUNNER_UNITY_BUILD ON CACHE BOOL "" FORCE)
set(PS2X_ENABLE_SCCACHE OFF CACHE BOOL "" FORCE)
set(PS2X_ENABLE_AGRESSIVE_LOGS OFF CACHE BOOL "" FORCE)
# Use installed Linux libraries; do not trigger upstream Windows downloads.
set(REA_HAVE_FFMPEG OFF)
if(NOT WIN32)
  find_package(PkgConfig QUIET)
  if(PkgConfig_FOUND)
    pkg_check_modules(REA_VIDEO QUIET libavcodec libavformat libavutil libswresample libswscale)
    if(REA_VIDEO_FOUND)
      set(REA_HAVE_FFMPEG ON)
    endif()
  endif()
endif()
set(PS2X_ENABLE_FFMPEG ${REA_HAVE_FFMPEG} CACHE BOOL "" FORCE)
add_subdirectory(runtime/ps2xIOP)
add_subdirectory(runtime/ps2xRuntime)
file(GLOB translated CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/../ps2-recomp/output/*.cpp")
if(NOT translated)
  message(FATAL_ERROR "No translated sources")
endif()
# Replace the upstream empty registration table and generic entry point.
set_property(TARGET ps2EntryRunner PROPERTY SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/main.cpp;${translated}")
target_include_directories(ps2EntryRunner BEFORE PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/../ps2-recomp/output")
option(REA_OPTIMIZE_GENERATED "Optimize translated code (can be very slow for recovered giant functions)" OFF)
option(REA_BALANCED_GENERATED "Use moderate optimization for translated code" OFF)
if(REA_BALANCED_GENERATED)
  if(MSVC)
    target_compile_options(ps2EntryRunner PRIVATE /O1)
  else()
    target_compile_options(ps2EntryRunner PRIVATE -O1 -fno-strict-aliasing)
  endif()
elseif(NOT REA_OPTIMIZE_GENERATED)
  if(MSVC)
    target_compile_options(ps2EntryRunner PRIVATE /Od)
  else()
    target_compile_options(ps2EntryRunner PRIVATE -O0)
  endif()
endif()
set_target_properties(ps2EntryRunner PROPERTIES OUTPUT_NAME rea-recompiled
  INTERPROCEDURAL_OPTIMIZATION_RELEASE FALSE)
set_target_properties(ps2_runtime PROPERTIES INTERPROCEDURAL_OPTIMIZATION_RELEASE FALSE)
'''

LAUNCH_HEADER = r'''#pragma once
#include <filesystem>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif
namespace rea {
namespace fs = std::filesystem;
inline fs::path executable_directory() {
#ifdef _WIN32
    std::wstring buffer(32768, L'\0');
    const auto size = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
    if (!size || size >= buffer.size()) throw std::runtime_error("Cannot locate executable");
    buffer.resize(size);
    return fs::path(buffer).parent_path();
#else
    return fs::read_symlink("/proc/self/exe").parent_path();
#endif
}
struct Inputs { fs::path boot, disc; };
inline Inputs inputs(int argc, char** argv) {
    Inputs result;
    if (argc == 3) {
        result = {fs::absolute(argv[1]), fs::absolute(argv[2])};
    } else if (argc == 1 || (argc == 2 && std::string(argv[1]) == "--check-inputs")) {
        const auto base = executable_directory();
        result.boot = base / "boot.elf";
        result.disc = base / "disc.iso";
        if (!fs::is_regular_file(result.disc)) {
            std::ifstream config(base / "disc-path.txt", std::ios::binary);
            const std::string path((std::istreambuf_iterator<char>(config)), std::istreambuf_iterator<char>());
            if (path.empty()) throw std::runtime_error("Missing ISO: place disc.iso beside the executable or set disc-path.txt");
            result.disc = fs::u8path(path);
            if (result.disc.is_relative()) result.disc = base / result.disc;
        }
    } else {
        throw std::runtime_error("Usage: rea-recompiled [<boot.elf> <disc.iso>] or --check-inputs");
    }
    if (!fs::is_regular_file(result.boot)) throw std::runtime_error("Missing boot.elf beside the executable");
    if (!fs::is_regular_file(result.disc)) throw std::runtime_error("ISO not found: restore its original path or place disc.iso beside the executable");
    return result;
}
}
'''

MAIN = r'''#include "ps2_runtime.h"
#include "rea_launch.h"
#include "runtime/ee_scheduler.h"
#include <cstdlib>
#include <iostream>
#include <syncstream>
#include <thread>
#if __has_include("runtime/ps2xRuntime/src/lib/Kernel/Syscalls/Common.h")
#include "runtime/ps2xRuntime/src/lib/Kernel/Syscalls/Common.h"
#define REA_RPC_DIAGNOSTICS 1
#endif
int main(int argc, char** argv) {
    try {
        const auto input = rea::inputs(argc, argv);
        if (argc == 2 && std::string(argv[1]) == "--check-inputs") {
            std::cout << input.boot << '\n' << input.disc << '\n';
            return 0;
        }
        PS2Runtime runtime;
        if (!runtime.initialize("REA - recompiled PS2 (unverified)")) return 3;
        if (!runtime.loadELF(input.boot.string())) return 4;
        auto paths = PS2Runtime::getIoPaths();
        paths.cdImage = input.disc;
        const auto modules = rea::executable_directory() / "disc-files";
        if (std::filesystem::is_directory(modules)) paths.cdRoot = modules;
        PS2Runtime::setIoPaths(paths);
        // Optional, bounded diagnostics from the scheduler's mutex-protected copy.
        // Do not read the live guest context or IOP structures from this thread.
        std::jthread diagnostics;
        if (const char* enabled = std::getenv("REA_DIAGNOSTICS"); enabled && std::string(enabled) == "1") {
            diagnostics = std::jthread([&runtime](std::stop_token stop) {
                for (int sample = 0; sample < 150 && !stop.stop_requested(); ++sample) {
                    for (int tick = 0; tick < 20 && !stop.stop_requested(); ++tick)
                        std::this_thread::sleep_for(std::chrono::milliseconds(100));
                    if (stop.stop_requested()) break;
#ifdef REA_RPC_DIAGNOSTICS
                    // Read only the existing RPC history under its own lock.
                    {
                        std::unique_lock lock(g_rpc_mutex, std::try_to_lock);
                        if (lock.owns_lock()) {
                            std::osyncstream output(std::cerr);
                            output << "[REA rpc] sequence=" << g_sif_rpc_debug_next_seq << '\n';
                            const auto first = g_sif_rpc_debug_next_seq > 8 ? g_sif_rpc_debug_next_seq - 7 : 1;
                            for (auto i = first; i <= g_sif_rpc_debug_next_seq; ++i) {
                                const auto& event = g_sif_rpc_debug_history[i % kSifRpcDebugHistoryCount];
                                output << "[REA rpc] " << event.seq << " " << event.op << " sid=0x" << std::hex
                                       << event.sid << " server=0x" << event.serverPtr << " pc=0x" << event.pc
                                       << " fn=" << event.rpcNum << " flags=" << event.flags << std::dec
                                       << " result=" << event.result << '\n';
                            }
                        }
                    }
#endif
                    const auto snapshot = runtime.eeScheduler().snapshot();
                    std::osyncstream output(std::cerr);
                    output << "[REA scheduler] sample=" << sample << " sequence=" << snapshot.sequence
                           << " cycle=" << snapshot.eeCycle << " running=" << snapshot.runningThreadId << '\n';
                    for (const auto& thread : snapshot.threads)
                        output << "[REA thread] id=" << thread.id << " pc=0x" << std::hex << thread.pc
                               << " ra=0x" << thread.ra << " sp=0x" << thread.sp << std::dec
                               << " priority=" << thread.currentPriority << " depth=" << thread.invocationDepth
                               << " state=" << static_cast<int>(thread.status)
                               << " wait=" << static_cast<int>(thread.waitReason) << " waitId=" << thread.waitId << '\n';
                }
            });
        }
        runtime.run();
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
'''


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def prepare_disc_modules(destination, iso, check):
    """Bounded extraction of IOP modules for the runtime's host-file loader."""
    from ps2 import Disc
    destination = Path(destination)
    if (destination / "disc-files").exists():
        raise ValueError("disc-files esiste già: usare una nuova cartella di build.")
    disc = Disc(iso, check)
    try:
        _, entries = disc.inventory()
        modules = [e for e in entries if not e["directory"] and e["path"].upper().endswith(".IRX")]
        if len(modules) > 1024 or sum(e["size"] for e in modules) > 64 * 1024 * 1024:
            raise ValueError("Limite di estrazione moduli IOP superato (1024 file / 64 MiB).")
        audit = []
        with tempfile.TemporaryDirectory(prefix=".rea-modules-", dir=destination) as temporary:
            staging = Path(temporary) / "disc-files"
            staging.mkdir()
            for entry in modules:
                check()
                # Restrict host names further than ISO9660, including Windows devices.
                for part in entry["path"].split("/"):
                    if (not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", part)
                            or part.endswith(".")
                            or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", part.split(".")[0], re.I)):
                        raise ValueError("Nome modulo IOP non utilizzabile sul sistema: " + entry["path"])
                path = staging / entry["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                audit.append({"path": entry["path"], "size": entry["size"], "sha256": disc.extract(entry, path)})
            check()
            staging.rename(destination / "disc-files")
        (destination / "disc-files.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
        return audit
    finally:
        disc.close()


CONTROLS_GUIDE = """# Comandi BURNOUT — profilo REA SLES-53506

Avvia `rea-recompiled` su Linux, oppure `rea-recompiled.exe` su Windows.
All'avvio compare **Scegli i comandi**:

1. Scegli **Tastiera**, **Gamepad** oppure **Entrambi**.
2. Per il gamepad, seleziona il dispositivo con le frecce accanto al suo nome.
3. Clicca il tasto da cambiare e premi il nuovo tasto. Per il pad, clicca il
   pulsante Pad e premi il pulsante del controller.
4. Premi **Salva e avvia**. Le preferenze sono in `controlli.ini` accanto
   all'eseguibile e vengono ricaricate all'avvio successivo.

Un tasto può avere una sola assegnazione. Esc annulla la modifica in corso.
**Ripristina predefiniti** ripristina questa tabella. Gli assi degli stick
del gamepad restano quelli standard. Se il pad non è collegato, scegli Tastiera
oppure collegalo prima di avviare.

| Comando PS2 | Tastiera predefinita |
| --- | --- |
| Croce / conferma | X oppure Spazio |
| Cerchio | C |
| Quadrato | Z |
| Triangolo | V |
| Croce direzionale / menu | Frecce |
| Stick sinistro | W A S D |
| Stick destro | I J K L |
| L1 / R1 | Q / E |
| L2 / R2 | 1 / 3 |
| Start | Invio |
| Select | Tab oppure Shift destro |
| L3 / R3 | Ctrl sinistro / Ctrl destro |
| Chiudi il gioco | Esc |

Spazio e Shift destro sono alternative solo con la mappatura predefinita e
se non sono assegnati ad altri comandi. Clicca nella finestra del gioco per
darle il focus. Acceleratore, freno e boost seguono le impostazioni del gioco.
Il pad usa di default il pulsante frontale inferiore per la Croce PS2.

Sono supportati i comandi del giocatore 1; vibrazione, multitap e secondo
giocatore non sono implementati da questo adattatore.

Conserva `boot.elf`, `disc-path.txt` e `disc-files` accanto all'eseguibile.
La ISO originale resta necessaria. Non eliminare eventuali cartelle `mc0`
e `mc1`: contengono i salvataggi.

Consulta `STATO.txt` per l'esito dei collaudi di questa copia. La presenza
della mappatura e di un eseguibile compilato non certifica la giocabilità.
"""


def write_controls_guide(destination):
    destination = Path(destination)
    (destination / "controlli.md").write_text(CONTROLS_GUIDE, encoding="utf-8")
    (destination / "TASTI.txt").write_text(CONTROLS_GUIDE, encoding="utf-8")


def prepare_launch_files(executable, boot, iso, check=lambda: None):
    """Keep required boot data beside the binary; reference, never duplicate, the ISO."""
    destination = Path(executable).parent
    shutil.copy2(boot, destination / "boot.elf")
    (destination / "disc-path.txt").write_text(str(Path(iso).resolve()), encoding="utf-8")
    from ps2_runtime_fixes import SUPPORTED_BOOT
    modules = prepare_disc_modules(destination, iso, check) if digest(boot) == SUPPORTED_BOOT else []
    (destination / "LEGGIMI.txt").write_text(
        "Avvia rea-recompiled (rea-recompiled.exe su Windows) senza argomenti.\n"
        "Conserva boot.elf e disc-path.txt accanto all'eseguibile.\n"
        "Se presente, conserva anche la cartella disc-files: contiene i moduli IOP originali.\n"
        "La ISO originale resta necessaria: non spostarla, oppure copia la tua ISO qui come disc.iso.\n"
        "Il binario contiene il codice ricompilato; i dati del gioco restano nella ISO.\n"
        "La compilazione riuscita non garantisce la giocabilita.\n", encoding="utf-8")
    if digest(boot) == SUPPORTED_BOOT:
        write_controls_guide(destination)
    return modules


def deliver_executable(executable, destination, title, check):
    """Copy the launch bundle into a fresh folder without replacing existing files."""
    executable = Path(executable)
    root = Path(destination).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    prefix = re.sub(r"[^A-Za-z0-9_-]+", "-", title).strip("-")[:60] or "REA"
    folder = Path(tempfile.mkdtemp(prefix=prefix + "-", dir=root))
    try:
        files = {executable, *(executable.parent / name for name in ("boot.elf", "disc-path.txt", "LEGGIMI.txt"))}
        files.update(executable.parent.glob("*.dll"))
        files.update(executable.parent.glob("*.so*"))
        if (executable.parent / "disc-files.json").is_file():
            files.add(executable.parent / "disc-files.json")
        for name in ("TASTI.txt", "controlli.md"):
            if (executable.parent / name).is_file():
                files.add(executable.parent / name)
        for source in sorted(files):
            check()
            shutil.copy2(source, folder / source.name)
        modules = executable.parent / "disc-files"
        if modules.exists():
            def copy_module(source, target):
                check()
                if Path(source).is_symlink():
                    raise ValueError("Link simbolico inatteso nei moduli IOP.")
                return shutil.copy2(source, target)
            for path in [modules, *modules.rglob("*")]:
                if path.is_symlink():
                    raise ValueError("Link simbolico inatteso nei moduli IOP.")
            shutil.copytree(modules, folder / "disc-files", copy_function=copy_module)
        check()
        return {"status": "copied", "directory": str(folder), "executable": str(folder / executable.name)}
    except BaseException:
        shutil.rmtree(folder)
        raise


def build_ps2(directory, config, check, progress, save, iso_path=None):
    from ps2 import run_tool
    directory = Path(directory).resolve()
    work = directory / "native-build"
    work.mkdir(exist_ok=False)
    state = {"status": "preparing", "playable": False, "executed": False,
             "host": {"system": platform.system(), "machine": platform.machine()},
             "directory": "native-build", "limitations": [
                 "Build x86-64, CPU AVX2 richiesta per eseguire il risultato.",
                 "Runtime PS2Recomp sperimentale: nessuna equivalenza o giocabilità certificata.",
                 "Compilazione sul sistema corrente; Windows richiede un compilatore C++20 locale."]}

    def persist():
        temporary = work / "build.json.tmp"
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(work / "build.json")
        save(dict(state))

    persist()
    source = Path(config.get("ps2_source", ""))
    raylib = Path(config.get("raylib_source", ""))
    cmake = config.get("cmake", "")
    missing = []
    if not cmake or not Path(cmake).is_file():
        missing.append("eseguibile CMake")
    for component in ("ps2xRuntime", "ps2xIOP"):
        if not (source / component / "CMakeLists.txt").is_file():
            missing.append("sorgenti PS2Recomp: " + component)
    if not (raylib / "src/raylib.h").is_file():
        missing.append("sorgenti raylib 5.5")
    if missing:
        state.update(status="build_tools_missing", reason="Configurare " + ", ".join(missing) + ".")
        persist()
        return state
    check()
    # Only copy configured, trusted build dependencies. Never consume CMake files
    # from the target ISO, or overwrite the user's upstream checkout.
    ignored = shutil.ignore_patterns(".git", "out", "build", "__pycache__")
    def copy_checked(src, dst):
        check()
        return shutil.copy2(src, dst)
    for component in ("ps2xRuntime", "ps2xIOP"):
        check()
        shutil.copytree(source / component, work / "runtime" / component, ignore=ignored, copy_function=copy_checked)
    if (source / "LICENSE").is_file():
        shutil.copy2(source / "LICENSE", work / "runtime/LICENSE")
    from ps2_runtime_fixes import apply_runtime_fixes
    try:
        state["runtime_fixes"] = apply_runtime_fixes(work / "runtime", directory / "ps2-recomp/input.elf")
    except (OSError, ValueError) as error:
        state.update(status="build_failed", reason=str(error))
        persist()
        return state
    (work / "runtime-fixes.json").write_text(json.dumps(state["runtime_fixes"], indent=2), encoding="utf-8")
    persist()
    shutil.copytree(raylib, work / "vendor/raylib", copy_function=copy_checked,
                    ignore=shutil.ignore_patterns(".git", ".github", "examples", "projects", "parser", "logo", "build"))
    (work / "CMakeLists.txt").write_text(CMAKE, encoding="utf-8")
    (work / "main.cpp").write_text(MAIN, encoding="utf-8")
    (work / "rea_launch.h").write_text(LAUNCH_HEADER, encoding="utf-8")
    sources = sorted(p for p in (directory / "ps2-recomp/output").iterdir() if p.is_file())
    state["inputs"] = {}
    for path in sources:
        check()
        state["inputs"][str(path.relative_to(directory))] = digest(path)
    state["project_inputs"] = {name: digest(work / name) for name in ("CMakeLists.txt", "main.cpp", "rea_launch.h")}
    dependencies = {}
    for subtree in (work / "runtime", work / "vendor"):
        for path in sorted(subtree.rglob("*")):
            check()
            if path.is_file():
                dependencies[str(path.relative_to(work))] = digest(path)
    (work / "dependencies.json").write_text(json.dumps(dependencies, indent=2), encoding="utf-8")
    state["dependencies_sha256"] = digest(work / "dependencies.json")
    state["boot_sha256"] = digest(directory / "ps2-recomp/input.elf")
    state["cmake"] = str(Path(cmake).resolve())
    optimization = config.get("build_optimization", "fast")
    if optimization not in ("fast", "balanced", "optimized"):
        state.update(status="build_failed", reason="Modalità di ottimizzazione PS2 non valida.")
        persist()
        return state
    state["optimization"] = optimization
    if optimization == "fast":
        state["limitations"].append("Codice tradotto senza ottimizzazione per accelerare la build; prestazioni di esecuzione non rappresentative di un port ottimizzato.")
    if optimization == "balanced":
        state["limitations"].append("Ottimizzazione intermedia del codice tradotto (-O1 su GCC/Clang, /O1 su MSVC); prestazioni del gioco da misurare.")
    state["commands"] = [
        [state["cmake"], "-S", ".", "-B", "build", "-DCMAKE_BUILD_TYPE=Release",
         "-DREA_OPTIMIZE_GENERATED=" + ("ON" if optimization == "optimized" else "OFF"),
         "-DREA_BALANCED_GENERATED=" + ("ON" if optimization == "balanced" else "OFF")],
        [state["cmake"], "--build", "build", "--config", "Release", "--target", "ps2EntryRunner",
         "--parallel", str(max(1, min(8, int(config.get("build_jobs", 2)))))]]
    (work / "README.md").write_text(
        "# Nuova compilazione PS2\n\n"
        "CMake compila i C++ in ../ps2-recomp/output e li collega al runtime copiato qui.\n"
        "Non usa il port Burnout 3 o Tenkaichi3Decomp precompilato.\n"
        "build.json conserva stato, comandi, hash e limiti. I log conservano gli errori.\n"
        "Una build riuscita non certifica il funzionamento del gioco. Nessun avvio automatico.\n\n"
        "La build rapida disattiva l’ottimizzazione del solo codice tradotto. Per ottimizzarlo "
        "aggiungere `-DREA_OPTIMIZE_GENERATED=ON` al comando di configurazione: può richiedere molto tempo.\n\n"
        "Alternativa bilanciata: `-DREA_BALANCED_GENERATED=ON`, con ottimizzazione intermedia (-O1 su GCC/Clang, /O1 su MSVC).\n\n"
        "Ricompilare: `cmake -S . -B build -DCMAKE_BUILD_TYPE=Release`, poi "
        "`cmake --build build --config Release --target ps2EntryRunner --parallel 2`.\n"
        "Avvio diretto: aprire `build/bin/rea-recompiled` (`.exe` su Windows), senza argomenti. "
        "Conservare boot.elf e disc-path.txt accanto al binario. La ISO originale rimane necessaria; "
        "per spostarla, copiarla accanto all'eseguibile come disc.iso. "
        "`--check-inputs` verifica i percorsi senza avviare il gioco.\n\n"
        "Avvio alternativo, dalla cartella del report: "
        "`native-build/build/bin/rea-recompiled ps2-recomp/input.elf /percorso/disco.iso` "
        "(su Windows aggiungere `.exe`). Conservare i file di runtime richiesti.\n",
        encoding="utf-8")
    try:
        for phase, message, command in zip(
                ("configuring", "compiling"),
                ("PS2: configurazione del progetto CMake", "PS2: compilazione C++ e collegamento del runtime"),
                state["commands"]):
            state.update(status=phase)
            persist()
            progress(message, 86 if phase == "configuring" else 92)
            timeout = int(config.get("build_timeout", 3600) if phase == "compiling" else config.get("timeout", 900))
            run_tool(command, work, work / (phase + ".log"), timeout, check)
            if phase == "configuring":
                cache = (work / "build/CMakeCache.txt").read_text(encoding="utf-8")
                state["ffmpeg"] = bool(re.search(r"(?m)^PS2X_ENABLE_FFMPEG:BOOL=(ON|TRUE|1)$", cache))
                if not state["ffmpeg"]:
                    state["limitations"].append("Decoder FFmpeg non disponibile in questa build; i filmati MPEG possono bloccare il gioco.")
        executable = work / "build/bin" / ("rea-recompiled.exe" if os.name == "nt" else "rea-recompiled")
        if not executable.is_file() or not executable.stat().st_size:
            raise RuntimeError("Il linker non ha prodotto l’eseguibile atteso.")
        if iso_path is None:
            raise ValueError("Percorso ISO necessario per preparare l’avvio diretto.")
        modules = prepare_launch_files(executable, directory / "ps2-recomp/input.elf", iso_path, check)
        state["launch"] = {"arguments_required": False, "iso_required": True,
                           "iop_modules": modules,
                           "files": {name: digest(executable.parent / name)
                                     for name in ("boot.elf", "disc-path.txt", "LEGGIMI.txt", "TASTI.txt", "controlli.md")
                                     if (executable.parent / name).is_file()}}
        state.update(status="built_unverified", executable=str(executable.relative_to(directory)),
                     sha256=digest(executable), size=executable.stat().st_size,
                     reason="Nuovo eseguibile compilato dai C++ tradotti. Non eseguito; giocabilità da verificare.")
        if config.get("executable_output", "").strip():
            progress("Copia dell’eseguibile nella destinazione scelta", 98)
            try:
                state["delivery"] = deliver_executable(executable, config["executable_output"], Path(iso_path).stem, check)
            except (OSError, ValueError) as error:
                state["delivery"] = {"status": "failed", "error": str(error)}
                state["reason"] += " Copia nella destinazione scelta non riuscita; eseguibile conservato nel report."
    except (RuntimeError, TimeoutError, OSError, ValueError) as error:
        state.update(status="build_failed", reason=str(error))
    except BaseException:
        state.update(status="interrupted", reason="Build interrotta; consultare il report principale.")
        persist()
        raise
    persist()
    return state

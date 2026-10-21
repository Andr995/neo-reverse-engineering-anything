"""Local REA orchestration. Targets are inspected, never launched."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

from ps2 import analyze_disc

ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
SCAN_BYTES = 32 * 1024 * 1024
STRING_LIMIT = 10000


class Cancelled(Exception):
    pass


class ReaToolError(RuntimeError):
    def __init__(self, response):
        self.response = response
        try:
            content = next(item["text"] for item in response["content"] if item.get("type") == "text")
            error = json.loads(content)["error"]
            message = f"{error.get('code', 'REA')}: {error['message']}"
            details = error.get("details", {})
            if details:
                message += "\n" + json.dumps(details, ensure_ascii=False, indent=2)
        except (KeyError, ValueError, StopIteration, TypeError):
            message = json.dumps(response, ensure_ascii=False)
        super().__init__(message)


def check_cancel(cancel):
    if cancel.is_set():
        raise Cancelled("Analisi interrotta dall’utente.")


def defaults():
    workspace = ROOT.parent
    nodes = sorted((workspace / ".tools").glob("node-*/bin/node"))
    bundled = ROOT / "runtime"
    node = bundled / ("node.exe" if os.name == "nt" else "node")
    rea = bundled / "rea" / "scripts" / "rea.mjs"
    tool_roots = [bundled / "tools", workspace / ".tools"]
    if getattr(sys, "frozen", False) and len(ROOT.parents) >= 3:
        tool_roots.append(ROOT.parents[2] / ".tools")
    launcher = "analyzeHeadless.bat" if os.name == "nt" else "analyzeHeadless"
    java = "java.exe" if os.name == "nt" else "java"
    javac = "javac.exe" if os.name == "nt" else "javac"
    ghidra = next((p for root in tool_roots for p in sorted(root.glob("ghidra_12.1.*_PUBLIC"), reverse=True)
                   if (p / "support" / launcher).is_file()), None)
    jdk = next((p for root in tool_roots for p in sorted(root.glob("jdk-21*"), reverse=True)
                if (p / "bin" / java).is_file() and (p / "bin" / javac).is_file()), None)
    def ps2_tool(name, component):
        filename = name + (".exe" if os.name == "nt" else "")
        candidates = [bundled / "ps2recomp" / filename,
                      workspace / "ps2recomp/out/build" / component / filename,
                      workspace / "ps2recomp/out/build" / component / "Release" / filename]
        return str(next((p for p in candidates if p.is_file()), ""))
    setup_name = "Tenkaichi3Decomp-setup" + (".exe" if os.name == "nt" else "")
    bt3_setup = next((p for root in tool_roots for p in sorted(root.glob(f"tenkaichi3-*/Tenkaichi3Decomp/{setup_name}"))
                      if p.is_file()), None)
    burnout = next((p for root in tool_roots for p in sorted(root.glob("burnout3-v*/Burnout3-PC-*/burnout3.exe"))
                    if p.is_file()), None)
    proton = Path.home() / ".local/share/Steam/steamapps/common/Proton - Experimental/files/bin/wine"
    ps2_sources = [workspace / "ps2recomp", ROOT / "source/ps2recomp"]
    raylib_sources = [root / "raylib-5.5" for root in tool_roots]
    raylib_sources.append(ROOT / "source/raylib-5.5")
    return {
        "node": str(node) if node.is_file() else str(nodes[-1]) if nodes else shutil.which("node") or "",
        "rea": str(rea) if rea.is_file() else str(workspace / "rea" / "scripts" / "rea.mjs"),
        "ghidra": os.environ.get("GHIDRA_INSTALL_DIR") or (str(ghidra) if ghidra else ""),
        "java_home": os.environ.get("JAVA_HOME") or (str(jdk) if jdk else ""),
        "output": str(Path.home() / "REA-Reports"),
        "executable_output": "",
        "timeout": 900,
        "max_functions": 0,
        "ps2_analyzer": ps2_tool("ps2_analyzer", "ps2xAnalyzer"),
        "ps2_recompiler": ps2_tool("ps2_recomp", "ps2xRecomp"),
        "ps2_mode": "recompile",
        "ps2_source": str(next((p for p in ps2_sources if (p / "ps2xRuntime/CMakeLists.txt").is_file()), "")),
        "raylib_source": str(next((p for p in raylib_sources if (p / "src/raylib.h").is_file()), "")),
        "cmake": shutil.which("cmake") or "",
        "build_jobs": 2,
        "build_timeout": 3600,
        "build_optimization": "fast",
        "bt3_setup": str(bt3_setup) if bt3_setup else "",
        "burnout3_executable": str(burnout) if burnout else "",
        "proton_wine": str(proton) if proton.is_file() else shutil.which("wine") or "",
    }


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def classify(data, suffix):
    if suffix.lower() == ".iso" or data[32769:32775] == b"CD001\x01":
        return "iso"
    if data.startswith(b"\x7fELF"):
        return "elf"
    if data.startswith(b"MZ"):
        try:
            pe = struct.unpack_from("<I", data, 0x3C)[0]
            if data[pe:pe + 4] != b"PE\0\0":
                return "dos-mz"
            optional = pe + 24
            magic = struct.unpack_from("<H", data, optional)[0]
            base = {0x10B: 96, 0x20B: 112}.get(magic)
            optional_size = struct.unpack_from("<H", data, pe + 20)[0]
            if base and optional_size >= base + 15 * 8:
                count = struct.unpack_from("<I", data, optional + base - 4)[0]
                rva, size = struct.unpack_from("<II", data, optional + base + 14 * 8)
                if count >= 15 and rva and size:
                    return "dotnet"
            return "pe"
        except struct.error:
            return "malformed-pe"
    if data[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce", b"\xca\xfe\xba\xbe"):
        return "mach-o"
    if suffix.lower() == ".asar":
        return "asar"
    if suffix.lower() in (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"):
        return "javascript"
    if data.startswith(b"PK\x03\x04"):
        return "zip"
    return "unknown"


def inspect_file(path, cancel):
    digest, counts, prefix, size = hashlib.sha256(), Counter(), bytearray(), 0
    before = path.stat()
    with path.open("rb") as source:
        initial = source.read(65536)
    is_iso = classify(initial, path.suffix) == "iso"
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            check_cancel(cancel)
            digest.update(chunk)
            if not is_iso:
                counts.update(chunk)
            size += len(chunk)
            scan_limit = 65536 if is_iso else SCAN_BYTES
            if len(prefix) < scan_limit:
                prefix.extend(chunk[:scan_limit - len(prefix)])
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise RuntimeError("Il file è cambiato durante la lettura. Ripetere l’analisi.")
    strings = []
    for pattern, encoding in ((rb"[\x20-\x7e]{5,}", "ascii"), (rb"(?:[\x20-\x7e]\x00){5,}", "utf-16-le")):
        for match in re.finditer(pattern, prefix):
            check_cancel(cancel)
            if len(strings) >= STRING_LIMIT:
                break
            raw = match.group()
            strings.append({"offset": hex(match.start()), "encoding": encoding,
                            "value": raw[:1024].decode(encoding), "truncated": len(raw) > 1024})
    entropy = -sum((n / size) * math.log2(n / size) for n in counts.values()) if size else 0
    return {"path": str(path), "name": path.name, "size": size, "sha256": digest.hexdigest(),
            "format": classify(prefix, path.suffix), "entropy": None if is_iso else round(entropy, 4),
            "strings": strings, "strings_scanned_bytes": len(prefix),
            "strings_limit": STRING_LIMIT, "strings_limit_reached": len(strings) == STRING_LIMIT,
            "strings_note": "Candidati ASCII/UTF-16LE di almeno 5 caratteri; massimo 1024 byte per valore. Non provano un comportamento."}


class ReaClient:
    """One persistent stdio MCP session per artifact; no shell interpolation."""

    def __init__(self, config, directory, cancel):
        self.cancel, self.config, self.sequence = cancel, config, 0
        self.messages = queue.Queue(maxsize=64)
        self.log = (directory / "rea-stderr.log").open("wb")
        env = os.environ.copy()
        # PyInstaller changes its own loader path; external engines need the host's.
        if getattr(sys, "frozen", False) and os.name != "nt":
            if "LD_LIBRARY_PATH_ORIG" in env:
                env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
            else:
                env.pop("LD_LIBRARY_PATH", None)
        if config.get("ghidra"):
            env["GHIDRA_INSTALL_DIR"] = config["ghidra"]
        if config.get("java_home"):
            env["JAVA_HOME"] = config["java_home"]
            env["PATH"] = str(Path(config["java_home"]) / "bin") + os.pathsep + env.get("PATH", "")
        env["REA_GHIDRA_STARTUP_TIMEOUT_MS"] = str(config["timeout"] * 1000)
        try:
            self.process = subprocess.Popen(
                [config["node"], config["rea"], "mcp"], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self.log, env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception:
            self.log.close()
            raise
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(64 * 1024 * 1024 + 1)
                if not line:
                    raise RuntimeError("REA ha terminato la connessione. Consultare rea-stderr.log.")
                if len(line) > 64 * 1024 * 1024:
                    raise RuntimeError("Risposta REA oltre 64 MiB: analisi parziale, ridurre l’ambito.")
                message = json.loads(line)
                # Ignore unrequested progress/log notifications without retaining them.
                if "id" in message:
                    self.messages.put(message)
        except Exception as error:
            self.messages.put(error)

    def send(self, message):
        self.process.stdin.write((json.dumps({"jsonrpc": "2.0", **message}) + "\n").encode())
        self.process.stdin.flush()

    def request(self, method, params, *, cleanup=False):
        self.sequence += 1
        request_id = self.sequence
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + (30 if cleanup else self.config["timeout"])
        while True:
            if not cleanup and self.cancel.is_set():
                self.send({"method": "notifications/cancelled", "params": {"requestId": request_id, "reason": "User cancellation"}})
                raise Cancelled("Analisi interrotta dall’utente.")
            if time.monotonic() >= deadline:
                self.send({"method": "notifications/cancelled", "params": {"requestId": request_id, "reason": "Timeout"}})
                raise TimeoutError(f"Tempo massimo superato: {method}.")
            try:
                message = self.messages.get(timeout=0.1)
            except queue.Empty:
                continue
            if isinstance(message, Exception):
                raise message
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
            return message["result"]

    def initialize(self):
        result = self.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                             "clientInfo": {"name": "rea-desktop", "version": "0.1.0"}})
        self.send({"method": "notifications/initialized"})
        return result

    def call(self, name, arguments, *, cleanup=False):
        result = self.request("tools/call", {"name": name, "arguments": arguments}, cleanup=cleanup)
        if result.get("isError"):
            raise ReaToolError(result)
        value = result.get("structuredContent")
        if value is None:
            texts = [item["text"] for item in result.get("content", []) if item.get("type") == "text"]
            value = json.loads("\n".join(texts))
        return value

    def close(self):
        issues = []
        try:
            self.call("close_binary", {}, cleanup=True)
        except Exception as error:
            issues.append(f"Chiusura sessione non verificata: {error}")
        try:
            self.process.stdin.close()
            self.process.wait(timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            issues.append("Arresto forzato di REA; pulizia dei processi del motore non verificata.")
        self.process.stdout.close()
        self.log.close()
        return issues


def normalized(evidence):
    if not isinstance(evidence, dict) or "normalized_result" not in evidence:
        raise RuntimeError("Risposta REA inattesa: normalized_result assente.")
    return evidence["normalized_result"]


def analyze(target, config, cancel, progress=lambda message, percent: None, on_directory=None):
    path = Path(target).expanduser().resolve(strict=True)
    if not path.is_file() and not path.is_dir():
        raise ValueError("Selezionare un file regolare o una cartella applicazione.")
    output = Path(config["output"]).expanduser().resolve()
    if path.is_dir() and (output == path or path in output.parents):
        raise ValueError("La cartella dei report deve essere esterna all’applicazione analizzata.")
    directory = output / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8])
    directory.mkdir(parents=True, mode=0o700)
    if on_directory:
        on_directory(str(directory))
    report = {"version": 1, "target": str(path), "created_at": datetime.now(timezone.utc).isoformat(),
              "directory": str(directory), "status": "running", "steps": [], "functions": [], "limitations": [
                  "Analisi statica: il programma non è stato eseguito; il comportamento runtime resta sconosciuto.",
                  "Il pseudocodice non è il sorgente originale e non garantisce un progetto ricompilabile."]}
    started = time.monotonic()
    last_saved = 0.0
    client = None

    def save(force=False):
        nonlocal last_saved
        if not force and time.monotonic() - last_saved < 1:
            return
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        write_json(directory / "report.json", report)
        last_saved = time.monotonic()

    def call(tool, arguments, filename):
        check_cancel(cancel)
        evidence = client.call(tool, arguments)
        write_json(directory / filename, evidence)
        if kind in ("elf", "pe", "mach-o", "dos-mz", "dotnet") and isinstance(evidence, dict):
            subject = evidence.get("subject", {})
            provider_hash = subject.get("digest", {}).get("sha256") if isinstance(subject, dict) else None
            if provider_hash and provider_hash != info["sha256"]:
                raise RuntimeError("L’impronta del target letto da REA differisce dalla lettura iniziale. Le evidenze sono conservate separatamente; ripetere l’analisi su un file stabile.")
        report["steps"].append({"tool": tool, "file": filename, "status": "ok"})
        if isinstance(evidence, dict) and evidence.get("limitations"):
            report["limitations"].append({"tool": tool, "details": evidence["limitations"]})
        save()
        return evidence

    try:
        progress("Identificazione e impronta del file", 2)
        info = {"path": str(path), "name": path.name, "format": "directory"} if path.is_dir() else inspect_file(path, cancel)
        write_json(directory / "file-info.json", info)
        report["file"] = {key: value for key, value in info.items() if key != "strings"}
        save()
        kind = info["format"]
        if kind in ("elf", "pe", "mach-o", "dos-mz", "dotnet"):
            report["recompilation"] = {
                "status": "unsupported", "target": "same_host", "executable": None,
                "reason": "Ricompilazione di binari PC non implementata: il pseudocodice Ghidra e il CIL non costituiscono un progetto compilabile. Disponibile l’analisi."}
            report["limitations"].append(report["recompilation"]["reason"])
        if kind == "iso":
            iso_state = path.stat()
            def save_ps2(project):
                report["ps2"] = project
                write_json(directory / "ps2-project.json", project)
                save(force=True)
            report["steps"].append({"tool": "PS2 ISO / PS2Recomp", "file": "ps2-project.json", "status": "running"})
            project = analyze_disc(path, directory, config, lambda: check_cancel(cancel), progress, save_ps2)
            current_state = path.stat()
            if (iso_state.st_size, iso_state.st_mtime_ns, iso_state.st_ino) != (current_state.st_size, current_state.st_mtime_ns, current_state.st_ino):
                raise RuntimeError("L’ISO è cambiata durante l’elaborazione. Ripetere su un file stabile.")
            report["limitations"].extend(project["limitations"])
            report["limitations"].append("Il progetto PS2 non è certificato giocabile. Consultare lo stato del port e i log del motore.")
            report["steps"][-1]["status"] = project["status"]
            report["status"] = "partial"
            return report
        if kind not in ("elf", "pe", "mach-o", "dos-mz", "dotnet", "asar", "directory", "javascript"):
            report["status"] = "partial"
            report["limitations"].append(f"Formato {kind}: disponibili impronta, entropia e stringhe. Nessuna decompilazione avviata.")
            return report
        progress("Avvio del motore REA", 8)
        client = ReaClient(config, directory, cancel)
        report["server"] = client.initialize().get("serverInfo")
        if kind in ("directory", "asar", "javascript"):
            input_path = path
            if kind == "javascript":
                input_path = directory / "javascript-input"
                input_path.mkdir()
                shutil.copy2(path, input_path / path.name)
                report["limitations"].append("File JavaScript isolato: dipendenze esterne non fornite e non analizzate.")
            progress("Analisi moduli e relazioni JavaScript", 30)
            call("analyze_javascript_application", {"input_path": str(input_path)}, "javascript.json")
        elif kind == "dotnet":
            progress("Analisi metadati .NET", 25)
            call("inspect_managed_artifact", {"path": str(path)}, "managed-artifact.json")
            progress("Estrazione membri e istruzioni CIL", 55)
            call("inspect_managed_members", {"path": str(path)}, "managed-members.json")
            report["limitations"].append("Per .NET vengono estratti metadati e CIL; questa versione non ricostruisce sorgenti C#.")
        else:
            progress("Importazione e analisi Ghidra (può richiedere alcuni minuti)", 15)
            call("open_binary", {"path": str(path), "provider_id": "ghidra"}, "session.json")
            call("binary_overview", {}, "overview.json")
            progress("Inventario funzioni, simboli e stringhe", 25)
            procedures = normalized(call("list_procedures", {}, "procedures.json"))
            if not isinstance(procedures, list):
                raise RuntimeError("Inventario funzioni REA non valido.")
            for tool, filename in (("list_names", "symbols.json"), ("list_strings", "strings.json")):
                call(tool, {}, filename)
            report["functions_discovered"] = len(procedures)
            maximum = config.get("max_functions", 0)
            selected = procedures[:maximum] if maximum else procedures
            if len(selected) < len(procedures):
                report["limitations"].append(f"Limite scelto: {len(selected)} funzioni su {len(procedures)} verranno tentate.")
            functions_dir = directory / "functions"
            functions_dir.mkdir()
            for index, procedure in enumerate(selected):
                check_cancel(cancel)
                address = procedure["address"]
                name = procedure.get("value") or address
                progress(f"Decompilazione {index + 1}/{len(selected)} · {name}", 30 + int(65 * index / max(1, len(selected))))
                entry = {"address": address, "name": name, "status": "error"}
                try:
                    evidence = client.call("analyze_function", {"procedure": address})
                    filename = f"functions/{index:06d}.json"
                    write_json(directory / filename, evidence)
                    entry.update(status="ok", file=filename)
                    dossier = normalized(evidence)
                    code = dossier.get("pseudocode")
                    if isinstance(code, str) and code:
                        code_file = f"functions/{index:06d}.c"
                        (directory / code_file).write_text(code, encoding="utf-8")
                        entry["pseudocode_file"] = code_file
                    else:
                        entry["status"] = "no_pseudocode"
                    if evidence.get("limitations"):
                        entry["limitations"] = evidence["limitations"]
                except (Cancelled, TimeoutError):
                    raise
                except Exception as error:
                    entry["error"] = str(error)
                    if isinstance(error, ReaToolError):
                        entry["rea_error"] = error.response
                report["functions"].append(entry)
                save()
            report["functions_decompiled"] = sum("pseudocode_file" in f for f in report["functions"])
        report["status"] = "completed"
        if any(f["status"] != "ok" for f in report["functions"]) or (report.get("functions_discovered", 0) > len(report["functions"])):
            report["status"] = "partial"
    except Cancelled:
        report["status"] = "cancelled"
        if "ps2" in report:
            report["ps2"]["status"] = "cancelled"
    except Exception as error:
        report["status"] = "partial" if "file" in report else "error"
        report["error"] = str(error)
        if "ps2" in report:
            report["ps2"].update(status="error", error=str(error))
        if isinstance(error, ReaToolError):
            write_json(directory / "rea-error.json", error.response)
    finally:
        if "ps2" in report:
            if report["status"] in ("cancelled", "partial") and report.get("error"):
                report["steps"][-1]["status"] = "error"
            elif report["status"] == "cancelled":
                report["steps"][-1]["status"] = "cancelled"
            for key in ("recompilation", "native_profile", "build"):
                stage = report["ps2"].get(key, {})
                if stage.get("status") in ("running", "installing", "preparing", "configuring", "compiling"):
                    stage["status"] = report["ps2"]["status"]
            if report["ps2"].get("build") and (directory / "native-build").is_dir():
                write_json(directory / "native-build/build.json", report["ps2"]["build"])
            write_json(directory / "ps2-project.json", report["ps2"])
        if client:
            cleanup_issues = client.close()
            report["limitations"].extend(cleanup_issues)
            if cleanup_issues and report["status"] == "completed":
                report["status"] = "partial"
        save(force=True)
        render_report(directory, report)
    return report


def render_report(directory, report):
    info = report.get("file", {})
    lines = ["# REA Desktop — Report", "", f"Target: {report['target']}",
             f"Stato: {report['status']}", f"Formato: {info.get('format', 'sconosciuto')}",
             f"SHA-256: {info.get('sha256', 'non disponibile per cartelle')}",
             f"Durata: {report['elapsed_seconds']} s", "",
             f"Funzioni individuate: {report.get('functions_discovered', 'non applicabile')}",
             f"Pseudocodici salvati: {sum('pseudocode_file' in f for f in report['functions'])}", ""]
    if report.get("error"):
        lines += ["## Errore", "", "```text", report["error"], "```", ""]
    if "ps2" in report:
        project = report["ps2"]
        labels = {"sources_generated": "Sorgenti C++ generati · port da completare",
                  "built_unverified": "Nuovo eseguibile compilato · funzionamento non verificato",
                  "build_failed": "Compilazione fallita · sorgenti e log conservati",
                  "build_tools_missing": "Sorgenti generati · strumenti di compilazione mancanti",
                  "tools_missing": "Motori PS2Recomp da configurare", "native_prepared": "Port esistente preparato · avvio da verificare",
                  "error": "Operazione PS2 non completata", "cancelled": "Operazione PS2 interrotta"}
        lines += ["## Progetto PS2", "", f"Disco: {project.get('serial') or project.get('volume', 'non identificato')}",
                  f"Stato: {labels.get(project['status'], project['status'])}",
                  "Giocabilità verificata: no", "Indice del disco: ps2-disc.json",
                  "Progetto e risultati: ps2-project.json", ""]
        recomp = project.get("recompilation", {})
        if recomp.get("reason"):
            lines += [recomp["reason"], ""]
        build = project.get("build", {})
        if build:
            lines += ["### Compilazione sul sistema corrente", "", build.get("reason", build["status"]),
                      "Comandi, hash e risultati: native-build/build.json", ""]
            if build.get("executable"):
                lines += [f"Nuovo eseguibile: {build['executable']}", f"SHA-256: {build['sha256']}", ""]
                if build.get("launch", {}).get("arguments_required") is False:
                    lines += ["Avvio diretto senza argomenti. Premi Mostra eseguibile compilato nell’app.",
                              "Conserva boot.elf e disc-path.txt accanto al binario; la ISO originale resta necessaria.", ""]
                delivery = build.get("delivery", {})
                if delivery.get("status") == "copied":
                    lines += [f"Eseguibile nella destinazione scelta: {delivery['executable']}", ""]
                elif delivery.get("status") == "failed":
                    lines += ["Copia nella destinazione scelta non riuscita: " + delivery["error"],
                              "L’eseguibile compilato resta disponibile nella cartella del report.", ""]
        if "native_profile" in project:
            profile = project["native_profile"]
            title = profile.get("title", "Tenkaichi 3")
            lines += [f"Profilo {title}: {profile['status']}", f"Release: {profile['url']}", ""]
            if profile.get("id") == "burnout3-usa":
                lines += [profile["execution"], profile.get("reason", "Port preparato. Premi Avvia Burnout 3 per giocare."),
                          "Versione upstream 0.3.0-alpha: non certificata stabile.", ""]
            else:
                lines += ["Per preparare il port esistente, selezionare Tenkaichi3Decomp-setup nelle Impostazioni e trascinare l’ISO.", ""]
            if profile.get("executable"):
                lines += [f"Eseguibile preparato: {profile['executable']}", ""]
    lines += ["## Risultati", ""]
    lines += [f"- {step['tool']}: {step['file']}" for step in report["steps"]]
    lines += ["", "## Limiti", ""]
    lines += ["- " + (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) for v in report["limitations"]]
    lines += ["", "I dossier completi e i limiti per funzione sono nei file JSON in functions/."]
    (directory / "report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Analisi statica automatica con REA")
    parser.add_argument("target")
    parser.add_argument("--output")
    parser.add_argument("--ghidra")
    args = parser.parse_args()
    config = defaults()
    if args.output:
        config["output"] = args.output
    if args.ghidra:
        config["ghidra"] = args.ghidra
    result = analyze(args.target, config, threading.Event(), lambda text, _: print(text, flush=True))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["status"] == "completed" else 2)

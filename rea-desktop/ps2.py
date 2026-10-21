"""PS2 disc inspection and experimental source generation; no game execution.

ISO names are evidence only: extraction uses fixed host filenames. A generated
C++ project is never reported as a working native port.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import time

SECTOR = 2048
MAX_ENTRIES = 50000
MAX_DIRECTORY_BYTES = 64 * 1024 * 1024
MAX_EXECUTABLE_BYTES = 256 * 1024 * 1024
BT3_URL = "https://github.com/z3xox/Tenkaichi3Decomp/releases"

# Exact BOOT2 fingerprints only. This is an entry into the original guest code,
# not a replacement stub. SLES-53506: observed JALR from 0x334364 to 0x450f30;
# the analyzer included this tail-call routine after a return in sub_00450D68.
OBSERVED_ENTRY_HINTS = {
    # 0x3012a8 is a virtual initializer reached by JALR at 0x2ffb04:
    # stores 2, 3, 1, 0 at a0 + 0x2a8..0x2b4, then returns through ra.
    "f33f153b4903a3026a29937e0e4610f6cff8ebf24005ee078e2dc1fd9b8a5242": (
        0x450F30, 0x3012A8, 0x354738,
        # RenderWare standard handlers: table 0x46b4a0, 28 (id, pointer) pairs.
        # IDs 1..28 and targets checked against this exact BOOT2.
        0x34ba38, 0x355ae8, 0x34c448, 0x355ba0, 0x35dd40, 0x35de38, 0x35df20, 0x35c130, 0x35bfa8, 0x355c38, 0x355c48, 0x355d00, 0x35bf28, 0x35bf70, 0x355ef0, 0x355e60, 0x352600, 0x3526f0, 0x355e00,
        # Initialization/cleanup pairs at 0x46bb80, 17 pairs consumed by
        # the bounded loop at 0x369bb0..0x369c38. First pair is already known.
        0x36ea10, 0x36ea98, 0x36f888, 0x36f8e8, 0x36d1f0, 0x36d240,
        0x36f0a8, 0x36f0f8, 0x369038, 0x369460, 0x3754d8, 0x375f20,
        0x367be8, 0x367c88, 0x368630, 0x368690, 0x36c1f0, 0x36c240,
        0x36add8, 0x36cec0, 0x36ce70, 0x36ae88, 0x36e138, 0x36e178,
        0x36e4e0, 0x36e510, 0x36ff10, 0x36ff80, 0x366ef8, 0x366f58,
        0x3753d0, 0x3753f0,
        # Secondary initialization/cleanup arrays, 0x46bc10..0x46bc40;
        # first three called by 0x3686f0 with a1=3 (trace 0x36871c).
        0x370718, 0x370688, 0x3705f8, 0x374eb0, 0x3721e8,
        0x370788, 0x3706f8, 0x370668, 0x374f38,
        0x372228,  # Singleton at 0x46bc08, called by 0x375f70 with a1=1.
    ),
}
# The startup loop at 0x3342d8 reads the count at 0x47f850 and calls each
# pointer in reverse order. Verified in this exact ELF and two runtime traces.
OBSERVED_CONSTRUCTOR_TABLES = {
    "f33f153b4903a3026a29937e0e4610f6cff8ebf24005ee078e2dc1fd9b8a5242": 0x47F850,
}
# This ELF uses zero-header, (zero-adjustment, code-pointer) virtual tables.
# Layouts at 0x4a2c60 and 0x4a1340, and the one-method table at 0x49fcf0,
# are confirmed by runtime dispatches.
METHOD_TABLE_PROFILES = {"f33f153b4903a3026a29937e0e4610f6cff8ebf24005ee078e2dc1fd9b8a5242"}
CALLBACK_PROFILES = set(METHOD_TABLE_PROFILES)


def code_and_data_sections(data):
    """Validate file-backed code and data used for entry-point inference."""
    elf_info(data[:52])
    offset = struct.unpack_from("<I", data, 32)[0]
    size, count, strings = struct.unpack_from("<HHH", data, 46)
    if size < 40 or not 0 <= strings < count or offset + size * count > len(data):
        raise ValueError("Sezioni ELF non valide per le tabelle metodi.")
    sections = [struct.unpack_from("<10I", data, offset + i * size) for i in range(count)]
    names_section = sections[strings]
    if names_section[4] + names_section[5] > len(data):
        raise ValueError("Nomi delle sezioni ELF troncati.")
    names = data[names_section[4]:names_section[4] + names_section[5]]
    selected = {}
    for section in sections:
        if section[0] >= len(names):
            raise ValueError("Nome sezione ELF non valido.")
        name = bytes(names[section[0]:].split(b"\0", 1)[0])
        if name in (b".text", b".data", b".rodata"):
            if section[1] != 1 or section[4] + section[5] > len(data) or section[3] + section[5] > 0x100000000:
                raise ValueError("Sezione metodi ELF fuori dai limiti.")
            selected[name] = section
    text = selected.get(b".text")
    if not text or not text[2] & 4:
        raise ValueError("Sezione codice ELF assente.")
    return selected


def callback_entries(data):
    """Data-referenced code immediately after JR ra/delay slot and up to two NOPs.

    This is bounded structural inference, not a complete function map. Keeping
    the original instructions also preserves callbacks with unusual prologues.
    """
    sections = code_and_data_sections(data)
    text = sections[b".text"]
    low, high = text[3], text[3] + text[5]
    entries = {}
    for name in (b".rodata", b".data"):
        section = sections.get(name)
        if section is None:
            continue
        for pos in range((-section[3]) % 4, section[5] - 3, 4):
            target = struct.unpack_from("<I", data, section[4] + pos)[0]
            if target & 3 or not low + 8 <= target < high:
                continue
            offset = text[4] + target - low
            for padding in range(3):
                boundary = target - 8 - 4 * padding
                if boundary < low:
                    break
                if struct.unpack_from("<I", data, offset - 8 - 4 * padding)[0] != 0x03E00008:
                    continue
                if any(struct.unpack_from("<I", data, offset - 4 * i)[0] != 0 for i in range(1, padding + 1)):
                    continue
                # Bound the manifest; repeated pointers only need one witness.
                entries.setdefault(target, {"address": hex(target), "reference": hex(section[3] + pos),
                                            "preceding_return": hex(boundary)})
                if len(entries) > 8192:
                    raise ValueError("Troppi ingressi callback: revisione della mappa richiesta.")
                break
    return set(entries), [entries[key] for key in sorted(entries)]


def method_entries(data):
    """Recognize candidate zero-adjustment method tables; never invent stubs."""
    selected = code_and_data_sections(data)
    text = selected[b".text"]
    low, high = text[3], text[3] + text[5]
    tables, addresses = [], set()
    for name in (b".data", b".rodata"):
        section = selected.get(name)
        if section is None:
            continue
        pos = (-section[3]) % 8
        while pos + 16 <= section[5]:
            if struct.unpack_from("<2I", data, section[4] + pos) != (0, 0):
                pos += 8
                continue
            end, entries = pos + 8, []
            while end + 8 <= section[5]:
                adjustment, entry = struct.unpack_from("<2I", data, section[4] + end)
                if adjustment != 0 or entry & 3 or not low <= entry < high:
                    break
                entries.append(entry)
                end += 8
            terminated_single = (len(entries) == 1 and end + 8 <= section[5]
                                 and struct.unpack_from("<2I", data, section[4] + end) == (0, 0))
            if len(entries) >= 2 or terminated_single:
                tables.append({"address": hex(section[3] + pos), "entries": [hex(a) for a in entries]})
                addresses.update(entries)
                if len(tables) > 4096 or len(addresses) > 8192:
                    raise ValueError("Troppe tabelle metodi: revisione della mappa richiesta.")
            pos = max(pos + 8, end)
    return addresses, tables


def constructor_entries(data, table):
    elf_info(data[:52])
    offset = struct.unpack_from("<I", data, 28)[0]
    size, count = struct.unpack_from("<HH", data, 42)
    if size < 32 or offset + size * count > len(data):
        raise ValueError("Tabella segmenti ELF non valida.")
    segments = []
    for i in range(count):
        kind, start, address, _, length, _, flags, _ = struct.unpack_from("<8I", data, offset + i * size)
        if kind == 1:
            if start + length > len(data):
                raise ValueError("Segmento ELF troncato.")
            segments.append((start, address, length, flags))
    for start, address, length, _ in segments:
        if address <= table and table + 4 <= address + length:
            position = start + table - address
            number = struct.unpack_from("<I", data, position)[0]
            if not 1 <= number <= 4096 or table + (number + 2) * 4 > address + length:
                raise ValueError("Dimensione tabella costruttori non valida.")
            entries = struct.unpack_from(f"<{number}I", data, position + 4)
            if struct.unpack_from("<I", data, position + (number + 1) * 4)[0] != 0:
                raise ValueError("Terminatore tabella costruttori assente.")
            for entry in entries:
                if entry & 3 or not any(flags & 1 and addr <= entry < addr + length for _, addr, length, flags in segments):
                    raise ValueError("Ingresso costruttore esterno al codice ELF.")
            return entries
    raise ValueError("Tabella costruttori assente nei segmenti ELF.")


def apply_entry_hints(configuration, boot, work):
    data = Path(boot).read_bytes()
    fingerprint = hashlib.sha256(data).hexdigest()
    addresses = set(OBSERVED_ENTRY_HINTS.get(fingerprint, ()))
    table = OBSERVED_CONSTRUCTOR_TABLES.get(fingerprint)
    if table is not None:
        addresses.update(constructor_entries(data, table))
    method_tables = []
    if fingerprint in METHOD_TABLE_PROFILES:
        methods, method_tables = method_entries(data)
        addresses.update(methods)
    callbacks = []
    if fingerprint in CALLBACK_PROFILES:
        recovered, callbacks = callback_entries(data)
        addresses.update(recovered)
    addresses = sorted(addresses)
    if addresses:
        # Change only [general]; keep the analyzer's existing entries and all
        # patches/stub bindings. Insert before the first element of its array.
        section = re.search(r"(?ms)^\[general\][^\n]*\n(.*?)(?=^\[|\Z)", configuration)
        if not section:
            raise ValueError("Sezione general assente: impossibile applicare gli ingressi verificati.")
        body = section[1]
        entries = "".join(f'\n  "rea_observed@0x{address:08X}",' for address in addresses)
        pattern = r"(?m)^entry_points\s*=\s*\["
        if re.search(pattern, body):
            body = re.sub(pattern, lambda m: m[0] + entries, body, count=1)
        else:
            body = "entry_points = [" + entries + "\n]\n" + body
        configuration = configuration[:section.start(1)] + body + configuration[section.end(1):]
    audit = {"boot_sha256": fingerprint, "addresses": [hex(a) for a in addresses],
             "constructor_table": hex(table) if table is not None else None,
             "method_tables": method_tables,
             "callback_entries": callbacks,
             "scope": "Exact BOOT2 match; runtime observations, verified constructor table, structurally inferred method tables and data-referenced return-boundary callbacks. Original guest instructions retained."}
    (Path(work) / "entry-hints.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return configuration, audit


def both(data, offset, size):
    little = int.from_bytes(data[offset:offset + size], "little")
    big = int.from_bytes(data[offset + size:offset + size * 2], "big")
    if little != big:
        raise ValueError("ISO: campi little/big endian discordanti.")
    return little


class Disc:
    """Bounded ISO9660 primary-volume reader for 2048-byte sector images."""

    def __init__(self, path, check):
        self.path, self.check = Path(path), check
        self.size = self.path.stat().st_size
        self.stream = self.path.open("rb")

    def close(self):
        self.stream.close()

    def read(self, offset, size):
        self.check()
        if offset < 0 or size < 0 or offset + size > self.size:
            raise ValueError("ISO troncata o estensione esterna all’immagine.")
        self.stream.seek(offset)
        data = self.stream.read(size)
        if len(data) != size:
            raise ValueError("ISO cambiata o troncata durante la lettura.")
        return data

    def record(self, data):
        if len(data) < 34 or data[0] != len(data) or 33 + data[32] > len(data):
            raise ValueError("ISO: record directory non valido.")
        if data[1] or data[26] or data[27] or data[25] & 0x80:
            raise ValueError("ISO con attributi estesi, interleave o multi-extent non supportata.")
        if both(data, 28, 2) != 1:
            raise ValueError("ISO multi-volume non supportata.")
        offset, size = both(data, 2, 4) * SECTOR, both(data, 10, 4)
        if offset + size > self.size:
            raise ValueError("ISO: estensione fuori dai limiti del file.")
        raw = data[33:33 + data[32]]
        name = raw.decode("ascii", errors="strict").split(";", 1)[0]
        if raw not in (b"\0", b"\1") and (
                not name or name in (".", "..") or any(c in name for c in '/\\:\x00')
                or any(ord(c) < 32 for c in name)):
            raise ValueError("ISO: nome file non valido.")
        return {"name": name, "offset": offset, "size": size,
                "directory": bool(data[25] & 2)}

    def inventory(self):
        primary = None
        for sector in range(16, 48):
            block = self.read(sector * SECTOR, SECTOR)
            if block[1:7] != b"CD001\x01":
                raise ValueError("Serve una ISO9660 a settori di 2048 byte (BIN/CUE, CHD e UDF non supportati).")
            if block[0] == 1:
                primary = block
                break
            if block[0] == 255:
                break
        if primary is None or both(primary, 128, 2) != SECTOR:
            raise ValueError("ISO9660: volume primario o dimensione dei settori non supportati.")
        volume_size = both(primary, 80, 4) * SECTOR
        if volume_size > self.size or volume_size < 17 * SECTOR:
            raise ValueError("ISO9660: dimensione volume non valida.")
        self.size = volume_size
        root = self.record(primary[156:156 + primary[156]])
        if not root["directory"]:
            raise ValueError("ISO9660: radice non valida.")
        pending, seen, names, entries, budget = [("", root, 0)], set(), set(), [], 0
        while pending:
            prefix, directory, depth = pending.pop()
            key = directory["offset"]
            if key in seen or depth > 32:
                raise ValueError("ISO: ciclo o profondità eccessiva nelle directory.")
            seen.add(key)
            budget += directory["size"]
            if budget > MAX_DIRECTORY_BYTES:
                raise ValueError("ISO: limite di 64 MiB di directory superato.")
            data = self.read(directory["offset"], directory["size"])
            cursor = 0
            while cursor < len(data):
                self.check()
                length = data[cursor]
                if not length:
                    cursor = (cursor // SECTOR + 1) * SECTOR
                    continue
                if cursor + length > len(data) or cursor % SECTOR + length > SECTOR:
                    raise ValueError("ISO: record directory troncato.")
                entry = self.record(data[cursor:cursor + length])
                cursor += length
                if entry["name"] in ("\0", "\1"):
                    continue
                entry["path"] = prefix + entry.pop("name")
                canonical = entry["path"].upper()
                if canonical in names:
                    raise ValueError("ISO: nomi duplicati o ambigui.")
                names.add(canonical)
                entries.append(entry)
                if len(entries) > MAX_ENTRIES:
                    raise ValueError("ISO: limite di 50000 voci superato.")
                if entry["directory"]:
                    pending.append((entry["path"] + "/", entry, depth + 1))
        return primary[40:72].decode("ascii", errors="replace").strip(), entries

    def extract(self, entry, destination):
        if entry["size"] > MAX_EXECUTABLE_BYTES:
            raise ValueError("Eseguibile PS2 oltre il limite di 256 MiB.")
        digest = hashlib.sha256()
        with destination.open("xb") as output:
            for offset in range(0, entry["size"], 1024 * 1024):
                data = self.read(entry["offset"] + offset, min(1024 * 1024, entry["size"] - offset))
                output.write(data)
                digest.update(data)
        return digest.hexdigest()


def elf_info(header):
    if len(header) < 52 or header[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("Il BOOT2 non è un ELF32 little-endian supportato (potrebbe essere compresso).")
    machine = struct.unpack_from("<H", header, 18)[0]
    if machine != 8:
        raise ValueError("Il BOOT2 non è un eseguibile MIPS.")
    return {"class": "ELF32", "byte_order": "little", "machine": "MIPS",
            "entry": hex(struct.unpack_from("<I", header, 24)[0]),
            "flags": hex(struct.unpack_from("<I", header, 36)[0])}


def run_tool(argv, cwd, log, timeout, check):
    """Run configured host tools, with bounded logs and process-tree cleanup."""
    check()
    env = os.environ.copy()
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
    else:
        env.pop("LD_LIBRARY_PATH", None)
    started = time.monotonic()
    with log.open("wb") as output:
        process = subprocess.Popen([str(a) for a in argv], cwd=cwd, env=env,
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=os.name != "nt")
        try:
            while process.poll() is None:
                check()
                if time.monotonic() - started > timeout:
                    raise TimeoutError(f"Timeout di {timeout} secondi: {Path(argv[0]).name}. Vedi {log.name}.")
                if log.stat().st_size > 64 * 1024 * 1024:
                    raise RuntimeError("Log del motore oltre 64 MiB; operazione interrotta.")
                time.sleep(0.1)
            check()
            if process.returncode:
                raise RuntimeError(f"{Path(argv[0]).name}: codice {process.returncode}. Dettagli in {log.name}.")
        finally:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            process.wait()


def generate_sources(boot, work, config, check, progress):
    analyzer, recompiler = (Path(config.get(key, "")) for key in ("ps2_analyzer", "ps2_recompiler"))
    if not analyzer.is_file() or not recompiler.is_file():
        return {"status": "tools_missing", "reason": "Configurare ps2_analyzer e ps2_recomp nelle Impostazioni."}
    work.mkdir()
    tools_manifest = {name: {"path": str(tool.resolve()), "sha256": hashlib.sha256(tool.read_bytes()).hexdigest()}
                      for name, tool in (("analyzer", analyzer), ("recompiler", recompiler))}
    (work / "tools.json").write_text(json.dumps(tools_manifest, indent=2), encoding="utf-8")
    # Fixed relative paths also avoid upstream TOML escaping issues for user paths.
    import shutil
    shutil.copyfile(boot, work / "input.elf")
    timeout = int(config.get("timeout", 900))
    progress("PS2: individuazione delle funzioni con PS2Recomp", 60)
    run_tool([analyzer.resolve(), "input.elf", "config.toml"], work, work / "analyzer.log", timeout, check)
    configuration = work / "config.toml"
    if not configuration.is_file() or configuration.stat().st_size > 16 * 1024 * 1024:
        raise RuntimeError("PS2Recomp non ha prodotto una configurazione valida.")
    original = configuration.read_text(encoding="utf-8")
    (work / "analyzer-original.toml").write_text(original, encoding="utf-8")
    # Preserve discovered bindings and patches, but bound parallelism and paths.
    values = {"input": '"input.elf"', "output": '"output/"',
              "low_memory_mode": "true", "output_worker_threads": "1"}
    for key, value in values.items():
        pattern = rf"(?m)^{key}\s*=.*$"
        if re.search(pattern, original):
            original = re.sub(pattern, lambda _: f"{key} = {value}", original)
        else:
            original = original.replace("[general]", f"[general]\n{key} = {value}", 1)
    original, entry_hints = apply_entry_hints(original, work / "input.elf", work)
    from ps2_codegen_fixes import restore_data_stores
    original, data_stores = restore_data_stores(original, work / "input.elf")
    (work / "data-stores.json").write_text(json.dumps(data_stores, indent=2) + "\n", encoding="utf-8")
    configuration.write_text(original, encoding="utf-8")
    progress("PS2: traduzione sperimentale MIPS → C++", 75)
    run_tool([recompiler.resolve(), "config.toml"], work, work / "recompiler.log", timeout, check)
    from ps2_codegen_fixes import repair
    codegen_fixes = repair(work / "input.elf", work / "output", check)
    from ps2_returns import recover
    returns = recover(work / "input.elf", work / "output", check)
    sources = [p for p in (work / "output").rglob("*.cpp") if p.stat().st_size]
    if not sources:
        raise RuntimeError("Il motore è terminato senza produrre sorgenti C++.")
    return {"status": "sources_generated", "cpp_files": len(sources),
            "codegen_fixes": codegen_fixes,
            "recovered_return_entries": returns["count"],
            "observed_entry_hints": entry_hints["addresses"],
            "directory": "ps2-recomp", "playable": False,
            "reason": "Codice da collegare al runtime PS2Recomp e adattare al gioco. Grafica, audio, IOP/VU, overlay e chiamate indirette richiedono verifiche."}


def analyze_disc(path, directory, config, check, progress, save):
    mode = config.get("ps2_mode", "recompile")
    if mode not in ("recompile", "sources", "existing_ports"):
        raise ValueError("Modalità PS2 non riconosciuta.")
    project = {"schema": 1, "platform": "PS2", "status": "inspecting", "playable": False,
               "backend": "https://github.com/ran-j/PS2Recomp", "limitations": []}
    save(project)
    disc = Disc(path, check)
    try:
        progress("PS2: lettura indice ISO9660 e SYSTEM.CNF", 15)
        volume, entries = disc.inventory()
        (directory / "ps2-disc.json").write_text(json.dumps({"volume": volume, "entries": entries}, indent=2), encoding="utf-8")
        files = {e["path"].upper(): e for e in entries if not e["directory"]}
        cnf = files.get("SYSTEM.CNF")
        if not cnf or cnf["size"] > 65536:
            raise ValueError("SYSTEM.CNF PS2 assente o non valido; nessuna conversione avviata.")
        system = disc.read(cnf["offset"], cnf["size"]).decode("ascii", errors="replace")
        match = re.search(r"(?im)^\s*BOOT2\s*=\s*cdrom0?:[/\\]+([^\r\n;]+)(?:;\d+)?\s*$", system)
        if not match:
            raise ValueError("BOOT2 PS2 non trovato in SYSTEM.CNF.")
        boot_name = match[1].strip().replace("\\", "/").upper()
        boot = files.get(boot_name)
        if not boot:
            raise ValueError("L’eseguibile BOOT2 indicato da SYSTEM.CNF non è presente nel disco.")
        header = elf_info(disc.read(boot["offset"], min(52, boot["size"])))
        serial_match = re.fullmatch(r"([A-Z]{4})_(\d{3})\.(\d{2})", boot_name.rsplit("/", 1)[-1])
        serial = f"{serial_match[1]}-{serial_match[2]}{serial_match[3]}" if serial_match else None
        extracted = directory / "ps2-extracted"
        extracted.mkdir()
        boot_file = extracted / "boot.elf"
        progress("PS2: estrazione dell’eseguibile principale", 35)
        digest = disc.extract(boot, boot_file)
        project.update(status="analysis_ready", serial=serial, volume=volume, boot_path=boot_name,
                       boot_sha256=digest, elf=header, file_count=len(files),
                       boot_file="ps2-extracted/boot.elf", system_cnf=system)
        project["limitations"].append("Traduzione del solo BOOT2. Asset inventariati; eseguibili secondari, IRX e overlay non vengono convertiti automaticamente.")
        project["limitations"].append("PS2Recomp usa qui l’analizzatore automatico: per giochi privi di simboli può servire una mappa funzioni Ghidra corretta manualmente.")
        if serial == "SLUS-21678" and mode == "existing_ports":
            project["native_profile"] = {"id": "tenkaichi3-usa", "url": BT3_URL,
                                         "status": "setup_missing", "verified_disc": False}
        save(project)
    finally:
        disc.close()
    # Prefer the existing native port for its exact title/version. The upstream
    # setup performs the disc-content checks; a matching serial alone is not proof.
    if project.get("serial") == "SLUS-21050" and mode == "existing_ports":
        from burnout3 import prepare
        progress("Burnout 3: verifica della build e preparazione del port esistente", 55)
        profile = prepare(path, project, config)
        project["native_profile"] = profile
        if profile["status"] == "ready_to_launch":
            project.update(status="native_prepared", mode="existing_native_port", backend=profile["url"])
            project["limitations"] = ["Port Burnout 3 upstream v0.3.0-alpha. Su Linux è eseguito tramite Wine/Proton. Avvio esplicito dal pulsante; nessuna nuova compilazione in questo percorso."]
            save(project)
            return project
        save(project)
    setup_value = config.get("bt3_setup", "")
    if project.get("native_profile", {}).get("id") == "tenkaichi3-usa" and setup_value:
        setup = Path(setup_value).expanduser().resolve(strict=True)
        expected_name = "Tenkaichi3Decomp-setup" + (".exe" if os.name == "nt" else "")
        if setup.name != expected_name or not setup.is_file():
            raise ValueError(f"Selezionare {expected_name} dalla release ufficiale completa.")
        profile = project["native_profile"]
        profile.update(status="installing", directory=str(setup.parent))
        save(project)
        progress("Tenkaichi 3: verifica ISO e preparazione del port nativo", 60)
        run_tool([setup, "--install", path], setup.parent, directory / "ps2-port-setup.log",
                 int(config.get("timeout", 900)), check)
        executable = setup.parent / ("Tenkaichi3Decomp.exe" if os.name == "nt" else "Tenkaichi3Decomp")
        if not executable.is_file():
            raise RuntimeError("Setup terminato, ma eseguibile del port nativo assente.")
        profile.update(status="prepared_unverified", executable=str(executable),
                       validation="Setup upstream terminato con codice 0; gameplay non verificato.")
        project.update(status="native_prepared", mode="existing_native_port", backend=BT3_URL)
        project["limitations"] = ["Usato il port precompilato Tenkaichi3Decomp; nessuna nuova decompilazione o compilazione del gioco. Il gioco non è stato avviato."]
    else:
        project["mode"] = "experimental_recompilation"
        project["recompilation"] = {"status": "running"}
        save(project)
        project["recompilation"] = generate_sources(boot_file, directory / "ps2-recomp", config, check, progress)
        project["status"] = project["recompilation"]["status"]
        if mode == "recompile" and project["status"] == "sources_generated":
            from recompile import build_ps2
            project["mode"] = "new_native_build"
            def save_build(state):
                project["build"] = state
                project["status"] = state["status"]
                save(project)
            project["build"] = build_ps2(directory, config, check, progress, save_build, iso_path=path)
            project["status"] = project["build"]["status"]
            project["recompilation"]["reason"] = "C++ generato dal BOOT2. Esito della compilazione nel campo build e nei log native-build/."
            project["limitations"].extend(project["build"]["limitations"])
    save(project)
    return project

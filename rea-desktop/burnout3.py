"""Explicit launch adapter for the existing Burnout 3 Windows port.

Linux uses the user's Wine/Proton executable. This is not a native Linux build
and does not change the upstream alpha's stability classification.
"""
import hashlib
import os
from pathlib import Path
import shlex
import subprocess

BOOT_SHA256 = "e118dba952bf9fde6a04ee284bb1f06fa0bb49c9e04bbe762af1039dcc443c66"
PORT_SHA256 = "bb920710336fcdf96b2eade90bf0bad68e2c7df7cdbb782886872e22f8fc848f"
URL = "https://github.com/danielgomesvieira2000/burnout3-pc/releases/tag/v0.3.0-alpha"


def configuration(config):
    executable = Path(config.get("burnout3_executable", "")).expanduser()
    if not executable.is_file():
        raise ValueError("Configurare burnout3.exe della release ufficiale v0.3.0-alpha nelle Impostazioni.")
    if hashlib.sha256(executable.read_bytes()).hexdigest() != PORT_SHA256:
        raise ValueError("Il profilo richiede burnout3.exe ufficiale v0.3.0-alpha. Questa build ha un’impronta diversa.")
    wine = None
    if os.name != "nt":
        wine = Path(config.get("proton_wine", "")).expanduser()
        if not wine.is_file():
            raise ValueError("Su Linux configurare l’eseguibile wine di Wine/Proton. Il port è Windows.")
        wine = wine.resolve()
    return executable.resolve(), wine


def windows_path(path):
    return str(path) if os.name == "nt" else "Z:" + str(path).replace("/", "\\")


def command(iso, config):
    executable, wine = configuration(config)
    work = Path(config["output"]).expanduser().resolve() / "native-ports/burnout3-usa"
    work.mkdir(parents=True, exist_ok=True)
    card = work / "memcard"
    card.mkdir(exist_ok=True)
    argv = ([str(wine)] if wine else []) + [str(executable), "--disc", windows_path(iso),
            "--memcard", windows_path(card), "--window", "--gpu", "--audio", "--timeout", "315360000"]
    env = os.environ.copy()
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
    else:
        env.pop("LD_LIBRARY_PATH", None)
    if wine:
        env.update(WINEPREFIX=str(work / "proton-prefix"), WINEDEBUG="-all", WINEESYNC="0", WINEFSYNC="0")
    return argv, env, work


def prepare(iso, project, config):
    profile = {"id": "burnout3-usa", "title": "Burnout 3: Takedown", "url": URL,
               "status": "unavailable", "upstream_version": "0.3.0-alpha",
               "execution": "Windows nativo" if os.name == "nt" else "Port Windows tramite Wine/Proton su Linux",
               "verified_disc": False}
    if project.get("boot_sha256") != BOOT_SHA256:
        profile.update(status="incompatible_build", reason="Seriale riconosciuto, ma eseguibile PS2 diverso dalla build supportata.")
        return profile
    profile["verified_disc"] = True  # exact BOOT2 build, not full disc integrity
    profile["validation_scope"] = "Impronta BOOT2; la giocabilità non viene verificata durante la preparazione."
    try:
        argv, env, work = command(iso, config)
    except (ValueError, OSError) as error:
        profile["reason"] = str(error)
        return profile
    launcher = work / ("avvia-burnout3.cmd" if os.name == "nt" else "avvia-burnout3.sh")
    if os.name == "nt":
        def quoted(value):
            if any(c in value for c in '\r\n"'):
                raise ValueError("Percorso non rappresentabile nel launcher Windows.")
            return '"' + value.replace('%', '%%') + '"'
        text = "@echo off\nsetlocal DisableDelayedExpansion\ncd /d " + quoted(str(work)) + "\n"
        text += " ".join(quoted(value) for value in argv) + " >burnout3.log 2>&1\n"
    else:
        text = "#!/usr/bin/env bash\nset -euo pipefail\n"
        text += "cd -- " + shlex.quote(str(work)) + "\n"
        for key in ("WINEPREFIX", "WINEDEBUG", "WINEESYNC", "WINEFSYNC"):
            text += f"export {key}={shlex.quote(env[key])}\n"
        text += "exec " + shlex.join(argv) + " >burnout3.log 2>&1\n"
    launcher.write_text(text, encoding="utf-8")
    if os.name != "nt":
        launcher.chmod(0o755)
    profile.update(status="ready_to_launch", directory=str(work), executable=argv[1] if os.name != "nt" else argv[0],
                   launcher=str(launcher))
    (work / "README.txt").write_text(
        "Burnout 3: Takedown USA — port esistente v0.3.0-alpha\n\n"
        "Avvia dall’app con Avvia Burnout 3 oppure esegui " + launcher.name + ".\n"
        "Linux usa Wine/Proton; questa non è una build nativa Linux.\n"
        "La prima apertura può richiedere tempo per creare il profilo Proton.\n"
        "Salvataggi: memcard/. Impostazioni: pc_settings.ini. Log: burnout3.log.\n"
        "Il port upstream resta alpha; la preparazione non certifica tutti i circuiti o la carriera.\n"
        "Fonte: " + URL + "\n", encoding="utf-8")
    return profile


def launch(iso, config):
    """Recheck the actual disc, rather than trusting commands in a loaded report."""
    from ps2 import Disc
    iso = Path(iso).expanduser().resolve(strict=True)
    disc = Disc(iso, lambda: None)
    try:
        _, entries = disc.inventory()
        boot = next((entry for entry in entries if entry["path"].upper() == "SLUS_210.50" and not entry["directory"]), None)
        if not boot or boot["size"] > 256 * 1024 * 1024:
            raise ValueError("Eseguibile Burnout 3 USA non trovato nel disco.")
        digest = hashlib.sha256()
        for offset in range(0, boot["size"], 1024 * 1024):
            digest.update(disc.read(boot["offset"] + offset, min(1024 * 1024, boot["size"] - offset)))
        if digest.hexdigest() != BOOT_SHA256:
            raise ValueError("L’eseguibile del disco non corrisponde alla build Burnout 3 supportata.")
    finally:
        disc.close()
    argv, env, work = command(iso, config)
    with (work / "burnout3.log").open("wb") as log:
        process = subprocess.Popen(argv, cwd=work, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
    return process, work

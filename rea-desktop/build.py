"""Build on the destination OS. Bundle an existing REA installation and Node."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parent


def build():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rea", required=True, type=Path, help="REA package root (already compiled)")
    parser.add_argument("--node", required=True, type=Path, help="Compatible Node executable for this OS")
    args = parser.parse_args()
    rea, node = args.rea.resolve(), args.node.resolve()
    if not (rea / "dist/mcp/main.js").is_file() or not node.is_file():
        parser.error("REA compilato e Node devono esistere.")
    if os.name == "nt" and not (rea / "native/windows/build/manifest.json").is_file():
        parser.error("Su Windows usare il pacchetto npm ufficiale, che include l’addon nativo, oppure compilarlo come da guida REA.")
    build_env = os.environ.copy()
    build_env["PYINSTALLER_CONFIG_DIR"] = str(ROOT / "build/pyinstaller-cache")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
                    "--name", "REA-Desktop", str(ROOT / "app.py")], cwd=ROOT, env=build_env, check=True)
    bundle = ROOT / "dist/REA-Desktop"
    runtime = bundle / "runtime"
    engine = runtime / "rea"
    engine.mkdir(parents=True, exist_ok=True)
    shutil.copy2(node, runtime / ("node.exe" if os.name == "nt" else "node"))
    for name in ("dist", "bridge", "scripts", "native", "third_party", "licenses", "skills",
                 "package.json", "LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "DISCLAIMER.md"):
        source = rea / name
        if source.is_dir():
            shutil.copytree(source, engine / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        elif source.is_file():
            shutil.copy2(source, engine / name)
    # Ask npm to resolve production dependencies; preserve its installed layout.
    candidates = [node.parent / "node_modules/npm/bin/npm-cli.js", node.parent.parent / "lib/node_modules/npm/bin/npm-cli.js"]
    npm = next((p for p in candidates if p.is_file()), None)
    if npm is None:
        parser.error("npm-cli.js non trovato accanto a Node: usare una distribuzione Node completa.")
    env = os.environ.copy()
    env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", "")
    resolved = subprocess.run([str(node), str(npm), "ls", "--omit=dev", "--omit=optional", "--parseable", "--all"],
                              cwd=rea, env=env, text=True, capture_output=True, check=True)
    dependencies = []
    installed_modules = rea.parent if rea.parent.name == "node_modules" else (
        rea.parent.parent if rea.parent.parent.name == "node_modules" else None
    )
    for line in resolved.stdout.splitlines():
        path = Path(line)
        if path == rea:
            continue
        if path.is_relative_to(rea):
            relative = path.relative_to(rea)
            if "node_modules" not in relative.parts:
                continue
            destination = engine / relative
        elif installed_modules and path.is_relative_to(installed_modules):
            # Published npm installs hoist dependencies beside rea-agents.
            # Keep that resolution level instead of flattening nested versions.
            destination = runtime / "node_modules" / path.relative_to(installed_modules)
        else:
            parser.error(f"Dipendenza esterna non impacchettabile: {path}")
        dependencies.append(str(destination.relative_to(runtime)))
        shutil.copytree(path, destination, dirs_exist_ok=True, symlinks=True)
    for name in ("README.md", "TECHNICAL.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "VERIFICATION.md"):
        shutil.copy2(ROOT / name, bundle / name)
    for name in ("app.py", "engine.py", "ps2.py", "ps2_returns.py", "ps2_codegen_fixes.py", "ps2_runtime_fixes.py", "ps2_iop_fixes.py", "ps2_sif_fixes.py", "ps2_spu_fixes.py", "ps2_input_fixes.py", "ps2_input_ui.py", "recompile.py", "burnout3.py", "build.py", "requirements.txt", "requirements-build.txt"):
        source_dir = bundle / "source"
        source_dir.mkdir(exist_ok=True)
        shutil.copy2(ROOT / name, source_dir / name)
    # Include locally built optional PS2 tools and their full source/licence.
    from engine import defaults
    ps2_config = defaults()
    raylib_source = Path(ps2_config.get("raylib_source", ""))
    if (raylib_source / "src/raylib.h").is_file():
        shutil.copytree(raylib_source, bundle / "source/raylib-5.5",
                        ignore=shutil.ignore_patterns(".git", ".github", "examples", "projects", "parser", "logo", "build"))
    if all(ps2_config[k] and Path(ps2_config[k]).is_file() for k in ("ps2_analyzer", "ps2_recompiler")):
        ps2_runtime = runtime / "ps2recomp"
        ps2_runtime.mkdir(exist_ok=True)
        for key in ("ps2_analyzer", "ps2_recompiler"):
            source = Path(ps2_config[key])
            shutil.copy2(source, ps2_runtime / source.name)
        ps2_source = ROOT.parent / "ps2recomp"
        if not (ps2_source / "LICENSE").is_file():
            parser.error("Sorgenti e licenza PS2Recomp mancanti per la distribuzione dei motori.")
        shutil.copytree(ps2_source, bundle / "source/ps2recomp", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", "out", "__pycache__"))
        shutil.copy2(ps2_source / "LICENSE", ps2_runtime / "LICENSE")
        # Statically linked dependencies retain their notices.
        for dependency in (ps2_source / "out/build/_deps").glob("*-src"):
            for pattern in ("LICENSE*", "COPYING*", "COPYRIGHT*", "LICENCE*"):
                for notice in dependency.rglob(pattern):
                    if notice.is_file():
                        destination = ps2_runtime / "licenses" / dependency.name / notice.relative_to(dependency)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(notice, destination)
        with tarfile.open(bundle / "source/ps2recomp-dependencies.tar.gz", "w:gz") as archive:
            for dependency in (ps2_source / "out/build/_deps").glob("*-src"):
                archive.add(dependency, arcname=dependency.name,
                            filter=lambda entry: None if ".git" in Path(entry.name).parts else entry)
    node_license = node.parent / "LICENSE" if os.name == "nt" else node.parent.parent / "LICENSE"
    if node_license.is_file():
        shutil.copy2(node_license, runtime / "NODE-LICENSE")
    import PySide6
    qt_licenses = Path(PySide6.__file__).parent / "Qt" / "licenses"
    if qt_licenses.is_dir():
        shutil.copytree(qt_licenses, bundle / "licenses/Qt", dirs_exist_ok=True)
    for name in ("LGPL-3", "GPL-3", "GPL-2"):
        license_file = Path("/usr/share/common-licenses") / name
        if license_file.is_file():
            (bundle / "licenses/Qt").mkdir(parents=True, exist_ok=True)
            shutil.copy2(license_file, bundle / "licenses/Qt" / name)
    # Preserve binding package notices even when wheels omit separate license files.
    for metadata in Path(PySide6.__file__).parent.parent.glob("*.dist-info/METADATA"):
        if metadata.parent.name.lower().startswith(("pyside6", "shiboken6")):
            (bundle / "licenses/Qt").mkdir(parents=True, exist_ok=True)
            shutil.copy2(metadata, bundle / "licenses/Qt" / (metadata.parent.name + ".txt"))
    manifest = {"platform": sys.platform, "python": sys.version, "rea_version": json.loads((rea / "package.json").read_text())["version"],
                "node_version": subprocess.check_output([str(node), "--version"], text=True).strip(),
                "dependencies": dependencies, "ghidra_bundled": False, "jdk_bundled": False}
    (bundle / "build-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nApp pronta: {bundle}")


if __name__ == "__main__":
    build()

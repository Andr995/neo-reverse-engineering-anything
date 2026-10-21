"""REA Desktop — Windows/Linux local drag-and-drop frontend."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time
import zipfile

import burnout3

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QStandardPaths, QTimer
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QListWidget, QListWidgetItem, QSplitter,
    QTabWidget, QPlainTextEdit, QProgressBar, QLineEdit, QDialog,
    QFormLayout, QDialogButtonBox, QSpinBox, QMessageBox, QComboBox, QScrollArea,
)

from engine import analyze, defaults, write_json

STATUS = {"completed": "Completata", "partial": "Parziale", "error": "Errore", "cancelled": "Interrotta"}
STYLE = """
QWidget { background:#10151f; color:#e3e9f4; font-family:'Segoe UI','DejaVu Sans',sans-serif; font-size:13px; }
QMainWindow, QDialog { background:#10151f; }
QLabel#title { font-size:28px; font-weight:700; color:#ffffff; }
QLabel#eyebrow { font-size:11px; letter-spacing:3px; color:#65dfbd; }
QLabel#subtle { color:#95a4bb; }
QLabel#drop { background:#172332; border:2px dashed #365b72; border-radius:12px; padding:26px; color:#b8f2e3; font-size:17px; }
QLabel#warning { background:#292519; color:#ebd090; border-radius:7px; padding:10px; }
QPushButton { background:#223147; border:1px solid #344762; border-radius:6px; padding:9px 15px; }
QPushButton:hover { background:#2e435e; }
QPushButton:disabled { color:#667285; background:#18212e; }
QPushButton#primary { background:#60d9b5; color:#0e2520; font-weight:700; border:0; }
QLineEdit, QSpinBox { background:#192332; border:1px solid #30435b; border-radius:5px; padding:7px; }
QListWidget, QPlainTextEdit { background:#131c29; border:1px solid #26364b; border-radius:6px; padding:7px; }
QPlainTextEdit { font-family:'Consolas','DejaVu Sans Mono',monospace; }
QListWidget::item { padding:10px 5px; border-bottom:1px solid #202e41; }
QListWidget::item:selected { background:#234b4b; color:#e5fff8; }
QTabWidget::pane { border:0; margin-top:8px; }
QTabBar::tab { background:#172231; color:#9bacbf; padding:10px 16px; border-bottom:2px solid transparent; }
QTabBar::tab:selected { color:#73e5c2; border-bottom:2px solid #73e5c2; }
QProgressBar { border:0; background:#243149; border-radius:4px; height:8px; text-align:center; }
QProgressBar::chunk { background:#60d9b5; border-radius:4px; }
QSplitter::handle { background:#10151f; width:12px; }
"""


def config_path():
    return Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)) / "settings.json"


def load_config():
    config = defaults()
    try:
        saved = json.loads(config_path().read_text(encoding="utf-8"))
        config.update({k: saved[k] for k in config if k in saved
                       and not (k in ("ghidra", "java_home", "ps2_analyzer", "ps2_recompiler") and saved[k] == "")})
    except (OSError, ValueError, TypeError):
        pass
    return config


def viewer():
    widget = QPlainTextEdit()
    widget.setReadOnly(True)
    widget.setFont(QFont("monospace", 11))
    return widget


def preview(path):
    with path.open("rb") as source:
        data = source.read(2 * 1024 * 1024 + 1)
    clipped = len(data) > 2 * 1024 * 1024
    text = data[:2 * 1024 * 1024].decode("utf-8", errors="replace")
    return text + ("\n\n[Anteprima limitata a 2 MiB. Il file completo è nella cartella del report.]" if clipped else "")


class Settings(QDialog):
    def __init__(self, config, parent):
        super().__init__(parent)
        self.setWindowTitle("Configurazione motori e analisi")
        self.resize(840, 700)
        layout = QVBoxLayout(self)
        note = QLabel("Scegli l’operazione sulle ISO PS2 e configura gli strumenti. I binari PC vengono solo analizzati.")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.fields = {}
        for key, label, folder in (("executable_output", "Destinazione eseguibili finali", True),
                                   ("node", "Eseguibile Node.js", False), ("rea", "REA · scripts/rea.mjs", False),
                                   ("ghidra", "Cartella Ghidra", True), ("java_home", "Cartella JDK (opzionale)", True),
                                   ("ps2_analyzer", "PS2 · ps2_analyzer", False),
                                   ("ps2_recompiler", "PS2 · ps2_recomp", False),
                                   ("ps2_source", "PS2 · sorgenti PS2Recomp", True),
                                   ("raylib_source", "PS2 · sorgenti raylib 5.5", True),
                                   ("cmake", "Eseguibile CMake", False),
                                   ("bt3_setup", "Tenkaichi3Decomp-setup (opzionale)", False),
                                   ("burnout3_executable", "Burnout 3 · burnout3.exe", False),
                                   ("proton_wine", "Linux · eseguibile wine di Wine/Proton", False),
                                   ("output", "Cartella report", True)):
            edit = QLineEdit(str(config[key]))
            if key == "executable_output":
                edit.setPlaceholderText("Vuoto: conserva l’eseguibile nella cartella del report")
                edit.setToolTip("Ogni compilazione crea una sottocartella distinta con eseguibile e file di avvio. La ISO resta al percorso originale.")
            self.fields[key] = edit
            row = QHBoxLayout()
            row.addWidget(edit)
            button = QPushButton("Sfoglia")
            button.clicked.connect(lambda checked=False, e=edit, d=folder: self.browse(e, d))
            row.addWidget(button)
            form.addRow(label, row)
        for key, label, minimum, maximum in (("timeout", "Timeout per operazione (secondi)", 30, 86400),
                                             ("build_timeout", "Timeout compilazione (secondi)", 30, 86400),
                                             ("build_jobs", "Processi di compilazione", 1, 8),
                                             ("max_functions", "Funzioni da analizzare (0 = tutte)", 0, 1000000)):
            spin = QSpinBox()
            spin.setRange(minimum, maximum)
            spin.setValue(int(config[key]))
            self.fields[key] = spin
            form.addRow(label, spin)
        mode = QComboBox()
        for label, value in (("Genera C++ e compila un nuovo eseguibile", "recompile"),
                             ("Genera soltanto i sorgenti C++", "sources"),
                             ("Usa port esistenti per i titoli supportati", "existing_ports")):
            mode.addItem(label, value)
        mode.setCurrentIndex(max(0, mode.findData(config.get("ps2_mode", "recompile"))))
        self.fields["ps2_mode"] = mode
        form.insertRow(0, "Operazione sulle ISO PS2", mode)
        optimization = QComboBox()
        optimization.addItem("Compilazione rapida (prestazioni ridotte)", "fast")
        optimization.addItem("Prestazioni bilanciate (build intermedia)", "balanced")
        optimization.addItem("Ottimizza le prestazioni (build più lenta)", "optimized")
        optimization.setCurrentIndex(max(0, optimization.findData(config.get("build_optimization", "fast"))))
        self.fields["build_optimization"] = optimization
        form.insertRow(1, "Compilazione PS2", optimization)
        fields_widget = QWidget()
        fields_widget.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(fields_widget)
        layout.addWidget(scroll)
        info = QLabel("Nuova compilazione PS2: richiede CMake, un compilatore C++20 e i sorgenti dei runtime. Una build riuscita non certifica il gioco.\nI port esistenti si usano solo nell’apposita modalità.\nBinari PC: analisi disponibile; ricompilazione sullo stesso sistema non ancora implementata.")
        info.setObjectName("subtle")
        info.setWordWrap(True)
        layout.addWidget(info)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse(self, edit, folder):
        value = QFileDialog.getExistingDirectory(self, "Scegli cartella", edit.text()) if folder else QFileDialog.getOpenFileName(self, "Scegli file", edit.text())[0]
        if value:
            edit.setText(value)

    def values(self):
        return {key: field.currentData() if isinstance(field, QComboBox) else
                field.value() if isinstance(field, QSpinBox) else field.text().strip()
                for key, field in self.fields.items()}


class AnalysisWorker(QThread):
    progress = Signal(str, int)
    directory_ready = Signal(str)
    result = Signal(dict)

    def __init__(self, path, config):
        super().__init__()
        self.path, self.config = path, dict(config)
        self.cancel = threading.Event()

    def run(self):
        try:
            self.result.emit(analyze(self.path, self.config, self.cancel, self.progress.emit,
                                    self.directory_ready.emit))
        except Exception as error:
            self.result.emit({"target": self.path, "status": "error", "error": str(error)})


class ExportWorker(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, directory, destination):
        super().__init__()
        self.directory, self.destination = Path(directory), Path(destination)

    def run(self):
        temporary = self.destination.with_suffix(self.destination.suffix + ".part")
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in self.directory.rglob("*"):
                    relative = path.relative_to(self.directory)
                    if (path.is_file() and not path.is_symlink()
                            and not {"javascript-input", "ps2-extracted"}.intersection(relative.parts)
                            and relative.as_posix() != "ps2-recomp/input.elf"
                            and relative.parts[:2] != ("native-build", "build")
                            and path not in (temporary, self.destination)):
                        archive.write(path, relative)
            temporary.replace(self.destination)
            self.done.emit(str(self.destination))
        except Exception as error:
            temporary.unlink(missing_ok=True)
            self.failed.emit(str(error))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.worker = None
        self.exporter = None
        self.pending = []
        self.current_item = None
        self.report = None
        self.active_report = None
        self.analysis_timer = QTimer(self)
        self.analysis_timer.setInterval(1000)
        self.analysis_timer.timeout.connect(self.refresh_running)
        self.closing = False
        self.game_process = None
        self.game_timer = QTimer(self)
        self.game_timer.setInterval(1000)
        self.game_timer.timeout.connect(self.check_game)
        self.setWindowTitle("REA Desktop · Analisi software")
        self.resize(1250, 850)
        self.setMinimumSize(860, 650)
        self.setAcceptDrops(True)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)
        header = QHBoxLayout()
        branding = QVBoxLayout()
        eyebrow = QLabel("LOCAL SOFTWARE INTELLIGENCE")
        eyebrow.setObjectName("eyebrow")
        branding.addWidget(eyebrow)
        title = QLabel("REA Desktop")
        title.setObjectName("title")
        branding.addWidget(title)
        subtitle = QLabel("Trascina il software. Esplora ciò che contiene.")
        subtitle.setObjectName("subtle")
        branding.addWidget(subtitle)
        header.addLayout(branding)
        header.addStretch()
        self.settings_button = QPushButton("Impostazioni")
        self.settings_button.clicked.connect(self.settings)
        header.addWidget(self.settings_button)
        layout.addLayout(header)
        self.warning = QLabel()
        self.warning.setObjectName("warning")
        self.warning.setWordWrap(True)
        layout.addWidget(self.warning)
        self.refresh_warning()
        self.drop = QLabel("↓  Trascina qui uno o più file\n.iso PS2 · .exe · .dll · ELF · .so · .asar · cartelle JavaScript")
        self.drop.setObjectName("drop")
        self.drop.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.drop)
        toolbar = QHBoxLayout()
        choose = QPushButton("Scegli file")
        choose.setObjectName("primary")
        choose.clicked.connect(self.choose_files)
        toolbar.addWidget(choose)
        folder = QPushButton("Cartella JavaScript / Electron")
        folder.clicked.connect(self.choose_folder)
        toolbar.addWidget(folder)
        load = QPushButton("Apri report")
        load.clicked.connect(self.open_report)
        toolbar.addWidget(load)
        toolbar.addStretch()
        self.stop = QPushButton("Interrompi")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.cancel)
        toolbar.addWidget(self.stop)
        layout.addLayout(toolbar)
        split = QSplitter()
        self.jobs = QListWidget()
        self.jobs.setMinimumWidth(220)
        self.jobs.currentItemChanged.connect(self.select_job)
        split.addWidget(self.jobs)
        self.tabs = QTabWidget()
        self.summary = viewer()
        self.summary.setPlainText("Pronto per l’analisi.\n\nOgni file genera un report locale con risultati e limiti.\n\n• Eseguibili nativi: funzioni, pseudocodice, assembly e riferimenti con Ghidra.\n• .NET: metadati, membri e CIL.\n• JavaScript/Electron: moduli e relazioni.\n\nIl programma analizzato non viene eseguito. Non viene usata un’API AI.\nIl recupero del sorgente originale non è garantito.")
        self.tabs.addTab(self.summary, "Panoramica")
        self.ps2_details = viewer()
        self.ps2_details.setPlainText("Trascina una ISO PS2 (ISO9660, settori 2048 byte).\n\nIn Impostazioni scegli: nuova compilazione, soli sorgenti oppure port esistenti.\nLa nuova compilazione traduce BOOT2 in C++ e lo collega al runtime PS2Recomp con CMake.\nGli errori restano nei log: nessuna sostituzione automatica con un port pronto.\nUna build riuscita non dimostra che il gioco funzioni.\nNessun gioco viene avviato automaticamente.")
        self.tabs.addTab(self.ps2_details, "Progetto PS2")
        functions = QWidget()
        function_layout = QVBoxLayout(functions)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca funzione o indirizzo…")
        self.search.textChanged.connect(self.filter_functions)
        function_layout.addWidget(self.search)
        function_split = QSplitter()
        self.functions = QListWidget()
        self.functions.currentItemChanged.connect(self.select_function)
        self.code = viewer()
        function_split.addWidget(self.functions)
        function_split.addWidget(self.code)
        function_split.setSizes([250, 600])
        function_layout.addWidget(function_split)
        self.tabs.addTab(functions, "Funzioni e codice")
        evidence_split = QSplitter()
        self.evidence = QListWidget()
        self.evidence.currentItemChanged.connect(self.select_evidence)
        self.evidence_text = viewer()
        evidence_split.addWidget(self.evidence)
        evidence_split.addWidget(self.evidence_text)
        evidence_split.setSizes([200, 650])
        self.tabs.addTab(evidence_split, "Dati e stringhe")
        self.log = viewer()
        self.log.setMaximumBlockCount(2000)
        self.tabs.addTab(self.log, "Attività")
        split.addWidget(self.tabs)
        split.setSizes([260, 900])
        layout.addWidget(split, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        footer = QHBoxLayout()
        self.status = QLabel("Pronto · tutto sul tuo computer")
        self.status.setObjectName("subtle")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.executable_folder = QPushButton("Mostra eseguibile compilato")
        self.executable_folder.setEnabled(False)
        self.executable_folder.clicked.connect(self.show_executable_folder)
        layout.addWidget(self.executable_folder)
        self.reveal = QPushButton("Cartella risultati")
        self.reveal.setEnabled(False)
        self.reveal.clicked.connect(self.show_folder)
        footer.addWidget(self.reveal)
        self.port_folder = QPushButton("Cartella port nativo")
        self.port_folder.setEnabled(False)
        self.port_folder.clicked.connect(self.show_port_folder)
        footer.addWidget(self.port_folder)
        self.play = QPushButton("Avvia Burnout 3")
        self.play.setEnabled(False)
        self.play.clicked.connect(self.launch_game)
        footer.addWidget(self.play)
        self.export = QPushButton("Esporta ZIP")
        self.export.setEnabled(False)
        self.export.clicked.connect(self.export_report)
        footer.addWidget(self.export)
        layout.addLayout(footer)

    def refresh_warning(self):
        missing = []
        for key, label in (("node", "Node.js"), ("rea", "REA")):
            if not Path(self.config[key]).is_file():
                missing.append(label)
        if missing:
            self.warning.setText("Configura " + ", ".join(missing) + " nelle Impostazioni per attivare l’analisi REA.")
        elif not self.config.get("ghidra"):
            self.warning.setText("Ghidra non configurato: l’analisi .NET e JavaScript è disponibile; per il pseudocodice nativo indica Ghidra nelle Impostazioni.")
        else:
            modes = {"recompile": "nuova compilazione C++", "sources": "soli sorgenti C++", "existing_ports": "port esistenti"}
            self.warning.setText("ISO PS2: " + modes.get(self.config.get("ps2_mode"), "nuova compilazione C++") +
                                 ". Binari PC: analisi, ricompilazione non disponibile. Configurazione modificabile in Impostazioni.")

    def settings(self):
        dialog = Settings(self.config, self)
        if dialog.exec() == QDialog.Accepted:
            self.config = dialog.values()
            try:
                config_path().parent.mkdir(parents=True, exist_ok=True)
                write_json(config_path(), self.config)
            except OSError as error:
                QMessageBox.warning(self, "Impostazioni", f"Impossibile salvare: {error}")
            self.refresh_warning()

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Seleziona il software", "", "Tutti i file (*)")
        self.enqueue(paths)

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Applicazione JavaScript / Electron")
        if path:
            self.enqueue([path])

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.enqueue([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()

    def enqueue(self, paths):
        for path in paths:
            item = QListWidgetItem(f"In coda · {Path(path).name}")
            item.setToolTip(path)
            self.jobs.addItem(item)
            self.pending.append((path, item))
        if self.worker is None:
            self.next_job()

    def next_job(self):
        if not self.pending or self.closing:
            self.stop.setEnabled(False)
            self.settings_button.setEnabled(True)
            if self.closing:
                self.close()
            return
        path, item = self.pending.pop(0)
        self.current_item = item
        self.jobs.setCurrentItem(item)
        item.setText(f"Analisi · {Path(path).name}")
        self.active_report = {"target": path, "status": "running", "phase": "Preparazione dell’analisi"}
        self.analysis_started = time.monotonic()
        item.setData(Qt.UserRole, dict(self.active_report))
        self.display_running(self.active_report)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status.setText("Preparazione dell’analisi")
        self.worker = AnalysisWorker(path, self.config)
        self.worker.directory_ready.connect(self.on_directory)
        self.worker.progress.connect(self.on_progress)
        self.worker.result.connect(self.on_result)
        self.worker.finished.connect(self.worker_finished)
        self.stop.setEnabled(True)
        self.settings_button.setEnabled(False)
        self.analysis_timer.start()
        self.worker.start()

    def on_directory(self, directory):
        self.active_report["directory"] = directory
        self.refresh_running()

    def display_running(self, report):
        self.report = report
        self.executable_folder.setEnabled(False)
        self.functions.clear()
        self.evidence.clear()
        self.code.clear()
        self.evidence_text.clear()
        self.ps2_details.setPlainText("Progetto in elaborazione. I file disponibili sono nella cartella risultati.")
        self.reveal.setEnabled(bool(report.get("directory")))
        self.port_folder.setEnabled(False)
        self.play.setEnabled(False)
        self.export.setEnabled(False)
        self.summary.setPlainText(self.running_text(report))

    def running_text(self, report):
        elapsed = int(time.monotonic() - self.analysis_started)
        lines = [f"In corso · {Path(report['target']).name}", "", report["phase"],
                 f"Tempo trascorso: {elapsed // 60} min {elapsed % 60} s",
                 "", "La barra indica le fasi del lavoro, non una stima del tempo rimanente.",
                 "La compilazione può richiedere diversi minuti senza nuovi messaggi."]
        if report.get("directory"):
            directory = Path(report["directory"])
            lines.extend(["", "Cartella risultati: " + str(directory)])
            for name in ("compiling.log", "configuring.log"):
                log = directory / "native-build" / name
                try:
                    with log.open("rb") as stream:
                        stream.seek(0, 2)
                        stream.seek(max(0, stream.tell() - 8192))
                        tail = stream.read(8192).decode("utf-8", errors="replace")
                    lines.extend(["", "Ultime righe del compilatore (possono restare invariate):", *tail.splitlines()[-8:]])
                    break
                except OSError:
                    continue
        return "\n".join(lines)

    def refresh_running(self):
        if self.active_report is None:
            return
        self.current_item.setData(Qt.UserRole, dict(self.active_report))
        if self.jobs.currentItem() is self.current_item:
            self.report = dict(self.active_report)
            self.reveal.setEnabled(bool(self.report.get("directory")))
            self.summary.setPlainText(self.running_text(self.report))

    def on_progress(self, message, percent):
        self.status.setText(message)
        self.progress.setRange(0, 0 if percent >= 86 else 100)
        if percent < 86:
            self.progress.setValue(percent)
        self.log.appendPlainText(message)
        if self.active_report is not None:
            self.active_report["phase"] = message
            self.refresh_running()

    def on_result(self, report):
        self.analysis_timer.stop()
        self.active_report = None
        self.progress.setRange(0, 100)
        item = self.current_item
        item.setData(Qt.UserRole, report)
        item.setText(f"{STATUS[report['status']]} · {Path(report['target']).name}")
        self.jobs.setCurrentItem(item)
        self.display_report(report)
        self.progress.setValue(100 if report["status"] == "completed" else 0)
        self.status.setText(f"{STATUS[report['status']]} · {Path(report['target']).name}")
        self.log.appendPlainText(self.status.text())

    def worker_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.next_job()

    def cancel(self):
        for path, item in self.pending:
            item.setText(f"Annullata · {Path(path).name}")
        self.pending.clear()
        if self.worker:
            self.worker.cancel.set()
            self.status.setText("Interruzione richiesta · chiusura della sessione in corso…")
        self.stop.setEnabled(False)

    def select_job(self, item, previous=None):
        if item and item.data(Qt.UserRole):
            report = item.data(Qt.UserRole)
            if report.get("status") == "running":
                self.display_running(report)
            else:
                self.display_report(report)

    def display_report(self, report):
        self.report = report
        executable = self.compiled_executable()
        self.executable_folder.setEnabled(executable is not None)
        self.executable_folder.setToolTip(str(executable) if executable else "Disponibile dopo una compilazione riuscita")
        self.functions.clear()
        self.evidence.clear()
        self.code.clear()
        self.evidence_text.clear()
        self.ps2_details.setPlainText(json.dumps(report["ps2"], ensure_ascii=False, indent=2)
                                      if "ps2" in report else "Nessun progetto PS2 in questo report.")
        directory = Path(report["directory"]) if report.get("directory") else None
        self.reveal.setEnabled(bool(directory))
        profile = report.get("ps2", {}).get("native_profile", {})
        self.port_folder.setEnabled(profile.get("status") in ("prepared_unverified", "ready_to_launch") and bool(profile.get("directory")))
        self.play.setEnabled(profile.get("id") == "burnout3-usa" and profile.get("status") == "ready_to_launch" and self.game_process is None)
        self.export.setEnabled(bool(directory) and self.exporter is None)
        if not directory:
            self.summary.setPlainText(report.get("error", "Report non disponibile"))
            return
        try:
            self.summary.setPlainText(preview(directory / "report.md"))
            for function in report.get("functions", []):
                item = QListWidgetItem(f"{function['name']}\n{function['address']} · {function['status']}")
                item.setData(Qt.UserRole, function)
                self.functions.addItem(item)
            for path in sorted(directory.glob("*.json")):
                item = QListWidgetItem(path.name)
                item.setData(Qt.UserRole, str(path))
                self.evidence.addItem(item)
            for path in (sorted(directory.glob("ps2-recomp/*.log")) + sorted(directory.glob("ps2-recomp/*.toml")) +
                         sorted(directory.glob("ps2-*.log")) + sorted(directory.glob("native-build/*.log")) +
                         sorted(directory.glob("native-build/*.json"))):
                item = QListWidgetItem(str(path.relative_to(directory)))
                item.setData(Qt.UserRole, str(path))
                self.evidence.addItem(item)
            if "ps2" in report:
                import itertools
                for path in itertools.islice((directory / "ps2-recomp/output").rglob("*.cpp"), 1000):
                    item = QListWidgetItem(f"C++ · {path.name}")
                    item.setData(Qt.UserRole, {"file": str(path.relative_to(directory))})
                    self.functions.addItem(item)
            self.filter_functions(self.search.text())
        except (OSError, KeyError, TypeError) as error:
            self.summary.setPlainText(f"Report incompleto o non leggibile: {error}")

    def filter_functions(self, value):
        for i in range(self.functions.count()):
            item = self.functions.item(i)
            item.setHidden(value.casefold() not in item.text().casefold())

    def select_function(self, item, previous=None):
        if not item or not self.report:
            return
        function = item.data(Qt.UserRole)
        relative = function.get("pseudocode_file") or function.get("file")
        if not relative:
            self.code.setPlainText(function.get("error", "Pseudocodice non disponibile"))
            return
        directory = Path(self.report["directory"]).resolve()
        path = (directory / relative).resolve()
        if directory not in path.parents:
            self.code.setPlainText("Percorso esterno al report rifiutato.")
            return
        try:
            self.code.setPlainText(preview(path))
        except OSError as error:
            self.code.setPlainText(str(error))

    def select_evidence(self, item, previous=None):
        if item:
            try:
                self.evidence_text.setPlainText(preview(Path(item.data(Qt.UserRole))))
            except OSError as error:
                self.evidence_text.setPlainText(str(error))

    def open_report(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Apri report.json", self.config["output"], "Report (report.json)")
        if filename:
            try:
                report = json.loads(Path(filename).read_text(encoding="utf-8"))
                if report.get("version") != 1 or report.get("status") not in STATUS or "target" not in report:
                    raise ValueError("Formato report non riconosciuto")
                report["directory"] = str(Path(filename).parent)
                item = QListWidgetItem(f"{STATUS[report['status']]} · {Path(report['target']).name}")
                item.setData(Qt.UserRole, report)
                self.jobs.addItem(item)
                self.jobs.setCurrentItem(item)
            except (ValueError, OSError, AttributeError) as error:
                QMessageBox.warning(self, "Report", str(error))

    def show_folder(self):
        if self.report:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.report["directory"]))

    def compiled_executable(self):
        if not self.report or not self.report.get("directory"):
            return None
        build = self.report.get("ps2", {}).get("build", {})
        if build.get("status") != "built_unverified" or not build.get("executable"):
            return None
        delivery = build.get("delivery", {})
        if delivery.get("status") == "copied" and delivery.get("executable"):
            delivered = Path(delivery["executable"])
            if delivered.is_absolute() and delivered.is_file():
                return delivered
        directory = Path(self.report["directory"]).resolve()
        executable = (directory / build["executable"]).resolve()
        if directory in executable.parents and executable.is_file():
            return executable
        return None

    def show_executable_folder(self):
        executable = self.compiled_executable()
        if executable:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(executable.parent)))
        else:
            QMessageBox.warning(self, "Eseguibile", "Eseguibile compilato non trovato. Controlla il report e i log di compilazione.")

    def show_port_folder(self):
        if self.report:
            directory = self.report.get("ps2", {}).get("native_profile", {}).get("directory")
            if directory and Path(directory).is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(directory))

    def launch_game(self):
        if not self.report or self.game_process is not None:
            return
        try:
            self.game_process, work = burnout3.launch(self.report["target"], self.config)
            self.play.setEnabled(False)
            self.game_timer.start()
            self.status.setText(f"Burnout 3 avviato · log e salvataggi in {work}")
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Avvio Burnout 3", str(error))

    def check_game(self):
        if self.game_process is None or self.game_process.poll() is None:
            return
        code = self.game_process.returncode
        self.game_timer.stop()
        self.game_process = None
        profile = self.report.get("ps2", {}).get("native_profile", {}) if self.report else {}
        self.play.setEnabled(profile.get("id") == "burnout3-usa" and profile.get("status") == "ready_to_launch")
        self.status.setText(f"Burnout 3 terminato · codice {code}. Dettagli in burnout3.log nella cartella del port.")

    def export_report(self):
        if not self.report or self.exporter:
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Esporta report", str(Path(self.config["output"]) / "rea-report.zip"), "Archivio ZIP (*.zip)")
        if filename:
            self.export.setEnabled(False)
            self.exporter = ExportWorker(self.report["directory"], filename)
            self.exporter.done.connect(lambda path: self.status.setText(f"Esportato: {path}"))
            self.exporter.failed.connect(lambda error: QMessageBox.warning(self, "Esportazione", error))
            self.exporter.finished.connect(self.export_finished)
            self.exporter.start()

    def export_finished(self):
        self.exporter.deleteLater()
        self.exporter = None
        self.export.setEnabled(bool(self.report and self.report.get("directory")))
        if self.closing and not self.worker:
            self.close()

    def closeEvent(self, event):
        if self.worker or self.exporter:
            self.closing = True
            self.cancel()
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("REA-Desktop")
    app.setApplicationName("REA-Desktop")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window()
    window.show()
    targets = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    if targets:
        QTimer.singleShot(0, lambda: window.enqueue(targets))
    if "--smoke-test" in sys.argv:
        QTimer.singleShot(500, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

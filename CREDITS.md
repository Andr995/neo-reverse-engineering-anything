# Autori originali e riconoscimenti

Neo Reverse Engineering Anything raccoglie l’interfaccia REA Desktop e le integrazioni sviluppate localmente su richiesta di Andrea. Il lavoro di integrazione, correzione e documentazione è stato assistito da OpenAI Codex. Non attribuiamo a questo progetto la creazione dei motori elencati qui sotto, né sosteniamo un’approvazione da parte dei loro autori.

| Progetto | Autori / organizzazione | Ruolo |
|---|---|---|
| [REA](https://github.com/morluto/rea) | morluto e contributori | CLI, MCP e provider di analisi |
| [PS2Recomp](https://github.com/ran-j/PS2Recomp) | ran-j e tutti i contributori del repository | Analizzatore, ricompilatore e runtime PS2/IOP |
| [raylib](https://github.com/raysan5/raylib) | Ramon Santamaria (@raysan5) e contributori | Grafica, finestra, input e audio host |
| [Ghidra](https://github.com/NationalSecurityAgency/ghidra) | National Security Agency e contributori | Disassemblaggio e decompilazione |
| [Qt for Python](https://www.qt.io/qt-for-python) | The Qt Company e contributori | PySide6/Shiboken6/Qt |
| [Python](https://www.python.org/) | Python Software Foundation e contributori | Linguaggio e runtime del frontend |
| [Node.js](https://github.com/nodejs/node) | Node.js contributors / OpenJS Foundation | Esecuzione del motore REA |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | PyInstaller contributors | Packaging dell’interfaccia |
| [FFmpeg](https://ffmpeg.org/) | FFmpeg developers | Decoder multimediale esterno |
| [PS2SDK](https://github.com/ps2dev/ps2sdk) | ps2dev e contributori | Riferimento per protocolli e ABI dei servizi PS2 |
| [Open PS2 Loader](https://github.com/ps2homebrew/Open-PS2-Loader) | Autori e contributori Open PS2 Loader | Riferimento al formato dei parametri e pulsanti Pad2 |
| [Tenkaichi3Decomp](https://github.com/z3xox/Tenkaichi3Decomp) | z3xox e contributori | Port esterno facoltativo |
| [burnout3-pc](https://github.com/danielgomesvieira2000/burnout3-pc) | danielgomesvieira2000 e contributori | Port esterno facoltativo |

I nomi dei manutentori non sostituiscono gli elenchi completi dei contributori, conservati nei progetti originali. Per PS2Recomp si conserva la revisione precisa invece di attribuire tutto il motore all’autore dell’ultimo commit.

## Riferimenti tecnici LOADFILE

Il bridge segue il formato dei pacchetti e il protocollo documentati dai sorgenti PS2SDK:

- [loadfile-common.h](https://github.com/ps2dev/ps2sdk/blob/master/common/include/loadfile-common.h)
- [Implementazione IOP loadfile](https://github.com/ps2dev/ps2sdk/blob/master/iop/system/loadfile/src/loadfile.c)
- [Client EE loadfile](https://github.com/ps2dev/ps2sdk/blob/master/ee/kernel/src/loadfile.c)

## Cosa aggiunge questa integrazione

GUI italiana, gestione coda/report, percorso ISO→progetto, build locale, destinazione configurabile, profili verificati per impronta, adattamenti runtime, configurazione dei controlli e test. I fix specifici non sono correzioni ufficiali dei progetti upstream.

Licenze e ambito della distribuzione: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Riferimento Pad2: [padhook.c di Open PS2 Loader](https://github.com/ps2homebrew/Open-PS2-Loader/blob/master/ee_core/src/padhook.c).

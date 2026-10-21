# Installazione completa

Esegui i comandi dalla radice della repository, salvo dove indicato. I motori sono opzionali: puoi installare solo quelli necessari. Questa cartella contiene sorgenti, non le dipendenze già installate.

## 1. Interfaccia

### Linux

Su Ubuntu/Mint, se mancano Python/venv o le librerie del backend Qt X11:

```bash
sudo apt install python3 python3-venv libxcb-cursor0 libxkbcommon-x11-0 libegl1
python3 -m venv .venv
.venv/bin/python -m pip install -r rea-desktop/requirements.txt
./avvia.sh
```

Python 3.12 è la versione di riferimento locale. Le dipendenze Qt aggiuntive dipendono dalla distribuzione e dalla sessione grafica. Per diagnosticare un plugin Qt mancante, esegui `QT_DEBUG_PLUGINS=1 ./avvia.sh` da terminale.

### Windows

Installa Python 3.12 x64 con il launcher `py`. Da PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r rea-desktop\requirements.txt
.\avvia.cmd
```

Non serve attivare la virtualenv né cambiare la ExecutionPolicy di PowerShell. Questa versione Windows richiede ancora una verifica sul sistema reale.

## 2. Analisi PC con REA

Installa Node e npm compatibili con REA 6.4.0. Il manifest accetta `^22.19.0 || ^24.11.0 || >=26.0.0`; la build locale ha usato Node 24.18.0.

```bash
npm install --prefix rea-runtime --omit=dev --omit=optional rea-agents@6.4.0
```

Su Windows puoi usare `npm.cmd`. L’installazione scarica il pacchetto e le dipendenze da npm. In **Impostazioni** configura:

| Campo | Valore |
|---|---|
| Node.js | Percorso assoluto di `node` / `node.exe` |
| REA | Percorso assoluto di `rea-runtime/node_modules/rea-agents/scripts/rea.mjs` |
| Ghidra | Cartella della propria installazione Ghidra 12.1.x |
| JDK | Cartella JDK 21 completa di `bin/java` e `bin/javac` |

Ghidra/JDK servono per l’analisi nativa, non per JavaScript/.NET o per il percorso PS2. Procurali dalle rispettive distribuzioni ufficiali per il tuo sistema. Sono supportate anche le variabili `GHIDRA_INSTALL_DIR` e `JAVA_HOME`.

Il supporto Ghidra Windows del REA utilizzato è sperimentale e limitato a PE x86/x64 su volumi locali NTFS. Per ELF usa Linux. L’analisi di PE su Linux non costituisce una verifica dell’app su Windows.

## Motori PS2

Servono Git, CMake 3.21+, compilatore C++20, sorgenti PS2Recomp e raylib 5.5. La configurazione di questo frontend produce eseguibili **x86-64 con AVX2**. Non è un percorso ARM né una build universale.

### Linux Ubuntu/Mint

```bash
sudo apt install git cmake build-essential pkg-config \
  libgl1-mesa-dev libx11-dev libxrandr-dev libxinerama-dev \
  libxcursor-dev libxi-dev libasound2-dev libudev-dev \
  zlib1g-dev libzstd-dev \
  libavcodec-dev libavformat-dev libavutil-dev libswresample-dev libswscale-dev
```

La prima configurazione dei motori può scaricare dipendenze upstream. Da questa repository:

```bash
git clone https://github.com/ran-j/PS2Recomp.git ps2recomp
git -C ps2recomp checkout 2c5fbb9389e11dd95693385969490c9e8e6f57b4
cmake -S ps2recomp -B ps2recomp/out/build -DCMAKE_BUILD_TYPE=Release \
  -DPS2X_BUILD_RUNTIME=OFF -DPS2X_BUILD_TEST=OFF -DPS2X_BUILD_STUDIO=OFF
cmake --build ps2recomp/out/build --config Release --target ps2_analyzer ps2_recomp -j 2
mkdir -p .tools
git clone https://github.com/raysan5/raylib.git .tools/raylib-5.5
git -C .tools/raylib-5.5 checkout c1ab645ca298a2801097931d1079b10ff7eb9df8
```

L’app cerca automaticamente questi percorsi. Se non li trova, apri le Impostazioni:

| Campo | Percorso relativo alla repository |
|---|---|
| Analizzatore PS2 | `ps2recomp/out/build/ps2xAnalyzer/ps2_analyzer` |
| Ricompilatore PS2 | `ps2recomp/out/build/ps2xRecomp/ps2_recomp` |
| Sorgenti PS2Recomp | `ps2recomp` |
| Sorgenti raylib | `.tools/raylib-5.5` |
| CMake | Eseguibile `cmake` installato sul sistema |

CMake abilita FFmpeg quando `pkg-config` trova **tutte** le librerie richieste. Verifica il campo `ffmpeg` in `native-build/build.json`; l’installazione delle librerie dopo una build richiede una nuova configurazione/build. Il solo decoder non garantisce il funzionamento del percorso MPEG del gioco.

### Windows

Installa Git, CMake e Visual Studio Build Tools con **Desktop development with C++**. Apri un terminale di sviluppo x64. Usa gli stessi commit e gli stessi comandi CMake; le righe seguenti sono singole righe per PowerShell:

```powershell
git clone https://github.com/ran-j/PS2Recomp.git ps2recomp
git -C ps2recomp checkout 2c5fbb9389e11dd95693385969490c9e8e6f57b4
cmake -S ps2recomp -B ps2recomp/out/build -DPS2X_BUILD_RUNTIME=OFF -DPS2X_BUILD_TEST=OFF -DPS2X_BUILD_STUDIO=OFF
cmake --build ps2recomp/out/build --config Release --target ps2_analyzer ps2_recomp -j 2
New-Item -ItemType Directory -Force .tools
git clone https://github.com/raysan5/raylib.git .tools/raylib-5.5
git -C .tools/raylib-5.5 checkout c1ab645ca298a2801097931d1079b10ff7eb9df8
```

Seleziona gli eseguibili `.exe`, eventualmente nelle sottocartelle `Release`. Avvia l’app dal terminale che rende disponibile il toolchain. La configurazione attuale **disabilita FFmpeg su Windows**. La costruzione e l’esecuzione su Windows restano non collaudate: non è sufficiente rinominare un binario Linux in `.exe`.

## 4. Impostazioni consigliate per provare il profilo PS2

- Operazione: **Genera C++ e compila un nuovo eseguibile**.
- Ottimizzazione: **Prestazioni bilanciate**. Il valore iniziale dell’app resta Compilazione rapida, per compatibilità con le impostazioni precedenti.
- Processi: inizia con **2**, oppure **1** se la RAM scarseggia.
- Timeout compilazione: predefinito **3600 secondi**, aumentabile.
- Cartella report: spazio sufficiente per ISO estratta, migliaia di C++ e oggetti intermedi.
- Destinazione eseguibili finali: una cartella scrivibile a tua scelta.

Non è indicato un requisito di RAM/spazio universale: dimensioni e costo della compilazione dipendono dal gioco e dall’analizzatore. Un timeout conserva i risultati intermedi; segui il `native-build/README.md` del progetto per riprendere manualmente.

## 5. Port esistenti facoltativi

La modalità **Usa port esistenti per i titoli supportati** è separata dalla ricompilazione. Configura la release completa di Tenkaichi3Decomp o burnout3-pc nelle Impostazioni. Questi port e i loro dati non sono inclusi. Il port Windows di Burnout può richiedere un Wine/Proton già installato su Linux; questo frontend non lo converte in un port Linux nativo.

Consulta gli autori upstream per i dischi/versioni accettati. Il seriale del disco da solo non prova la compatibilità, che viene verificata anche tramite impronte o setup del port.


# Sviluppo e verifiche

## Struttura

```
README.md                    panoramica, installazione e uso
CHANGELOG.md                 differenze rispetto allo sviluppo precedente
controlli.md                 comandi e rimappatura
CREDITS.md / licenses/        autori e licenze conservate
upstream-versions.json        dipendenze di riferimento
rea-desktop/
  app.py                     interfaccia PySide6
  engine.py                  provider REA e report
  ps2.py                     lettura ISO9660 e pipeline PS2
  recompile.py               progetto CMake, runner e consegna eseguibile
  ps2_returns.py             recupero controllato di ingressi di ritorno
  ps2_codegen_fixes.py        correzioni della traduzione per profilo
  ps2_*_fixes.py              adattamenti verificati del runtime
  ps2_input_ui.py             template dell’interfaccia dei controlli
  burnout3.py                 integrazione separata del port esistente
  build.py                   pacchetto PyInstaller per il sistema host
  test_*.py                  test unitari e integrazioni opzionali
  runtime_checks/            controlli C++ e diagnostica avanzata
  examples/native-fixture.c  campione sintetico per analisi
```

## Test unitari sulla copia sorgente

Dopo aver installato le dipendenze Python, dalla radice su Linux:

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s rea-desktop -p 'test_*.py' -v
QT_QPA_PLATFORM=offscreen .venv/bin/python rea-desktop/app.py --smoke-test
```

Su Windows:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m unittest discover -s rea-desktop -p 'test_*.py' -v
.\.venv\Scripts\python.exe rea-desktop\app.py --smoke-test
```

Alcune prove richiedono CMake/GCC, sorgenti upstream o integrazioni esplicite e vengono saltate quando mancano. I test non usano ISO commerciali. La suite della GUI non certifica che un gioco sia giocabile.

## Test dei motori e del runtime

Con i motori installati, da `rea-desktop` puoi abilitare le integrazioni con `REA_DESKTOP_INTEGRATION=1`, `REA_PS2_INTEGRATION=1`, `REA_BUILD_INTEGRATION=1` e, se hai il port esterno, `REA_BT3_INTEGRATION=1`. `verify_native.py` usa campioni sintetici costruibili da `examples/native-fixture.c`; `verify_ps2.py` crea una piccola ISO homebrew di prova.

`runtime_checks/check_inputs.py <native-build>` compila test contro gli oggetti di un progetto già generato e il suo decoder Pad2. `check_loadfile.py <native-build>` verifica il protocollo con un backend di test. `check_data_stores.py` richiede anche l’audit di rigenerazione `data-store-generation/changed.json`: non è un test generico eseguibile senza quel progetto. I restanti C++ sono harness di sviluppo, da collegare con il runtime coerente.

Questi controlli sono orientati al toolchain Linux GCC/Makefiles. `window_probe.py --help` e `profile_child.py --help` descrivono le prove controllate su un proprio processo grafico; non sono l’avvio ordinario del gioco. Nessuno degli artefatti commerciali necessari a tali prove è incluso.

## Costruire una distribuzione dell’app

Il pacchetto deve essere compilato **sul sistema di destinazione**. Dalla radice:

```bash
.venv/bin/python -m pip install -r rea-desktop/requirements-build.txt
.venv/bin/python rea-desktop/build.py --rea "$PWD/rea-runtime/node_modules/rea-agents" --node "$(command -v node)"
```

`build.py` richiede una distribuzione Node completa con `npm-cli.js` nel percorso previsto accanto a Node. Se la distribuzione di sistema usa una struttura diversa, passa l’eseguibile di una distribuzione Node completa. Il pacchetto REA deve contenere `dist/mcp/main.js` e le dipendenze installate. Per Windows serve anche l’addon nativo REA previsto dal controllo del builder.

Su Windows usa `.venv\Scripts\python.exe` e il percorso di `node.exe`. Il risultato è in `rea-desktop/dist/REA-Desktop`. Distribuisci **tutta** quella cartella; non soltanto l’eseguibile principale. Ghidra e JDK rimangono esterni.

Il builder include gli strumenti PS2 e i loro sorgenti se li trova nel layout documentato, con licenze e dipendenze della build. I port commerciali/giochi non vengono inclusi. Prima della pubblicazione verifica che il pacchetto contenga soltanto i file attesi e gli avvisi delle dipendenze effettive.

## Regole delle correzioni PS2

La pipeline verifica BOOT2 e hash dei sorgenti upstream prima di modificare la copia di build. Non rimuovere questi controlli per accettare versioni sconosciute. Un’istruzione omessa, una funzione non individuata o un servizio non implementato richiedono un caso riproducibile e un test di comportamento.

Le funzioni non supportate non devono essere dichiarate implementate restituendo indiscriminatamente successo. I report distinguono compilazione, esecuzione e giocabilità. Se il runtime stampa un errore ma restituisce 0, registrare comunque il fallimento della prova.

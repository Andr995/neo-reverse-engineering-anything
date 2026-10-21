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

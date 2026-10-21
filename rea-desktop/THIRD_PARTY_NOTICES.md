# Componenti, provenienza e licenze

Questa repository distribuisce il frontend e i suoi adattatori, non i pacchetti binari delle dipendenze. I sorgenti dei motori completi vengono acquisiti separatamente. I frammenti e adattamenti derivati dai runtime mantengono le condizioni dei rispettivi upstream: la licenza MIT del frontend non li rilascia sotto una licenza diversa.

| Componente | Licenza / avvisi di riferimento | Distribuzione in questa repository |
|---|---|---|
| REA Desktop, codice originale del frontend | [MIT](LICENSE), copyright REA Desktop contributors | Sorgenti Python, script e test |
| REA 6.4.0 | MIT, copyright 2026 morluto; [testo conservato](../licenses/REA-MIT.txt) | Integrazione, versione e riferimenti; motore separato |
| PS2Recomp | [GNU GPL v3](../licenses/PS2Recomp-GPL-3.0.md) | Adattamenti e frammenti per il runtime; motore completo separato |
| raylib 5.5 | zlib/libpng; [testo conservato](../licenses/raylib-LICENSE.txt), copyright Ramon Santamaria | Dipendenza separata |
| PySide6 / Shiboken6 / Qt | Avvisi LGPL-3.0 / GPL e altre condizioni applicabili dei pacchetti Qt | Dipendenze separate |
| Python | PSF e avvisi incorporati nella distribuzione | Dipendenza separata |
| Node.js | Licenza e avvisi terze parti della distribuzione Node | Dipendenza separata |
| PyInstaller | GPL con eccezione del bootloader per il packaging delle applicazioni | Strumento di build separato |
| Ghidra | Apache-2.0 e avvisi terze parti upstream | Dipendenza opzionale separata |
| FFmpeg | Licenze della specifica build FFmpeg e dei componenti abilitati | Librerie di sistema separate |
| Open PS2 Loader | Licenze dei file upstream consultati | Riferimento al protocollo Pad2; loader non incluso |
| PS2SDK | Licenze dei file upstream consultati | Riferimenti al protocollo; SDK non incluso |
| Tenkaichi3Decomp, burnout3-pc | Avvisi e licenze delle rispettive release | Port separati, non distribuiti |

## Runtime derivati e pacchetti binari

I moduli `ps2_runtime_fixes.py`, `ps2_iop_fixes.py`, `ps2_sif_fixes.py`, `ps2_spu_fixes.py`, `ps2_input_fixes.py` e i relativi template/test includono adattamenti per il codice PS2Recomp. Le parti derivate dal runtime sono soggette alla sua GPLv3. Conservare provenienza e testo GPL insieme a questi adattamenti.

`rea-desktop/build.py` conserva sorgenti/licenze dei motori che trova, gli avvisi delle dipendenze Node e le informazioni Qt. Prima di distribuire una build binaria occorre verificare i componenti effettivamente incorporati e conservare i relativi sorgenti e avvisi, incluse le modifiche: questa repository sorgente da sola non è il corredo completo di ogni possibile build del gioco.

Non sono inclusi dati, sorgenti tradotti o eseguibili commerciali di giochi, né BIOS PS2. I marchi e i nomi dei giochi appartengono ai rispettivi titolari.

Origini e revisioni: [upstream-versions.json](../upstream-versions.json). Autori: [CREDITS.md](../CREDITS.md).

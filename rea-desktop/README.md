# REA Desktop

Interfaccia locale italiana per analizzare programmi con REA e preparare progetti PS2 con PS2Recomp. Non usa API AI. Il nome della repository è Neo Reverse Engineering Anything; la finestra dell’app mantiene REA Desktop.

La guida completa della repository è nel [README principale](../README.md). Le istruzioni tecniche indipendenti sono in [TECHNICAL.md](TECHNICAL.md), lo stato delle verifiche in [VERIFICATION.md](VERIFICATION.md).

## Avvio dai sorgenti

Dalla cartella che contiene `rea-desktop`, su Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r rea-desktop/requirements.txt
bash rea-desktop/avvia.sh
```

Su Windows puoi invece creare `.venv` **dentro `rea-desktop`**, installare `requirements.txt` e usare `avvia.cmd` di questa cartella. Il launcher nella radice della repository supporta anche la virtualenv nella radice.

Per un pacchetto PyInstaller, conserva tutta `dist/REA-Desktop` e avvia `REA-Desktop` / `REA-Desktop.exe`. Node, REA ed eventuali motori PS2 sono inclusi solo se il pacchetto è stato costruito con tali dipendenze; Ghidra e JDK restano esterni.

## Uso

1. Apri **Impostazioni** e configura Node/REA, Ghidra/JDK per l’analisi nativa oppure PS2Recomp/CMake/raylib per PS2.
2. Imposta **Cartella report** e, se desiderata, **Destinazione eseguibili finali**.
3. Trascina il file o usa **Scegli file**. Per ISO scegli ricompilazione, soli sorgenti oppure port esistenti.
4. Leggi i risultati nelle schede e usa **Cartella risultati**. **Mostra eseguibile compilato** apre il risultato di una build riuscita.
5. **Apri report** riapre un `report.json`; **Interrompi** conserva i risultati parziali.

I report predefiniti sono nella cartella personale `REA-Reports`. La destinazione finale crea una sottocartella distinta per ogni nuova build; le vecchie copie non vengono aggiornate automaticamente.

## Controlli e prestazioni PS2

Il profilo aggiornato BURNOUT SLES-53506 offre una schermata iniziale Tastiera/Gamepad/Entrambi, rimappatura e salvataggio in `controlli.ini`. X o Spazio corrispondono alla Croce, Invio a Start, le frecce ai menu. La guida `controlli.md` viene scritta accanto all’eseguibile.

Seleziona **Prestazioni bilanciate** nelle Impostazioni per `-O1`/`/O1`; il runtime è compilato in Release. La modalità rapida rimane il valore predefinito e usa meno ottimizzazione del codice generato. Il timeout compilazione iniziale è 3600 secondi, con 2 processi.

Su Linux FFmpeg viene rilevato tramite pkg-config e incluso solo se tutte le librerie di sviluppo richieste sono presenti. Su Windows rimane disattivato.

## Limiti attuali

I binari PC vengono analizzati, non ricompilati automaticamente. Il pseudocodice non è il sorgente originale. ISO PS2 supportate: ISO9660 a settori 2048 byte; solo BOOT2 viene tradotto automaticamente. Il risultato usa x86-64/AVX2 e richiede runtime/dati originali.

Al 21 ottobre 2026, X conferma la lingua nel profilo verificato; il gioco si blocca successivamente nel percorso MPEG e termina con `EE invocation stack space exhausted`. Gara e giocabilità non sono verificate. La versione Windows non è collaudata.

L’esito di compilazione non è una certificazione di funzionamento. I port esterni Tenkaichi3Decomp/burnout3-pc sono integrazioni separate, non una conversione universale.

Crediti originali: morluto/REA, ran-j e contributori/PS2Recomp, Ramon Santamaria/raylib, Qt Company e contributori/PySide6, NSA e contributori/Ghidra. Vedi gli avvisi di terze parti per licenze e origini.

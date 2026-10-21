# Stato reale delle verifiche

Aggiornamento: **21 ottobre 2026**. Ambiente di sviluppo Linux x86-64; Windows non verificato. I log privati e i dati commerciali non fanno parte di questa repository.

## Profilo BURNOUT

Il profilo riguarda il disco identificato **SLES-53506** e il BOOT2 SHA-256:

```
f33f153b4903a3026a29937e0e4610f6cff8ebf24005ee078e2dc1fd9b8a5242
```

Il nome del file ISO non è un criterio di compatibilità. Non si deve confondere questo profilo con il port esterno Burnout 3 USA SLUS-21050.

### Evidenze disponibili

- Build C++ locale riuscita, codice generato a `-O1`, runtime Release, FFmpeg incluso.
- Menu lingua raggiunto; cambio lingua con direzioni e conferma con X verificati sul programma.
- UI di rimappatura: modifica X→B, salvataggio, riapertura e ripristino dei predefiniti verificati.
- Controlli C++ su configurazione, tastiera e decoder Pad2; bridge LOADFILE; ordinamento/scadenze dei thread IOP; scritture dati ripristinate.
- Confronto locale del menu iniziale: circa 115 → 35 secondi, campionamento immagini ogni 5 secondi.
- I test dei servizi verificano quei contratti, non il comportamento completo dell’hardware PS2.

### Blocco ancora presente

Dopo la conferma della lingua il thread principale attende MPEG. Nella prova con decoder FFmpeg incluso compare infine:

```
Error during program execution: EE invocation stack space exhausted
```

La prova termina dopo circa 253 secondi. Il codice di uscita 0 non equivale a successo. Non sono stati verificati gara, carriera, stabilità prolungata, audio completo o prestazioni durante il gioco.

**Stato: compilato e avviato; giocabilità non raggiunta.** Non viene offerta una certificazione universale dei giochi PS2.

## Test della repository

Il riepilogo della suite eseguita sulla copia pulita è in [TEST-RESULTS.md](TEST-RESULTS.md). I test che richiedono motori esterni non installati sono indicati come saltati, non come superati. Gli script di diagnostica avanzata richiedono un progetto nativo locale separato.

## Limiti della distribuzione

Questa è una repository di sorgenti. Non include ISO, BOOT2, IRX, C++ generato da giochi, salvataggi, report privati, Ghidra, JDK, Node, motori PS2 compilati o eseguibili dei giochi. Le dipendenze vengono installate separatamente con versioni e origini documentate.

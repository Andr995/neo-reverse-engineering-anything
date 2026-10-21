# Controlli nativi di sviluppo

Questi test non includono file di giochi. Richiedono un progetto `native-build` locale con gli stessi sorgenti e la stessa configurazione del profilo. Non è sufficiente installare PySide6.

- `check_inputs.py <native-build>`: configurazione comandi, tastiera e Pad2. Usa GCC/Makefiles, runtime e file generati del profilo.
- `check_loadfile.py <native-build>`: protocollo RPC LOADFILE con backend di prova.
- `check_data_stores.py <native-build>`: richiede l’audit della rigenerazione; confronta le effettive espressioni di scrittura generate.
- `window_probe.py --help`: avvio limitato di un proprio eseguibile, input sintetico e immagini del suo framebuffer.
- `profile_child.py --help`: diagnostica di un proprio processo avviato dallo script.

I file C++ restanti sono harness per servizi IOP/SIF, memoria, scheduler e SPU. Vanno collegati con il runtime corrispondente. Non costituiscono test della giocabilità completa.

Non vengono distribuiti gli script di manutenzione specifici della macchina originale, i percorsi privati dei report o i log delle ISO commerciali.

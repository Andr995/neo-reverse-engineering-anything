# Modifiche rispetto alle versioni precedenti

## 21 ottobre 2026 — raccolta dei fix e repository sorgente

Questa è una fotografia dello sviluppo, non una release dichiarata stabile o giocabile.

| Prima | Ora | Cosa resta da verificare / risolvere |
|---|---|---|
| Input incompleto nel profilo Pad2 del disco | Lettura host sulla finestra, snapshot per il runtime, adattatore Pad2; X/Spazio confermano la lingua | Gara, pad fisico, secondo giocatore, vibrazione |
| Comandi non configurabili all’avvio | UI Tastiera/Gamepad/Entrambi, rimappatura e `controlli.ini` | Altri titoli/profili |
| Scansioni continue della coda IOP inattiva | Cache della coda vuota e della prossima scadenza, invalidata quando cambia lo stato | Prestazioni in gara |
| Attesa di un servizio LOADFILE mancante dopo X | Bridge RPC `0x80000006`: versione, moduli e accessi alla memoria, con validazione dei buffer | Altre chiamate non implementate rimangono errori |
| Scritture dati eliminate nella traduzione | Ripristino controllato di 28 istruzioni originali; 26 presenti e verificate nel C++ di questa build | Altre mappe funzioni / revisioni |
| Codice generato senza ottimizzazione nella modalità rapida | Aggiunta modalità bilanciata `-O1` / `/O1`, runtime Release | Tempi/FPS reali di gioco |
| FFmpeg forzatamente escluso | Rilevamento delle librerie tramite pkg-config su Linux | Alimentazione del decoder nel percorso del gioco; Windows resta senza decoder |
| Build confuse con una conversione giocabile | Stato `built_unverified`, `playable=false`, limiti e risultati documentati | Superamento dell’attesa MPEG e dell’errore di stack EE |
| Materiale di sviluppo mescolato a report e build | Repository sorgente separata, `.gitignore`, licenze, guide e test | Dipendenze da installare separatamente |

Le correzioni preesistenti di memoria, stack, chiamate indirette, letture CD/DVD, moduli IOP, trasferimenti SIF e servizi audio rimangono nei moduli `ps2_*_fixes.py`. I sorgenti upstream sono verificati per hash e copiati nel progetto prima delle modifiche.

### Misura locale del caricamento

Nel confronto diagnostico sulla stessa macchina, la prima immagine corrispondente al menu lingua passa da circa **115 secondi** a circa **35 secondi**, con catture ogni 5 secondi. È una misura di quel punto di avvio, non un benchmark di FPS o una promessa su altri computer. La gara non è stata raggiunta.

### Regressioni e problemi aperti

Il test della build con FFmpeg conferma la lingua; successivamente il thread principale attende MPEG. Dopo circa 253 secondi l’esecuzione termina con `EE invocation stack space exhausted`. Il processo restituisce 0, ma questo non viene considerato un successo: il log contiene un errore runtime e non è stato raggiunto un menu di gioco utilizzabile.

## Evoluzione precedente

- Interfaccia locale per REA: drag & drop, coda, annullamento, dossier e report JSON/Markdown.
- Supporto ISO PS2: inventario ISO9660, estrazione BOOT2, generazione C++, CMake e destinazione finale configurabile.
- Separazione dei port preesistenti dal percorso di nuova compilazione.
- Profilo BURNOUT SLES-53506: adattamenti specifici e verificati sull’impronta del BOOT2, senza estenderli automaticamente a tutti i giochi.

Non è disponibile una cronologia completa di release pubbliche: questa repository nasce dalla raccolta pulita dello sviluppo locale.

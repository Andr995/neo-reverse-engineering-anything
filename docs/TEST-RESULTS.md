# Verifiche della raccolta sorgente

Data: **21 ottobre 2026**. Ambiente: Linux x86-64, Python 3.12, PySide6 6.10.2. Nessun collaudo Windows dichiarato.

| Verifica | Esito | Portata |
|---|---|---|
| Suite sulla copia pulita senza motori upstream | 63 test: **57 superati, 6 saltati**, nessun errore | Unit test e test dei componenti disponibili |
| Stessa suite nel workspace con sorgenti PS2Recomp | 63 test: **59 superati, 4 saltati**, nessun errore | Include verifica applicazione/hash dei fix sulla revisione upstream |
| Avvio GUI `--smoke-test`, Qt offscreen | Uscita 0 | Caricamento interfaccia, non un test interattivo completo |
| Test C++ configurazione comandi, tastiera, Pad2 | Superati contro il runtime aggiornato con FFmpeg | Configurazione e propagazione input, non pad fisico o giocabilità |
| Protocollo LOADFILE C++ | Superato | Pacchetti, argomenti, memoria, buffer e casi non supportati |
| Script shell | Sintassi valida | Launcher Linux |
| Sorgenti Python e link Markdown locali | Validati | Nessun artefatto privato o cache nella copia sorgente |

I test saltati nella copia pulita richiedono REA, PS2Recomp, un port esterno o l’abilitazione della build integrata. Non sono conteggiati come successi.

La compilazione del test Pad2 è stata adeguata a collegare le librerie FFmpeg quando il runtime le abilita. I controlli del runtime utilizzano un progetto locale separato: i suoi dati commerciali non vengono pubblicati.

L’esecuzione del gioco resta bloccata come descritto in [STATO.md](STATO.md). Nessuno di questi test autorizza a dichiarare la build definitivamente giocabile.

# Controlli del profilo PS2 aggiornato

Questi comandi riguardano il runtime del profilo BURNOUT SLES-53506 verificato. Non dimostrano compatibilità universale dei giochi.

## Schermata iniziale

Avvia `rea-recompiled` (Linux) o `rea-recompiled.exe` (Windows). Nella schermata **Scegli i comandi**:

1. Seleziona **Tastiera**, **Gamepad** oppure **Entrambi**.
2. Clicca il comando da cambiare e premi il tasto/pulsante desiderato.
3. Usa **Ripristina predefiniti** per annullare una mappatura sbagliata.
4. Premi **Salva e avvia**.

La configurazione viene scritta in `controlli.ini` accanto all’eseguibile; la cartella deve essere scrivibile. Per riconfigurare, chiudi e riapri l’eseguibile. Le assegnazioni duplicate vengono controllate dalla schermata.

| Tastiera predefinita | Comando PS2 |
|---|---|
| Frecce | Croce direzionale / menu |
| W A S D | Stick sinistro |
| I J K L | Stick destro |
| X oppure Spazio | Croce / conferma |
| C | Cerchio |
| Z | Quadrato |
| V | Triangolo |
| Q / E | L1 / R1 |
| 1 / 3 | L2 / R2 |
| Invio | Start |
| Tab oppure Shift destro | Select |
| Ctrl sinistro / destro | L3 / R3 |
| Esc | Chiude la finestra |

Il tasto **X della tastiera** corrisponde alla **Croce del controller PS2**. Acceleratore, freno e boost dipendono dalla mappatura scelta dentro il gioco.

## Gamepad

Collega un pad riconosciuto da raylib/sistema operativo e scegli Gamepad o Entrambi. I pulsanti possono essere rimappati; gli stick mantengono gli assi standard. In Entrambi, tastiera e pad agiscono sul **giocatore 1**. Il collaudo con un pad fisico non è stato eseguito per questa raccolta.

L’adattatore non implementa secondo giocatore, multitap o vibrazione Pad2. Le preferenze dei controlli sono separate dai salvataggi `mc0` e `mc1`.

## Se non risponde

Dai il focus alla finestra e controlla il dispositivo selezionato. Leggi `controlli.ini` o ripristina i predefiniti. Le vecchie build non acquisiscono le correzioni copiando solo questo documento: occorre il nuovo eseguibile.

La Croce è stata verificata nella selezione della lingua, ma il gioco si blocca più avanti nel percorso video. Premere altri tasti non risolve un thread fermo in attesa MPEG. Vedi [stato reale](docs/STATO.md).

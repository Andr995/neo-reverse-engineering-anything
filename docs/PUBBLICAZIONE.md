# Caricare la repository

La repository locale è preparata con sorgenti e documentazione. Non viene pubblicato automaticamente alcun contenuto su GitHub. Non sono inclusi la cronologia privata del workspace o dati di gioco.

## Primo commit

Da questa cartella, controlla i file preparati:

```bash
git status
git diff --cached --stat
```

Se la tua identità Git non è già configurata, imposta il tuo nome e la tua email (puoi usare quella noreply di GitHub). Poi:

```bash
git add .
git commit -m "Prepare Neo Reverse Engineering Anything source release"
```

Crea su GitHub una repository vuota, scegliendo tu se pubblica o privata; nome suggerito: `neo-reverse-engineering-anything`. Non far generare un secondo README o una seconda licenza. Collega l’indirizzo reale:

```bash
git remote add origin https://github.com/TUO-ACCOUNT/neo-reverse-engineering-anything.git
git push -u origin main
```

Sostituisci `TUO-ACCOUNT` con il tuo account. La cartella consegnata non ha un remote configurato né contiene credenziali. Il commit iniziale è lasciato alla tua identità Git.

## Contenuto da tenere fuori

`.gitignore` esclude ambienti virtuali, dipendenze scaricate, motori clonati, report, cache, build, immagini disco, salvataggi, eseguibili e preferenze. Non usare `git add -f` su queste cartelle per aggirare le esclusioni.

L’archivio ZIP sorgente consegnato a fianco della cartella contiene gli stessi sorgenti senza `.git`. È una copia pulita, non un’app portatile pronta da avviare senza installazione.

## Release successive

Aggiorna CHANGELOG, stato delle verifiche e revisioni upstream quando cambia il codice. Mantieni distinte le release sorgente e gli eventuali pacchetti binari Windows/Linux. Per i binari conserva dipendenze, sorgenti richiesti e avvisi secondo le licenze effettive; non pubblicare BOOT2, ISO, IRX estratti, salvataggi o C++ generato da giochi commerciali.

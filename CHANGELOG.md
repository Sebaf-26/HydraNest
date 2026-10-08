# Changelog

HydraNest è un fork di [momenbasel/timenest](https://github.com/momenbasel/timenest)
(server Time Machine su Samba + Avahi + Web UI) con le correzioni emerse
installandolo su Proxmox + Portainer.

## v0.2.1 — 2026-10-08

### Web UI
- Storage: la sezione SMART viene nascosta quando il container non vede un
  disco fisico (caso tipico su Proxmox/VM, dove la salute del disco si
  controlla dall'host). Rimosso il vecchio messaggio "SMART data
  unavailable" che parlava di Docker Desktop for Mac.

## v0.2.0 — 2026-10-08

### Web UI — nuove pagine in stile mockup
- **Overview** (al posto della Dashboard): ciambella di occupazione del
  disco (backup / altri dati / libero), stato di salute dei backup, Mac
  connessi, utenti con più spazio occupato rispetto alla quota, ultimi backup
  Time Machine.
- **Backups**: una scheda per ogni backup di Mac con modello, dimensione,
  numero e lista degli snapshot, stato di verifica, ultima scrittura.
- **Clients**: ogni Mac con online/offline, IP, ultima volta visto, ultimo
  backup e stato (aggiornato, backup in corso, in ritardo, mai fatto).
- **Quotas**: barra di utilizzo per utente, spazio libero, modifica della
  quota direttamente nella tabella, avviso se la somma delle quote supera il
  disco.
- Nuovo stile (sfondo a gradiente, card, accento ciano), pulsante
  **Refresh**, indicatore **Samba online/offline** reale (prima era fisso).
- Pagina Settings aggiornata per Portainer.

### Backend
- `timemachine.py`: legge i bundle Time Machine (`.sparsebundle` /
  `.backupbundle`), nome e modello del Mac, `SnapshotHistory.plist`, stato
  di verifica; dimensioni in cache per 2 minuti.
- `monitor.py`: interroga Samba ogni minuto (`smbstatus --json`, con
  fallback al vecchio formato) e salva quando ogni Mac è stato visto
  l'ultima volta in `DATA_PATH/web/clients.json`.
- "Ultimo backup" ora usa gli snapshot reali invece del file
  `.com.apple.timemachine.supported`.

## v0.1.3 — 2026-10-08

### Documentazione
- README riscritto per HydraNest: deploy con Portainer passo per passo,
  tabella delle variabili, gestione utenti, collegamento del Mac,
  troubleshooting (dalla guida Proxmox/Portainer) e tabella dei fix del fork.
- Rimosso il mockup promozionale di TimeNest (mostrava pagine che l'app non
  ha) e il materiale di lancio upstream (`docs/press`, `docs/SEO.md`,
  `docs/social-preview.png`).
- Screenshot rifatti dalla Web UI reale di HydraNest, incluso il popup Edit.

### Web UI
- Placeholder del campo username: `macbook-pro` invece del nome dell'autore
  originale.

## v0.1.2 — 2026-10-08

### Web UI
- Rebranding: la Web UI mostra "HydraNest" (sidebar, login, titoli delle
  pagine) invece di "TimeNest".
- La versione in sidebar viene da `__version__` invece di essere scritta a
  mano nel template (prima mostrava sempre v0.1.0).
- `server string` di Samba ora è `<SERVER_NAME> (HydraNest)`.

## v0.1.1 — 2026-10-08

### Deploy
- Un solo `docker-compose.yml` per `docker compose` e per Portainer: rimosso
  `docker-compose.portainer.yml`. Il compose usa le immagini precompilate
  `ghcr.io/sebaf-26/hydranest-*` (niente più sezioni `build:`) e i percorsi
  persistenti da `DATA_PATH` (default `./data`, su Portainer va messo
  assoluto, es. `/TRE_TB/timenest/data`).
- `install.sh` scarica le immagini invece di compilarle in locale;
  `CONTRIBUTING.md` spiega come costruirle a mano per lo sviluppo.

## v0.1.0 — 2026-10-08

Correzioni di Samba e della gestione utenti (vedi guida di troubleshooting
TimeNest su Proxmox/Portainer).

### Samba
- **smbd non partiva**: `--log-stdout` non esiste più da Samba 4.15 (Debian
  bookworm ha la 4.17). L'entrypoint ora usa `--debug-stdout` o
  `--log-stdout` in base a quello che supporta lo smbd installato.
- **Share non caricate (`NT_STATUS_BAD_NETWORK_NAME`)**: Samba non espande i
  wildcard in `include = /etc/timenest/shares.d/*.conf`. Il nuovo
  `sync-shares.sh` genera `/etc/samba/timenest-shares.conf` con un `include`
  esplicito per ogni `<utente>.conf`; viene eseguito all'avvio e a ogni
  creazione/modifica/cancellazione utente, seguito da un reload di smbd.
- **Utenti persi dopo un redeploy**: gli account POSIX vivevano solo nel
  filesystem effimero del container. All'avvio vengono ricreati per ogni
  utente presente in `shares.d` o nel passdb, con UID/GID presi dal
  proprietario di `/backup/<utente>` così i backup esistenti restano leggibili.
- **Template che sparivano**: i template ora stanno in `/usr/share/timenest`,
  quindi montare un volume su `/etc/timenest` non li nasconde più. Il compose
  monta solo `shares.d`.
- Con `SMB_INTERFACES` vuoto non viene più scritto `interfaces = lo`.
- Healthcheck del container samba basato su `pidof smbd` (lo
  `smbclient -L -N` anonimo veniva rifiutato da `restrict anonymous = 2`).

### Web UI
- **"Configured users: 0"**: nuova variabile `SHARES_PATH` (default
  `/config/shares.d`); il compose monta nello stesso path la directory
  `shares.d` scritta dal container samba.
- Nuovo pulsante **Edit** per utente: modifica quota e reset password
  (nuovo script `set-quota.sh`).

### Deploy
- `docker-compose.portainer.yml` con immagini precompilate e variabili
  `BACKUP_PATH` / `DATA_PATH`; nessun entrypoint patchato da montare.
- `DATA_PATH` (default `./data`) anche nel `docker-compose.yml`.
- Immagini pubblicate come `ghcr.io/sebaf-26/hydranest-{samba,avahi,web}`.
- Il workflow `release` (pkg macOS firmato su runner self-hosted upstream)
  non parte più sui tag; aggiunto test di integrazione Samba in CI.

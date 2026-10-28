# Changelog

HydraNest è un fork di [momenbasel/timenest](https://github.com/momenbasel/timenest)
(server Time Machine su Samba + Avahi + Web UI) con le correzioni emerse
installandolo su Proxmox + Portainer.

## v0.5.3 — 2026-10-28

### Web UI
- La pagina **Clients** si chiama **Macs** (voce del menu, titolo e indirizzo
  `/macs`); il vecchio indirizzo `/clients` porta alla nuova pagina.
- README: la tabella delle pagine descrive la nuova Overview e la pagina
  iPhone.

## v0.5.2 — 2026-10-28

### Sezione iPhone
- L'indirizzo Tailscale non ha più una scheda a sé in fondo alla pagina
  dell'iPhone: è la riga **Remote access** della card Backup, sotto
  Automatic cleanup, con stato (Reachable, Not reachable, Off), indirizzo e
  ultimo controllo. Si imposta o si cambia da una finestra («Set up…» /
  «Change…»), dove c'è anche «Turn off».

### Web UI
- Sotto il nome e la versione, in alto a sinistra: «forked from TimeNest &
  AirVault», con i link ai due progetti (AirVault solo se la sezione iPhone
  è attiva).

## v0.5.1 — 2026-10-28

### Overview riordinata
- **Storage Usage** divide i backup tra Mac (Time Machine) e iPhone: il
  cerchio mostra la quota di ciascuno, la legenda anche lo spazio libero e la
  percentuale usata.
- **Devices**: un'unica lista con tutti i Mac e gli iPhone (nome, modello,
  utente o iOS, online o ultima volta visto, ultimo backup, spazio e quota,
  stato). Sostituisce le card «Connected Macs» e «Top Users by Usage», che
  restano come pagine Clients e Quotas.
- **Recent Backups** mette insieme gli snapshot dei Mac e i backup degli
  iPhone, cinque righe.
- Backup Health non cambia.

## v0.5.0 — 2026-10-28

### Sezione iPhone dentro HydraNest
- **Un solo indirizzo e un solo login.** La pagina **iPhone** del menu mostra
  la sezione iPhone dentro HydraNest, con la barra laterale e l'intestazione
  di HydraNest: il server web fa da tramite verso il container iPhone
  (`/iphone/app/`) e ci entra da solo con `IPHONE_AUTH_TOKEN`. La barra in
  alto e il piè di pagina della parte iPhone si nascondono quando è dentro
  HydraNest. «Open in a new tab» apre la stessa interfaccia a tutta pagina,
  sempre senza un secondo login.
- **iPhone in Overview e Backups**, accanto ai Mac: nome, modello, iOS,
  collegamento, ultimo backup, spazio, restore point e stato; un clic apre la
  pagina dell'iPhone. Backup Health segnala anche gli iPhone senza backup da
  più di 7 giorni, l'ultimo backup fallito o il servizio iPhone non
  raggiungibile.
- `IPHONE_URL` ora è l'indirizzo del container iPhone visto dal container web
  (es. `http://192.168.20.10:8089`), e il container web riceve anche
  `IPHONE_AUTH_TOKEN`.
- Interfaccia iPhone: percorsi relativi (funziona sia da sola sia sotto
  `/iphone/app/`); i testi del backup automatico non dicono più «at home».

## v0.4.0 — 2026-10-28

### Sezione iPhone (nuova)
- Due servizi nuovi nello stack: `iphone` (immagine
  `ghcr.io/sebaf-26/hydranest-iphone`) e `tailscale` (immagine ufficiale).
  Il servizio iPhone è [AirVault](https://github.com/wizier/airvault)
  modificato, importato in `iphone/` con `git subtree`, sotto GPL-3.0; il
  resto di HydraNest resta MIT. Le modifiche sono elencate in
  `iphone/NOTICE.md`.
- **Indirizzo Tailscale per iPhone**: nella pagina di ogni iPhone il campo
  *Remote access (Tailscale)* accetta l'IP Tailscale o il nome MagicDNS. Il
  motore lo passa a netmuxd con `AddDevice` (UDID + IP) all'avvio, ogni
  minuto e subito dopo una modifica, così il backup parte anche fuori casa.
  Serve comunque un Wi-Fi qualsiasi: sui soli dati mobili iOS rifiuta la
  connessione (provato il 2026-10-28, iOS 27.2).
- Il container iPhone usa la rete del container Tailscale, che sta anche
  sulla macvlan della LAN degli iPhone: a casa la scoperta via Bonjour
  funziona come prima, anche con Tailscale spento sull'iPhone.
- Percorsi e variabili pensati per riprendere i dati di uno stack AirVault
  esistente (`IPHONE_CONFIG_PATH`, `IPHONE_BACKUP_PATH`): abbinamenti e
  backup restano.
- Interfaccia ribrandizzata HydraNest (nome, logo, colori, tema scuro).
- Immagine iPhone per amd64 e arm64 (netmuxd non ha una release armv7).

### Web UI
- Voce **iPhone** nel menu, che apre l'interfaccia del container iPhone;
  compare solo se `IPHONE_URL` è impostata.

### CI
- `docker.yml` costruisce e firma anche `hydranest-iphone`; `ci.yml` esegue
  `make check` di AirVault (golangci-lint, svelte-check, test Go).

## v0.3.0 — 2026-10-08

### Web UI
- **Storage Usage** (Overview) parla solo dei backup: il totale è lo spazio
  utilizzabile dai backup (backup + spazio libero), gli altri dati presenti
  sul volume non vengono più mostrati ("Other data" rimosso).
- Lo stato di salute e la pagina Quotas usano lo stesso calcolo ("Available
  for backups" al posto della capacità totale del disco).
- Rimossa la pagina **Storage** (e il codice SMART, `smartmontools` non è
  più installato nell'immagine web).

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
  assoluto, es. `/srv/hydranest/data`).
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

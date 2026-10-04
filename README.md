# Assistente scolastico locale

Prototipo di punto informazioni vocale basato su ESP32-S3 e servizi eseguiti
nella rete locale della scuola. Il dispositivo registra la domanda, la invia
al server, riceve una risposta vocale e la riproduce tramite un amplificatore
I2S. È disponibile anche un'interfaccia web.

## Flusso

1. L'ESP32 registra una domanda in WAV mentre il pulsante è premuto.
2. Whisper trascrive localmente l'audio.
3. Il server combina ricerca esatta, testuale, fuzzy e semantica.
4. Llama viene consultato soltanto per disambiguare i candidati.
5. Piper, oppure la voce di macOS, genera la risposta audio.
6. L'ESP32 scarica il WAV e lo riproduce sull'altoparlante.

Le ubicazioni e i percorsi provengono sempre dal database: il modello non può
inventare stanze o indicazioni.

## Struttura

```text
app/                         server HTTP e orchestratore
data/schema.sql              struttura del database SQLite
firmware/assistente_esp32/   firmware Arduino per il dispositivo
services/                    avvio di Whisper, embedding e Llama locali
web/                         interfaccia browser
bootloader-patch/            correzione riproducibile per flash XMC MFID 0x70
config.example.json          configurazione di esempio
start.sh                     avvio del server
```

## Requisiti

- Python 3;
- macOS con `ffmpeg`, oppure un servizio Piper compatibile, per la sintesi;
- una compilazione locale di `whisper.cpp` con `whisper-server`;
- llama.cpp opzionale, usato per embedding semantici e domande ambigue;
- Arduino IDE con supporto ESP32 per caricare il firmware.

## Modelli consigliati

La configurazione fornita è stata preparata per questi modelli locali:

| Funzione | Modello consigliato | Configurazione | Necessario |
|---|---|---|---|
| Trascrizione italiana | Whisper `base` multilingue | `ggml-base.bin` | Solo per usare il microfono |
| Ricerca semantica | Qwen3 Embedding 0.6B | `Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0` | No |
| Disambiguazione | MiniCPM5 2B | `openbmb/MiniCPM5-2B-GGUF:Q4_K_M` | No |

Whisper `base` è il compromesso consigliato per la demo tra velocità e qualità
della trascrizione in italiano. Su un computer poco potente si può usare
`tiny`; per privilegiare l'accuratezza si può provare `small`, accettando tempi
e consumo di memoria maggiori. Dopo aver scaricato un modello diverso, passare
il suo percorso allo script:

```bash
WHISPER_MODEL=/percorso/ggml-small.bin ./services/start-whisper.sh
```

Il modello embedding migliora le domande formulate indirettamente. MiniCPM5
interviene soltanto quando deve scegliere fra destinazioni già recuperate: non
genera autonomamente nomi di aule o percorsi. La prova testuale di base funziona
anche senza tutti e tre i modelli.

## Installazione delle dipendenze

Il server HTTP e la prova testuale usano soltanto la libreria standard di
Python: non esiste un `requirements.txt` e non occorre installare pacchetti
con `pip`.

### Installazione minima su macOS

Installare gli strumenti di compilazione e, tramite Homebrew, CMake e ffmpeg:

```bash
xcode-select --install
brew install cmake ffmpeg
```

`ffmpeg` serve per convertire in WAV la voce generata da macOS. Non è
necessario per la sola prova testuale.

### Whisper per la prova con il microfono

Gli script cercano per impostazione predefinita `whisper.cpp` nella cartella
`~/whisper.cpp` e il modello italiano/base in
`~/whisper.cpp/models/ggml-base.bin`:

```bash
cd ~
git clone https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
sh ./models/download-ggml-model.sh base
cmake -B build
cmake --build build --config Release -j --target whisper-server
```

Se Whisper è installato altrove, indicare la cartella al momento dell'avvio:

```bash
WHISPER_CPP_DIR=/percorso/whisper.cpp ./services/start-whisper.sh
```

### Llama ed embedding opzionali

I due servizi sono facoltativi. Gli script cercano l'eseguibile universale di
llama.cpp in `~/.local/bin/llama`; è possibile usare un'altra posizione con la
variabile `LLAMA_BINARY`. Dopo aver installato una versione compatibile di
llama.cpp, scaricare entrambi i modelli mentre è disponibile Internet:

```bash
~/.local/bin/llama download \
  --hf-repo "openbmb/MiniCPM5-2B-GGUF:Q4_K_M"
~/.local/bin/llama download \
  --hf-repo "Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0"
```

Gli script li avviano poi con l'opzione `--offline`, quindi durante il normale
utilizzo non accedono a servizi cloud. Per la versione e le istruzioni di
installazione aggiornate consultare il progetto ufficiale
[llama.cpp](https://github.com/ggml-org/llama.cpp).

## Configurazione del server

Creare la configurazione locale:

```bash
cp config.example.json config.json
```

Modificare, se necessario, gli indirizzi dei servizi. Se si cambia
`llama_api_key`, avviare Llama passando lo stesso valore nella variabile
`LLAMA_API_KEY`. `config.json` è ignorato da Git.

Al primo avvio il server crea automaticamente `data/school.db` e inserisce
cinque ambienti dimostrativi. Il database generato è ignorato da Git.

## Prova locale senza ESP32

L'ESP32 non è necessario per provare il progetto. L'interfaccia web permette
di verificare prima il server, la ricerca delle destinazioni e, se Whisper è
attivo, anche l'intero ciclo vocale usando il microfono del computer.

### Prova testuale minima

Questa modalità richiede soltanto Python 3 e non richiede Whisper, Llama,
embedding o firmware:

```bash
cp config.example.json config.json
./start.sh
```

Aprire `http://127.0.0.1:8000` nel browser e scrivere, per esempio:

```text
Dove si trova la segreteria?
Come arrivo in palestra?
Dove posso prendere un libro?
```

Al primo avvio viene creato automaticamente il database dimostrativo. La
ricerca per nome, alias, numero d'aula e somiglianza testuale funziona anche se
gli altri servizi risultano «Da collegare». La risposta viene letta dalla voce
del browser quando la sintesi locale non è disponibile.

### Prova vocale dal computer

Per parlare anziché scrivere, avviare prima Whisper in un terminale:

```bash
./services/start-whisper.sh
```

In un secondo terminale avviare il server:

```bash
./start.sh
```

Aprire `http://127.0.0.1:8000`, consentire al browser l'accesso al microfono,
tenere premuto il pulsante **Premi per parlare**, pronunciare la domanda e
rilasciarlo. Whisper trascrive la registrazione, il server cerca la
destinazione e il browser riproduce la risposta. Su macOS, se è installato
`ffmpeg`, il server può generare l'audio con la voce di sistema; altrimenti usa
la sintesi vocale del browser.

Il pannello di stato della pagina indica quali servizi sono attivi. Llama e il
servizio embedding non sono necessari per questa prova di base: si possono
aggiungere in seguito per verificare domande indirette e casi ambigui.

## Inserire un nuovo locale

Avviare almeno una volta il server, in modo che venga creato
`data/school.db`, quindi arrestarlo con `Ctrl+C`. Aprire il database con il
programma `sqlite3`:

```bash
sqlite3 data/school.db
```

Al prompt di SQLite incollare un'istruzione come questa, sostituendo i dati
d'esempio:

```sql
INSERT INTO locations (
    canonical_name,
    aliases,
    building,
    floor,
    room,
    directions,
    accessible_directions,
    notes,
    description,
    services,
    keywords,
    example_questions
) VALUES (
    'Laboratorio di chimica',
    'chimica|laboratorio chimico|lab chimica',
    'Edificio principale',
    'Secondo piano',
    'Aula 210',
    'Dall’ingresso raggiungi le scale centrali, sali al secondo piano e gira a destra.',
    'Usa l’ascensore accanto alla segreteria, sali al secondo piano e gira a destra.',
    'Accesso consentito soltanto con un docente.',
    'Laboratorio usato per esperimenti e lezioni di chimica.',
    'esperimenti|analisi|lezioni di chimica',
    'chimica|reagenti|laboratorio|esperimenti',
    'Dove si fanno gli esperimenti?|Dov’è il laboratorio di chimica?'
);
.quit
```

Nei campi `aliases`, `services` ed `example_questions` separare le alternative
con il carattere `|`. Compilare sempre indicazioni normali e accessibili con
informazioni reali; lasciare una stringa vuota `''` soltanto per i campi non
pertinenti.

Riavviare poi `./start.sh`. All'avvio il server ricostruisce l'indice testuale;
se il servizio embedding è attivo, calcola automaticamente anche il vettore
del nuovo locale. Verificare dal browser con il nome ufficiale, almeno un alias
e una domanda indiretta.

Per correggere un locale esistente:

```sql
UPDATE locations
SET room = 'Aula 212', floor = 'Secondo piano'
WHERE canonical_name = 'Laboratorio di chimica';
```

Per nasconderlo senza cancellarne i dati:

```sql
UPDATE locations SET active = 0
WHERE canonical_name = 'Laboratorio di chimica';
```

Eseguire le modifiche a server spento e conservarne una copia di sicurezza.
Il file `data/school.db` contiene i dati specifici della scuola ed è escluso da
Git; `data/schema.sql` contiene invece soltanto la struttura del database.

## Avvio dei servizi opzionali

Avviare Whisper in un terminale:

```bash
./services/start-whisper.sh
```

Llama è opzionale e può essere avviato in un secondo terminale:

```bash
./services/start-llama.sh
```

Per comprendere anche domande indirette, avviare il servizio embedding in un
altro terminale:

```bash
./services/start-embeddings.sh
```

Il modello embedding deve essere scaricato una volta prima dell'avvio offline:

```bash
~/.local/bin/llama download \
  --hf-repo "Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0"
```

Gli embedding vengono conservati in SQLite e rigenerati soltanto per gli
ambienti modificati. Senza questo servizio rimangono disponibili ricerca per
nome, alias, numero d'aula e somiglianza testuale.

Per avviare il server e usare il browser sullo stesso computer:

```bash
./start.sh
```

Aprire `http://127.0.0.1:8000`.

Per rendere il server raggiungibile dall'ESP32 nella rete locale:

```bash
./start.sh --host 0.0.0.0
```

Limitare l'accesso con il firewall o con la VLAN dell'istituto prima di usare
questa modalità su una rete condivisa.

## Configurazione dell'ESP32

Nella cartella `firmware/assistente_esp32`:

```bash
cp wifi_secrets.example.h wifi_secrets.h
cp device_config.example.h device_config.h
```

Inserire in `wifi_secrets.h` nome e password della rete. In
`device_config.h` inserire l'indirizzo IP del computer che esegue il server.
I due file sono ignorati da Git.

Aprire `assistente_esp32.ino` nell'Arduino IDE e caricarlo sulla scheda.

### Pin utilizzati

| Componente | Pin ESP32-S3 |
|---|---|
| Pulsante | GPIO15 e GND |
| Microfono SCK, WS, SD | GPIO4, GPIO5, GPIO6 |
| Amplificatore DIN, BCLK, LRC | GPIO16, GPIO17, GPIO18 |

Il microfono deve essere alimentato a 3,3 V. L'uscita negativa del MAX98357A
non è una massa e non deve essere collegata a GND.

## API

- `GET /api/health`: stato dei servizi;
- `GET /api/locations`: ambienti attivi;
- `POST /api/query`: domanda testuale;
- `POST /api/transcribe`: trascrizione audio;
- `POST /api/speak`: sintesi vocale;
- `POST /api/device/respond`: ciclo completo per il dispositivo fisico.

## Ricerca ibrida e chiarimenti

Ogni ambiente contiene anche descrizione, servizi, parole chiave e domande di
esempio. Il server combina numeri e nomi esatti, SQLite FTS5, somiglianza
testuale ed embedding. Llama può scegliere soltanto fra i candidati recuperati;
edificio, piano e percorso arrivano sempre dal database. Se due risultati sono
troppo vicini, l'API restituisce `clarification_required` e la pagina mostra i
pulsanti fra cui scegliere.

Per eseguire i test automatici:

```bash
python3 -m unittest discover -s tests -v
```

## Privacy

Il sistema non contiene tracker e non richiede servizi cloud durante l'uso. Le
domande non vengono salvate nel database. Llama riceve soltanto il testo della
domanda e i candidati recuperati; ubicazioni e percorsi provengono sempre da
SQLite.

## Nota sul bootloader XMC

La cartella `bootloader-patch` riguarda esclusivamente le schede interessate
dall'errore `XMC flash startup fail`. Non applicare la patch senza aver prima
verificato l'identificativo della memoria flash.

## Stato del prototipo

Sono stati verificati individualmente bootloader, microfono, pulsante,
amplificatore, registrazione in PSRAM, Wi-Fi e trascrizione Whisper. Il codice
del ciclo completo, inclusi sintesi vocale, download e riproduzione della
risposta, è presente; è consigliato un collaudo end-to-end sul montaggio finale.

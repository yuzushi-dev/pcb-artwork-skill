# PCB Artwork Skill: completare geometria, clipping e verifica

**Data:** 30 settembre 2026  
**Repository:** `yuzushi-dev/pcb-artwork-skill`  
**Baseline:** `main`, commit `8357fe2ccfced14915921b065d2ee495e97406d7`  
**Stato:** specifica di implementazione. Revisione statica di file selezionati; nessun test KiCad, DRC o Gerber eseguito.  
**Destinazione suggerita:** `docs/plans/geometry-pipeline.md`

## 1. Risultato da ottenere

Portare la pipeline da un piano di artwork a una copia del PCB che rispetti gli ostacoli geometrici supportati, conservi il progetto elettrico e produca un rapporto di verifica riproducibile. Il modello deve continuare a descrivere la composizione in un formato intermedio; il codice deve decidere dove può esistere la serigrafia.

Questa iterazione riguarda il compilatore locale, la qualità dell'output e i test. Non comprende un viewer web, un plugin ChatGPT, nuove funzioni di computer use, generazione del circuito o modifica dei footprint. Non richiede un nuovo modello o accesso API.

La prima release deve dichiarare un perimetro geometrico preciso. Un costrutto non supportato che incide sull'area stampabile deve bloccare la compilazione: non basta riportare un avviso e produrre un file dall'aspetto valido.

## 2. Gap verificati nel codice

`inspect_board.py` conta gli oggetti con espressioni regolari; non estrae pad, forature o contorni. `clip_artwork.py` legge il PCB senza usarne la geometria, converte alcune primitive e registra `keepout_parser: "not-yet-implemented"`. Il parametro di clearance finisce nei metadati, senza una sottrazione degli ostacoli. [^R1]

Lo stesso script lascia passare l'hatching senza espanderlo, mentre `patch_kicad.py` accetta soltanto poligoni. Inoltre il compilatore serializza il solo contorno esterno: aggiungere una sottrazione geometrica senza gestire gli anelli interni rischierebbe di riempire di nuovo le aperture create dal clipping. [^R1] [^R2]

Lo schema corrente non vincola a sufficienza dimensioni, campi obbligatori per primitiva e cardinalità delle coordinate. I due test in `tests/test_geometry.py` verificano operazioni Shapely isolate; non dimostrano il corretto percorso PCB → keepout → serigrafia. [^R3] [^R4]

Il patcher individua marcatori testuali, cerca l'ultima parentesi e scrive il risultato. Non dimostra che il PCB compilato corrisponda a quello usato per il clipping e non verifica l'invarianza degli oggetti elettrici. La presente revisione non accerta il comportamento di ogni file del repository. [^R2]

## 3. Architettura da implementare

```text
PCB sorgente + artwork.json + profilo geometrico
                 |
                 v
parsing strutturale e validazione degli input
                 |
                 v
geometria globale per lato + provenienza delle trasformazioni
                 |
                 v
espansione primitive -> clipping -> gestione dei fori
                 |
                 v
artefatto compilato legato agli hash degli input
                 |
                 v
patch su copia -> nuova lettura -> controlli invarianti
                 |
                 v
verifiche KiCad/Gerber + rapporto con esiti distinti
```

Usare `skills/pcb-artwork/` come sorgente canonica della logica distribuita. Per le copie a livello root scegliere una sola strategia: wrapper sottili oppure sincronizzazione controllata. Preferire wrapper per gli script e un controllo di uguaglianza per gli asset che devono restare copiati. Non mantenere due implementazioni manuali.

### 3.1 Introdurre parsing strutturale con un perimetro esplicito

Aggiungere un parser S-expression che riconosca stringhe quotate, escape, annidamento e intervalli nel testo sorgente. Valutare una libreria mantenuta prima di scriverlo; registrare dipendenza, versione e licenza nella PR. Il parser deve imporre limiti di dimensione e profondità e segnalare input troncati o malformati.

La scelta progettuale è **leggere la struttura senza riscrivere tutto il PCB**. Conservare gli intervalli originali per il patcher; usare KiCad come controllo indipendente del risultato, non come passaggio che risalva senza distinzione ogni oggetto.

Leggere il token di versione del file e congelare una versione KiCad di destinazione nella matrice dei test. Il formato documenta una struttura S-expression e un identificatore di versione; questi elementi non garantiscono che un parser nuovo supporti ogni revisione. [^K1]

Per il primo insieme supportato includere pad circolari, rettangolari, ovali e rettangolari arrotondati, fori circolari e asolati, trasformazioni dei footprint, contorni rettilinei e archi. Pad custom, forme smussate o altri costrutti non implementati devono produrre un errore nominativo con posizione e tipo. Estendere il supporto solo insieme a fixture di confronto.

### 3.2 Calcolare la geometria effettiva per lato

Convertire coordinate di pad e footprint in coordinate globali, includendo rotazione, offset delle forature e appartenenza ai layer. Per il retro verificare le trasformazioni contro un export KiCad: non applicare una specchiatura intuitiva che potrebbe duplicare quella già rappresentata nel file.

Risolvere le aperture della solder mask attraverso le impostazioni effettive: override del pad, impostazioni del footprint e impostazioni della scheda. Il formato KiCad documenta questi livelli e distingue margini della maschera, forme dei pad e forature. Una clearance del rame non equivale a una distanza richiesta alla serigrafia. [^K2]

Il modello geometrico intermedio deve conservare, per ogni ostacolo, tipo, lato, origine nel file e regola che lo ha generato. Proteggere aperture della maschera, forature e altre regioni richieste dal profilo. Non trattare tutto il rame coperto dalla maschera come superficie vietata senza una regola esplicita.

Ricostruire il contorno della scheda come area chiusa, con ritagli interni. Segmenti scollegati, auto-intersezioni, contorni aperti e geometrie ambigue devono bloccare il risultato. Il riconoscimento dei ritagli deve dipendere dalla topologia dei loop, non da un solo rettangolo di ingombro.

Per gli archi definire un errore massimo di approssimazione nel profilo numerico. Rendere conservativa l'approssimazione: sovrastimare gli ostacoli e sottostimare l'area disponibile. Verificare le distanze dopo arrotondamento e serializzazione; una tolleranza numerica non deve concedere una violazione della clearance.

### 3.3 Rafforzare lo schema ed espandere le primitive

Mantenere il formato di input separato dal formato compilato. Per l'input v1 aggiungere vincoli per tipo: coordinate finite bidimensionali, almeno tre vertici per un poligono, almeno due punti per una polilinea, quattro valori per una regione e spessori positivi. Rifiutare identificatori duplicati, numeri non finiti, campi incompatibili e geometrie degeneri.

Verificare i piani già pubblici prima di irrigidire lo schema. Se un cambiamento rompe un input v1 valido, documentare una migrazione o introdurre una versione nuova; non cambiare il significato del numero di versione in silenzio.

Espandere rettangoli, polilinee e hatching in geometrie prima del clipping. Per l'hatching generare barre nel sistema locale della regione, ruotarle, intersecarle con la regione richiesta e assegnare ID deterministici. Definire l'unità e il significato di `spacing_mm`, verificando la convenzione usata dalle istruzioni attuali. Zero o valori negativi devono fallire prima del ciclo di generazione.

Introdurre limiti configurati per numero di primitive, vertici e barre. Un input che supera il budget deve produrre un errore leggibile, non un'elaborazione illimitata. Conservare la mappa fra primitiva originale e frammenti generati.

### 3.4 Eseguire il clipping senza perdere topologia

Per ciascun lato calcolare:

```text
area_disponibile = area_scheda_con_ritagli ridotta del margine al bordo
ostacoli = unione delle aree protette espanse della distanza richiesta
serigrafia_finale = (artwork espanso ∩ area_disponibile) − ostacoli
```

Il valore `0.16 mm` presente negli esempi è un parametro esistente, non una garanzia di producibilità per ogni fornitore. Il profilo deve specificare distanze, unità e origine dei requisiti. Se il progetto non fornisce vincoli produttivi, riportare la limitazione nel rapporto. [^R5]

Gestire `Polygon`, `MultiPolygon` e le componenti risultanti da `GeometryCollection`. Classificare residui di dimensione inferiore e geometrie vuote; non scartarli senza una voce nel rapporto. Un artwork interamente rimosso deve avere un esito esplicito, distinto da una compilazione utile completata.

Conservare i fori interni. Se la rappresentazione scelta per KiCad richiede poligoni semplici, decomporre ogni area con fori in pezzi senza fori. Una triangolazione deve essere vincolata oppure seguita da intersezione e verifica: non basta triangolare l'inviluppo esterno. Controllare che l'unione dei pezzi equivalga all'area da serializzare entro la tolleranza dichiarata e che nessun pezzo invada gli ostacoli.

Rifiutare riparazioni geometriche che alterano la composizione senza un resoconto. Per frammenti troppo sottili o piccoli, consentire una rimozione solo tramite una policy esplicita, con area e primitive coinvolte nel report. Se non esiste un controllo di larghezza affidabile per una forma, segnalare il controllo come non completato.

### 3.5 Legare l'output agli input e proteggere il file originale

Aggiungere uno schema compilato separato, proposto come `pcb-artwork-compiled/v1`. Deve contenere hash del PCB sorgente e dell'artwork, versione del compilatore, profilo e tolleranze, lato, poligoni risultanti, provenienza dei frammenti e stato dei controlli. Il patcher deve accettare solo uno stato compatibile con la produzione del file di revisione.

Prima della patch ricalcolare l'hash del PCB. Una differenza deve bloccare l'operazione: una board modificata dopo il clipping richiede una nuova compilazione. Proteggere anche il caso in cui l'output risolva sullo stesso file tramite symlink o hardlink. Scrivere su un temporaneo nella directory di destinazione e promuoverlo dopo i controlli, senza sovrascrivere la sorgente.

Modificare soltanto gli oggetti generati e identificati dalla pipeline. Conservare byte e ordine degli oggetti non gestiti, poi confrontarne anche una rappresentazione strutturale. La verifica deve comprendere footprint, pad, segmenti, vias, zone, reti, forature, bordo e serigrafia preesistente. Il solo confronto dei conteggi non basta.

Rendere la gestione degli oggetti generati indipendente per `F.SilkS` e `B.SilkS`: un aggiornamento del retro non deve cancellare il fronte. Associare ID stabili e un manifest di proprietà agli oggetti creati. Mantenere compatibilità con i marcatori esistenti solo quando risultano univoci. Se un salvataggio in KiCad elimina i marcatori, riconoscere gli oggetti tramite identità e contenuto atteso oppure fermarsi; non aggiungere copie alla cieca.

Il patcher deve essere idempotente sullo stesso input. Riaprire e verificare il file finale dopo la serializzazione, non soltanto la geometria in memoria.

## 4. File da modificare o aggiungere

| File o area | Stato | Lavoro |
|---|---|---|
| `skills/pcb-artwork/scripts/inspect_board.py` | Esistente, letto | Conservare i conteggi utili; aggiungere inventario strutturato e stato di supporto |
| `skills/pcb-artwork/scripts/clip_artwork.py` | Esistente, letto | Collegare parser, primitive, ostacoli e compilatore |
| `skills/pcb-artwork/scripts/patch_kicad.py` | Esistente, letto | Hash degli input, proprietà degli oggetti, scrittura atomica e invarianti |
| `skills/pcb-artwork/schemas/artwork.schema.json` | Esistente, letto | Validazione per tipo e controlli semantici complementari |
| `skills/pcb-artwork/lib/board_geometry.py` | Nuovo proposto | Coordinate, aperture, forature e bordo |
| `skills/pcb-artwork/lib/primitives.py` | Nuovo proposto | Espansione deterministica, incluso hatching |
| `skills/pcb-artwork/lib/compiler.py` | Nuovo proposto | Clipping, topologia, decomposizione e rapporto |
| `skills/pcb-artwork/lib/board_invariants.py` | Nuovo proposto | Confronto prima/dopo e verifica della patch |
| `skills/pcb-artwork/schemas/compiled.schema.json` | Nuovo proposto | Contratto fra compilatore e patcher |
| `tests/fixtures/boards/` | Nuova proposta | Board sintetiche pubblicabili e risultati attesi |
| `tests/test_pipeline.py` | Nuovo proposto | Percorso completo, incluso pacchetto installabile |
| `scripts/verify_bundle.py` | Nuovo proposto | Controllo copie/wrapper e dipendenze distribuite |

Creare gli eventuali file di package Python necessari e provare l'importazione da una copia della sola skill, fuori dal checkout. Non affidarsi al fatto che la root del repository sia presente nel percorso di import.

## 5. Piano per pull request

| PR | Contenuto | Evidenza richiesta |
|---|---|---|
| P1 | Schema, fixture, rilevazione dei casi non supportati | I casi oggi ingannevoli falliscono con un errore esplicito |
| P2 | Parser, coordinate globali e ostacoli per lato | Confronto delle fixture con geometria/export KiCad |
| P3 | Hatching, clipping, fori e decomposizione | Area e distanze verificate dopo serializzazione |
| P4 | Patcher sicuro, proprietà degli oggetti e idempotenza | Nessun oggetto non gestito cambia; fronte/retro indipendenti |
| P5 | E2E KiCad/Gerber, pacchetto e documentazione | Stesso esito dalla skill installabile; limiti dichiarati |

P1 non deve far sembrare completa la pipeline: lo stato di supporto resta parziale finché P2–P5 non superano i gate. Evitare nello stesso ciclo refactor estetici, nuovi effetti grafici o modifiche al design elettrico.

## 6. Matrice minima dei test

| ID | Fixture o caso | Verifica |
|---|---|---|
| G01 | Pad circolare frontale | Apertura della mask e distanza finale |
| G02 | Pad rettangolare in footprint ruotato | Trasformazione globale contro riferimento KiCad |
| G03 | Footprint sul retro | Lato e orientamento, senza doppia specchiatura |
| G04 | Override di margine pad/footprint/board | Risoluzione della regola effettiva |
| G05 | Foro circolare, asola e offset | Forma e posizione della zona protetta |
| G06 | Contorno con arco e ritaglio interno | Artwork fuori board o nel ritaglio assente |
| G07 | Contorno aperto o ambiguo | Compilazione bloccata |
| G08 | Forma di pad non supportata | Errore nominativo, nessun file apparentemente verificato |
| G09 | Hatching e polyline | Espansione completa prima del patcher |
| G10 | Ostacolo al centro di un poligono | Foro preservato nel file serializzato |
| G11 | Frammenti multipli e residui degeneri | Esiti espliciti e area tracciabile |
| G12 | Input malformato, NaN, spaziatura zero | Validazione prima della generazione |
| G13 | PCB modificato dopo il clipping | Hash discordante, patch rifiutata |
| G14 | Output coincidente, symlink o hardlink | Sorgente intatta |
| G15 | Patch ripetuta; aggiornamento del solo retro | Idempotenza e conservazione del fronte |
| G16 | Componenti elettrici e silk preesistente | Invarianza strutturale e testuale fuori area gestita |
| G17 | Skill copiata senza repository root | Stessi output e nessuna dipendenza implicita dal checkout |

Costruire le fixture da zero. Non importare board, Gerber, immagini o geometrie dei progetti privati dell'autore. Rimuovere dai report percorsi personali e qualsiasi dato estraneo ai casi di prova.

## 7. Comandi e protocollo di verifica

Questi comandi fanno già parte del workflow documentato; i loro nomi restano stabili: [^R5]

```bash
python scripts/inspect_board.py board.kicad_pcb > board-geometry.json
python scripts/validate_artwork.py artwork.json
python scripts/clip_artwork.py --board board.kicad_pcb --artwork artwork.json --output artwork-clipped.json
python scripts/patch_kicad.py --board board.kicad_pcb --artwork artwork-clipped.json --output board-artwork.kicad_pcb
```

Eseguirli nel laboratorio con copie sintetiche. L'implementazione deve aggiungere un runner dei test e le dipendenze di sviluppo versionate; non considerare la presenza di due funzioni di test una suite E2E già pronta.

Registrare `kicad-cli --version` e ricavare i comandi DRC/export dall'help della versione scelta. Congelare quei comandi nel runner: non inventare flag compatibili con tutte le release. Confrontare DRC della board sorgente e della board modificata e conservare i report. Su board reali, nessuna nuova violazione non significa che eventuali violazioni preesistenti siano accettabili per la produzione.

Esportare Gerber e verificare i layer reali, comprese le impostazioni di sottrazione della mask dalla silk. Un'opzione di export che nasconde un'intersezione non sostituisce il test del compilatore. Registrare impostazioni, hash degli output e versione dello strumento. La sola anteprima nell'editor non completa il gate.

## 8. Definition of Done e rollback

La release deve completare tutte le fixture del perimetro dichiarato, rifiutare i casi non supportati e mantenere invariato il progetto elettrico. Il report deve distinguere validazione dello schema, correttezza geometrica, DRC, export e revisione visuale. Un controllo non eseguito deve comparire come tale.

Documentare forme supportate, tolleranze, limiti produttivi e versioni KiCad provate. Dimostrare il workflow del README con un esempio pubblico E2E. Non usare formule come “pronto alla produzione” senza i controlli richiesti e senza requisiti del fabbricante.

Il rollback consiste nel ripristino della versione precedente della skill. La sorgente PCB resta intatta, gli output sono copie e il manifest identifica le modifiche gestite. Non cancellare file dell'utente durante il rollback e non rimuovere oggetti la cui proprietà è incerta.

**Istruzione di avvio per l'agente:** iniziare da P1 con fixture sintetiche e test che espongano keepout assenti, hatching non compilato e perdita dei fori. Leggere lo schema e la skill installabile, scegliere e registrare la versione KiCad di prova. Non usare design privati, non modificare rame o footprint, non dichiarare completato un test sostituito da un mock.

## Fonti

[^R1]: Script installabili di ispezione e clipping: `https://github.com/yuzushi-dev/pcb-artwork-skill/blob/8357fe2ccfced14915921b065d2ee495e97406d7/skills/pcb-artwork/scripts/inspect_board.py` e `https://github.com/yuzushi-dev/pcb-artwork-skill/blob/8357fe2ccfced14915921b065d2ee495e97406d7/skills/pcb-artwork/scripts/clip_artwork.py`.
[^R2]: Patcher: `https://github.com/yuzushi-dev/pcb-artwork-skill/blob/8357fe2ccfced14915921b065d2ee495e97406d7/skills/pcb-artwork/scripts/patch_kicad.py`.
[^R3]: Schema: `https://github.com/yuzushi-dev/pcb-artwork-skill/blob/8357fe2ccfced14915921b065d2ee495e97406d7/skills/pcb-artwork/schemas/artwork.schema.json`.
[^R4]: Test geometrici presenti: `https://github.com/yuzushi-dev/pcb-artwork-skill/blob/8357fe2ccfced14915921b065d2ee495e97406d7/tests/test_geometry.py`.
[^R5]: README e workflow: `https://github.com/yuzushi-dev/pcb-artwork-skill/blob/8357fe2ccfced14915921b065d2ee495e97406d7/README.md`.
[^K1]: KiCad, formato PCB: `https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/`, consultato il 30 settembre 2026.
[^K2]: KiCad, strutture comuni, footprint e pad: `https://dev-docs.kicad.org/en/file-formats/sexpr-intro/index.html`, consultato il 30 settembre 2026.

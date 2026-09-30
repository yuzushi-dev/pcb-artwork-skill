# Serigrafia: coupon di calibrazione

Questo coupon sintetico da 60 × 40 mm serve a confrontare la resa della
serigrafia prodotta da un fabbricante. Include volutamente dettagli sotto il
profilo prudente da 0,20 mm: non è una scheda pronta per la produzione e non
stabilisce da solo una regola di accettazione.

Input:

- board: `tests/fixtures/boards/calibration.kicad_pcb`;
- artwork originale: `tests/fixtures/artwork/calibration.json`;
- layer: `F.SilkS`;
- clearance richiesta dalle aperture mask: 0,25 mm;
- pad centrale: centro (30, 20), diametro rame 4 mm, foro 2 mm;
- espansione mask esplicita della board: 0,10 mm.

## Mappa del layout

Tutte le coordinate e le misure sono in millimetri.

| Zona | Geometria richiesta |
|---|---|
| x 4–24, y 4 | linea larga 0,10 |
| x 4–24, y 6 | linea larga 0,15 |
| x 4–24, y 8 | linea larga 0,20 |
| x 4–24, y 10 | linea larga 0,25 |
| x 4–24, y 12 | linea larga 0,30 |
| x 4–20, y 16–19 | retino: barra 0,15, passo centro-centro 0,30, spazio nominale 0,15 |
| x 4–20, y 21–24 | retino: barra 0,20, passo centro-centro 0,40, spazio nominale 0,20 |
| x 4–20, y 26–29 | retino: barra 0,25, passo centro-centro 0,50, spazio nominale 0,25 |
| x 36–45 e 45,10–55, y 17 | linee da 0,20; spazio longitudinale 0,10 |
| x 36–45 e 45,15–55, y 20 | linee da 0,20; spazio longitudinale 0,15 |
| x 36–45 e 45,20–55, y 23 | linee da 0,20; spazio longitudinale 0,20 |
| x 36–45 e 45,25–55, y 26 | linee da 0,20; spazio longitudinale 0,25 |
| x 36–45 e 45,30–55, y 29 | linee da 0,20; spazio longitudinale 0,30 |
| x 46/49/52, y 4 | lettere poligonali “E” alte 0,8 / 1,0 / 1,2 |
| intorno a (30, 20) | barra con collo richiesto da 0,90 che interseca la zona protetta del pad |

Le lettere sono poligoni, non testo o font KiCad. In questo modo il coupon
misura la geometria fornita e non dipende dalla sostituzione di un font.

La barra presso il pad è un caso di clipping intenzionale. Il suo collo va da
y 21,90 a y 22,80, ma la geometria finale viene sottratta dall'apertura mask
più la clearance. La larghezza dichiarata nell'input quindi non garantisce la
larghezza residua: va controllato il Gerber compilato.

## Compilazione

Da `skills/pcb-artwork`:

```sh
python scripts/validate_artwork.py ../../tests/fixtures/artwork/calibration.json
python scripts/compile_artwork.py \
  --board ../../tests/fixtures/boards/calibration.kicad_pcb \
  --artwork ../../tests/fixtures/artwork/calibration.json \
  --output calibration-output.kicad_pcb \
  --report calibration-report.json \
  --review-svg calibration-review.svg
```

Il profilo conservativo predefinito deve produrre `review_required`: le linee
da 0,10 e 0,15 mm e parte del retino sono intenzionalmente sotto il target da
0,20 mm. Il PCB viene comunque scritto per consentire la produzione del
campione. `calibration-review.svg` evidenzia i dettagli da confrontare con il
risultato fisico.

## Pacchetto per il fabbricante

Sul computer che dispone di KiCad 10, eseguire prima il DRC, poi esportare i
sette layer necessari per questo coupon a due facce e il file Excellon:

```sh
kicad-cli pcb drc --format json --units mm --severity-all \
  --output calibration-drc.json calibration-output.kicad_pcb
mkdir calibration-gerbers
kicad-cli pcb export gerbers \
  --layers F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts \
  --precision 6 --output calibration-gerbers calibration-output.kicad_pcb
kicad-cli pcb export drill --format excellon --drill-origin absolute \
  --excellon-units mm --output calibration-gerbers calibration-output.kicad_pcb
```

Il pacchetto da caricare al fabbricante è il contenuto di
`calibration-gerbers`: Gerber di rame, mask, serigrafia e bordo, file job e
file di foratura. Controllare nel visualizzatore CAM del fornitore che siano
presenti tutti e sette i layer e un foro. Questa procedura prepara i file, ma
non implica che il coupon sia stato ordinato o verificato fisicamente.

Prima di ordinare un campione, misurare nei Gerber linee, spazi e collo dopo
il clipping. Annotare fabbricante, stack-up, colore solder mask, colore
serigrafia, data e risultato: questi fattori possono cambiare la resa anche
con la stessa geometria nominale.

## Export verificato

Il coupon è stato compilato con il profilo conservativo ed esportato da
KiCad 10.0.5. Il pacchetto completo è
[fabrication-gerbers.zip](verification/kicad-10.0.5/calibration-conservative-final/fabrication-gerbers.zip).
Il [report](verification/kicad-10.0.5/calibration-conservative-final/evidence.json)
conserva DRC, impostazioni ed esportazioni.
L’[anteprima con le zone a rischio](verification/kicad-10.0.5/calibration-conservative-final/manufacturing-review.svg)
è in spazio modello; l’[overlay Gerber](verification/kicad-10.0.5/calibration-conservative-final/previews/overlay-F.png)
mostra l’export reale. La verifica del campione fisico resta da eseguire.

# Correzione bootloader per flash XMC MFID 0x70

La scheda YD-ESP32-S3-N16R8 provata usa una flash XMC con identificativo
JEDEC `0x207018`. Alcune versioni di ESP-IDF non riconoscono il valore MFID
`0x70` e il bootloader entra in un ciclo di riavvio con il messaggio
`XMC flash startup fail`.

Il file `esp-idf-xmc-mfid-70.patch` contiene la modifica minima applicata a
ESP-IDF 5.5.5. L'intero albero ESP-IDF e i risultati della compilazione non
sono inclusi nel repository perché sono scaricabili o rigenerabili.

Prima di applicarla, verificare che la versione di ESP-IDF usata presenti
ancora la stessa condizione e che la flash della propria scheda abbia davvero
MFID `0x70`.

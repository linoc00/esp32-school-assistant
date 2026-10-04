#include <Arduino.h>
#include <driver/i2s.h>
#include <esp_heap_caps.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include "wifi_secrets.h"
#include "device_config.h"

// Pulsante: un lato a GND, l'altro a GPIO15.
// Con INPUT_PULLUP: rilasciato = HIGH, premuto = LOW.
constexpr uint8_t PIN_PULSANTE = 15;

// Microfono I2S INMP441.
constexpr gpio_num_t PIN_MIC_SCK = GPIO_NUM_4;
constexpr gpio_num_t PIN_MIC_WS  = GPIO_NUM_5;
constexpr gpio_num_t PIN_MIC_SD  = GPIO_NUM_6;
constexpr i2s_port_t I2S_MIC = I2S_NUM_0;

// Amplificatore I2S MAX98357A.
constexpr gpio_num_t PIN_AMP_DIN  = GPIO_NUM_16;
constexpr gpio_num_t PIN_AMP_BCLK = GPIO_NUM_17;
constexpr gpio_num_t PIN_AMP_LRC  = GPIO_NUM_18;
constexpr i2s_port_t I2S_AMP = I2S_NUM_1;

constexpr uint32_t SAMPLE_RATE = 16000;
constexpr uint32_t DURATA_MASSIMA_SECONDI = 15;
constexpr size_t HEADER_WAV = 44;
constexpr size_t CAMPIONI_MASSIMI = SAMPLE_RATE * DURATA_MASSIMA_SECONDI;
constexpr size_t BYTE_AUDIO_MASSIMI = CAMPIONI_MASSIMI * sizeof(int16_t);
constexpr size_t CAPACITA_BUFFER_WAV = 2 * 1024 * 1024;
constexpr size_t BLOCCO_MIC = 512;
constexpr size_t FRAME_AMP = 256;
constexpr uint8_t VOLUME_RISPOSTA_PERCENTO = 35;

uint8_t *wav = nullptr;
int32_t bufferMicrofono[BLOCCO_MIC];
int16_t bufferStereo[FRAME_AMP * 2];
size_t campioniRegistrati = 0;
int32_t piccoRegistrazione = 0;

bool connettiWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.printf("Connessione Wi-Fi a: %s", WIFI_SSID);
  const uint32_t inizio = millis();

  while (WiFi.status() != WL_CONNECTED && millis() - inizio < 30000) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("ERRORE: connessione Wi-Fi non riuscita");
    return false;
  }

  Serial.println("WI-FI CONNESSO");
  Serial.print("Indirizzo ESP32: ");
  Serial.println(WiFi.localIP());
  return true;
}

void scrivi16LE(uint8_t *destinazione, uint16_t valore) {
  destinazione[0] = valore & 0xFF;
  destinazione[1] = (valore >> 8) & 0xFF;
}

void scrivi32LE(uint8_t *destinazione, uint32_t valore) {
  destinazione[0] = valore & 0xFF;
  destinazione[1] = (valore >> 8) & 0xFF;
  destinazione[2] = (valore >> 16) & 0xFF;
  destinazione[3] = (valore >> 24) & 0xFF;
}

uint16_t leggi16LE(const uint8_t *sorgente) {
  return static_cast<uint16_t>(sorgente[0]) |
         (static_cast<uint16_t>(sorgente[1]) << 8);
}

uint32_t leggi32LE(const uint8_t *sorgente) {
  return static_cast<uint32_t>(sorgente[0]) |
         (static_cast<uint32_t>(sorgente[1]) << 8) |
         (static_cast<uint32_t>(sorgente[2]) << 16) |
         (static_cast<uint32_t>(sorgente[3]) << 24);
}

void preparaHeaderWav(size_t byteAudio) {
  memcpy(wav + 0, "RIFF", 4);
  scrivi32LE(wav + 4, 36 + byteAudio);
  memcpy(wav + 8, "WAVE", 4);
  memcpy(wav + 12, "fmt ", 4);
  scrivi32LE(wav + 16, 16);
  scrivi16LE(wav + 20, 1);
  scrivi16LE(wav + 22, 1);
  scrivi32LE(wav + 24, SAMPLE_RATE);
  scrivi32LE(wav + 28, SAMPLE_RATE * sizeof(int16_t));
  scrivi16LE(wav + 32, sizeof(int16_t));
  scrivi16LE(wav + 34, 16);
  memcpy(wav + 36, "data", 4);
  scrivi32LE(wav + 40, byteAudio);
}

bool configuraMicrofono() {
  const i2s_config_t configurazione = {
    .mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 256,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };

  const i2s_pin_config_t pin = {
    .mck_io_num = I2S_PIN_NO_CHANGE,
    .bck_io_num = PIN_MIC_SCK,
    .ws_io_num = PIN_MIC_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = PIN_MIC_SD
  };

  if (i2s_driver_install(I2S_MIC, &configurazione, 0, nullptr) != ESP_OK) return false;
  if (i2s_set_pin(I2S_MIC, &pin) != ESP_OK) return false;
  i2s_zero_dma_buffer(I2S_MIC);
  return true;
}

bool configuraAmplificatore() {
  const i2s_config_t configurazione = {
    .mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 256,
    .use_apll = false,
    .tx_desc_auto_clear = true,
    .fixed_mclk = 0
  };

  const i2s_pin_config_t pin = {
    .mck_io_num = I2S_PIN_NO_CHANGE,
    .bck_io_num = PIN_AMP_BCLK,
    .ws_io_num = PIN_AMP_LRC,
    .data_out_num = PIN_AMP_DIN,
    .data_in_num = I2S_PIN_NO_CHANGE
  };

  if (i2s_driver_install(I2S_AMP, &configurazione, 0, nullptr) != ESP_OK) return false;
  if (i2s_set_pin(I2S_AMP, &pin) != ESP_OK) return false;
  i2s_zero_dma_buffer(I2S_AMP);
  return true;
}

int16_t limitaA16Bit(int32_t valore) {
  if (valore > 32767) return 32767;
  if (valore < -32768) return -32768;
  return static_cast<int16_t>(valore);
}

void registraFinchePremuto() {
  campioniRegistrati = 0;
  piccoRegistrazione = 0;
  int16_t *pcm = reinterpret_cast<int16_t *>(wav + HEADER_WAV);

  i2s_zero_dma_buffer(I2S_MIC);
  Serial.println("REGISTRAZIONE INIZIATA: parla ora");

  while (digitalRead(PIN_PULSANTE) == LOW && campioniRegistrati < CAMPIONI_MASSIMI) {
    size_t byteLetti = 0;
    const esp_err_t risultato = i2s_read(
      I2S_MIC,
      bufferMicrofono,
      sizeof(bufferMicrofono),
      &byteLetti,
      portMAX_DELAY
    );

    if (risultato != ESP_OK || byteLetti == 0) {
      Serial.println("ERRORE LETTURA MICROFONO");
      break;
    }

    const size_t disponibili = byteLetti / sizeof(int32_t);
    const size_t spazio = CAMPIONI_MASSIMI - campioniRegistrati;
    const size_t daCopiare = disponibili < spazio ? disponibili : spazio;

    for (size_t i = 0; i < daCopiare; ++i) {
      const int16_t campione = static_cast<int16_t>(bufferMicrofono[i] >> 16);
      pcm[campioniRegistrati++] = campione;

      const int32_t assoluto = campione < 0 ? -static_cast<int32_t>(campione) : campione;
      if (assoluto > piccoRegistrazione) piccoRegistrazione = assoluto;
    }
  }

  preparaHeaderWav(campioniRegistrati * sizeof(int16_t));
  const uint32_t durataMs = campioniRegistrati * 1000UL / SAMPLE_RATE;

  Serial.println("REGISTRAZIONE TERMINATA");
  Serial.printf("Durata: %lu ms - Picco: %ld / 32767\n",
                static_cast<unsigned long>(durataMs),
                static_cast<long>(piccoRegistrazione));

  if (campioniRegistrati >= CAMPIONI_MASSIMI) {
    Serial.println("Raggiunto il limite massimo di 15 secondi");
  }
}

void riproduciRegistrazione(uint8_t volumePercento = 100) {
  if (campioniRegistrati == 0) {
    Serial.println("Nessun audio da riprodurre");
    return;
  }

  // Porta il picco verso un volume udibile, senza amplificare oltre 8 volte.
  int32_t guadagno = 1;
  if (piccoRegistrazione > 0 && piccoRegistrazione < 12000) {
    guadagno = 12000 / piccoRegistrazione;
    if (guadagno < 1) guadagno = 1;
    if (guadagno > 8) guadagno = 8;
  }

  const int16_t *pcm = reinterpret_cast<const int16_t *>(wav + HEADER_WAV);
  const size_t campioniDissolvenza = SAMPLE_RATE / 100;  // 10 ms
  size_t posizione = 0;

  i2s_zero_dma_buffer(I2S_AMP);
  Serial.printf("RIPRODUZIONE INIZIATA - Guadagno: %ldx - Volume: %u%%\n",
                static_cast<long>(guadagno), volumePercento);

  while (posizione < campioniRegistrati) {
    const size_t rimanenti = campioniRegistrati - posizione;
    const size_t frame = rimanenti < FRAME_AMP ? rimanenti : FRAME_AMP;

    for (size_t i = 0; i < frame; ++i) {
      const size_t indice = posizione + i;
      int32_t campione = static_cast<int32_t>(pcm[indice]) * guadagno;
      campione = campione * volumePercento / 100;

      if (indice < campioniDissolvenza) {
        campione = campione * static_cast<int32_t>(indice) / campioniDissolvenza;
      }
      const size_t dallaFine = campioniRegistrati - 1 - indice;
      if (dallaFine < campioniDissolvenza) {
        campione = campione * static_cast<int32_t>(dallaFine) / campioniDissolvenza;
      }

      const int16_t uscita = limitaA16Bit(campione);
      bufferStereo[i * 2] = uscita;
      bufferStereo[i * 2 + 1] = uscita;
    }

    size_t byteScritti = 0;
    const esp_err_t risultato = i2s_write(
      I2S_AMP,
      bufferStereo,
      frame * 2 * sizeof(int16_t),
      &byteScritti,
      portMAX_DELAY
    );

    if (risultato != ESP_OK) {
      Serial.println("ERRORE RIPRODUZIONE AMPLIFICATORE");
      break;
    }

    posizione += frame;
  }

  memset(bufferStereo, 0, sizeof(bufferStereo));
  size_t byteScritti = 0;
  i2s_write(I2S_AMP, bufferStereo, sizeof(bufferStereo), &byteScritti, portMAX_DELAY);
  i2s_zero_dma_buffer(I2S_AMP);

  Serial.println("RIPRODUZIONE TERMINATA");
  Serial.println("Pronto: tieni nuovamente premuto il pulsante per registrare");
}

bool preparaRispostaWav(size_t dimensioneWav) {
  if (dimensioneWav < 44 || memcmp(wav, "RIFF", 4) != 0 || memcmp(wav + 8, "WAVE", 4) != 0) {
    Serial.println("RISPOSTA NON VALIDA: il server non ha restituito un WAV");
    return false;
  }

  uint16_t formato = 0;
  uint16_t canali = 0;
  uint16_t bitPerCampione = 0;
  uint32_t frequenza = 0;
  size_t inizioDati = 0;
  size_t byteDati = 0;
  size_t posizione = 12;

  while (posizione + 8 <= dimensioneWav) {
    const uint8_t *chunk = wav + posizione;
    const uint32_t dimensioneChunk = leggi32LE(chunk + 4);
    const size_t contenuto = posizione + 8;

    if (contenuto + dimensioneChunk > dimensioneWav) break;

    if (memcmp(chunk, "fmt ", 4) == 0 && dimensioneChunk >= 16) {
      formato = leggi16LE(wav + contenuto);
      canali = leggi16LE(wav + contenuto + 2);
      frequenza = leggi32LE(wav + contenuto + 4);
      bitPerCampione = leggi16LE(wav + contenuto + 14);
    } else if (memcmp(chunk, "data", 4) == 0) {
      inizioDati = contenuto;
      byteDati = dimensioneChunk;
      break;
    }

    posizione = contenuto + dimensioneChunk + (dimensioneChunk & 1U);
  }

  if (formato != 1 || canali != 1 || frequenza != SAMPLE_RATE || bitPerCampione != 16 || byteDati == 0) {
    Serial.println("RISPOSTA NON COMPATIBILE: serve PCM mono, 16 bit, 16000 Hz");
    return false;
  }

  byteDati -= byteDati % sizeof(int16_t);
  if (HEADER_WAV + byteDati > CAPACITA_BUFFER_WAV) {
    Serial.println("RISPOSTA TROPPO LUNGA PER LA MEMORIA AUDIO");
    return false;
  }

  memmove(wav + HEADER_WAV, wav + inizioDati, byteDati);
  campioniRegistrati = byteDati / sizeof(int16_t);
  piccoRegistrazione = 0;

  const int16_t *pcm = reinterpret_cast<const int16_t *>(wav + HEADER_WAV);
  for (size_t i = 0; i < campioniRegistrati; ++i) {
    const int32_t assoluto = pcm[i] < 0 ? -static_cast<int32_t>(pcm[i]) : pcm[i];
    if (assoluto > piccoRegistrazione) piccoRegistrazione = assoluto;
  }

  preparaHeaderWav(byteDati);
  Serial.printf("RISPOSTA VOCALE RICEVUTA: %u byte, picco %ld\n",
                static_cast<unsigned int>(HEADER_WAV + byteDati),
                static_cast<long>(piccoRegistrazione));
  return true;
}

void inviaRegistrazioneAlServer() {
  if (campioniRegistrati == 0) {
    Serial.println("INVIO ANNULLATO: registrazione vuota");
    return;
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi scollegato: provo a riconnettermi");
    if (!connettiWiFi()) {
      Serial.println("INVIO FALLITO: Wi-Fi non disponibile");
      return;
    }
  }

  const size_t dimensioneWav = HEADER_WAV + campioniRegistrati * sizeof(int16_t);
  HTTPClient http;
  http.setConnectTimeout(5000);
  http.setTimeout(60000);

  if (!http.begin(URL_RISPOSTA)) {
    Serial.println("INVIO FALLITO: indirizzo server non valido");
    return;
  }

  http.addHeader("Content-Type", "audio/wav");
  http.addHeader("Connection", "close");

  Serial.printf("INVIO AL SERVER: %u byte\n", static_cast<unsigned int>(dimensioneWav));
  const int codiceHttp = http.POST(wav, dimensioneWav);

  if (codiceHttp <= 0) {
    Serial.printf("INVIO FALLITO: %s\n", http.errorToString(codiceHttp).c_str());
    http.end();
    return;
  }

  Serial.printf("RISPOSTA SERVER HTTP %d\n", codiceHttp);
  if (codiceHttp != HTTP_CODE_OK) {
    Serial.println(http.getString());
    http.end();
    return;
  }

  const int dimensioneRisposta = http.getSize();
  if (dimensioneRisposta <= 0 || static_cast<size_t>(dimensioneRisposta) > CAPACITA_BUFFER_WAV) {
    Serial.println("DOWNLOAD FALLITO: dimensione della risposta non valida");
    http.end();
    return;
  }

  WiFiClient *flusso = http.getStreamPtr();
  size_t ricevuti = 0;
  uint32_t ultimoDato = millis();

  Serial.printf("DOWNLOAD RISPOSTA VOCALE: %d byte\n", dimensioneRisposta);
  while (ricevuti < static_cast<size_t>(dimensioneRisposta) && millis() - ultimoDato < 30000) {
    const int disponibili = flusso->available();
    if (disponibili > 0) {
      const size_t rimanenti = static_cast<size_t>(dimensioneRisposta) - ricevuti;
      const size_t daLeggere = static_cast<size_t>(disponibili) < rimanenti
        ? static_cast<size_t>(disponibili)
        : rimanenti;
      const int letti = flusso->read(wav + ricevuti, daLeggere);
      if (letti > 0) {
        ricevuti += static_cast<size_t>(letti);
        ultimoDato = millis();
      }
    } else {
      delay(2);
    }
  }

  http.end();

  if (ricevuti != static_cast<size_t>(dimensioneRisposta)) {
    Serial.printf("DOWNLOAD INCOMPLETO: ricevuti %u di %d byte\n",
                  static_cast<unsigned int>(ricevuti), dimensioneRisposta);
    return;
  }

  if (preparaRispostaWav(ricevuti)) {
    Serial.println("L'ASSISTENTE STA RISPONDENDO");
    riproduciRegistrazione(VOLUME_RISPOSTA_PERCENTO);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_PULSANTE, INPUT_PULLUP);
  delay(1000);

  connettiWiFi();

  Serial.printf("PSRAM disponibile: %u byte\n", ESP.getPsramSize());

  wav = static_cast<uint8_t *>(heap_caps_malloc(
    CAPACITA_BUFFER_WAV,
    MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT
  ));

  if (wav == nullptr) {
    Serial.println("ERRORE: impossibile allocare la memoria per l'audio");
    while (true) delay(1000);
  }

  if (!configuraMicrofono()) {
    Serial.println("ERRORE: impossibile configurare il microfono I2S");
    while (true) delay(1000);
  }

  if (!configuraAmplificatore()) {
    Serial.println("ERRORE: impossibile configurare l'amplificatore I2S");
    while (true) delay(1000);
  }

  Serial.println("TEST PRONTO");
  Serial.println("Tieni premuto il pulsante, parla e rilascialo per riascoltarti");
}

void loop() {
  if (digitalRead(PIN_PULSANTE) == LOW) {
    delay(30);
    if (digitalRead(PIN_PULSANTE) == LOW) {
      registraFinchePremuto();
      delay(30);
      riproduciRegistrazione();
      inviaRegistrazioneAlServer();

      while (digitalRead(PIN_PULSANTE) == LOW) delay(5);
      delay(50);
    }
  }

  delay(5);
}

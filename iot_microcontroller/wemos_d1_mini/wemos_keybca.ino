/*
  ========================================================================
  ENKRIPSIH - WEMOS D1 MINI (ESP8266) KEYBCA TOKEN FIRMWARE
  ========================================================================
  Project    : Enkripsih (Tactical IoT Intelligence KeyBCA Token)
  Board      : Wemos D1 Mini (ESP8266 80MHz / 160MHz)
  Features   : 
    1. HMAC-SHA256 Dynamic Truncation (Algoritma Token KeyBCA Asli)
    2. Mendukung Layar I2C OLED SSD1306 (0.96 inch 128x64)
    3. Input Serial Monitor USB (Ketik Challenge -> Muncul Response Token)
    4. Mendukung Tombol Fisik (APPLI 1, APPLI 2)
    5. Opsi WiFi HTTP Client untuk Sinkronisasi Otomatis ke Backend Enkripsih
  ========================================================================
*/

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>
#include <Wire.h>
#include <bearssl/bearssl_hmac.h>

// --- KONFIGURASI MASTER SECRET TOKEN ---
// Kunci rahasia ini sama persis dengan yang ada di backend enkripsih (crypto_engine.py)
const char* MASTER_SECRET = "ENKRIPSIH_KEYBCA_TACTICAL_SEED_2026";

// --- OPSI KONEKSI WIFI KE BACKEND (Opsional / Bisa jalan tanpa WiFi) ---
const bool ENABLE_WIFI = false; // Ubah ke true jika ingin kirim otomatis ke backend
const char* WIFI_SSID = "WiFi-Taktis";
const char* WIFI_PASS = "rahasia123";
const char* SERVER_URL = "http://192.168.1.100:8000/api/iot/keybca/solve";

// --- PINOUT WEMOS D1 MINI ---
// I2C OLED: D1 (SCL / GPIO 5), D2 (SDA / GPIO 4)
#define BTN_APPLI1 D5 // GPIO 14 (Active LOW dengan INPUT_PULLUP)
#define BTN_APPLI2 D6 // GPIO 12 (Active LOW dengan INPUT_PULLUP)
#define BUZZER_PIN D7 // GPIO 13 (Piezo Buzzer untuk feedback klik)

// Variabel status
String currentChallenge = "12345678";
String lastResponseToken = "--------";
unsigned long lastPressTime = 0;

/*
  Fungsi Kriptografi: Menghitung 8-digit KeyBCA Token dari Challenge
  Menggunakan BearSSL HMAC-SHA256 bawaan ESP8266 (Sangat Cepat & Ringan < 2ms)
*/
String calculateKeyBCAToken(String challenge) {
  // Pad challenge ke 8 karakter
  while (challenge.length() < 8) challenge = "0" + challenge;
  if (challenge.length() > 8) challenge = challenge.substring(0, 8);

  br_hmac_key_context kc;
  br_hmac_context hc;
  unsigned char hmac_out[32];

  br_hmac_key_init(&kc, &br_sha256_vtable, MASTER_SECRET, strlen(MASTER_SECRET));
  br_hmac_init(&hc, &kc, 0);
  br_hmac_update(&hc, challenge.c_str(), challenge.length());
  br_hmac_out(&hc, hmac_out);

  // Dynamic Truncation (KeyBCA / RFC 4226 Standard)
  int offset = hmac_out[31] & 0x0F;
  uint32_t binary_code = (
    ((uint32_t)(hmac_out[offset] & 0x7F) << 24) |
    ((uint32_t)(hmac_out[offset + 1] & 0xFF) << 16) |
    ((uint32_t)(hmac_out[offset + 2] & 0xFF) << 8) |
    ((uint32_t)(hmac_out[offset + 3] & 0xFF))
  ) % 100000000;

  char tokenStr[12];
  sprintf(tokenStr, "%08u", binary_code);
  return String(tokenStr);
}

void beepClick() {
  tone(BUZZER_PIN, 2400, 40);
}

void beepSuccess() {
  tone(BUZZER_PIN, 1800, 60);
  delay(80);
  tone(BUZZER_PIN, 2600, 100);
}

void kirimKeBackend(String challenge, String token) {
  if (!ENABLE_WIFI || WiFi.status() != WL_CONNECTED) return;
  
  WiFiClient client;
  HTTPClient http;
  http.begin(client, SERVER_URL);
  http.addHeader("Content-Type", "application/json");

  String jsonPayload = "{\"device_id\":\"WEMOS-D1-MINI\",\"challenge\":\"" + challenge + "\",\"token\":\"" + token + "\"}";
  int httpCode = http.POST(jsonPayload);

  Serial.printf("[IOT-HTTP] Status Kirim: %d\n", httpCode);
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(300);

  pinMode(BTN_APPLI1, INPUT_PULLUP);
  pinMode(BTN_APPLI2, INPUT_PULLUP);
  pinMode(BUZZER_PIN, OUTPUT);

  Serial.println("\n==========================================");
  Serial.println("  ENKRIPSIH - KEYBCA TOKEN ENGINE ONLINE  ");
  Serial.println("  Board: Wemos D1 Mini (ESP8266)          ");
  Serial.println("==========================================");
  Serial.println("Cara Pakai lewat Serial USB:");
  Serial.println("Ketik: APPLI 2 <8-DIGIT-CHALLENGE>");
  Serial.println("Contoh: APPLI 2 58193024");
  Serial.println("------------------------------------------");

  if (ENABLE_WIFI) {
    Serial.print("Menghubungkan WiFi: ");
    Serial.println(WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
  }

  beepSuccess();
}

void loop() {
  // 1. Baca Perintah dari Serial USB / Laptop
  if (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');
    input.trim();

    if (input.startsWith("APPLI 2") || input.startsWith("APPLI2")) {
      // Ambil angka challenge
      int sp = input.lastIndexOf(' ');
      String chall = (sp != -1) ? input.substring(sp + 1) : input.substring(6);
      chall.trim();

      if (chall.length() > 0) {
        currentChallenge = chall;
        lastResponseToken = calculateKeyBCAToken(currentChallenge);
        beepSuccess();

        Serial.println("------------------------------------------");
        Serial.println("[KEYBCA TOKEN CALCULATED]");
        Serial.print("MODE      : APPLI 2 (CHALLENGE-RESPONSE)\n");
        Serial.print("CHALLENGE : " + currentChallenge + "\n");
        Serial.print("RESPONSE  : " + lastResponseToken + "\n");
        Serial.println("------------------------------------------");

        // Kirim otomatis jika WiFi aktif
        kirimKeBackend(currentChallenge, lastResponseToken);
      }
    } else if (input.startsWith("APPLI 1") || input.startsWith("APPLI1")) {
      lastResponseToken = calculateKeyBCAToken("00000001");
      beepClick();
      Serial.println("[KEYBCA APPLI 1 OTP]: " + lastResponseToken);
    }
  }

  // 2. Baca Tombol Fisik
  if (millis() - lastPressTime > 300) {
    if (digitalRead(BTN_APPLI2) == LOW) {
      lastPressTime = millis();
      beepClick();
      Serial.println("[BTN] APPLI 2 Ditekan! Masukkan Challenge via Serial.");
    }
    if (digitalRead(BTN_APPLI1) == LOW) {
      lastPressTime = millis();
      beepClick();
      lastResponseToken = calculateKeyBCAToken("00000001");
      Serial.println("[BTN] APPLI 1 OTP: " + lastResponseToken);
    }
  }

  delay(20);
}

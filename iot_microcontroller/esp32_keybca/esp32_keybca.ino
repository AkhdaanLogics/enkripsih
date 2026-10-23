/*
  ========================================================================
  ENKRIPSIH - ESP32 / WEMOS KEYBCA SYMBOL TOKEN FIRMWARE
  ========================================================================
  Features:
    - 4 Simbol Taktis: △ (Triangle/T), ○ (Circle/C), ✕ (Cross/X), □ (Square/S)
    - 1 Tombol Merah: Klik = Hapus 1 / Challenge Baru, Tahan 2 dtk = ON/OFF
    - Layar OLED 128x64 (SSD1306)
    - mbedtls HMAC-SHA256 (Kalkulasi < 2ms)
    - Input: 4 Simbol Challenge -> Output: 12 Simbol Respon Dekripsi
  ========================================================================
*/

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#if defined(ESP32)
  #include "mbedtls/md.h"
#elif defined(ESP8266)
  #include <bearssl/bearssl_hmac.h>
#endif

Adafruit_SSD1306 display(128, 64, &Wire, -1);

// ===== Kunci rahasia: HARUS sama dengan di Backend Enkripsih =====
const char SECRET_KEY[] = "GANTI_KUNCI_RAHASIA_INI";
const int CHAL_LEN = 4;    // panjang challenge
const int RESP_LEN = 12;   // panjang response

// ===== Pin tombol ESP32 =====
const int BTN_TRIANGLE = 32;  // simbol 0 (T / △)
const int BTN_CIRCLE   = 25;  // simbol 1 (C / ○)
const int BTN_CROSS    = 26;  // simbol 2 (X / ✕)
const int BTN_SQUARE   = 33;  // simbol 3 (S / □)
const int BTN_RED      = 27;  // klik = hapus 1 / challenge baru, tahan 2 dtk = ON/OFF

const unsigned long HOLD_MS     = 2000;
const unsigned long DEBOUNCE_MS = 30;

enum Mode { MODE_INPUT, MODE_RESULT };
bool powerOn = false;
Mode mode = MODE_INPUT;

uint8_t chal[CHAL_LEN];
int chalCount = 0;
uint8_t resp[RESP_LEN];

// Tombol merah
bool redDown = false;
bool holdDone = false;
unsigned long redStart = 0;
int holdProgress = 0;

// Tombol simbol (edge detection + debounce)
struct Btn { int pin; bool last; unsigned long t; };
Btn symBtn[4] = {
  { BTN_TRIANGLE, false, 0 },
  { BTN_CIRCLE,   false, 0 },
  { BTN_CROSS,    false, 0 },
  { BTN_SQUARE,   false, 0 }
};

bool pressedEvent(Btn &b) {
  bool st = (digitalRead(b.pin) == LOW);
  unsigned long now = millis();
  if (st != b.last && now - b.t > DEBOUNCE_MS) {
    b.t = now;
    b.last = st;
    return st;  // true hanya saat baru ditekan
  }
  return false;
}

void computeResponse() {
  uint8_t digest[32];

#if defined(ESP32)
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1);
  mbedtls_md_hmac_starts(&ctx, (const unsigned char *)SECRET_KEY, strlen(SECRET_KEY));
  mbedtls_md_hmac_update(&ctx, chal, CHAL_LEN);
  mbedtls_md_hmac_finish(&ctx, digest);
  mbedtls_md_free(&ctx);
#elif defined(ESP8266)
  br_hmac_key_context kc;
  br_hmac_context hc;
  br_hmac_key_init(&kc, &br_sha256_vtable, SECRET_KEY, strlen(SECRET_KEY));
  br_hmac_init(&hc, &kc, 0);
  br_hmac_update(&hc, chal, CHAL_LEN);
  br_hmac_out(&hc, digest);
#endif

  for (int i = 0; i < RESP_LEN; i++) {
    resp[i] = (digest[i / 4] >> (2 * (i % 4))) & 3;
  }

  // Print ke Serial Monitor USB agar terbaca oleh Serial Bridge
  const char LETTERS[] = "TCXS";
  Serial.print("\n[KEYBCA TOKEN SOLVED] Challenge: ");
  for (int i = 0; i < CHAL_LEN; i++) Serial.print(LETTERS[chal[i]]);
  Serial.print(" -> Response: ");
  for (int i = 0; i < RESP_LEN; i++) Serial.print(LETTERS[resp[i]]);
  Serial.println();
}

void setPower(bool on) {
  powerOn = on;
  mode = MODE_INPUT;
  chalCount = 0;
  memset(resp, 0, sizeof(resp));
  if (on) {
    display.ssd1306_command(SSD1306_DISPLAYON);
  } else {
    display.clearDisplay();
    display.display();
    display.ssd1306_command(SSD1306_DISPLAYOFF);
  }
}

// Klik tombol merah
void onOK() {
  if (mode == MODE_INPUT) {
    if (chalCount > 0) chalCount--;   // hapus 1 simbol
  } else {
    mode = MODE_INPUT;                // challenge baru
    chalCount = 0;
  }
}

void drawShape(uint8_t s, int x, int y, int sz) {
  switch (s) {
    case 0: display.fillTriangle(x + sz / 2, y, x, y + sz, x + sz, y + sz, WHITE); break;
    case 1: display.drawCircle(x + sz / 2, y + sz / 2, sz / 2, WHITE); break;
    case 2:
      display.drawLine(x, y, x + sz, y + sz, WHITE);
      display.drawLine(x + sz, y, x, y + sz, WHITE);
      break;
    case 3: display.drawRect(x, y, sz, sz, WHITE); break;
  }
}

void render() {
  if (!powerOn) return;
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(WHITE);
  display.setCursor(0, 0);

  if (mode == MODE_INPUT) {
    display.printf("Challenge %d/%d", chalCount, CHAL_LEN);
    for (int i = 0; i < chalCount; i++) {
      drawShape(chal[i], 8 + i * 30, 22, 16);
    }
    display.setCursor(0, 50);
    display.print("OK = hapus 1");
  } else {
    display.print("Response (OK=baru)");
    for (int i = 0; i < RESP_LEN; i++) {
      drawShape(resp[i], 4 + (i % 6) * 20, 16 + (i / 6) * 24, 14);
    }
  }

  if (redDown && !holdDone && holdProgress > 0) {
    display.fillRect(0, 60, holdProgress, 4, WHITE);
  }
  display.display();
}

void handleRed() {
  bool pressed = (digitalRead(BTN_RED) == LOW);
  unsigned long now = millis();
  if (pressed && !redDown) {
    redDown = true;
    holdDone = false;
    redStart = now;
    holdProgress = 0;
  } else if (pressed && redDown) {
    unsigned long held = now - redStart;
    if (!holdDone) {
      holdProgress = (int)min(128UL, held * 128UL / HOLD_MS);
      if (held >= HOLD_MS) {
        holdDone = true;
        holdProgress = 0;
        setPower(!powerOn);
      }
    }
  } else if (!pressed && redDown) {
    unsigned long held = now - redStart;
    redDown = false;
    holdProgress = 0;
    if (!holdDone && held >= DEBOUNCE_MS && powerOn) {
      onOK();
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(BTN_TRIANGLE, INPUT_PULLUP);
  pinMode(BTN_CIRCLE, INPUT_PULLUP);
  pinMode(BTN_CROSS, INPUT_PULLUP);
  pinMode(BTN_SQUARE, INPUT_PULLUP);
  pinMode(BTN_RED, INPUT_PULLUP);

#if defined(ESP32)
  Wire.begin(21, 22);
#elif defined(ESP8266)
  Wire.begin(D2, D1); // SDA D2, SCL D1
#endif

  Wire.setClock(400000);
  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  setPower(false);

  Serial.println("\n[ENKRIPSIH] KeyBCA Token Ready (Tahan tombol merah 2 detik untuk menyalakan)");
}

void loop() {
  handleRed();
  for (int s = 0; s < 4; s++) {
    if (pressedEvent(symBtn[s]) && powerOn && mode == MODE_INPUT && chalCount < CHAL_LEN) {
      chal[chalCount++] = s;
      if (chalCount == CHAL_LEN) {
        computeResponse();
        mode = MODE_RESULT;
      }
    }
  }
  render();
  delay(10);
}

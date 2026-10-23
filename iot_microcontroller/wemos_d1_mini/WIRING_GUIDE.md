# Panduan Rangkaian Hardware KeyBCA (Wemos D1 Mini)

Perangkat ini bertindak sebagai **Token Pemecah Kode Kriptografi (KeyBCA Hardware)** untuk sistem **Enkripsih**.

---

### Komponen yang Digunakan:
1. **Board Mikrokontroler:** Wemos D1 Mini (ESP8266)
2. **Display (Opsional):** Layar OLED 0.96 inch I2C (SSD1306 128x64)
3. **Tombol:** 2x Push Button (Tactile Switch)
   - Tombol 1: Mode APPLI 1 (OTP Generator)
   - Tombol 2: Mode APPLI 2 (Challenge-Response)
4. **Buzzer (Opsional):** Piezo Buzzer 5V/3.3V untuk audio feedback klik
5. **Kabel Jumper & Breadboard**

---

### Diagram Pinout Wemos D1 Mini:

```
      +---------------------+
      |   WEMOS D1 MINI     |
      |                     |
      | [D1] (SCL) -------> OLED SCL
      | [D2] (SDA) -------> OLED SDA
      |                     |
      | [D5] -------------> Push Button APPLI 1 (Kaki lainnya ke GND)
      | [D6] -------------> Push Button APPLI 2 (Kaki lainnya ke GND)
      | [D7] -------------> Buzzer (+) (Kaki (-) ke GND)
      |                     |
      | [3V3] ------------> VCC OLED
      | [GND] ------------> GND OLED & Ground Tombol
      +---------------------+
```

---

### Cara Menguji Tanpa Komponen Eksternal (Hanya Wemos D1 Mini + Kabel USB):
Kamu bahkan **tidak wajib langsung memasang layar OLED atau tombol**! 
Sketsa `wemos_keybca.ino` sudah mendukung input/output langsung via **Serial USB**:
1. Buka Arduino IDE, upload file [wemos_keybca.ino](file:///e:/enkripsih/iot_microcontroller/wemos_d1_mini/wemos_keybca.ino).
2. Buka **Serial Monitor** di Arduino IDE pada baud rate `115200`.
3. Masukkan challenge code yang tertera di web Enkripsih:
   ```text
   APPLI 2 58193024
   ```
4. Wemos D1 Mini akan langsung menampilkan kalkulasi token:
   ```text
   [KEYBCA TOKEN CALCULATED]
   MODE      : APPLI 2 (CHALLENGE-RESPONSE)
   CHALLENGE : 58193024
   RESPONSE  : 74921083
   ```
5. Masukkan kode respon tersebut ke web Receiver untuk mendekripsi pesan!

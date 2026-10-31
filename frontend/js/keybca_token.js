/**
 * Enkripsih - Lexa Tactical Token (Device 2)
 * Features Symbol-based Challenge-Response:
 * Symbols: Triangle (△ / T), Circle (○ / C), Cross (✕ / X), Square (□ / S)
 * Matches the ESP32 / Wemos D1 Mini C++ sketch!
 */

const KeyBCAToken = {
  STATE_OFF: 'OFF',
  STATE_INPUT: 'INPUT',
  STATE_RESULT: 'RESULT',

  currentState: 'OFF',
  chalCount: 0,
  maxChal: 4,
  currentChal: [], // array of indices [0..3]
  responseIndices: [],
  responseLetters: '',
  responseSymbols: '',

  NAMES: ["△", "○", "✕", "□"], // taste-skill-ignore: operational crypto symbols
  LETTERS: "TCXS",

  init() {
    this.renderScreen();
    this.bindEvents();

    window.onIoTTokenSolved = (event) => {
      this.displayIoTResult(event);
    };
  },

  bindEvents() {
    // 4 Tactical Symbol Buttons
    document.querySelectorAll('.btn-key-sym').forEach(btn => {
      btn.addEventListener('click', () => {
        const sym = parseInt(btn.dataset.sym, 10);
        this.inputSymbol(sym);
      });
    });

    // Red Power / OK Button
    const btnRed = document.getElementById('keybcaBtnRed');
    if (btnRed) {
      btnRed.addEventListener('click', () => this.handleRedButton());
    }

    // Copy and IoT Sync buttons
    const btnCopyToken = document.getElementById('btnCopyKeybcaToken');
    const btnSyncIoT = document.getElementById('btnSyncIoTKeybca');

    if (btnCopyToken) {
      btnCopyToken.addEventListener('click', () => {
        if (!this.responseLetters) {
          showToast("Belum ada token respon yang dihitung!", "warning");
          return;
        }
        navigator.clipboard.writeText(this.responseLetters);
        showToast(`Token [${this.responseLetters}] disalin ke clipboard!`, "info");
      });
    }

    if (btnSyncIoT) {
      btnSyncIoT.addEventListener('click', () => this.syncToReceiver());
    }

    // Keyboard support: T, C, X, S keys or Numbers 0, 1, 2, 3
    window.addEventListener('keydown', (e) => {
      if (State.activeTab !== 'keybca') return;
      const k = e.key.toUpperCase();
      if (k === 'T' || k === '0') this.inputSymbol(0);
      else if (k === 'C' || k === '1' || k === 'O') this.inputSymbol(1);
      else if (k === 'X' || k === '2') this.inputSymbol(2);
      else if (k === 'S' || k === '3') this.inputSymbol(3);
      else if (k === 'ENTER' || k === 'BACKSPACE') this.handleRedButton();
    });
  },

  handleRedButton() {
    AudioSys.keybcaBeep();

    if (this.currentState === this.STATE_OFF) {
      // Turn ON
      this.currentState = this.STATE_INPUT;
      this.currentChal = [];
      this.chalCount = 0;
      this.renderScreen();
      showToast("Lexa aktif. Masukkan 4 simbol challenge.", "info");
      return;
    }

    if (this.currentState === this.STATE_INPUT) {
      // If symbols present, backspace/delete 1 symbol (matches C++ sketch onOK())
      if (this.currentChal.length > 0) {
        this.currentChal.pop();
        this.chalCount = this.currentChal.length;
      } else {
        // Turn OFF if empty
        this.currentState = this.STATE_OFF;
      }
    } else if (this.currentState === this.STATE_RESULT) {
      // Challenge baru (matches C++ sketch onOK())
      this.currentState = this.STATE_INPUT;
      this.currentChal = [];
      this.chalCount = 0;
    }

    this.renderScreen();
  },

  async inputSymbol(symIndex) {
    if (this.currentState === this.STATE_OFF) return;
    if (this.currentState === this.STATE_RESULT) return;

    AudioSys.keybcaBeep();

    if (this.currentChal.length < this.maxChal) {
      this.currentChal.push(symIndex);
      this.chalCount = this.currentChal.length;
      this.renderScreen();

      // If full 4 symbols entered, compute response immediately! (matches C++ computeResponse())
      if (this.currentChal.length === this.maxChal) {
        await this.computeResponse();
      }
    }
  },

  async computeResponse() {
    ProcessingModal.show("Menghitung respons Lexa…", 30);
    try {
      const chalStr = this.currentChal.map(i => this.LETTERS[i]).join('');
      const res = await fetch('/api/iot/keybca/calculate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ challenge: chalStr })
      });
      const data = await res.json();

      if (data.success) {
        AudioSys.tokenVerified();
        this.responseIndices = data.response_indices;
        this.responseLetters = data.response_letters;
        this.responseSymbols = data.response_symbols;
        this.currentState = this.STATE_RESULT;
        this.renderScreen();
        showToast(`Token Dihitung: ${this.responseLetters}`, "success");
      }
    } catch (e) {
      console.error(e);
      showToast("Gagal menghitung respon Lexa.", "error");
    } finally {
      ProcessingModal.hide();
    }
  },

  async syncToReceiver() {
    AudioSys.click();
    if (!this.responseLetters) {
      showToast("Hitung respon terlebih dahulu!", "warning");
      return;
    }

    const chalStr = this.currentChal.map(i => this.LETTERS[i]).join('');
    ProcessingModal.show("Menyinkronkan token ke receiver…", 40);
    try {
      const res = await fetch('/api/iot/keybca/solve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: 'VIRTUAL-KEYBCA',
          challenge: chalStr,
          token: this.responseLetters
        })
      });
      const data = await res.json();
      if (data.success) {
        AudioSys.tokenVerified();
        showToast("Token respon dipancarkan via IoT ke Receiver!", "success");
      }
    } catch (e) {
      console.error(e);
    } finally {
      ProcessingModal.hide();
    }
  },

  displayIoTResult(event) {
    this.responseLetters = event.token;
    this.currentState = this.STATE_RESULT;
    this.renderScreen();

    const logBox = document.getElementById('iotHardwareLogs');
    if (logBox) {
      const row = document.createElement('div');
      row.className = 'iot-log-row';
      const deviceSpan = document.createElement('span');
      deviceSpan.className = 'iot-log-device';
      deviceSpan.textContent = `[${event.device_id}]`;
      const challengeLabel = document.createTextNode(' Challenge: ');
      const challengeStrong = document.createElement('strong');
      challengeStrong.textContent = event.challenge;
      const arrowLabel = document.createTextNode(' \u2192 ');
      const tokenLabel = document.createTextNode(' Token: ');
      const tokenStrong = document.createElement('strong');
      tokenStrong.className = 'iot-log-token';
      tokenStrong.textContent = event.token;
      row.append(deviceSpan, challengeLabel, challengeStrong, arrowLabel, tokenLabel, tokenStrong);
      logBox.prepend(row);
    }
  },

  renderScreen() {
    const lcd = document.getElementById('keybcaLcd');
    const l1 = document.getElementById('lcdLine1');
    const l2 = document.getElementById('lcdLine2');
    if (!lcd || !l1 || !l2) return;

    if (this.currentState === this.STATE_OFF) {
      lcd.classList.add('screen-off');
      l1.textContent = "";
      l2.textContent = "";
      return;
    }

    lcd.classList.remove('screen-off');

    if (this.currentState === this.STATE_INPUT) {
      l1.textContent = `Challenge ${this.chalCount}/${this.maxChal} (OK=hapus)`;
      // Render symbols
      if (this.currentChal.length === 0) {
        l2.textContent = "_ _ _ _";
      } else {
        const syms = this.currentChal.map(i => this.NAMES[i]).join(' ');
        const letters = this.currentChal.map(i => this.LETTERS[i]).join('');
        l2.textContent = syms + ' (' + letters + ')';
      }
    } else if (this.currentState === this.STATE_RESULT) {
      l1.textContent = "Response (OK=baru)";
      const syms = this.responseIndices.map(i => this.NAMES[i]).join(' ');
      l2.innerHTML = '';
      const symsDiv = document.createElement('div');
      symsDiv.className = 'lcd-symbols';
      symsDiv.textContent = syms;
      const lettersDiv = document.createElement('div');
      lettersDiv.className = 'lcd-response';
      lettersDiv.textContent = this.responseLetters;
      l2.append(symsDiv, lettersDiv);
    }
  }
};

document.addEventListener('DOMContentLoaded', () => {
  KeyBCAToken.init();
});

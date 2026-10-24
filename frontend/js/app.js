/**
 * Enkripsih - Core Application Controller, WebSocket & Web Audio Synthesizer
 * Refined under tasteskill v2 (data-terminal)
 */

// Global State
const State = {
  activeTab: 'commander',
  ws: null,
  wsHeartbeat: null,
  isLoggedIn: false,
  role: null,
  principalId: null,
  commander: null,
  messages: [],
  audioEnabled: true
};

// Web Audio API Synthesizer (Zero external dependencies)
class TacticalAudio {
  constructor() {
    this.ctx = null;
  }

  init() {
    if (!this.ctx) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AudioContext();
    }
    if (this.ctx.state === 'suspended') {
      this.ctx.resume();
    }
  }

  playTone(freq = 1200, type = 'sine', duration = 0.05, gain = 0.1) {
    if (!State.audioEnabled) return;
    try {
      this.init();
      const osc = this.ctx.createOscillator();
      const g = this.ctx.createGain();
      osc.type = type;
      osc.frequency.setValueAtTime(freq, this.ctx.currentTime);
      g.gain.setValueAtTime(gain, this.ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.0001, this.ctx.currentTime + duration);
      osc.connect(g);
      g.connect(this.ctx.destination);
      osc.start();
      osc.stop(this.ctx.currentTime + duration);
    } catch (e) {
      console.warn("Audio error:", e);
    }
  }

  click() {
    this.playTone(1800, 'sine', 0.03, 0.05);
  }

  keybcaBeep() {
    this.playTone(2400, 'square', 0.04, 0.04);
  }

  accessGranted() {
    this.init();
    this.playTone(880, 'sine', 0.08, 0.1);
    setTimeout(() => this.playTone(1320, 'sine', 0.15, 0.15), 90);
  }

  accessDenied() {
    this.init();
    this.playTone(320, 'sawtooth', 0.15, 0.15);
    setTimeout(() => this.playTone(220, 'sawtooth', 0.25, 0.15), 160);
  }

  tokenVerified() {
    this.init();
    this.playTone(600, 'triangle', 0.06, 0.1);
    setTimeout(() => this.playTone(900, 'triangle', 0.08, 0.12), 70);
    setTimeout(() => this.playTone(1200, 'triangle', 0.18, 0.15), 150);
  }

  alarm() {
    this.init();
    for (let i = 0; i < 3; i++) {
      setTimeout(() => this.playTone(1000 - i * 150, 'sawtooth', 0.12, 0.15), i * 140);
    }
  }
}

const AudioSys = new TacticalAudio();

// Toast Notifications (Text-based status badges, no emojis)
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  
  let label = '[INFO]';
  if (type === 'success') label = '[SUCCESS]';
  if (type === 'error') label = '[ALERT]';
  if (type === 'warning') label = '[WARN]';

  const labelElement = document.createElement('span');
  labelElement.style.cssText = 'font-size:10px; font-weight:700; color:var(--muted);';
  labelElement.textContent = label;
  const messageElement = document.createElement('span');
  messageElement.textContent = message;
  toast.append(labelElement, document.createTextNode(' '), messageElement);
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(4px)';
    toast.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
    setTimeout(() => toast.remove(), 200);
  }, 4000);
}

// WebSocket Connection
function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  State.ws = new WebSocket(wsUrl);

  State.ws.onopen = () => {
    console.log("[WS] Terhubung ke Server Enkripsih WebSocket.");
    const led = document.getElementById('wsLed');
    if (led) {
      led.classList.remove('offline');
      led.title = "Koneksi Real-time Taktis Aktif";
    }
    clearInterval(State.wsHeartbeat);
    State.wsHeartbeat = setInterval(() => {
      if (State.ws && State.ws.readyState === WebSocket.OPEN) {
        State.ws.send(JSON.stringify({ type: 'PING' }));
      }
    }, 25000);
  };

  State.ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleWebSocketEvent(data);
    } catch (e) {
      console.error("[WS] Parse error:", e);
    }
  };

  State.ws.onclose = () => {
    console.warn("[WS] Koneksi terputus. Mencoba rekoneksi dalam 3 detik...");
    const led = document.getElementById('wsLed');
    if (led) {
      led.classList.add('offline');
      led.title = "Koneksi Terputus - Mencoba menyambung...";
    }
    clearInterval(State.wsHeartbeat);
    State.wsHeartbeat = null;
    State.ws = null;
    if (State.isLoggedIn) {
      setTimeout(() => {
        if (State.isLoggedIn) initWebSocket();
      }, 3000);
    }
  };
}

function handleWebSocketEvent(event) {
  console.log("[WS Event]", event);

  if (event.type === 'NEW_MESSAGE') {
    AudioSys.playTone(1400, 'sine', 0.1, 0.15);
    showToast(`Transmisi Masuk: [${event.message.id}] - Status Terkunci`, 'warning');
    if (window.loadMessages) window.loadMessages();
  }

  if (event.type === 'MESSAGE_BURNED') {
    AudioSys.alarm();
    showToast(`Pesan [${event.message_id}] Telah Dihancurkan (Self-Destruct)`, 'error');
    if (window.loadMessages) window.loadMessages();
  }

}

// Tab Switching (Marked by 1px bottom accent line)
function switchTab(tabName) {
  AudioSys.click();
  if (State.activeTab === 'members' && tabName !== 'members' && window.clearRecipientRegistrationSecret) {
    window.clearRecipientRegistrationSecret();
  }
  if (State.activeTab === 'receiver' && tabName !== 'receiver' && window.clearDecryptedMessages) {
    window.clearDecryptedMessages();
  }
  State.activeTab = tabName;

  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });

  document.querySelectorAll('.view-section').forEach(sec => {
    sec.classList.toggle('active', sec.id === `view-${tabName}`);
  });

  if (tabName === 'receiver' && window.loadMessages) {
    window.loadMessages();
  }
  if (tabName === 'commander' && window.loadCommanderMessages) {
    window.loadCommanderMessages();
  }
  if (tabName === 'members' && window.loadCommanderRecipients) {
    window.loadCommanderRecipients();
  }
}

// Clock updates (Military 24h format)
function updateTacticalClock() {
  const clockEl = document.getElementById('tacticalClock');
  if (!clockEl) return;
  const now = new Date();
  const timeStr = now.toLocaleTimeString('id-ID', { hour12: false }) + ' WIB';
  clockEl.textContent = timeStr;
}

// Initializer
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  setInterval(updateTacticalClock, 1000);
  updateTacticalClock();

});

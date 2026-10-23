/**
 * Enkripsih - Subordinate Receiver Controller (Device 3)
 * Displays encrypted intelligence transmissions, accepts 12-symbol KeyBCA tokens,
 * and performs cyber deciphering animations.
 * Refined under tasteskill v2 (data-terminal).
 */

const Receiver = {
  init() {
    const btnRefresh = document.getElementById('btnRefreshReceiverMsgs');
    if (btnRefresh) {
      btnRefresh.addEventListener('click', () => {
        AudioSys.click();
        this.loadMessages();
      });
    }

    window.loadMessages = () => this.loadMessages();
  },

  async loadMessages() {
    const listEl = document.getElementById('receiverMessageList');
    if (!listEl) return;

    try {
      const res = await fetch('/api/messages');
      const data = await res.json();
      const messages = data.messages || [];

      // Update badge count
      const badge = document.getElementById('receiverBadge');
      if (badge) {
        const lockedCount = messages.filter(m => m.status === 'LOCKED').length;
        badge.textContent = lockedCount > 0 ? `${lockedCount} Baru` : `${messages.length}`;
      }

      if (messages.length === 0) {
        listEl.innerHTML = `
          <div style="text-align:center; padding:40px; color:var(--muted); font-size:13px;">
            Belum ada pesan intelijen yang diterima dari Komandan.
          </div>
        `;
        return;
      }

      listEl.innerHTML = messages.map(msg => this.renderMessageCard(msg)).join('');
    } catch (err) {
      console.error("Load receiver messages error:", err);
    }
  },

  renderMessageCard(msg) {
    let badgeClass = 'priority-confidential';
    if (msg.priority.includes('TOP SECRET')) badgeClass = 'priority-top-secret';
    if (msg.priority.includes('URGENT')) badgeClass = 'priority-urgent';

    const isLocked = msg.status === 'LOCKED';
    const isUnlocked = msg.status === 'UNLOCKED';
    const isBurned = msg.status === 'BURNED';

    return `
      <div class="intel-card ${msg.status.toLowerCase()}" id="card-${msg.id}">
        <div class="intel-header">
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
            <span class="badge-priority ${badgeClass}">${msg.priority}</span>
            <span style="font-weight:700; color:var(--text);">${msg.id}</span>
            <span style="font-size:12px; color:var(--muted);">
              Dari: <strong>${msg.sender_name}</strong> &rarr; Untuk: <strong>${msg.target_unit}</strong>
            </span>
          </div>
          <div>
            ${isLocked ? '<span class="logo-badge" style="border-color:var(--warning); color:var(--warning); background:var(--pill-warning-bg);">TERENKRIPSI [AES-GCM]</span>' : ''}
            ${isUnlocked ? '<span class="logo-badge" style="border-color:var(--positive); color:var(--positive); background:var(--pill-positive-bg);">TERVERIFIKASI & TERBUKA</span>' : ''}
            ${isBurned ? '<span class="logo-badge" style="border-color:var(--negative); color:var(--negative); background:var(--pill-negative-bg);">DIHANCURKAN</span>' : ''}
          </div>
        </div>

        <div class="intel-body">
          <h3 style="font-size:15px; font-weight:600; margin-bottom:6px; color:var(--text);">${msg.subject}</h3>
          <div style="font-size:11px; color:var(--muted); margin-bottom:12px;">
            Waktu Transmisi: ${new Date(msg.created_at).toLocaleString('id-ID')}
          </div>

          ${isLocked ? this.renderLockedForm(msg) : ''}
          ${isUnlocked ? this.renderUnlockedIntel(msg) : ''}
          ${isBurned ? '<div style="color:var(--negative); font-size:13px;">[PESAN TELAH DIHANCURKAN SECARA AMAN - SELF DESTRUCTED]</div>' : ''}
        </div>
      </div>
    `;
  },

  renderLockedForm(msg) {
    return `
      <div class="challenge-highlight-box">
        <div>
          <div style="font-size:11px; color:var(--muted); font-weight:600; text-transform:uppercase;">
            KODE CHALLENGE (MASUKKAN KE KEYBCA):
          </div>
          <div class="challenge-code-display" style="font-size:24px; margin-top:2px;">
            ${msg.challenge_symbols}
            <span style="font-size:14px; color:var(--muted); font-weight:400;">(${msg.challenge_letters})</span>
          </div>
        </div>
        <button class="btn-tactical btn-tactical-secondary" style="font-size:11px; padding:5px 10px;" onclick="Receiver.copyChallenge('${msg.challenge_letters}')">
          Salin Huruf (${msg.challenge_letters})
        </button>
      </div>

      <div style="margin-top:12px; background:var(--ground); border:1px solid var(--border); border-radius:var(--radius-control); padding:12px;">
        <label class="form-label">OTORISASI KODE RESPON DARI KEYBCA (12 SIMBOL / HURUF):</label>
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
          <input type="text" class="form-input" id="token-input-${msg.id}" 
            placeholder="Contoh: TCXSSTCCXTSC" maxlength="16" 
            style="font-family:var(--font-mono); font-size:15px; font-weight:700; letter-spacing:1.5px; max-width:260px; color:var(--text); text-transform:uppercase;" />
          <button class="btn-tactical btn-tactical-primary" onclick="Receiver.submitDecrypt('${msg.id}')">
            DEKRIPSI DENGAN TOKEN KEYBCA
          </button>
        </div>
        <div style="font-size:11px; color:var(--muted); margin-top:6px;">
          Ketik huruf (T, C, X, S) atau paste 12 simbol yang tertera pada layar KeyBCA.
        </div>
      </div>
    `;
  },

  renderUnlockedIntel(msg) {
    return `
      <div class="decrypted-intel-box" id="intel-text-${msg.id}">
        <div style="font-size:11px; color:var(--positive); margin-bottom:6px; border-bottom:1px solid var(--border); padding-bottom:4px;">
          [KORIDOR RAHASIA TERBUKA - DEKRIPSI SUKSES PADA ${msg.decrypted_at ? new Date(msg.decrypted_at).toLocaleTimeString('id-ID') : 'WAKTU INI'}]
        </div>
        <div style="font-size:13px; line-height:1.6; color:var(--text);">${msg.plaintext || '[Pesan Terbuka]'}</div>
      </div>
      <div style="display:flex; justify-content:flex-end; margin-top:10px;">
        <button class="btn-tactical btn-tactical-danger" style="font-size:11px; padding:5px 12px;" onclick="Receiver.burnMessage('${msg.id}')">
          Hancurkan Pesan (Self-Destruct)
        </button>
      </div>
    `;
  },

  copyChallenge(code) {
    AudioSys.click();
    navigator.clipboard.writeText(code);
    showToast(`Challenge code [${code}] disalin ke clipboard`, "info");
  },

  async submitDecrypt(msgId) {
    AudioSys.click();
    const inputEl = document.getElementById(`token-input-${msgId}`);
    if (!inputEl) return;

    const token = inputEl.value.trim();
    if (!token) {
      showToast("Ketik 12-simbol kode respon KeyBCA terlebih dahulu!", "warning");
      return;
    }

    try {
      const res = await fetch(`/api/messages/${msgId}/decrypt`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: token })
      });

      const data = await res.json();
      if (data.success) {
        AudioSys.intelDecrypted();
        showToast("Token Valid. Pesan berhasil didekripsi.", "success");

        const card = document.getElementById(`card-${msgId}`);
        if (card) {
          this.playScrambleAnimation(card, data.plaintext, () => {
            this.loadMessages();
          });
        } else {
          this.loadMessages();
        }
      } else {
        AudioSys.accessDenied();
        showToast(data.message || "Kode respon KeyBCA salah!", "error");
      }
    } catch (err) {
      console.error("Decrypt error:", err);
      showToast("Kesalahan koneksi saat mendekripsi pesan.", "error");
    }
  },

  playScrambleAnimation(cardEl, finalText, onComplete) {
    const body = cardEl.querySelector('.intel-body');
    if (!body) {
      if (onComplete) onComplete();
      return;
    }

    const chars = "TCXS0123456789!@#$%^&*";
    let iterations = 0;
    const maxIterations = 16;

    const interval = setInterval(() => {
      let scramble = "";
      for (let i = 0; i < Math.min(finalText.length, 120); i++) {
        if (iterations > (i / 4)) {
          scramble += finalText[i];
        } else {
          scramble += chars[Math.floor(Math.random() * chars.length)];
        }
      }

      body.innerHTML = `
        <div style="background:var(--ground); border:1px solid var(--border); border-left:3px solid var(--positive); border-radius:var(--radius-card); padding:14px;">
          <div style="font-size:11px; color:var(--positive); margin-bottom:6px;">[MENDEKRIPSI DENGAN TOKEN KEYBCA...]</div>
          <div class="scramble-text" style="font-size:13px; font-family:var(--font-mono);">${scramble}</div>
        </div>
      `;

      iterations++;
      if (iterations >= maxIterations) {
        clearInterval(interval);
        if (onComplete) onComplete();
      }
    }, 50);
  },

  async burnMessage(msgId) {
    if (!confirm("Apakah Anda yakin ingin menghancurkan pesan intelijen ini secara permanen?")) {
      return;
    }

    AudioSys.click();
    try {
      const res = await fetch(`/api/messages/${msgId}/burn`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        AudioSys.alarm();
        showToast("Pesan intelijen berhasil dihancurkan", "error");
        this.loadMessages();
      }
    } catch (err) {
      console.error("Burn error:", err);
    }
  }
};

document.addEventListener('DOMContentLoaded', () => {
  Receiver.init();
});

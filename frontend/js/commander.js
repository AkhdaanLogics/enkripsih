/**
 * Enkripsih - Commander Transmission Controller (Device 1)
 * Drafts intelligence, triggers AES-GCM encryption, displays symbol challenge.
 * Styled under tasteskill v2 app-screens.
 */

const Commander = {
  init() {
    const form = document.getElementById('commanderTransmitForm');
    if (form) {
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        this.sendMessage();
      });
    }

    const btnRefresh = document.getElementById('btnRefreshCommanderMsgs');
    if (btnRefresh) {
      btnRefresh.addEventListener('click', () => this.loadMessages());
    }

    window.loadCommanderMessages = () => this.loadMessages();
  },

  async sendMessage() {
    AudioSys.click();
    const targetUnit = document.getElementById('targetUnit').value;
    const priority = document.getElementById('priorityLevel').value;
    const subject = document.getElementById('intelSubject').value;
    const plaintext = document.getElementById('intelMessage').value;

    if (!plaintext.trim()) {
      showToast("Pesan intelijen tidak boleh kosong!", "warning");
      return;
    }

    const btnSubmit = document.getElementById('btnTransmitIntel');
    btnSubmit.disabled = true;
    btnSubmit.innerHTML = '<span>Mengenkripsi...</span>';

    try {
      const res = await fetch('/api/messages/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sender_id: State.commander?.id || 'CMD-01',
          sender_name: State.commander?.name || 'Kolonel M. Haris',
          target_unit: targetUnit,
          priority: priority,
          subject: subject,
          plaintext: plaintext
        })
      });

      const data = await res.json();
      if (!res.ok || !data.success || !data.message_id) {
        throw new Error(data.detail || "Server menolak pengiriman pesan.");
      }

      const verifyRes = await fetch(`/api/messages/${encodeURIComponent(data.message_id)}`);
      const stored = await verifyRes.json();
      if (!verifyRes.ok || stored.id !== data.message_id || stored.status !== 'LOCKED' ||
          stored.encrypted !== true || stored.plaintext !== undefined) {
        throw new Error(`Pesan diterima server, tetapi penyimpanannya belum dapat diverifikasi. ID: ${data.message_id}`);
      }

      AudioSys.accessGranted();
      showToast(`Pesan tersimpan dan terenkripsi: ${data.message_id}`, 'success');
      this.displayTransmissionSuccess(data);

      document.getElementById('intelSubject').value = '';
      document.getElementById('intelMessage').value = '';
      this.loadMessages();
    } catch (err) {
      console.error("Transmit error:", err);
      AudioSys.accessDenied();
      showToast(err.message || "Kesalahan koneksi saat mentransmisikan pesan.", "error");
    } finally {
      btnSubmit.disabled = false;
      btnSubmit.innerHTML = '<span>ENKRIPSI & TRANSMISIKAN PESAN</span>';
    }
  },

  displayTransmissionSuccess(data) {
    const box = document.getElementById('lastTransmitNotice');
    if (!box) return;

    box.style.display = 'block';
    box.innerHTML = `
      <div style="background: var(--ground); border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: var(--radius-card); padding: 14px; margin-top: 14px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 6px;">
          <div style="font-weight:600; font-size:13px; color:var(--text); text-transform:uppercase;">
            Pesan terkirim dan tersimpan
          </div>
          <span class="logo-badge">PBKDF2 + AES-GCM</span>
        </div>
        <p style="font-size:12px; color:var(--muted); margin-bottom: 10px;">
          Server mengonfirmasi ciphertext tersimpan. Pesan menunggu token penerima untuk dibuka.
        </p>
        <div style="background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-control); padding:10px 14px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
          <div>
            <div style="font-size:11px; color:var(--muted);">KODE CHALLENGE (MASUKKAN KE KEYBCA):</div>
            <div style="font-size:22px; font-weight:700; color:var(--text); letter-spacing:3px;">
              ${data.challenge_symbols} 
              <span style="font-size:14px; color:var(--muted); font-weight:400;">(${data.challenge_letters})</span>
            </div>
          </div>
          <button class="btn-tactical btn-tactical-secondary" type="button" data-copy-challenge="${data.challenge_letters}">
            Salin kode
          </button>
        </div>
      </div>
    `;
    box.querySelector('[data-copy-challenge]').addEventListener('click', async (event) => {
      try {
        await navigator.clipboard.writeText(event.currentTarget.dataset.copyChallenge);
        showToast('Kode challenge disalin.', 'info');
      } catch (err) {
        console.error('Copy challenge error:', err);
        showToast('Kode tidak dapat disalin. Silakan salin manual.', 'error');
      }
    });
  },

  async loadMessages() {
    const listEl = document.getElementById('commanderSentList');
    if (!listEl) return;

    try {
      const res = await fetch('/api/messages');
      const data = await res.json();
      const messages = data.messages || [];

      if (messages.length === 0) {
        listEl.innerHTML = `<div style="text-align:center; padding:30px; color:var(--muted); font-size:13px;">Belum ada transmisi pesan yang dikirim.</div>`;
        return;
      }

      listEl.innerHTML = messages.map(msg => {
        let badgeClass = 'priority-confidential';
        if (msg.priority.includes('TOP SECRET')) badgeClass = 'priority-top-secret';
        if (msg.priority.includes('URGENT')) badgeClass = 'priority-urgent';

        let statusClass = 'locked';
        let statusBadge = '<span class="logo-badge" style="border-color:var(--warning); color:var(--warning); background:var(--pill-warning-bg);">TERKUNCI</span>';
        if (msg.status === 'UNLOCKED') {
          statusClass = 'unlocked';
          statusBadge = '<span class="logo-badge" style="border-color:var(--positive); color:var(--positive); background:var(--pill-positive-bg);">TERDEKRIPSI</span>';
        } else if (msg.status === 'BURNED') {
          statusClass = 'burned';
          statusBadge = '<span class="logo-badge" style="border-color:var(--negative); color:var(--negative); background:var(--pill-negative-bg);">DIHANCURKAN</span>';
        }

        return `
          <div class="intel-card ${statusClass}" style="margin-bottom: 10px;">
            <div class="intel-header">
              <div style="display:flex; align-items:center; gap:8px;">
                <span class="badge-priority ${badgeClass}">${msg.priority}</span>
                <span style="font-weight:600; font-size:12px;">${msg.id}</span>
                <span style="font-size:12px; color:var(--muted);">&rarr; ${msg.target_unit}</span>
              </div>
              <div>
                ${statusBadge}
              </div>
            </div>
            <div class="intel-body" style="padding:10px 14px;">
              <div style="font-weight:600; font-size:13px; margin-bottom:4px;">${msg.subject}</div>
              <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; color:var(--muted); flex-wrap:wrap; gap:4px;">
                <span>Challenge: <strong style="color:var(--text);">${msg.challenge_symbols}</strong> (${msg.challenge_letters})</span>
                <span>${new Date(msg.created_at).toLocaleTimeString('id-ID')}</span>
              </div>
            </div>
          </div>
        `;
      }).join('');
    } catch (err) {
      console.error("Load messages error:", err);
    }
  }
};

document.addEventListener('DOMContentLoaded', () => {
  Commander.init();
});

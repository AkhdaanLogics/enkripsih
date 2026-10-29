/**
 * Commander console: register recipient keys and encrypt messages in the browser.
 */
const Commander = {
  _pollTimer: null,

  init() {
    document.getElementById("commanderTransmitForm")
      ?.addEventListener("submit", event => {
        event.preventDefault();
        this.sendMessage();
      });
    document.getElementById("recipientRegisterForm")
      ?.addEventListener("submit", event => {
        event.preventDefault();
        this.registerRecipient();
      });
    document.getElementById("btnGenerateRecipientKey")
      ?.addEventListener("click", () => {
        document.getElementById("recipientSecretKey").value =
          MessageCrypto.generateSecret();
      });
    document.getElementById("btnCopyRegisteredKey")
      ?.addEventListener("click", () => this.copyRegisteredKey());
    document.getElementById("btnDismissRegisteredKey")
      ?.addEventListener("click", () => this.clearRegisteredKey());
    document.getElementById("btnDismissReceiverAccount")
      ?.addEventListener("click", () => this.clearReceiverAccountNotice());
    document.getElementById("btnRefreshCommanderMsgs")
      ?.addEventListener("click", () => this.loadMessages());
    document.getElementById("btnRefreshRecipients")
      ?.addEventListener("click", () => this.loadRecipients());
    window.loadCommanderMessages = () => this.loadMessages();
    window.loadCommanderRecipients = () => this.loadRecipients();
    window.clearCommanderSensitiveData = () => this.clearSensitiveData();
    window.clearRegisteredRecipientKey = () => this.clearRegisteredKey();
    window.clearRecipientRegistrationSecret = () => {
      document.getElementById("recipientSecretKey").value = "";
      this.clearRegisteredKey();
    };
    this.startPolling();
  },

  startPolling() {
    if (this._pollTimer) return;
    this._pollTimer = setInterval(() => {
      if (State.isLoggedIn && (State.activeTab === "commander" || State.activeTab === "members")) {
        this.loadMessages();
      }
    }, 15_000);
  },

  clearSensitiveData() {
    document.getElementById("recipientSecretKey").value = "";
    document.getElementById("senderSecretKey").value = "";
    document.getElementById("intelMessage").value = "";
    this.clearRegisteredKey();
    document.getElementById("lastTransmitNotice").replaceChildren();
  },

  clearRegisteredKey() {
    const output = document.getElementById("registeredKeyOutput");
    const password = document.getElementById("registeredReceiverPassword");
    const username = document.getElementById("registeredReceiverUsername");
    const notice = document.getElementById("registeredKeyNotice");
    if (output) output.textContent = "";
    if (password) password.textContent = "";
    if (username) username.textContent = "";
    if (notice) notice.hidden = true;
    this.clearReceiverAccountNotice();
  },

  clearReceiverAccountNotice() {
    document.getElementById("receiverAccountName").textContent = "";
    document.getElementById("receiverAccountUsername").textContent = "";
    document.getElementById("receiverAccountPassword").textContent = "";
    document.getElementById("receiverAccountNotice").hidden = true;
  },

  async requestJSON(url, options) {
    const response = await fetch(url, options);
    if (response.status === 401 && State.isLoggedIn) {
      if (window.AppAuth) AppAuth.logout("Sesi berakhir. Silakan masuk kembali.");
      throw new Error("Sesi berakhir.");
    }
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Permintaan gagal.");
    }
    return data;
  },

  async loadRecipients(selectedId = "") {
    const select = document.getElementById("recipientId");
    if (!select) return;
    try {
      const data = await this.requestJSON("/api/recipients");
      const list = document.getElementById("recipientList");
      select.replaceChildren();
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = data.recipients.length
        ? "Pilih anggota"
        : "Daftarkan anggota terlebih dahulu";
      select.append(placeholder);
      for (const recipient of data.recipients) {
        const option = document.createElement("option");
        option.value = recipient.id;
        option.textContent = recipient.name;
        select.append(option);
      }
      if (selectedId) select.value = selectedId;
      if (list) {
        list.replaceChildren();
        if (!data.recipients.length) {
          list.textContent = "Belum ada anggota terdaftar.";
        } else {
          const members = document.createElement("div");
          members.className = "recipient-list";
          for (const recipient of data.recipients) {
            const item = document.createElement("div");
            item.className = "recipient-row";

            const info = document.createElement("div");
            info.className = "recipient-info";
            const name = document.createElement("strong");
            name.className = "recipient-name";
            name.textContent = recipient.name;
            const hint = document.createElement("span");
            hint.className = "recipient-meta";
            hint.textContent = "Secret key dan password tidak dapat dipulihkan";
            info.append(name, hint);

            const actionRow = document.createElement("div");
            actionRow.className = "recipient-actions";

            const accountButton = document.createElement("button");
            accountButton.type = "button";
            accountButton.className = "btn-tactical btn-tactical-secondary";
            accountButton.textContent = "Reset akun";
            accountButton.title = "Reset password akun receiver untuk anggota ini";
            accountButton.addEventListener("click", () => this.issueReceiverAccount(recipient));

            const reissueButton = document.createElement("button");
            reissueButton.type = "button";
            reissueButton.className = "btn-tactical btn-tactical-secondary";
            reissueButton.textContent = "Reset kunci";
            reissueButton.title = "Hasilkan kunci secret baru (pesan lama tidak bisa dibuka)";
            reissueButton.addEventListener("click", () => this.reissueRecipientKey(recipient));

            const deleteButton = document.createElement("button");
            deleteButton.type = "button";
            deleteButton.className = "btn-tactical btn-tactical-secondary recipient-delete-btn";
            deleteButton.textContent = "Hapus";
            deleteButton.title = "Hapus anggota dan semua pesannya";
            deleteButton.addEventListener("click", () => this.deleteRecipient(recipient));

            actionRow.append(accountButton, reissueButton, deleteButton);
            item.append(info, actionRow);
            members.append(item);
          }
          list.append(members);
        }
      }
    } catch (error) {
      console.error("Load recipient keys error:", error);
      showToast(error.message || "Gagal memuat daftar anggota.", "error");
    }
  },

  async registerRecipient() {
    AudioSys.click();
    const nameInput = document.getElementById("recipientName");
    const keyInput = document.getElementById("recipientSecretKey");
    const button = document.getElementById("btnRegisterRecipient");
    const name = nameInput.value.trim();
    let secret = keyInput.value.trim();
    if (!name) {
      showToast("Nama anggota wajib diisi.", "warning");
      return;
    }
    if (secret.length < 32) {
      showToast("Gunakan secret key minimal 32 karakter atau buat kunci acak.", "warning");
      return;
    }

    this.clearRegisteredKey();
    button.disabled = true;
    try {
      const salt = MessageCrypto.toHex(MessageCrypto.randomBytes(16));
      const verifier = await MessageCrypto.verifier(secret, salt);
      const result = await this.requestJSON("/api/recipients/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, salt, verifier }),
      });
      if (
        typeof result.username !== "string"
        || !result.username
        || typeof result.temporary_password !== "string"
        || !result.temporary_password
      ) {
        await this.loadRecipients();
        throw new Error(
          "Backend yang berjalan masih versi lama. Anggota mungkin sudah tersimpan, tetapi password belum dibuat. Restart server, refresh daftar anggota, lalu gunakan Buat/reset akun receiver. Jangan daftarkan nama yang sama lagi."
        );
      }
      document.getElementById("registeredKeyOutput").textContent = secret;
      document.getElementById("registeredKeyNotice").hidden = false;
      document.getElementById("registeredKeyName").textContent = result.name;
      document.getElementById("registeredReceiverUsername").textContent = result.username;
      document.getElementById("registeredReceiverPassword").textContent =
        result.temporary_password;
      nameInput.value = "";
      keyInput.value = "";
      showToast("Anggota terdaftar. Salin kunci dan bagikan melalui jalur aman.", "success");
      AudioSys.accessGranted();
      await this.loadRecipients(result.recipient_id);
    } catch (error) {
      console.error("Register recipient key error:", error);
      showToast(error.message || "Pendaftaran anggota gagal.", "error");
    } finally {
      secret = "";
      button.disabled = false;
    }
  },

  async copyRegisteredKey() {
    const secret = document.getElementById("registeredKeyOutput").textContent;
    try {
      await navigator.clipboard.writeText(secret);
      showToast("Kunci disalin. Bagikan kepada anggota lewat jalur aman.", "success");
    } catch (error) {
      console.error("Copy registered key error:", error);
      showToast("Kunci tidak dapat disalin. Salin manual dari layar ini.", "error");
    }
  },

  async issueReceiverAccount(recipient) {
    if (!confirm(`Buat/reset akun receiver untuk ${recipient.name}? Sesi aktif anggota akan dihentikan.`)) {
      return;
    }
    if (document.getElementById("registeredKeyNotice").hidden === false) {
      this.clearRegisteredKey();
    }
    this.clearReceiverAccountNotice();
    try {
      const result = await this.requestJSON(
        `/api/recipients/${encodeURIComponent(recipient.id)}/account`,
        { method: "POST" }
      );
      document.getElementById("receiverAccountName").textContent = recipient.name;
      document.getElementById("receiverAccountUsername").textContent = result.username;
      document.getElementById("receiverAccountPassword").textContent =
        result.temporary_password;
      document.getElementById("receiverAccountNotice").hidden = false;
      showToast("Password sementara dibuat. Bagikan secara aman dan terpisah.", "success");
    } catch (error) {
      console.error("Receiver account provisioning error:", error);
      showToast(error.message || "Akun receiver tidak dapat dibuat.", "error");
    }
  },

  async reissueRecipientKey(recipient) {
    if (!confirm(
      `Reset secret key untuk ${recipient.name}?\n\n` +
      "Kunci baru akan digenerate otomatis dan hanya ditampilkan sekali. " +
      "Pesan lama yang masih LOCKED tetap bisa dibuka dengan kunci lama, " +
      "tapi pesan baru wajib pakai kunci baru."
    )) {
      return;
    }
    AudioSys.click();
    if (document.getElementById("registeredKeyNotice").hidden === false) {
      this.clearRegisteredKey();
    }
    try {
      const result = await this.requestJSON(
        `/api/recipients/${encodeURIComponent(recipient.id)}/reissue`,
        { method: "POST" }
      );
      document.getElementById("registeredKeyOutput").textContent = result.new_secret_key;
      document.getElementById("registeredKeyName").textContent = recipient.name;
      document.getElementById("registeredKeyNotice").hidden = false;
      showToast("Kunci baru dibuat. Salin dan bagikan ke anggota lewat jalur aman.", "success");
      AudioSys.accessGranted();
      await this.loadRecipients();
    } catch (error) {
      console.error("Reissue recipient key error:", error);
      showToast(error.message || "Gagal me-reissue kunci.", "error");
    }
  },

  async deleteRecipient(recipient) {
    const msgCount = prompt(
      `Hapus anggota ${recipient.name} beserta semua pesan terkait?\n\n` +
      "Ketik 'HAPUS' untuk konfirmasi. Aksi ini tidak bisa dipulihkan.",
      ""
    );
    if (msgCount !== "HAPUS") {
      showToast("Penghapusan dibatalkan.", "info");
      return;
    }
    AudioSys.click();
    try {
      const result = await this.requestJSON(
        `/api/recipients/${encodeURIComponent(recipient.id)}`,
        { method: "DELETE" }
      );
      showToast(
        `Anggota dihapus. ${result.deleted_messages} pesan terkait juga terhapus.`,
        "success"
      );
      AudioSys.accessGranted();
      // Clear commander select if the deleted recipient was selected
      const select = document.getElementById("recipientId");
      if (select && select.value === recipient.id) {
        select.value = "";
      }
      await this.loadRecipients();
      this.loadMessages();
    } catch (error) {
      console.error("Delete recipient error:", error);
      showToast(error.message || "Gagal menghapus anggota.", "error");
    }
  },

  runInWorker(action, data) {
    const worker = window.__cryptoWorker;
    if (!worker) {
      throw new Error("Web Worker tidak tersedia di browser ini.");
    }
    return new Promise((resolve, reject) => {
      const handler = (event) => {
        const msg = event.data || {};
        if (msg.action === "result" || msg.action === "error") {
          worker.removeEventListener("message", handler);
          if (msg.action === "error") {
            reject(new Error(msg.error || "Worker error"));
          } else {
            resolve(msg.result);
          }
        }
      };
      worker.addEventListener("message", handler);
      worker.postMessage({ action, ...data });
    });
  },

  async sendMessage() {
    AudioSys.click();
    const recipientId = document.getElementById("recipientId").value;
    const keyInput = document.getElementById("senderSecretKey");
    const messageInput = document.getElementById("intelMessage");
    const plaintext = messageInput.value;
    let secret = keyInput.value.trim();
    const button = document.getElementById("btnTransmitIntel");
    if (!recipientId) {
      showToast("Pilih anggota penerima yang sudah terdaftar.", "warning");
      return;
    }
    if (!plaintext.trim()) {
      showToast("Isi pesan tidak boleh kosong.", "warning");
      return;
    }
    if (secret.length < 32) {
      showToast("Masukkan secret key anggota minimal 32 karakter.", "warning");
      return;
    }
    button.disabled = true;
    const originalBtnHTML = button.innerHTML;
    button.innerHTML = `
      <div class="progress-indicator">
        <span class="progress-step" id="stepVerify">…</span>
        <span class="progress-line"></span>
        <span class="progress-step" id="stepEncrypt">…</span>
        <span class="progress-line"></span>
        <span class="progress-step" id="stepSave">…</span>
      </div>
      <span id="progressLabel">Memverifikasi anggota...</span>
    `;
    function setStep(step, label, done = false) {
      document.querySelectorAll('.progress-step').forEach(s => {
        if (s.id !== step) { s.style.color = 'var(--dim)'; s.style.fontWeight = 'normal'; s.textContent = s.textContent === '✓' ? '✓' : '…'; }
      });
      const activeStep = document.getElementById(step);
      if (activeStep) {
        activeStep.style.color = done ? 'var(--positive)' : 'var(--accent)';
        activeStep.style.fontWeight = '700';
        activeStep.textContent = done ? '✓' : '…';
      }
      const labelEl = document.getElementById('progressLabel');
      if (labelEl) labelEl.textContent = label;
    }
    try {
      setStep('stepVerify', 'Memverifikasi anggota...');
      // Single backend call handles: verify + challenge + response + PBKDF2 600k + AES-GCM + save
      const result = await this.requestJSON("/api/messages/encrypt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plaintext,
          recipient_id: recipientId,
          secret_key: secret,
          save: true,
        }),
      });

      setStep('stepVerify', 'Verifikasi ✓', true);
      setStep('stepEncrypt', 'Menghitung kunci & enkripsi...');

      // Now PBKDF2 + AES runs on server — instant for the user
      setStep('stepEncrypt', 'Enkripsi ✓', true);
      setStep('stepSave', 'Menyimpan ciphertext...', true);

      const recipient = result; // backend already returned target_unit
      const targetUnit = result.target_unit || recipientId;
      AudioSys.accessGranted();
      showToast(`Ciphertext tersimpan untuk ${targetUnit}: ${result.saved.message_id}`, "success");
      this.displayTransmissionSuccess({
        message_id: result.saved.message_id,
      }, targetUnit, result.challenge_indices);
      messageInput.value = "";
      keyInput.value = "";
      setStep('stepSave', 'Selesai ✓', true);
      await this.loadMessages();
    } catch (error) {
      console.error("Transmit error:", error);
      AudioSys.accessDenied();
      showToast(error.message || "Gagal mengenkripsi atau mengirim pesan.", "error");
    } finally {
      secret = "";
      button.disabled = false;
      button.innerHTML = originalBtnHTML;
    }
  },

  displayTransmissionSuccess(data, recipientName, challengeIndices, passkey) {
    const box = document.getElementById("lastTransmitNotice");
    if (!box) return;
    box.replaceChildren();
    const notice = document.createElement("div");
    notice.className = "transmission-notice";
    const heading = document.createElement("strong");
    heading.textContent = "Ciphertext tersimpan";
    const details = document.createElement("p");
    details.textContent = `${data.message_id} · Untuk ${recipientName}. Isi pesan tidak dikirim dalam bentuk plaintext.`;
    const challenge = document.createElement("p");
    challenge.textContent = `Challenge 4 simbol (bagikan ke receiver): ${Array.from(challengeIndices, index =>
      MessageCrypto.symbols[index]
    ).join(" ")}`;
    const guidance = document.createElement("p");
    guidance.textContent = "Receiver menginput challenge ke perangkat passkey, lalu menyetel 12 simbol respons yang tampil di perangkat ke kotak input di kotak masuknya untuk membuka pesan.";
    notice.append(heading, details, challenge, guidance);
    box.append(notice);
    box.style.display = "block";
  },

  async loadMessages() {
    const list = document.getElementById("commanderSentList");
    if (!list) return;
    try {
      const data = await this.requestJSON("/api/messages");
      list.replaceChildren();
      if (!data.messages.length) {
        list.textContent = "Belum ada pesan terkirim.";
        return;
      }
      for (const message of data.messages) {
        const row = document.createElement("div");
        row.className = `intel-card ${message.status.toLowerCase()}`;
        const header = document.createElement("div");
        header.className = "intel-header";
        const destination = document.createElement("span");
        destination.textContent = `${message.id} · ${message.target_unit}`;
        const status = document.createElement("span");
        status.className = `logo-badge status-badge ${message.status.toLowerCase()}`;
        status.textContent = {
          LOCKED: "TERENKRIPSI",
          UNLOCKED: "DIBUKA",
          BURNED: "DIHANCURKAN",
          LEGACY: "FORMAT LAMA",
        }[message.status] || message.status;
        header.append(destination, status);
        const details = document.createElement("div");
        details.className = "intel-body";
        details.textContent = new Date(message.created_at).toLocaleString("id-ID");
        row.append(header, details);
        list.append(row);
      }
    } catch (error) {
      console.error("Load messages error:", error);
      showToast(error.message || "Gagal memuat riwayat pesan.", "error");
    }
  },
};

document.addEventListener("DOMContentLoaded", () => Commander.init());

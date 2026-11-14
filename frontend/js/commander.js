/**
 * Commander console: register recipient keys and encrypt messages in the browser.
 */
const Commander = {
  _pollTimer: null,
  _agentKeys: null,

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
      ?.addEventListener("click", () => this.loadMessages({ trigger: "manual" }));
    document.getElementById("btnRefreshRecipients")
      ?.addEventListener("click", () => this.loadRecipients());
    document.getElementById("recipientId")
      ?.addEventListener("change", () => this._onRecipientChange());
    window.loadCommanderMessages = () => this.loadMessages();
    window.loadCommanderRecipients = () => this.loadRecipients();
    window.clearCommanderSensitiveData = () => this.clearSensitiveData();
    window.clearRegisteredRecipientKey = () => this.clearRegisteredKey();
    window.clearRecipientRegistrationSecret = () => {
      document.getElementById("recipientSecretKey").value = "";
      this.clearRegisteredKey();
    };
    this._fetchAgentKeys();
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
    document.getElementById("intelMessage").value = "";
    this.clearRegisteredKey();
    document.getElementById("lastTransmitNotice")?.replaceChildren();
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
    ProcessingModal.show("Memuat daftar anggota…", 30);
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
         const scrollWrap = document.createElement("div");
         scrollWrap.className = "members-list-scroll";
         list.appendChild(scrollWrap);
         if (!data.recipients.length) {
          const empty = document.createElement("div");
          empty.className = "list-placeholder";
          const icon = document.createElement("div");
          icon.className = "list-placeholder-icon";
          icon.setAttribute("aria-hidden", "true");
          icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>';
          const title = document.createElement("div");
          title.className = "list-placeholder-text";
          title.textContent = "Belum ada anggota";
          const sub = document.createElement("div");
          sub.className = "list-placeholder-sub";
          sub.textContent = "Daftarkan anggota di panel sebelah kiri untuk mulai mengirim pesan terenkripsi.";
          empty.append(icon, title, sub);
           scrollWrap.append(empty);
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
            info.append(name);

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
           scrollWrap.append(members);
        }
      }
      } catch (error) {
       console.error("Load recipient keys error:", error);
       const list = document.getElementById("recipientList");
       if (list) {
         list.replaceChildren();
         const err = document.createElement("div");
         err.className = "list-error";
         err.setAttribute("role", "alert");
         const msg = document.createElement("p");
         msg.textContent = "Gagal memuat daftar anggota.";
         const retry = document.createElement("button");
         retry.type = "button";
         retry.className = "btn-tactical btn-tactical-secondary";
         retry.textContent = "Coba lagi";
         retry.addEventListener("click", () => this.loadRecipients());
         err.append(msg, retry);
         list.append(err);
       }
       showToast(error.message || "Gagal memuat daftar anggota.", "error");
     } finally {
      ProcessingModal.hide();
    }
    this._refreshAgentKeyHint();
    // If agent keys are already loaded, trigger a visual update (badge if any)
    if (select && select.value && this._agentKeys) {
      this._onRecipientChange();
    }
  },

  async _fetchAgentKeys(retries = 2, delayMs = 500) {
    // Agent keys are commander-only. Receivers (and the unauthenticated
    // pre-login page load) must not hit /api/agent-keys: it just produces
    // avoidable 401/403 noise in the receiver console.
    if (State.role !== "COMMANDER") return;
    for (let i = 0; i <= retries; i++) {
      try {
        const data = await this.requestJSON("/api/agent-keys");
        this._agentKeys = {};
        for (const entry of data.agent_keys || []) {
          this._agentKeys[entry.recipient_id] = entry.key;
        }
        this._refreshAgentKeyHint();
        // If a recipient is already selected, trigger auto-fill now that keys are ready
        const select = document.getElementById("recipientId");
        if (select && select.value) {
          this._onRecipientChange();
        }
        return;
      } catch (e) {
        if (i < retries) {
          await new Promise((r) => setTimeout(r, delayMs * (i + 1)));
        }
      }
    }
    console.warn("Gagal memuat kunci agen setelah", retries + 1, "percobaan.");
  },

  _onRecipientChange() {
    const select = document.getElementById("recipientId");
    if (!select) return;
    this._refreshAgentKeyHint();
  },

  _refreshAgentKeyHint() {
    const select = document.getElementById("recipientId");
    const hint = document.getElementById("agentHint");
    if (!select || !hint) return;
    const rid = select.value;
    const isAgent = this._agentKeys && rid && this._agentKeys[rid];
    hint.style.display = isAgent ? "block" : "none";
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
    ProcessingModal.show("Mendaftarkan anggota…", 30);
    try {
      const salt = MessageCrypto.toHex(MessageCrypto.randomBytes(16));
      const verifier = await MessageCrypto.verifier(secret, salt);
      const result = await this.requestJSON("/api/recipients/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, salt, verifier, secret_key: secret }),
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
      ProcessingModal.update("Menyimpan data akun receiver…", 80);
      await this.loadRecipients(result.recipient_id);
    } catch (error) {
      console.error("Register recipient key error:", error);
      showToast(error.message || "Pendaftaran anggota gagal.", "error");
    } finally {
      ProcessingModal.hide();
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
    showConfirmDialog(
      `Buat/reset akun receiver untuk ${recipient.name}?\n\nSesi aktif anggota akan dihentikan.`,
      async () => {
        if (document.getElementById("registeredKeyNotice").hidden === false) {
          this.clearRegisteredKey();
        }
        this.clearReceiverAccountNotice();
        ProcessingModal.show("Membuat akun receiver…", 50);
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
        } finally {
          ProcessingModal.hide();
        }
      }
    );
  },

  async reissueRecipientKey(recipient) {
    showConfirmDialog(
      `Reset secret key untuk ${recipient.name}?\n\nKunci baru akan digenerate otomatis dan hanya ditampilkan sekali. Pesan lama yang masih LOCKED tetap bisa dibuka dengan kunci lama, tapi pesan baru wajib pakai kunci baru.`,
      async () => {
        AudioSys.click();
        ProcessingModal.show("Me-reset kunci anggota…", 40);
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
        } finally {
          ProcessingModal.hide();
        }
      }
    );
  },

  async deleteRecipient(recipient) {
    const msgCount = await showConfirmDialog(
      `Hapus anggota ${recipient.name} beserta semua pesan terkait?\n\nKetik HAPUS di bawah ini untuk konfirmasi. Aksi ini tidak bisa dipulihkan.`,
      () => this._executeDeleteRecipient(recipient)
    );
  },

  async _executeDeleteRecipient(recipient) {
    AudioSys.click();
    ProcessingModal.show("Menghapus anggota & pesan terkait…", 50);
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
      const select = document.getElementById("recipientId");
      if (select && select.value === recipient.id) {
        select.value = "";
      }
      await this.loadRecipients();
      this.loadMessages();
    } catch (error) {
      console.error("Delete recipient error:", error);
      showToast(error.message || "Gagal menghapus anggota.", "error");
    } finally {
      ProcessingModal.hide();
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
    const messageInput = document.getElementById("intelMessage");
    const plaintext = messageInput.value;
    const button = document.getElementById("btnTransmitIntel");
    if (!recipientId) {
      showToast("Pilih anggota penerima yang sudah terdaftar.", "warning");
      return;
    }
    if (!plaintext.trim()) {
      showToast("Isi pesan tidak boleh kosong.", "warning");
      return;
    }
    button.disabled = true;
    ProcessingModal.show("Memverifikasi anggota…", 20);

    try {
      ProcessingModal.update("Memverifikasi anggota…", 35);
      // Use agent-key endpoint when the selected recipient has a server-side key.
      const agentKey = this._agentKeys && this._agentKeys[recipientId];
      const isAgent = !!agentKey;
      let endpoint, body;
      if (isAgent) {
        endpoint = "/api/messages/encrypt-agent";
        body = JSON.stringify({ plaintext, recipient_id: recipientId, save: true });
      } else {
        // Agent key belum ada di server. Coba fetch ulang sekali; kalau masih
        // tidak ada, minta Sender daftar dulu di tab members.
        await this._fetchAgentKeys();
        const retryKey = this._agentKeys && this._agentKeys[recipientId];
        if (retryKey) {
          endpoint = "/api/messages/encrypt-agent";
          body = JSON.stringify({ plaintext, recipient_id: recipientId, save: true });
        } else {
          ProcessingModal.hide();
          showToast(
            "Anggota ini belum punya agent key. Daftar dulu di tab Members, lalu kirim lagi.",
            "warning",
          );
          button.disabled = false;
          return;
        }
      }

      ProcessingModal.update("Mengenkripsi & mengirim ke receiver…", 60);
      const result = await this.requestJSON(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });

      ProcessingModal.update("Menyimpan ciphertext…", 90);
      const targetUnit = result.target_unit || recipientId;
      AudioSys.accessGranted();
      showToast(`Ciphertext tersimpan untuk ${targetUnit}: ${result.saved.message_id}`, "success");
       this.displayTransmissionSuccess({
        message_id: result.saved.message_id,
      }, targetUnit, result.challenge_indices);
      messageInput.value = "";
      ProcessingModal.update("Selesai!", 100);
      await this.loadMessages();
    } catch (error) {
      console.error("Transmit error:", error);
      AudioSys.accessDenied();
      showToast(error.message || "Gagal mengenkripsi atau mengirim pesan.", "error");
    } finally {
      ProcessingModal.hide();
      button.disabled = false;
    }
  },

  displayTransmissionSuccess(data, recipientName, challengeIndices, passkey) {
    showSuccessModal("Pesan terkirim", `Untuk ${recipientName}`);
  },

  async loadMessages({ trigger = "poll" } = {}) {
    const list = document.getElementById("commanderSentList");
    if (!list) return;
    const showProgress = trigger === "manual";
    if (showProgress) ProcessingModal.show("Memuat riwayat pesan…", 30);
    try {
      const data = await this.requestJSON("/api/messages");
      const messageIds = data.messages.map(m => m.id).join(",");
      if (list.dataset.loadedIds !== messageIds) {
        list.replaceChildren();
        if (!data.messages.length) {
          const empty = document.createElement("div");
          empty.className = "list-placeholder";
          const icon = document.createElement("div");
          icon.className = "list-placeholder-icon";
          icon.setAttribute("aria-hidden", "true");
          icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 10h8M8 14h5"/></svg>';
          const title = document.createElement("div");
          title.className = "list-placeholder-text";
          title.textContent = "Belum ada transmisi";
          const sub = document.createElement("div");
          sub.className = "list-placeholder-sub";
          sub.textContent = "Kirim pesan pertama di panel sebelah kiri. Ciphertext akan muncul di sini secara real-time.";
          empty.append(icon, title, sub);
          list.append(empty);
          list.dataset.loadedIds = messageIds;
          return;
        }
        for (const message of data.messages) {
          const row = document.createElement("div");
          row.className = `intel-card ${message.status.toLowerCase()}`;
          const header = document.createElement("div");
          header.className = "intel-header";
          const destination = document.createElement("span");
          destination.className = "destination";
          destination.textContent = `${message.id} · ${message.target_unit}`;
          const status = document.createElement("span");
          status.className = `status-badge ${message.status.toLowerCase()}`;
          status.textContent = {
            LOCKED: "TERENKRIPSI",
            UNLOCKED: "DIBUKA",
            BURNED: "DIHANCURKAN",
            LEGACY: "FORMAT LAMA",
          }[message.status] || message.status;
          header.append(destination, status);
          const details = document.createElement("div");
          details.className = "intel-body";
          const ts = document.createElement("span");
          ts.textContent = new Date(message.created_at).toLocaleString("id-ID", { timeZone: "Asia/Jakarta" });
          details.append(ts);
          row.append(header, details);
          list.append(row);
        }
        list.dataset.loadedIds = messageIds;
      }
    } catch (error) {
      console.error("Load messages error:", error);
      if (trigger === "manual") {
        list.replaceChildren();
        const err = document.createElement("div");
        err.className = "list-error";
        err.setAttribute("role", "alert");
        const msg = document.createElement("p");
        msg.textContent = "Gagal memuat riwayat pesan.";
        const retry = document.createElement("button");
        retry.type = "button";
        retry.className = "btn-tactical btn-tactical-secondary";
        retry.textContent = "Coba lagi";
        retry.addEventListener("click", () => this.loadMessages({ trigger: "manual" }));
        err.append(msg, retry);
        list.append(err);
      }
      showToast(error.message || "Gagal memuat riwayat pesan.", "error");
    } finally {
      if (showProgress) ProcessingModal.hide();
    }
  },
};

document.addEventListener("DOMContentLoaded", () => Commander.init());

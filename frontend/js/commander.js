/**
 * Commander console: register recipient keys and encrypt messages in the browser.
 */
const Commander = {
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
          const members = document.createElement("ul");
          members.className = "recipient-list";
          for (const recipient of data.recipients) {
            const item = document.createElement("li");
            const name = document.createElement("strong");
            name.textContent = recipient.name;
            const hint = document.createElement("span");
            hint.textContent = "Secret key dan password tidak dapat dipulihkan";
            const resetButton = document.createElement("button");
            resetButton.type = "button";
            resetButton.className = "btn-tactical btn-tactical-secondary";
            resetButton.textContent = "Buat/reset akun receiver";
            resetButton.addEventListener("click", () => {
              this.issueReceiverAccount(recipient);
            });
            item.append(name, hint, resetButton);
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
    button.textContent = "MENGENKRIPSI DI BROWSER...";
    try {
      const recipients = await this.requestJSON("/api/recipients");
      const recipient = recipients.recipients.find(item => item.id === recipientId);
      if (!recipient) throw new Error("Anggota tidak ditemukan. Muat ulang daftar anggota.");

      const verifier = await MessageCrypto.verifier(secret, recipient.salt);
      const verification = await this.requestJSON(
        `/api/recipients/${encodeURIComponent(recipientId)}/verify`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ verifier }),
        }
      );
      if (!verification.valid) {
        throw new Error("Secret key tidak cocok dengan kunci anggota yang terdaftar.");
      }

      const challengeIndices = Array.from(
        MessageCrypto.randomBytes(4),
        byte => byte & 3
      );
      const paket = await MessageCrypto.encrypt(
        plaintext,
        secret,
        recipientId,
        challengeIndices
      );
      const sent = await this.requestJSON("/api/messages/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sender_id: State.commander?.id || "CMD-01",
          sender_name: State.commander?.name || "Komandan",
          recipient_id: recipientId,
          paket,
        }),
      });
      const stored = await this.requestJSON(
        `/api/messages/${encodeURIComponent(sent.message_id)}`
      );
      const storedPacket = await this.requestJSON(
        `/api/messages/${encodeURIComponent(sent.message_id)}/ciphertext`
      );
      if (
        stored.id !== sent.message_id ||
        stored.recipient_id !== recipientId ||
        stored.status !== "LOCKED" ||
        stored.encrypted !== true ||
        "paket" in stored ||
        "subject" in stored ||
        "priority" in stored ||
        storedPacket.recipient_id !== recipientId ||
        storedPacket.paket !== paket
      ) {
        throw new Error("Ciphertext terkirim, tetapi penyimpanannya belum dapat diverifikasi.");
      }

      AudioSys.accessGranted();
      showToast(`Ciphertext tersimpan untuk ${recipient.name}: ${sent.message_id}`, "success");
      const challenge = challengeIndices
        .map(index => MessageCrypto.letters[index])
        .join("");
      this.displayTransmissionSuccess(sent, recipient.name, challenge);
      messageInput.value = "";
      keyInput.value = "";
      await this.loadMessages();
    } catch (error) {
      console.error("Transmit error:", error);
      AudioSys.accessDenied();
      showToast(error.message || "Gagal mengenkripsi atau mengirim pesan.", "error");
    } finally {
      secret = "";
      button.disabled = false;
      button.textContent = "ENKRIPSI & KIRIM";
    }
  },

  displayTransmissionSuccess(data, recipientName, challengeLetters) {
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
    challenge.textContent = `Challenge 4 simbol: ${Array.from(challengeLetters, letter =>
      MessageCrypto.symbols[MessageCrypto.letters.indexOf(letter)]
    ).join(" ")}`;
    const guidance = document.createElement("p");
    guidance.textContent = "Challenge juga tersedia di inbox receiver. Receiver memasukkannya ke perangkat passkey, lalu mengetik respons 12 simbol dari perangkat untuk membuka pesan.";
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
        status.className = "logo-badge";
        status.textContent = {
          LOCKED: "TERENKRIPSI",
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

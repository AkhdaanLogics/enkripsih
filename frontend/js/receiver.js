/**
 * Receiver inbox: unlock ciphertext in this browser.
 */
const Receiver = {
  recipients: [],

  init() {
    document.getElementById("btnRefreshReceiverMsgs")
      ?.addEventListener("click", () => {
        AudioSys.click();
        this.loadMessages();
      });
    window.loadMessages = () => this.loadMessages();
    window.clearReceiverSensitiveData = () => this.clearSensitiveData();
    window.clearDecryptedMessages = () => this.clearSensitiveData();
  },

  clearSensitiveData() {
    const list = document.getElementById("receiverMessageList");
    list?.replaceChildren();
    this.recipients = [];
  },

  async requestJSON(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Permintaan gagal.");
    return data;
  },

  async loadMessages() {
    const list = document.getElementById("receiverMessageList");
    if (!list) return;
    try {
      const [messages, recipients] = await Promise.all([
        this.requestJSON("/api/messages"),
        this.requestJSON("/api/recipients"),
      ]);
      this.recipients = recipients.recipients;
      const badge = document.getElementById("receiverBadge");
      if (badge) {
        const locked = messages.messages.filter(message => message.status === "LOCKED").length;
        badge.textContent = locked ? `${locked} Baru` : `${messages.messages.length}`;
      }
      list.replaceChildren();
      if (!messages.messages.length) {
        list.textContent = "Belum ada pesan untuk anggota.";
        return;
      }
      for (const message of messages.messages) {
        list.append(this.renderMessageCard(message));
      }
    } catch (error) {
      console.error("Load receiver messages error:", error);
      showToast(error.message || "Gagal memuat kotak masuk.", "error");
    }
  },

  renderMessageCard(message) {
    const card = document.createElement("article");
    card.className = `intel-card ${message.status.toLowerCase()}`;
    card.id = `card-${message.id}`;

    const header = document.createElement("div");
    header.className = "intel-header";
    const identity = document.createElement("strong");
    identity.textContent = message.id;
    const recipient = document.createElement("span");
    recipient.textContent = `Untuk ${message.target_unit}`;
    const state = document.createElement("span");
    state.className = "logo-badge";
    state.textContent = {
      LOCKED: "TERENKRIPSI",
      BURNED: "DIHANCURKAN",
      LEGACY: "FORMAT LAMA",
    }[message.status] || message.status;
    header.append(identity, recipient, state);

    const body = document.createElement("div");
    body.className = "intel-body";
    const sentAt = document.createElement("p");
    sentAt.textContent = `Dikirim ${new Date(message.created_at).toLocaleString("id-ID")}`;
    body.append(sentAt);

    if (message.status === "LOCKED") {
      body.append(this.renderUnlockForm(message));
    } else if (message.status === "LEGACY") {
      const note = document.createElement("p");
      note.textContent = "Pesan lama tidak dapat dibuka dengan sistem kunci anggota yang baru.";
      body.append(note);
    } else if (message.status === "BURNED") {
      const note = document.createElement("p");
      note.textContent = "Ciphertext pesan telah dihapus.";
      body.append(note);
    }
    if (message.status === "LOCKED") {
      const burnButton = document.createElement("button");
      burnButton.type = "button";
      burnButton.className = "btn-tactical btn-tactical-secondary";
      burnButton.textContent = "Hapus ciphertext";
      burnButton.addEventListener("click", () => this.burnMessage(message.id));
      body.append(burnButton);
    }
    card.append(header, body);
    return card;
  },

  renderUnlockForm(message) {
    const wrapper = document.createElement("div");
    wrapper.className = "recipient-key-form";
    let input = null;
    const passkeyOnly = [4, 5].includes(message.encryption_version);
    if (!passkeyOnly) {
      const label = document.createElement("label");
      label.className = "form-label";
      label.htmlFor = `receiver-key-${message.id}`;
      label.textContent = "Masukkan secret key yang diberikan komandan";
      input = document.createElement("input");
      input.id = label.htmlFor;
      input.type = "password";
      input.autocomplete = "off";
      input.className = "form-input";
      input.minLength = 32;
      input.placeholder = "Secret key anggota";
      const fields = document.createElement("div");
      fields.className = "form-group";
      fields.append(label, input);
      wrapper.append(fields);
    }

    let passkeyInput = null;
    if (message.passkey_challenge) {
      const challenge = document.createElement("p");
      challenge.className = "passkey-challenge";
      challenge.textContent = `Challenge passkey: ${message.passkey_challenge
        .split("")
        .map(letter => MessageCrypto.symbols[MessageCrypto.letters.indexOf(letter)])
        .join(" ")}`;
      const passkeyHelp = document.createElement("p");
      passkeyHelp.textContent = passkeyOnly
        ? "Masukkan challenge ke perangkat passkey, lalu ketik respons 12 simbol yang muncul di perangkat."
        : "Masukkan urutan 4 simbol challenge ke perangkat passkey. Ketik respons 12 simbol yang muncul di perangkat.";
      const passkeyLabel = document.createElement("label");
      passkeyLabel.className = "form-label";
      passkeyInput = document.createElement("input");
      passkeyInput.type = "text";
      passkeyInput.autocomplete = "off";
      passkeyInput.className = "form-input";
      passkeyInput.placeholder = "Respons dari perangkat";
      passkeyInput.id = `receiver-passkey-${message.id}`;
      passkeyLabel.htmlFor = passkeyInput.id;
      const passkeyCount = document.createElement("output");
      passkeyCount.className = "passkey-count";
      passkeyCount.setAttribute("aria-live", "polite");
      passkeyCount.textContent = "0/12 simbol";
      passkeyInput.addEventListener("input", () => {
        const compact = passkeyInput.value.toUpperCase().replace(/\s+/g, "");
        const letters = Array.from(compact, character => {
          const symbolIndex = MessageCrypto.symbols.indexOf(character);
          return symbolIndex === -1 ? character : MessageCrypto.letters[symbolIndex];
        }).join("");
        const valid = /^[TCXS]*$/.test(letters);
        passkeyCount.textContent = valid
          ? `${letters.length}/12 simbol${letters.length === 12 ? " — siap diperiksa" : ""}`
          : "Gunakan hanya T, C, X, S atau simbol perangkat.";
        passkeyCount.dataset.valid = String(valid && letters.length === 12);
      });
      wrapper.append(challenge, passkeyHelp);
      passkeyLabel.textContent = "Respons passkey 12 simbol";
      passkeyLabel.append(passkeyInput);
      wrapper.append(passkeyLabel, passkeyCount);
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn-tactical btn-tactical-primary message-open-action";
    button.textContent = "Buka Pesan";
    button.addEventListener("click", () =>
      this.unlockMessage(message, input, passkeyInput, wrapper)
    );
    wrapper.append(button);
    return wrapper;
  },

  async unlockMessage(message, input, passkeyInput, wrapper) {
    AudioSys.click();
    let secret = input?.value.trim() || "";
    const passkeyOnly = [4, 5].includes(message.encryption_version);
    const requiresSecret = !passkeyOnly;
    if (requiresSecret && secret.length < 32) {
      showToast("Secret key harus minimal 32 karakter.", "warning");
      return;
    }
    if (!passkeyInput?.value.trim() && passkeyOnly) {
      showToast("Masukkan respons 12 simbol dari perangkat passkey.", "warning");
      return;
    }
    if (
      passkeyOnly &&
      passkeyInput &&
      passkeyInput.parentElement.nextElementSibling?.dataset.valid !== "true"
    ) {
      const count = passkeyInput.value.toUpperCase().replace(/\s+/g, "").length;
      showToast(`Respons passkey harus tepat 12 simbol; yang dimasukkan ${count}.`, "warning");
      return;
    }
    const recipient = this.recipients.find(item => item.id === message.recipient_id);
    if (!recipient) {
      showToast("Kunci penerima tidak terdaftar di aplikasi ini.", "error");
      return;
    }
    const button = wrapper.querySelector("button");
    button.disabled = true;
    button.textContent = "Membuka pesan...";
    try {
      if (requiresSecret) {
        const verifier = await MessageCrypto.verifier(secret, recipient.salt);
        const verification = await this.requestJSON(
          `/api/recipients/${encodeURIComponent(recipient.id)}/verify`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ verifier }),
          }
        );
        if (!verification.valid) {
          throw new Error("Secret key tidak cocok dengan anggota penerima.");
        }
      }

      const packet = await this.requestJSON(
        `/api/messages/${encodeURIComponent(message.id)}/ciphertext`
      );
      if (packet.recipient_id !== recipient.id) {
        throw new Error("Kunci ini bukan milik penerima pesan.");
      }
      const plaintext = await MessageCrypto.decrypt(
        packet.paket,
        secret,
        recipient.id,
        passkeyInput?.value.trim()
      );
      const content = document.createElement("section");
      content.className = "decrypted-intel-box";
      const heading = document.createElement("strong");
      heading.textContent = "Pesan berhasil dibuka di perangkat ini";
      const text = document.createElement("p");
      text.textContent = plaintext;
      content.append(heading, text);
      wrapper.replaceChildren(content);
      if (input) input.value = "";
      secret = "";
      AudioSys.accessGranted();
      showToast(
        passkeyOnly
          ? "Passkey cocok. Pesan dibuka di browser ini."
          : "Kunci cocok. Pesan didekripsi di browser ini.",
        "success"
      );
    } catch (error) {
      console.error("Message decryption error:", error);
      if (input) input.value = "";
      const detail = passkeyOnly
        ? "Respons passkey tidak cocok dengan pesan. Periksa challenge dan respons 12 simbol dari perangkat."
        : error.message || "Kunci salah atau ciphertext rusak.";
      showToast(detail, "error");
      button.disabled = false;
      button.textContent = "Buka Pesan";
      AudioSys.accessDenied();
    } finally {
      secret = "";
    }
  },

  async burnMessage(messageId) {
    if (!confirm("Hapus ciphertext pesan ini secara permanen?")) return;
    try {
      const result = await this.requestJSON(`/api/messages/${encodeURIComponent(messageId)}/burn`, {
        method: "POST",
      });
      if (result.success) {
        showToast("Ciphertext pesan telah dihapus.", "success");
        await this.loadMessages();
      }
    } catch (error) {
      console.error("Burn message error:", error);
      showToast(error.message || "Gagal menghapus pesan.", "error");
    }
  },
};

document.addEventListener("DOMContentLoaded", () => Receiver.init());

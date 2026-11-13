/**
 * Receiver inbox: unlock ciphertext in this browser.
 */
const Receiver = {
  recipients: [],
  _pollTimer: null,
  _decrypting: false,
  _decryptedTexts: new Map(),
  _messages: [],
  _renderedDetailStatus: null,
  currentMessageId: null,

  init() {
    document.getElementById("btnRefreshReceiverMsgs")
      ?.addEventListener("click", () => {
        AudioSys.click();
        this.loadMessages({ trigger: "manual" });
      });
    window.loadMessages = () => this.loadMessages();
    window.clearReceiverSensitiveData = () => this.clearSensitiveData();
    window.clearDecryptedMessages = () => this.clearSensitiveData();
    this.startPolling();
  },

  startPolling() {
    if (this._pollTimer) return;
    this._pollTimer = setInterval(() => {
      if (State.isLoggedIn && State.activeTab === "receiver" && !this._decrypting && !this.isEditingPasskey()) {
        this.loadMessages();
      }
    }, 15_000);
  },

  clearSensitiveData() {
    const list = document.getElementById("receiverMessageList");
    list?.replaceChildren();
    this.recipients = [];
    this._decryptedTexts.clear();
  },

  isEditingPasskey() {
    const active = document.activeElement;
    if (active && active.closest && active.closest(".passkey-symbol-picker")) return true;
    const activePicker = document.querySelector(".passkey-symbol-picker");
    if (activePicker) {
      const filled = activePicker.querySelectorAll(".symbol-slot.filled").length;
      if (filled > 0) return true;
    }
    return false;
  },

  async requestJSON(url, options, { allow401 = false } = {}) {
    const response = await fetch(url, options);
    if (response.status === 401 && State.isLoggedIn) {
      if (window.AppAuth && !allow401) AppAuth.logout("Sesi berakhir. Silakan masuk kembali.");
      throw new Error("Sesi berakhir.");
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Permintaan gagal.");
    return data;
  },

  async loadMessages({ trigger = "poll" } = {}) {
    if (this._decrypting || this._loading) return;
    const showProgress = trigger === "manual";
    if (showProgress) ProcessingModal.show("Memuat kotak masuk…", 30);
    const preserveSelection = !!this.currentMessageId;
    const wasEditing = this.isEditingPasskey();
    this._loading = true;

    try {
      const [messages, recipients] = await Promise.all([
        this.requestJSON("/api/messages"),
        this.requestJSON("/api/recipients"),
      ]);
      if (this._decrypting) {
        this._loading = false;
        return;
      }
      this.recipients = recipients.recipients;
      const ids = list => list.map(m => `${m.id}|${m.status}`).join(",");
      const prevIds = ids(this._messages || []);
      const nextIds = ids(messages.messages);
      this._messages = messages.messages;

      const badge = document.getElementById("receiverBadge");
      if (badge) {
        const locked = messages.messages.filter(message => message.status === "LOCKED").length;
        badge.textContent = locked ? `${locked} Baru` : `${messages.messages.length}`;
      }

      // If the user is actively typing a passkey into the open form, do NOT
      // rebuild the list or the detail pane - that would wipe their input.
      if (wasEditing) {
        this._loading = false;
        return;
      }

      // Only re-render the list when the message set actually changed.
      const list = document.getElementById("receiverMessageList");
      if (!list) {
        this._loading = false;
        return;
      }
      if (list.dataset.loadedIds !== nextIds) {
        list.dataset.loadedIds = nextIds;
        list.replaceChildren();
        if (!messages.messages.length) {
          const empty = document.createElement("div");
          empty.className = "list-placeholder";
          const icon = document.createElement("div");
          icon.className = "list-placeholder-icon";
          icon.setAttribute("aria-hidden", "true");
          icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="M3 9l9 5 9-5"/></svg>';
          const title = document.createElement("div");
          title.className = "list-placeholder-text";
          title.textContent = "Kotak masuk kosong";
          const sub = document.createElement("div");
          sub.className = "list-placeholder-sub";
          sub.textContent = "Pesan dari Commander akan muncul di sini setelah dikirim.";
          empty.append(icon, title, sub);
          list.appendChild(empty);
        } else {
          for (const message of messages.messages) {
            list.append(this.renderChatItem(message));
          }
        }
      }

      if (!messages.messages.length) {
        this._resetDetailPane();
        return;
      }
      const stillThere = messages.messages.some(m => m.id === this.currentMessageId);
      if (preserveSelection && stillThere) {
        this.selectMessage(this.currentMessageId);
      } else {
        this.selectMessage(messages.messages[0].id);
      }
    } catch (error) {
      console.error("Load receiver messages error:", error);
      showToast(error.message || "Gagal memuat kotak masuk.", "error");
    } finally {
      this._loading = false;
      if (showProgress) ProcessingModal.hide();
    }
  },

  renderChatItem(message) {
    const item = document.createElement("div");
    item.className = `receiver-chat-item ${message.status === "LOCKED" ? "has-unread" : ""}`;
    item.dataset.messageId = message.id;
    item.setAttribute("role", "button");
    item.setAttribute("tabindex", "0");
    item.setAttribute("aria-selected", "false");

    const statusLabel = {
      LOCKED: "TERENKRIPSI",
      UNLOCKED: "DIBUKA",
      BURNED: "DIHANCURKAN",
      LEGACY: "FORMAT LAMA",
    }[message.status] || message.status;

    const sender = document.createElement("div");
    sender.className = "sender";

    const displayName = message.id.slice(0, 8).toUpperCase();
    const nameEl = document.createElement("span");
    nameEl.className = "sender-name";
    nameEl.textContent = displayName;

    const meta = document.createElement("span");
    meta.className = "sender-meta";
    const timeEl = document.createElement("span");
    timeEl.className = "sender-time";
    timeEl.textContent = new Date(message.created_at).toLocaleTimeString("id-ID", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Asia/Jakarta",
    });
    const statusEl = document.createElement("span");
    statusEl.className = `status-badge--compact ${message.status.toLowerCase()}`;
    statusEl.textContent = statusLabel;
    meta.append(timeEl, statusEl);

    sender.append(nameEl, meta);
    item.append(sender);

    const activate = () => this.selectMessage(message.id);
    item.addEventListener("click", activate);
    item.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        activate();
      }
    });
    return item;
  },

  selectMessage(messageId) {
    const messages = this._messages || [];
    const message = messages.find(m => m.id === messageId);
    if (!message) {
      this._resetDetailPane();
      return;
    }

    const noChat = document.getElementById("receiverNoChat");
    const container = document.getElementById("receiverMessageContainer");

    // If the same message is already open and its status hasn't changed, don't
    // wipe and rebuild the detail pane (that causes the flicker). Re-render when
    // the status changed server-side (e.g. LOCKED -> UNLOCKED -> BURNED) so the
    // view actually updates after a burn/decrypt that arrived over polling.
    const sameSelection =
      this.currentMessageId === messageId &&
      container &&
      !container.hidden &&
      noChat &&
      noChat.hidden;
    const statusChanged = this._renderedDetailStatus !== message.status;
    if (sameSelection && !statusChanged) {
      this.currentMessageId = messageId;
      return;
    }

    this.currentMessageId = messageId;
    this._renderedDetailStatus = message.status;

    document.querySelectorAll(".receiver-chat-item").forEach(item => {
      const isActive = item.dataset.messageId === messageId;
      item.classList.toggle("active", isActive);
      item.setAttribute("aria-selected", String(isActive));
    });

    if (noChat) noChat.hidden = true;
    if (container) container.hidden = false;

    this.renderMessageDetail(message);
  },

  _resetDetailPane() {
    this.currentMessageId = null;
    this._renderedDetailStatus = null;
    const container = document.getElementById("receiverMessageContainer");
    const noChat = document.getElementById("receiverNoChat");
    const header = document.getElementById("receiverMessageHeader");
    const body = document.getElementById("receiverMessageBody");
    const footer = document.getElementById("receiverMessageFooter");
    if (container) container.hidden = true;
    if (noChat) noChat.hidden = false;
    if (header) header.replaceChildren();
    if (body) body.replaceChildren();
    if (footer) footer.replaceChildren();
    document.querySelectorAll(".receiver-chat-item").forEach(item => item.classList.remove("active"));
  },

  renderMessageDetail(message) {
    const header = document.getElementById("receiverMessageHeader");
    const body = document.getElementById("receiverMessageBody");
    const footer = document.getElementById("receiverMessageFooter");
    if (!header || !body || !footer) return;

    header.replaceChildren();
    body.replaceChildren();
    footer.replaceChildren();

    const contactInfo = document.createElement("div");
    contactInfo.className = "contact-info";
    const avatar = document.createElement("div");
    avatar.className = "contact-avatar";
    const contactName = message.target_unit || message.id.slice(0, 8).toUpperCase();
    avatar.textContent = contactName.slice(0, 1);
    const nameWrap = document.createElement("div");
    nameWrap.className = "contact-name-wrap";
    const nameEl = document.createElement("div");
    nameEl.className = "contact-name";
    nameEl.textContent = contactName;
    const metaEl = document.createElement("div");
    metaEl.className = "contact-meta";
    metaEl.textContent = `ID: ${message.id.slice(0, 12)}... · ${new Date(message.created_at).toLocaleString("id-ID", { timeZone: "Asia/Jakarta" })}`;
    nameWrap.append(nameEl, metaEl);
    contactInfo.append(avatar, nameWrap);

    const statusBadge = document.createElement("span");
    statusBadge.className = `status-badge ${message.status.toLowerCase()}`;
    statusBadge.textContent = {
      LOCKED: "TERENKRIPSI",
      UNLOCKED: "DIBUKA",
      BURNED: "DIHANCURKAN",
      LEGACY: "FORMAT LAMA",
    }[message.status] || message.status;

    const headerActions = document.createElement("div");
    headerActions.className = "receiver-header-actions";

    const backButton = document.createElement("button");
    backButton.type = "button";
    backButton.className = "btn-tactical btn-tactical-secondary receiver-back-btn";
    backButton.setAttribute("aria-label", "Kembali ke daftar pesan");
    backButton.textContent = "Kembali";
    backButton.addEventListener("click", () => this._resetDetailPane());

    headerActions.append(backButton, statusBadge);
    header.append(contactInfo, headerActions);

    if (message.status === "LOCKED") {
      body.append(this.renderUnlockForm(message));
      const burnButton = document.createElement("button");
      burnButton.type = "button";
      burnButton.className = "btn-tactical btn-tactical-secondary";
      burnButton.textContent = "Sudah dibuka, hapus ciphertext";
      burnButton.disabled = true;
      burnButton.title = "Tombol aktif setelah pesan berhasil dibuka";
      burnButton.addEventListener("click", () => this.burnMessage(message.id));
      body.append(burnButton);
      message._burnButton = burnButton;
    } else if (message.status === "UNLOCKED") {
      const cached = this._decryptedTexts.get(message.id);
      if (cached) {
        body.append(this.renderDecryptedBox(cached));
      } else {
        body.append(this.renderDecryptedNote());
      }
      const burnButton = document.createElement("button");
      burnButton.type = "button";
      burnButton.className = "btn-tactical btn-tactical-secondary";
      burnButton.textContent = "Hapus ciphertext";
      burnButton.addEventListener("click", () => this.burnMessage(message.id));
      body.append(burnButton);
    } else if (message.status === "LEGACY") {
      const note = document.createElement("p");
      note.textContent = "Pesan lama tidak dapat dibuka dengan sistem kunci anggota yang baru.";
      body.append(note);
    } else if (message.status === "BURNED") {
      const note = document.createElement("p");
      note.textContent = "Ciphertext pesan telah dihapus.";
      body.append(note);
    }
  },

  renderDecryptedBox(plaintext) {
    const box = document.createElement("section");
    box.className = "receiver-message-bubble incoming";
    const heading = document.createElement("div");
    heading.className = "bubble-heading";
    heading.textContent = "Pesan berhasil dibuka di perangkat ini";
    const text = document.createElement("p");
    text.textContent = plaintext;
    text.className = "bubble-text";
    box.append(heading, text);
    return box;
  },

  renderDecryptedNote() {
    const note = document.createElement("p");
    note.textContent = "Pesan ini sudah dibuka. Ciphertext tetap tersimpan sampai Anda menghapusnya. Buka kembali pesan untuk melihat isinya.";
    return note;
  },

  renderWokwiDemoLink() {
    const a = document.createElement("a");
    a.className = "wokwi-demo-link";
    a.id = "wokwiDemoLink";
    a.href = "https://wokwi.com/projects/478446530349223937";
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.title = "Buka enkripsi dengan perangkat demo (simulasi Wokwi)";
    const tag = document.createElement("span");
    tag.className = "wokwi-demo-tag";
    tag.textContent = "demo";
    a.append(tag, document.createTextNode(" Buka di Wokwi"));
    return a;
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
      label.textContent = "Masukkan secret key yang diberikan Sender";
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
    const showSymbolPicker = passkeyOnly && message.passkey_challenge;
    if (showSymbolPicker) {
      const challenge = document.createElement("p");
      challenge.className = "passkey-challenge";
      const prefix = document.createElement("span");
      prefix.className = "passkey-challenge-label";
      prefix.textContent = "Challenge passkey: ";
      const symbolsWrap = document.createElement("span");
      symbolsWrap.className = "passkey-challenge-symbols";
      if (message.passkey_challenge) {
        for (const letter of message.passkey_challenge) {
          const idx = MessageCrypto.letters.indexOf(letter);
          if (idx === -1) continue;
          const svg = document.createElement("span");
          svg.className = "passkey-challenge-sym";
          svg.setAttribute("data-sym", letter);
          svg.innerHTML = PASSKEY_SVG.icons[letter];
          symbolsWrap.append(svg);
        }
      } else {
        symbolsWrap.textContent = "(otomatis)";
      }
      challenge.append(prefix, symbolsWrap);
      const wokwiLink = this.renderWokwiDemoLink();
      challenge.append(wokwiLink);
      const passkeyHelp = document.createElement("p");
      passkeyHelp.className = "passkey-help";
      passkeyHelp.textContent = "Masukkan challenge ke perangkat passkey, lalu ketuk 12 simbol respons yang tampil di bawah.";
      passkeyInput = document.createElement("input");
      passkeyInput.type = "hidden";
      passkeyInput.id = `receiver-passkey-${message.id}`;
      passkeyInput.name = "passkey_response";
      wrapper.append(challenge, passkeyHelp);
      wrapper.append(this.renderSymbolPicker(message, passkeyOnly, passkeyInput, "", wrapper));
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn-tactical btn-tactical-primary message-open-action";
    button.textContent = "Buka Pesan";
    button.disabled = passkeyOnly;
    button.addEventListener("click", () =>
      this.unlockMessage(message, input, passkeyInput, wrapper)
    );
    wrapper.append(button);
    return wrapper;
  },

  renderSymbolPicker(message, passkeyOnly, passkeyInput, initialValue = "", wrapper) {
    const container = document.createElement("div");
    container.className = "passkey-symbol-picker";

    const state = { letters: "" };
    const totalSlots = 12;
    const slotsGrid = document.createElement("div");
    slotsGrid.className = "symbol-grid";
    const slotElements = [];
    for (let i = 0; i < totalSlots; i++) {
      const slot = document.createElement("button");
      slot.type = "button";
      slot.className = "symbol-slot";
      slot.dataset.slot = String(i);
      slot.setAttribute("aria-label", `Simbol ${i + 1} dari 12`);
      slot.innerHTML = "·";
      slot.addEventListener("click", () => {
        // Clicking a filled slot removes the last entered symbol (undo).
        if (state.letters.length > 0) {
          state.letters = state.letters.slice(0, -1);
        }
        render();
      });
      slotElements.push(slot);
      slotsGrid.append(slot);
    }
    container.append(slotsGrid);

    const render = () => {
      slotElements.forEach((slot, i) => {
        const letter = state.letters[i];
        if (letter) {
          slot.classList.add("filled");
          slot.dataset.sym = letter;
          slot.innerHTML = PASSKEY_SVG.icons[letter];
        } else {
          slot.classList.remove("filled");
          slot.removeAttribute("data-sym");
          slot.innerHTML = "·";
        }
      });
      if (passkeyInput) passkeyInput.value = state.letters;
      const count = container.querySelector(".passkey-count");
      if (count) {
        const full = state.letters.length === 12;
        count.textContent = `${state.letters.length}/12 simbol${full ? ", siap dibuka" : ""}`;
        count.dataset.valid = String(full);
      }
      const openBtn = wrapper && wrapper.querySelector(".message-open-action");
      if (openBtn) {
        openBtn.disabled = state.letters.length !== 12;
      }
    };

    const palette = document.createElement("div");
    palette.className = "symbol-palette";
    for (let i = 0; i < 4; i++) {
      const letter = MessageCrypto.letters[i];
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "palette-btn";
      btn.dataset.sym = letter;
      btn.setAttribute("aria-label", PASSKEY_SVG.label[letter] || letter);
      btn.innerHTML = PASSKEY_SVG.icons[letter];
      const label = document.createElement("span");
      label.className = "palette-label";
      label.textContent = PASSKEY_SVG.label[letter] || letter;
      btn.append(label);
      btn.addEventListener("click", () => {
        if (state.letters.length >= 12) return;
        state.letters += letter;
        render();
      });
      palette.append(btn);
    }
    container.append(palette);

    if (initialValue && passkeyInput) {
      const letters = initialValue.replace(/\s+/g, "").toUpperCase().slice(0, 12);
      if (MessageCrypto.isPasskeyValid(letters)) {
        state.letters = letters;
      }
    }

    const countEl = document.createElement("output");
    countEl.className = "passkey-count";
    countEl.setAttribute("aria-live", "polite");
    countEl.textContent = `0/12 simbol`;
    container.append(countEl);

    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.className = "btn-tactical btn-tactical-secondary passkey-clear";
    clearBtn.textContent = "Hapus semua";
    clearBtn.addEventListener("click", () => {
      state.letters = "";
      render();
    });
    container.append(clearBtn);

    render();
    return container;
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
    const passkeyValue = (passkeyInput?.value || "").trim().toUpperCase();
    if (passkeyOnly) {
      if (!MessageCrypto.isPasskeyValid(passkeyValue)) {
        showToast("Wajib memilih 12 simbol respons dari perangkat. Tekan 4 tombol palet secara berurutan.", "warning");
        return;
      }
    }
    if (this._decrypting) return;
    this._decrypting = true;
    const button = wrapper.querySelector(".message-open-action");
    button.disabled = true;
    ProcessingModal.show("Membuka pesan…", 30);
    try {
      // Use backend decrypt endpoint (fast, PBKDF2 runs on server, owner-check included)
      const passkeyForDecrypt = passkeyValue;
      const decryptRes = await this.requestJSON("/api/messages/decrypt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message_id: message.id,
          passkey_letters: passkeyForDecrypt,
        }),
      });
      const decryptedText = decryptRes.plaintext;
      this._decryptedTexts.set(message.id, decryptedText);
      const content = this.renderDecryptedBox(decryptedText);
      wrapper.replaceChildren(content);
      if (input) input.value = "";
      secret = "";
      AudioSys.accessGranted();
      showToast(
        passkeyOnly
          ? "Passkey cocok. Pesan dibuka di perangkat ini."
          : "Kunci cocok. Pesan didekripsi di perangkat ini.",
        "success"
      );
      if (message._burnButton) {
        message._burnButton.disabled = false;
        message._burnButton.textContent = "Hapus ciphertext";
      }
      message.status = "UNLOCKED";
    } catch (error) {
      console.error("Message decryption error:", error);
      if (input) input.value = "";
      const detail = passkeyOnly
        ? "Respons passkey tidak cocok dengan pesan. Periksa challenge dan respons 12 simbol dari perangkat."
        : error.message || "Kunci salah atau ciphertext rusak.";
      showToast(detail, "error");
      button.disabled = false;
      AudioSys.accessDenied();
    } finally {
      ProcessingModal.hide();
      secret = "";
      this._decrypting = false;
    }
  },

  async burnMessage(messageId) {
    await new Promise((resolve) => {
      showConfirmDialog(
        "Hapus ciphertext pesan ini secara permanen?",
        resolve
      );
    });
    ProcessingModal.show("Menghapus ciphertext…", 50);
    try {
      const result = await this.requestJSON(`/api/messages/${encodeURIComponent(messageId)}/burn`, {
        method: "POST",
      });
      if (result.success) {
        this._decryptedTexts.delete(messageId);
        showToast("Ciphertext pesan telah dihapus.", "success");
        await this.loadMessages();
      }
    } catch (error) {
      console.error("Burn message error:", error);
      showToast(error.message || "Gagal menghapus pesan.", "error");
    } finally {
      ProcessingModal.hide();
    }
  },
};

document.addEventListener("DOMContentLoaded", () => Receiver.init());

const MessageCrypto = {
  iterations: 600000,
  encoder: new TextEncoder(),
  symbols: ["△", "○", "✕", "□"], // taste-skill-ignore: required passkey notation, not decoration.
  letters: "TCXS",

  randomBytes(size) {
    return crypto.getRandomValues(new Uint8Array(size));
  },

  toHex(bytes) {
    return Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
  },

  fromHex(value) {
    if (!/^(?:[0-9a-f]{2})+$/i.test(value)) {
      throw new Error("Format salt tidak valid.");
    }
    return new Uint8Array(value.match(/.{2}/g).map(byte => parseInt(byte, 16)));
  },

  toBase64Url(bytes) {
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  },

  fromBase64Url(value) {
    if (!/^[A-Za-z0-9_-]+$/.test(value)) {
      throw new Error("Paket ciphertext memiliki format yang tidak valid.");
    }
    const base64 = value.replace(/-/g, "+").replace(/_/g, "/");
    const binary = atob(base64 + "=".repeat((4 - (base64.length % 4)) % 4));
    return Uint8Array.from(binary, character => character.charCodeAt(0));
  },

  async deriveBits(secret, salt, purpose) {
    if (secret.length < 32) {
      throw new Error("Secret key harus minimal 32 karakter.");
    }
    const material = await crypto.subtle.importKey(
      "raw",
      this.encoder.encode(secret),
      "PBKDF2",
      false,
      ["deriveBits"]
    );
    const domainSalt = new Uint8Array([
      ...this.encoder.encode(`enkripsih:${purpose}:v1:`),
      ...salt,
    ]);
    return new Uint8Array(await crypto.subtle.deriveBits(
      { name: "PBKDF2", salt: domainSalt, iterations: this.iterations, hash: "SHA-256" },
      material,
      256
    ));
  },

  async deriveBitsFromPasskey(passkeyLetters, salt) {
    const material = await crypto.subtle.importKey(
      "raw",
      this.encoder.encode(passkeyLetters),
      "PBKDF2",
      false,
      ["deriveBits"]
    );
    const domainSalt = new Uint8Array([
      ...this.encoder.encode("enkripsih:message-passkey:v1:"),
      ...salt,
    ]);
    return new Uint8Array(await crypto.subtle.deriveBits(
      { name: "PBKDF2", salt: domainSalt, iterations: this.iterations, hash: "SHA-256" },
      material,
      256
    ));
  },

  async deriveBitsFromDeviceResponse(responseIndices, salt) {
    if (
      !Array.isArray(responseIndices)
      || responseIndices.length !== 12
      || responseIndices.some(index => !Number.isInteger(index) || index < 0 || index > 3)
    ) {
      throw new Error("Respons perangkat harus terdiri dari 12 simbol yang valid.");
    }
    const material = await crypto.subtle.importKey(
      "raw",
      new Uint8Array(responseIndices),
      "PBKDF2",
      false,
      ["deriveBits"]
    );
    return new Uint8Array(await crypto.subtle.deriveBits(
      { name: "PBKDF2", salt, iterations: 200_000, hash: "SHA-256" },
      material,
      256
    ));
  },

  async verifier(secret, saltHex) {
    const bits = await this.deriveBits(
      secret,
      this.fromHex(saltHex),
      "recipient"
    );
    return this.toHex(bits);
  },

  generateSecret() {
    return this.toBase64Url(this.randomBytes(32));
  },

  async derivePasskey(secret, challengeIndices) {
    if (secret.length < 32) {
      throw new Error("Secret key harus minimal 32 karakter.");
    }
    if (
      !Array.isArray(challengeIndices)
      || challengeIndices.length !== 4
      || challengeIndices.some(index => !Number.isInteger(index) || index < 0 || index > 3)
    ) {
      throw new Error("Challenge harus terdiri dari 4 simbol yang valid.");
    }

    const key = await crypto.subtle.importKey(
      "raw",
      this.encoder.encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"]
    );
    const challengeBytes = new Uint8Array(challengeIndices);
    const digest = new Uint8Array(await crypto.subtle.sign("HMAC", key, challengeBytes));
    const responseIndices = Array.from(
      { length: 12 },
      (_, index) => (digest[Math.floor(index / 4)] >> ((index % 4) * 2)) & 3
    );
    return {
      challenge_letters: challengeIndices.map(index => this.letters[index]).join(""),
      challenge_symbols: challengeIndices.map(index => this.symbols[index]).join(" "),
      response_letters: responseIndices.map(index => this.letters[index]).join(""),
      response_symbols: responseIndices.map(index => this.symbols[index]).join(" "),
      response_indices: responseIndices,
    };
  },

  async deriveLegacyPasskey(secret, recipientId, challengeIndices) {
    const key = await crypto.subtle.importKey(
      "raw",
      this.encoder.encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"]
    );
    const challengeBytes = new Uint8Array([
      ...this.encoder.encode(`enkripsih:passkey:v1:${recipientId}:`),
      ...challengeIndices,
    ]);
    const digest = new Uint8Array(await crypto.subtle.sign("HMAC", key, challengeBytes));
    const responseIndices = Array.from(
      { length: 12 },
      (_, index) => (digest[Math.floor(index / 4)] >> ((index % 4) * 2)) & 3
    );
    return responseIndices.map(index => this.letters[index]).join("");
  },

  normalizePasskey(value) {
    if (typeof value !== "string") {
      throw new Error("Passkey harus berisi tepat 12 simbol.");
    }
    const compact = value.toUpperCase().replace(/\s+/g, "");
    const letters = Array.from(compact, character => {
      const symbolIndex = this.symbols.indexOf(character);
      return symbolIndex === -1 ? character : this.letters[symbolIndex];
    }).join("");
    if (!/^[TCXS]{12}$/.test(letters)) {
      throw new Error("Passkey harus berisi tepat 12 simbol.");
    }
    return letters;
  },

  async encrypt(plaintext, secret, recipientId, challengeIndices) {
    const generatedPasskey = await this.derivePasskey(
      secret,
      challengeIndices
    );
    const salt = this.randomBytes(16);
    const iv = this.randomBytes(12);
    const keyBytes = await this.deriveBitsFromDeviceResponse(
      generatedPasskey.response_indices,
      salt
    );
    const key = await crypto.subtle.importKey(
      "raw",
      keyBytes,
      { name: "AES-GCM" },
      false,
      ["encrypt"]
    );
    const ciphertext = await crypto.subtle.encrypt(
      {
        name: "AES-GCM",
        iv,
        tagLength: 128,
      },
      key,
      this.encoder.encode(plaintext)
    );
    return JSON.stringify({
      v: 5,
      salt: this.toBase64Url(salt),
      iv: this.toBase64Url(iv),
      ciphertext: this.toBase64Url(new Uint8Array(ciphertext)),
      challenge: generatedPasskey.challenge_letters,
    });
  },

  async decrypt(envelopeText, secret, recipientId, passkey) {
    const envelope = JSON.parse(envelopeText);
    if (
      ![1, 2, 3, 4, 5].includes(envelope.v) ||
      typeof envelope.salt !== "string" ||
      typeof envelope.iv !== "string" ||
      typeof envelope.ciphertext !== "string"
    ) {
      throw new Error("Format ciphertext pesan tidak dikenal.");
    }
    const salt = this.fromBase64Url(envelope.salt);
    const iv = this.fromBase64Url(envelope.iv);
    const ciphertext = this.fromBase64Url(envelope.ciphertext);
    if (salt.length !== 16 || iv.length !== 12 || ciphertext.length < 16) {
      throw new Error("Paket ciphertext rusak atau tidak lengkap.");
    }
    let keyBytes;
    if (envelope.v === 5) {
      if (typeof envelope.challenge !== "string" || !/^[TCXS]{4}$/.test(envelope.challenge)) {
        throw new Error("Challenge passkey pada pesan tidak valid.");
      }
      const responseIndices = Array.from(
        this.normalizePasskey(passkey),
        letter => this.letters.indexOf(letter)
      );
      keyBytes = await this.deriveBitsFromDeviceResponse(
        responseIndices,
        salt
      );
    } else if (envelope.v === 4) {
      if (typeof envelope.challenge !== "string" || !/^[TCXS]{4}$/.test(envelope.challenge)) {
        throw new Error("Challenge passkey pada pesan tidak valid.");
      }
      keyBytes = await this.deriveBitsFromPasskey(
        this.normalizePasskey(passkey),
        salt
      );
    } else {
      let messageSecret = secret;
      if (envelope.v === 2 || envelope.v === 3) {
        if (typeof envelope.challenge !== "string" || !/^[TCXS]{4}$/.test(envelope.challenge)) {
          throw new Error("Challenge passkey pada pesan tidak valid.");
        }
        const challengeIndices = Array.from(
          envelope.challenge,
          letter => this.letters.indexOf(letter)
        );
        const expectedResponse = envelope.v === 2
          ? await this.deriveLegacyPasskey(secret, recipientId, challengeIndices)
          : (await this.derivePasskey(secret, challengeIndices)).response_letters;
        if (this.normalizePasskey(passkey) !== expectedResponse) {
          throw new Error("Passkey tidak cocok dengan challenge pesan.");
        }
        messageSecret = `${secret}\u0000${expectedResponse}`;
      }
      keyBytes = await this.deriveBits(messageSecret, salt, "message");
    }
    const key = await crypto.subtle.importKey(
      "raw",
      keyBytes,
      { name: "AES-GCM" },
      false,
      ["decrypt"]
    );
    const plaintext = await crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv,
        ...(envelope.v === 5
          ? {}
          : { additionalData: this.encoder.encode(`enkripsih:v1:${recipientId}`) }),
        tagLength: 128,
      },
      key,
      ciphertext
    );
    return new TextDecoder().decode(plaintext);
  },
};

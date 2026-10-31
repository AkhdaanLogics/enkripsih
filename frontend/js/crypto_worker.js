/**
 * ENKRIPSIH - Crypto Web Worker
 * Handles PBKDF2 key derivation + AES-GCM encryption in background thread
 * Keeps UI responsive during 600k-iteration PBKDF2 operations
 */

const enc = new TextEncoder();
const ITERATIONS = 600000;

self.onmessage = async function (event) {
  const { action, secret, recipientId, challengeIndices, responseLetters, plaintext, salt, saltHex, domainSaltHex, hash, hashName } = event.data || {};

  try {
    switch (action) {
      case "deriveVerifier":
        self.postMessage({
          action: "result",
          result: await deriveVerifier(secret, saltHex, hashName),
        });
        break;

      case "deriveBits":
        self.postMessage({
          action: "result",
          result: await deriveBits(secret, saltHex, hashName),
        });
        break;

      case "derivePasskey":
        self.postMessage({
          action: "result",
          result: await derivePasskey(secret, challengeIndices, responseLetters),
        });
        break;

      case "encryptMessage":
        self.postMessage({
          action: "result",
          result: await encryptMessage(secret, recipientId, challengeIndices, responseLetters, plaintext),
        });
        break;

      default:
        self.postMessage({ action: "error", error: `Unknown action: ${action}` });
    }
  } catch (err) {
    self.postMessage({ action: "error", error: err.message });
  }
};

async function deriveVerifier(secret, saltHex, hashName) {
  const salt = fromHex(saltHex);
  const key = await importKey("HMAC", secret, "SHA-256");
  const verifierBytes = await crypto.subtle.sign("HMAC", key, enc.encode("enkripsih:verifier:v1:"));
  const verifier = Array.from(new Uint8Array(verifierBytes), b => b.toString(16).padStart(2, "0")).join("");
  return { verifier };
}

async function deriveBits(secret, saltHex, hashName) {
  const salt = fromHex(saltHex);
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations: ITERATIONS, hash: hashName || "SHA-256" },
    await importKeyRaw(secret, "AES-GCM"),
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"]
  );
  return { key };
}

async function derivePasskey(secret, challengeIndices, responseLetters) {
  const salt = randomBytes(16);
  const domainSalt = enc.encode("enkripsih:passkey:v1");
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const challengeBytes = new Uint8Array(challengeIndices);
  const digest = new Uint8Array(await crypto.subtle.sign("HMAC", key, challengeBytes));
  const responseIndices = Array.from({ length: 12 }, (_, i) => (digest[Math.floor(i / 4)] >> ((i % 4) * 2)) & 3);

  // Derive response letters from indices
  const LETTERS = "TCXS";
  const responseLettersStr = responseIndices.map(i => LETTERS[i]).join("");

  return {
    salt: toHex(salt),
    response_indices: responseIndices,
    response_letters: responseLettersStr ?? responseLetters,
    challenge_symbols: challengeIndices.map(i => "△○✕□"[i]).join(" "),
  };
}

async function encryptMessage(secret, recipientId, challengeIndices, responseLetters, plaintext) {
  const salt = randomBytes(16);
  const iv = randomBytes(12);

  let keyBytes;
  const responseIndices = Array.from(responseLetters, l => "TCXS".indexOf(l));

  // Derive key from response indices
  const saltBytes = fromHex(toHex(salt));
  const domainSalt = enc.encode("enkripsih:messaging:passkey:v1");
  const hmacKey = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const challengeBytes = new Uint8Array([...domainSalt, ...challengeIndices, ...responseIndices]);
  const rawDigest = await crypto.subtle.sign("HMAC", hmacKey, challengeBytes);
  const digestBytes = new Uint8Array(rawDigest);

  // PBKDF2 from digest bytes
  const deriveKey = await crypto.subtle.importKey("raw", digestBytes, { name: "PBKDF2" }, false, ["deriveKey"]);
  keyBytes = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: saltBytes, iterations: ITERATIONS, hash: "SHA-256" },
    deriveKey,
    { name: "AES-GCM", length: 256 },
    true,
    ["encrypt", "decrypt"]
  );

  const additionalData = enc.encode(`enkripsih:v1:${recipientId}`);
  const encrypted = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv, additionalData, tagLength: 128 },
    keyBytes,
    enc.encode(plaintext)
  );

  return {
    paket: toBase64Url(new Uint8Array(encrypted)),
    iv_hex: toHex(iv),
    salt_hex: toHex(salt),
    v: 5,
    additional_data: additionalData.toString(),
  };
}

function randomBytes(size) {
  const arr = new Uint8Array(size);
  crypto.getRandomValues(arr);
  return Array.from(arr);
}

function toHex(bytes) {
  return Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
}

function fromHex(hex) {
  const cleaned = hex.replace(/^bytes:/, "");
  if (!/^(?:[0-9a-f]{2})+$/i.test(cleaned)) {
    throw new Error("Invalid hex string");
  }
  return Uint8Array.from(cleaned.match(/.{2}/g).map(h => parseInt(h, 16)));
}

function toBase64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function importKeyRaw(secret, name) {
  return crypto.subtle.importKey("raw", enc.encode(secret), { name, hash: "SHA-256" }, false, ["deriveKey"]);
}

async function importKeyHmac(secret, algo) {
  return crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: algo }, false, ["sign"]);
}

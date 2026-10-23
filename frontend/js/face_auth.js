/**
 * Enkripsih - Face Biometric Authentication Controller
 * Handles Webcam feed, Canvas capture, and OpenCV Backend Face Verification.
 */

const FaceAuth = {
  video: null,
  canvas: null,
  stream: null,
  isScanning: false,

  init() {
    this.video = document.getElementById('webcamVideo');
    this.canvas = document.getElementById('webcamCanvas');

    const btnStartCam = document.getElementById('btnStartCam');
    const btnVerifyFace = document.getElementById('btnVerifyFace');
    const btnRegisterFace = document.getElementById('btnRegisterFace');
    const btnBypassLogin = document.getElementById('btnBypassLogin');
    const btnLogout = document.getElementById('btnLogout');

    if (btnStartCam) btnStartCam.addEventListener('click', () => this.startCamera());
    if (btnVerifyFace) btnVerifyFace.addEventListener('click', () => this.verifyFace());
    if (btnRegisterFace) btnRegisterFace.addEventListener('click', () => this.registerFace());
    if (btnBypassLogin) btnBypassLogin.addEventListener('click', () => this.bypassLogin());
    if (btnLogout) btnLogout.addEventListener('click', () => this.logout());

    // Check existing session / commander profile
    this.checkCommanderStatus();
  },

  async startCamera() {
    AudioSys.click();
    const promptEl = document.getElementById('cameraPrompt');
    const reticleBox = document.querySelector('.reticle-box');

    try {
      if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        this.stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" }
        });
        this.video.srcObject = this.stream;
        this.video.play();

        if (promptEl) promptEl.style.display = 'none';
        if (reticleBox) reticleBox.classList.add('detected');

        document.getElementById('btnStartCam').style.display = 'none';
        document.getElementById('btnVerifyFace').disabled = false;
        document.getElementById('btnRegisterFace').disabled = false;

        this.updateTelemetry("KAMERA AKTIF - MENUNGGU PEMINDAIAN", "READY");
        showToast("Kamera web berhasil diaktifkan. Arahkan wajah ke kotak reticle.", "success");
      } else {
        showToast("Webcam tidak didukung di browser ini.", "error");
      }
    } catch (err) {
      console.error("Camera error:", err);
      showToast("Gagal mengakses kamera: " + err.message + ". Gunakan Mode Simulasi.", "warning");
    }
  },

  captureFrameBase64() {
    if (!this.video || !this.video.videoWidth) {
      return null;
    }
    this.canvas.width = this.video.videoWidth;
    this.canvas.height = this.video.videoHeight;
    const ctx = this.canvas.getContext('2d');
    ctx.drawImage(this.video, 0, 0, this.canvas.width, this.canvas.height);
    return this.canvas.toDataURL('image/jpeg', 0.85);
  },

  updateTelemetry(statusText, matchText = "--%") {
    const statusEl = document.getElementById('hudStatus');
    const matchEl = document.getElementById('hudMatch');
    if (statusEl) statusEl.textContent = statusText;
    if (matchEl) matchEl.textContent = matchText;
  },

  async verifyFace() {
    AudioSys.click();
    const b64 = this.captureFrameBase64();
    if (!b64) {
      showToast("Aktifkan kamera terlebih dahulu!", "warning");
      return;
    }

    this.updateTelemetry("MEMINDAI BIOMETRIK WAJAH...", "SCANNING");
    AudioSys.playTone(1600, 'sawtooth', 0.08, 0.1);

    try {
      const res = await fetch('/api/auth/verify-face', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_base64: b64, user_id: 'CMD-01' })
      });
      const data = await res.json();

      if (data.success) {
        AudioSys.accessGranted();
        this.updateTelemetry(`TERVERIFIKASI (${data.confidence}%)`, `${data.confidence}%`);
        showToast(data.message, "success");
        this.onLoginSuccess(data.user || { name: "Kolonel M. Haris", rank: "Panglima Operasi" });
      } else {
        AudioSys.accessDenied();
        this.updateTelemetry(`GAGAL: ${data.message.substring(0, 24)}`, `${data.confidence || 0}%`);
        showToast(data.message, "error");
      }
    } catch (err) {
      console.error("Verify face error:", err);
      showToast("Terjadi kesalahan koneksi saat verifikasi wajah.", "error");
    }
  },

  async registerFace() {
    AudioSys.click();
    const b64 = this.captureFrameBase64();
    if (!b64) {
      showToast("Aktifkan kamera terlebih dahulu!", "warning");
      return;
    }

    try {
      const res = await fetch('/api/auth/register-face', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_base64: b64, user_id: 'CMD-01' })
      });
      const data = await res.json();

      if (data.success) {
        AudioSys.accessGranted();
        showToast(data.message, "success");
        this.updateTelemetry("BIOMETRIK TERDAFTAR", "100%");
      } else {
        AudioSys.accessDenied();
        showToast(data.message, "error");
      }
    } catch (err) {
      console.error("Register face error:", err);
      showToast("Gagal mendaftarkan wajah.", "error");
    }
  },

  onLoginSuccess(user) {
    State.isLoggedIn = true;
    State.commander = user;

    // UI Updates
    document.getElementById('authLoginCard').style.display = 'none';
    document.getElementById('commanderCommandCenter').style.display = 'block';

    const officerName = document.getElementById('officerName');
    const officerRank = document.getElementById('officerRank');
    if (officerName) officerName.textContent = user.name;
    if (officerRank) officerRank.textContent = user.rank;

    // Load commander sent messages
    if (window.loadCommanderMessages) {
      window.loadCommanderMessages();
    }
  },

  logout() {
    AudioSys.click();
    State.isLoggedIn = false;
    State.commander = null;

    if (this.stream) {
      this.stream.getTracks().forEach(track => track.stop());
    }

    document.getElementById('authLoginCard').style.display = 'block';
    document.getElementById('commanderCommandCenter').style.display = 'none';
    document.getElementById('btnStartCam').style.display = 'inline-flex';
    document.getElementById('btnVerifyFace').disabled = true;
    document.getElementById('btnRegisterFace').disabled = true;
    const promptEl = document.getElementById('cameraPrompt');
    if (promptEl) promptEl.style.display = 'flex';

    showToast("Komandan berhasil logout dari sistem Enkripsih.", "info");
  },

  async checkCommanderStatus() {
    try {
      const res = await fetch('/api/auth/commander-status');
      const data = await res.json();
      if (data.commander && data.commander.face_enrolled) {
        const enrollBadge = document.getElementById('enrollmentBadge');
        if (enrollBadge) {
          enrollBadge.textContent = "BIOMETRIK AKTIF";
          enrollBadge.className = "logo-badge";
        }
      }
    } catch (e) {
      console.warn("Commander status check failed:", e);
    }
  }
};

document.addEventListener('DOMContentLoaded', () => {
  FaceAuth.init();
});

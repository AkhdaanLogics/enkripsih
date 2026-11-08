const AppAuth = {
  lockoutTimer: null,
  lockoutDeadline: 0,

  init() {
    // ?a=1 (or #a) bypasses the landing and goes straight to the app.
    // The landing page CTA links to "/?a=1".
    const params = new URLSearchParams(window.location.search);
    const hashA = window.location.hash === '#a';
    if (!params.has('a') && !hashA) {
      // Landing-bound: unauthenticated visitors go to the marketing page.
      // Returning users (valid session) stay on the app.
      // That is the expected flow when ?a=1 is absent but a cookie exists.
      fetch('/api/auth/session')
        .then(r => r.json())
        .then((d) => {
          if (d && !d.authenticated) {
            window.location.replace('/landing');
          }
        })
        .catch(() => {});
      // Let checkSession() proceed: it will show the workspace for
      // returning users, and if the user has no session at all we
      // already redirected above.
    }
    const loginForm = document.getElementById('loginForm');
    loginForm.addEventListener('submit', (event) => {
      event.preventDefault();
      if (this.isLocked()) return;
      this.login();
    });
    loginForm.addEventListener('input', () => this.clearLoginError());
    document.getElementById('loginRole').addEventListener('change', () => {
      this.updateLoginFields();
      this.clearLoginError();
    });
    document.getElementById('passwordChangeForm').addEventListener('submit', (event) => {
      event.preventDefault();
      this.changePassword();
    });
    document.getElementById('btnLogout').addEventListener('click', () => this.logout());
    this.updateLoginFields();
    this.checkSession();
  },

  clearLoginError() {
    const errorBox = document.getElementById('loginError');
    errorBox.textContent = '';
    errorBox.hidden = true;
  },

  showLoginError(message) {
    const errorBox = document.getElementById('loginError');
    errorBox.textContent = message;
    errorBox.hidden = false;
  },

  isLocked() {
    return this.lockoutDeadline > Date.now();
  },

  applyLockout(retryAfterSeconds) {
    this.lockoutDeadline = Date.now() + Math.max(1, Number(retryAfterSeconds) || 0) * 1000;
    this.startLockoutCountdown();
  },

  startLockoutCountdown() {
    const form = document.getElementById('loginForm');
    const notice = document.getElementById('loginLockoutNotice');
    const button = document.getElementById('loginSubmit');
    form.classList.add('is-locked');
    button.disabled = true;
    notice.hidden = false;

    const tick = () => {
      const remainingMs = this.lockoutDeadline - Date.now();
      if (remainingMs <= 0) {
        this.clearLockout();
        return;
      }
      const totalSeconds = Math.ceil(remainingMs / 1000);
      const minutes = Math.floor(totalSeconds / 60);
      const seconds = totalSeconds % 60;
      notice.innerHTML = '';
      const prefix = document.createElement('span');
      prefix.textContent = 'Akses dikunci. Mencoba lagi dalam ';
      const countdown = document.createElement('span');
      countdown.className = 'lockout-countdown';
      countdown.textContent = `${minutes}:${String(seconds).padStart(2, '0')}`;
      const suffix = document.createElement('span');
      suffix.textContent = '...';
      notice.append(prefix, countdown, suffix);
      this.lockoutTimer = setTimeout(tick, 250);
    };
    tick();
  },

  clearLockout() {
    const form = document.getElementById('loginForm');
    const notice = document.getElementById('loginLockoutNotice');
    const button = document.getElementById('loginSubmit');
    clearTimeout(this.lockoutTimer);
    this.lockoutTimer = null;
    this.lockoutDeadline = 0;
    form.classList.remove('is-locked');
    button.disabled = false;
    notice.hidden = true;
    notice.textContent = '';
  },

  updateLoginFields() {
    const receiverMode = document.getElementById('loginRole').value === 'RECEIVER';
    document.getElementById('receiverUsernameGroup').hidden = !receiverMode;
    document.getElementById('receiverUsername').required = receiverMode;
    document.getElementById('loginPasswordLabel').textContent = receiverMode
      ? 'Password akun receiver'
      : 'Password aplikasi';
  },

  async checkSession() {
    try {
      const response = await fetch('/api/auth/session');
      const data = await response.json();
      if (response.ok && data.authenticated) {
        if (data.must_change_password) {
          this.showPasswordChangeGate(data);
        } else {
          this.showWorkspace(data);
        }
      }
    } catch (error) {
      console.error('Session check failed:', error);
    }
  },

  async login() {
    const form = document.getElementById('loginForm');
    const button = document.getElementById('loginSubmit');
    const receiverMode = document.getElementById('loginRole').value === 'RECEIVER';
    const password = document.getElementById('loginPassword').value;
    const endpoint = receiverMode ? '/api/auth/receiver-login' : '/api/auth/login';
    const body = receiverMode
      ? {
        username: document.getElementById('receiverUsername').value.trim(),
        password
      }
      : { password };
    button.disabled = true;
    this.clearLoginError();
    ProcessingModal.show("Masuk ke aplikasi…", 30);

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        if (response.status === 429) {
          const retryAfter = Number(response.headers.get('Retry-After')) || 300;
          this.applyLockout(retryAfter);
          this.showLoginError(data.detail || 'Terlalu banyak percobaan.');
          return;
        }
        throw new Error(data.detail || 'Login gagal.');
      }

      this.clearLoginError();
      this.clearLockout();
      form.reset();
      this.updateLoginFields();
      if (data.must_change_password) {
        this.showPasswordChangeGate(data);
      } else {
        this.showWorkspace(data);
      }
    } catch (error) {
      if (!this.isLocked()) button.disabled = false;
      ProcessingModal.hide();
      this.showLoginError(error.message || 'Tidak dapat masuk ke aplikasi.');
    } finally {
      if (!this.isLocked()) button.disabled = false;
      ProcessingModal.hide();
    }
  },

  showPasswordChangeGate(session) {
    State.isLoggedIn = true;
    State.role = session.role;
    State.principalId = session.principal_id;
    document.getElementById('authGate').hidden = true;
    document.getElementById('passwordChangeGate').hidden = false;
    document.getElementById('appLayout').classList.remove('is-visible');
    const workspace = document.getElementById('appWorkspace');
    if (workspace) workspace.hidden = true;
    const mobileNavToggle = document.getElementById('mobileNavToggle');
    if (mobileNavToggle) mobileNavToggle.hidden = true;
    const mobileMenu = document.getElementById('mobileMenu');
    if (mobileMenu) mobileMenu.hidden = true;
    const btnLogout = document.getElementById('btnLogout');
    if (btnLogout) btnLogout.hidden = false;
  },

  async changePassword() {
    const form = document.getElementById('passwordChangeForm');
    const button = document.getElementById('changePasswordSubmit');
    const errorBox = document.getElementById('passwordChangeError');
    const password = document.getElementById('newReceiverPassword').value;
    const confirmation = document.getElementById('confirmReceiverPassword').value;
    errorBox.hidden = true;
    if (password.length < 16) {
      errorBox.textContent = 'Password baru minimal 16 karakter.';
      errorBox.hidden = false;
      return;
    }
    if (password !== confirmation) {
      errorBox.textContent = 'Kedua password tidak sama.';
      errorBox.hidden = false;
      return;
    }

    button.disabled = true;
    try {
      const response = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_password: password })
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.detail || 'Password tidak dapat diperbarui.');
      }
      form.reset();
      this.showWorkspace({
        role: 'RECEIVER',
        principal_id: State.principalId,
        must_change_password: false,
        idle_timeout_seconds: data.idle_timeout_seconds
      });
    } catch (error) {
      errorBox.textContent = error.message || 'Password tidak dapat diperbarui.';
      errorBox.hidden = false;
    } finally {
      button.disabled = false;
    }
  },

  showWorkspace(session) {
    State.isLoggedIn = true;
    State.role = session.role;
    State.principalId = session.principal_id;
    if (!State.role || !State.principalId) {
      console.error('Auth: session role/principal_id kosong', session);
      return;
    }
    document.getElementById('authGate').hidden = true;
    document.getElementById('passwordChangeGate').hidden = true;
    document.getElementById('appLayout').classList.add('is-visible');
    const workspace = document.getElementById('appWorkspace');
    if (!workspace) return console.error('appWorkspace not found');
    workspace.hidden = false;
    const btnLogout = document.getElementById('btnLogout');
    if (btnLogout) btnLogout.hidden = false;
    const mobileNavToggle = document.getElementById('mobileNavToggle');
    if (mobileNavToggle) mobileNavToggle.setAttribute('aria-expanded', 'false');
    // Mobile hamburger: always available (even for receivers), so the top bar
    // never stacks three buttons on a narrow screen.
    const mobileMenu = document.getElementById('mobileMenu');
    if (mobileMenu) mobileMenu.hidden = false;

    const isReceiver = State.role === 'RECEIVER';
    const sidebar = document.querySelector('.app-sidebar');
    const appNavigation = document.getElementById('appNavigation');
    if (isReceiver) {
      if (sidebar) sidebar.hidden = true;
      if (appNavigation) appNavigation.hidden = true;
    } else {
      if (sidebar) sidebar.hidden = false;
      if (appNavigation) appNavigation.hidden = false;
      if (appNavigation) appNavigation.style.display = 'flex';
    }
    if (mobileNavToggle) mobileNavToggle.hidden = isReceiver;

    // Hide the receiver (inbox) tab for commanders - they send, not receive.
    // Commander message history is already shown in the transmit card.
    document.querySelectorAll('.tab-btn').forEach((tab) => {
      const isReceiverTab = tab.dataset.tab === 'receiver';
      if (isReceiver) {
        tab.hidden = !isReceiverTab;
      } else {
        tab.hidden = isReceiverTab;
      }
    });
    if (isReceiver) {
      switchTab('receiver');
    } else {
      if (window.loadCommanderRecipients) window.loadCommanderRecipients();
      if (window.loadCommanderMessages) window.loadCommanderMessages();
      switchTab('commander');
    }
    if (!State.ws) initWebSocket();
  },

  async logout(message = '') {
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
    } catch (error) {
      console.error('Logout request failed:', error);
    }

    if (window.clearCommanderSensitiveData) window.clearCommanderSensitiveData();
    if (window.clearReceiverSensitiveData) window.clearReceiverSensitiveData();
    State.isLoggedIn = false;
    State.role = null;
    State.principalId = null;
    if (State.ws) State.ws.close();
    document.getElementById('authGate').hidden = false;
    document.getElementById('passwordChangeGate').hidden = true;
    const nav = document.getElementById('appNavigation');
    if (nav) nav.hidden = true;
    document.getElementById('appLayout').classList.remove('is-visible');
    const workspace = document.getElementById('appWorkspace');
    if (workspace) workspace.hidden = true;
    const mobileNavToggle = document.getElementById('mobileNavToggle');
    if (mobileNavToggle) mobileNavToggle.setAttribute('aria-expanded', 'false');
    const mobileMenu = document.getElementById('mobileMenu');
    if (mobileMenu) {
      mobileMenu.hidden = true;
      mobileMenu.setAttribute('aria-expanded', 'false');
    }
    const btnLogout = document.getElementById('btnLogout');
    if (btnLogout) btnLogout.hidden = true;
    if (message) showToast(message, 'warning');
  }
};

document.addEventListener('DOMContentLoaded', () => AppAuth.init());

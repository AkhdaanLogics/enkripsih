const AppAuth = {
  idleTimeoutMs: 5 * 60 * 1000,
  idleTimer: null,
  lastActivitySyncAt: 0,

  init() {
    const loginForm = document.getElementById('loginForm');
    loginForm.addEventListener('submit', (event) => {
      event.preventDefault();
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
    for (const eventName of ['pointerdown', 'keydown', 'touchstart', 'scroll']) {
      window.addEventListener(eventName, () => this.recordActivity(), { passive: true });
    }
    this.updateLoginFields();
    this.restoreLoginError();
    this.checkSession();
  },

  restoreLoginError() {
    try {
      const message = sessionStorage.getItem('enkripsih_login_error');
      if (message) this.showLoginError(message);
    } catch (error) {
      console.warn('Login error could not be restored:', error);
    }
  },

  showLoginError(message) {
    const errorBox = document.getElementById('loginError');
    errorBox.textContent = message;
    errorBox.hidden = false;
    try {
      sessionStorage.setItem('enkripsih_login_error', message);
    } catch (error) {
      console.warn('Login error could not be saved for refresh:', error);
    }
  },

  clearLoginError() {
    try {
      sessionStorage.removeItem('enkripsih_login_error');
    } catch (error) {
      console.warn('Saved login error could not be cleared:', error);
    }
    const errorBox = document.getElementById('loginError');
    errorBox.textContent = '';
    errorBox.hidden = true;
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

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.detail || 'Login gagal.');
      }

      this.clearLoginError();
      form.reset();
      this.updateLoginFields();
      if (data.must_change_password) {
        this.showPasswordChangeGate(data);
      } else {
        this.showWorkspace(data);
      }
    } catch (error) {
      this.showLoginError(error.message || 'Tidak dapat masuk ke aplikasi.');
    } finally {
      button.disabled = false;
    }
  },

  showPasswordChangeGate(session) {
    State.isLoggedIn = true;
    State.role = session.role;
    State.principalId = session.principal_id;
    this.startIdleMonitor(session.idle_timeout_seconds);
    document.getElementById('authGate').style.display = 'none';
    document.getElementById('passwordChangeGate').style.display = 'block';
    document.getElementById('appLayout').classList.remove('is-visible');
    document.getElementById('appWorkspace').style.display = 'none';
    document.getElementById('mobileNavToggle').hidden = true;
    document.getElementById('btnLogout').style.display = 'inline-flex';
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
    State.role = session.role || 'COMMANDER';
    State.principalId = session.principal_id || 'CMD-01';
    document.getElementById('authGate').style.display = 'none';
    document.getElementById('passwordChangeGate').style.display = 'none';
    document.getElementById('appLayout').classList.add('is-visible');
    document.getElementById('appNavigation').style.display = 'flex';
    document.getElementById('appNavigation').classList.remove('is-open');
    document.querySelector('.app-sidebar').classList.remove('is-open');
    document.getElementById('appWorkspace').style.display = 'block';
    document.getElementById('mobileNavToggle').hidden = false;
    document.getElementById('mobileNavToggle').setAttribute('aria-expanded', 'false');
    document.getElementById('btnLogout').style.display = 'inline-flex';
    this.startIdleMonitor(session.idle_timeout_seconds);

    document.querySelectorAll('.tab-btn').forEach((tab) => {
      tab.hidden = State.role === 'RECEIVER' && tab.dataset.tab !== 'receiver';
    });
    if (State.role === 'RECEIVER') {
      switchTab('receiver');
    } else {
      if (window.loadCommanderRecipients) window.loadCommanderRecipients();
      if (window.loadCommanderMessages) window.loadCommanderMessages();
      switchTab('commander');
    }
    if (!State.ws) initWebSocket();
  },

  startIdleMonitor(timeoutSeconds = 300) {
    this.idleTimeoutMs = Math.max(1, Number(timeoutSeconds) || 300) * 1000;
    this.lastActivitySyncAt = Date.now();
    clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(
      () => this.logout('Sesi berakhir karena tidak ada aktivitas. Silakan masuk kembali.'),
      this.idleTimeoutMs
    );
  },

  recordActivity() {
    if (!State.isLoggedIn) return;

    const now = Date.now();
    clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(
      () => this.logout('Sesi berakhir karena tidak ada aktivitas. Silakan masuk kembali.'),
      this.idleTimeoutMs
    );

    const syncIntervalMs = Math.min(30_000, this.idleTimeoutMs / 3);
    if (now - this.lastActivitySyncAt < syncIntervalMs) return;
    this.lastActivitySyncAt = now;
    fetch('/api/auth/activity', { method: 'POST' })
      .then((response) => {
        if (response.status === 401) {
          this.logout('Sesi berakhir. Silakan masuk kembali.');
        } else if (!response.ok) {
          throw new Error(`Pembaruan sesi gagal (HTTP ${response.status}).`);
        }
      })
      .catch((error) => console.error('Session activity update failed:', error));
  },

  async logout(message = '') {
    clearTimeout(this.idleTimer);
    this.idleTimer = null;
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
    document.getElementById('authGate').style.display = 'block';
    document.getElementById('passwordChangeGate').style.display = 'none';
    document.getElementById('appNavigation').style.display = 'none';
    document.getElementById('appNavigation').classList.remove('is-open');
    document.getElementById('appLayout').classList.remove('is-visible');
    document.querySelector('.app-sidebar').classList.remove('is-open');
    document.getElementById('appWorkspace').style.display = 'none';
    document.getElementById('mobileNavToggle').hidden = true;
    document.getElementById('mobileNavToggle').setAttribute('aria-expanded', 'false');
    document.getElementById('btnLogout').style.display = 'none';
    if (message) showToast(message, 'warning');
  }
};

document.addEventListener('DOMContentLoaded', () => AppAuth.init());

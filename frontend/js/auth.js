const AppAuth = {
  lockoutTimer: null,
  lockoutDeadline: 0,

  init() {
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
    this.restoreLoginError();
    this.restoreLockout();
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

  isLocked() {
    return this.lockoutDeadline > Date.now();
  },

  restoreLockout() {
    let deadline = 0;
    try {
      deadline = Number(sessionStorage.getItem('enkripsih_lockout_until') || 0);
    } catch (error) {
      console.warn('Lockout state could not be restored:', error);
    }
    if (deadline > Date.now()) {
      this.lockoutDeadline = deadline;
      this.startLockoutCountdown();
    } else {
      this.clearLockoutState();
    }
  },

  applyLockout(retryAfterSeconds) {
    this.lockoutDeadline = Date.now() + Math.max(1, Number(retryAfterSeconds) || 0) * 1000;
    try {
      sessionStorage.setItem('enkripsih_lockout_until', String(this.lockoutDeadline));
    } catch (error) {
      console.warn('Lockout state could not be saved:', error);
    }
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
    this.clearLockoutState();
  },

  clearLockoutState() {
    try {
      sessionStorage.removeItem('enkripsih_lockout_until');
    } catch (error) {
      console.warn('Lockout state could not be cleared:', error);
    }
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
      this.showLoginError(error.message || 'Tidak dapat masuk ke aplikasi.');
    } finally {
      if (!this.isLocked()) button.disabled = false;
    }
  },

  showPasswordChangeGate(session) {
    State.isLoggedIn = true;
    State.role = session.role;
    State.principalId = session.principal_id;
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

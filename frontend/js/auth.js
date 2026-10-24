const AppAuth = {
  init() {
    document.getElementById('loginForm').addEventListener('submit', (event) => {
      event.preventDefault();
      this.login();
    });
    document.getElementById('loginRole').addEventListener('change', () => {
      this.updateLoginFields();
    });
    document.getElementById('passwordChangeForm').addEventListener('submit', (event) => {
      event.preventDefault();
      this.changePassword();
    });
    document.getElementById('btnLogout').addEventListener('click', () => this.logout());
    this.updateLoginFields();
    this.checkSession();
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
    const errorBox = document.getElementById('loginError');
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
    errorBox.hidden = true;

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

      form.reset();
      this.updateLoginFields();
      if (data.must_change_password) {
        this.showPasswordChangeGate(data);
      } else {
        this.showWorkspace(data);
      }
    } catch (error) {
      errorBox.textContent = error.message || 'Tidak dapat masuk ke aplikasi.';
      errorBox.hidden = false;
    } finally {
      button.disabled = false;
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
        must_change_password: false
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

  async logout() {
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
  }
};

document.addEventListener('DOMContentLoaded', () => AppAuth.init());

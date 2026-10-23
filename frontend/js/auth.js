const AppAuth = {
  init() {
    document.getElementById('loginForm').addEventListener('submit', (event) => {
      event.preventDefault();
      this.login();
    });
    document.getElementById('btnLogout').addEventListener('click', () => this.logout());
    this.checkSession();
  },

  async checkSession() {
    try {
      const response = await fetch('/api/auth/session');
      const data = await response.json();
      if (response.ok && data.authenticated) this.showWorkspace();
    } catch (error) {
      console.error('Session check failed:', error);
    }
  },

  async login() {
    const form = document.getElementById('loginForm');
    const button = document.getElementById('loginSubmit');
    const errorBox = document.getElementById('loginError');
    const password = document.getElementById('loginPassword').value;
    button.disabled = true;
    errorBox.hidden = true;

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password })
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.detail || 'Login gagal.');
      }

      form.reset();
      this.showWorkspace();
    } catch (error) {
      errorBox.textContent = error.message || 'Tidak dapat masuk ke aplikasi.';
      errorBox.hidden = false;
    } finally {
      button.disabled = false;
    }
  },

  showWorkspace() {
    State.isLoggedIn = true;
    document.getElementById('authGate').style.display = 'none';
    document.getElementById('appNavigation').style.display = 'flex';
    document.getElementById('appWorkspace').style.display = 'block';
    document.getElementById('btnLogout').style.display = 'inline-flex';
    if (window.loadCommanderMessages) window.loadCommanderMessages();
    if (!State.ws) initWebSocket();
  },

  async logout() {
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
    } catch (error) {
      console.error('Logout request failed:', error);
    }

    State.isLoggedIn = false;
    if (State.ws) State.ws.close();
    document.getElementById('authGate').style.display = 'block';
    document.getElementById('appNavigation').style.display = 'none';
    document.getElementById('appWorkspace').style.display = 'none';
    document.getElementById('btnLogout').style.display = 'none';
  }
};

document.addEventListener('DOMContentLoaded', () => AppAuth.init());

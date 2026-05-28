/* ============================================================
   ChessMate &mdash; Home page logic.
   - Show login/profile state in topbar
   - Gate "needs-auth" cards: prompt login, then redirect onward
   - Login + register inside the auth modal
   - Persist board theme via board-themes.js
   ============================================================ */

const TOKEN_KEY = 'chessmate_token';
const PENDING_REDIRECT_KEY = 'chessmate_pending_redirect';

let authToken = localStorage.getItem(TOKEN_KEY);
let currentUser = null;

const userChipEl   = document.querySelector('#user-chip');
const userNameEl   = document.querySelector('#user-name');
const userRatingEl = document.querySelector('#user-rating');
const loginBtn     = document.querySelector('#login-btn');
const logoutBtn    = document.querySelector('#logout-btn');
const profileBtn   = document.querySelector('#profile-btn');
const profileCard  = document.querySelector('#profile-card');
const guestCard    = document.querySelector('#guest-card');
const guestLogin   = document.querySelector('#guest-login-btn');

const authModalEl   = document.querySelector('#auth-modal');
const authModalClose = document.querySelector('#auth-modal-close');
const authTabLogin  = document.querySelector('#auth-tab-login');
const authTabReg    = document.querySelector('#auth-tab-register');
const authLoginForm = document.querySelector('#auth-login-form');
const authRegForm   = document.querySelector('#auth-register-form');
const authErrorEl   = document.querySelector('#auth-error');
const loginUserEl   = document.querySelector('#login-username');
const loginPassEl   = document.querySelector('#login-password');
const loginSubmitEl = document.querySelector('#login-submit');
const regUserEl     = document.querySelector('#register-username');
const regPassEl     = document.querySelector('#register-password');
const regSubmitEl   = document.querySelector('#register-submit');

// ---------------------- Auth helpers ----------------------

function showAuthModal(redirectTo) {
  authErrorEl.textContent = '';
  if (redirectTo) {
    localStorage.setItem(PENDING_REDIRECT_KEY, redirectTo);
  }
  authModalEl.hidden = false;
}

function hideAuthModal() {
  authModalEl.hidden = true;
  localStorage.removeItem(PENDING_REDIRECT_KEY);
}

function switchAuthTab(tab) {
  const isLogin = tab === 'login';
  authTabLogin.classList.toggle('active', isLogin);
  authTabReg.classList.toggle('active', !isLogin);
  authLoginForm.hidden = !isLogin;
  authRegForm.hidden = isLogin;
  authErrorEl.textContent = '';
}

function updateChrome() {
  if (currentUser) {
    userChipEl.hidden = false;
    userNameEl.textContent = currentUser.username;
    userRatingEl.textContent = currentUser.rating ? `★ ${currentUser.rating}` : '';
    loginBtn.hidden = true;
    profileBtn.hidden = false;
    guestCard.hidden = true;
    profileCard.hidden = false;
    document.querySelector('#profile-card-name').textContent = currentUser.username;
    document.querySelector('#profile-rating').textContent = currentUser.rating || '—';
    document.querySelector('#profile-rd').textContent = currentUser.rd || '—';
    document.querySelector('#profile-games').textContent = currentUser.games != null ? currentUser.games : '—';
  } else {
    userChipEl.hidden = true;
    loginBtn.hidden = false;
    profileBtn.hidden = true;
    guestCard.hidden = false;
    profileCard.hidden = true;
  }
}

async function fetchMe() {
  if (!authToken) return null;
  try {
    const res = await fetch('/auth/me', {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    const data = await res.json();
    if (!data.ok) return null;
    return {
      username: data.user.username,
      rating: data.user.rating,
      rd: data.user.rd,
      games: (data.history && data.history.length) || 0,
    };
  } catch {
    return null;
  }
}

async function checkAuthSilently() {
  if (!authToken) return false;
  const me = await fetchMe();
  if (!me) {
    authToken = null;
    localStorage.removeItem(TOKEN_KEY);
    currentUser = null;
    return false;
  }
  currentUser = me;
  return true;
}

// ---------------------- Login / register ----------------------

async function performLogin(e) {
  e.preventDefault();
  const username = loginUserEl.value.trim();
  const password = loginPassEl.value;
  if (!username || !password) {
    authErrorEl.textContent = 'Please fill in both fields.';
    return;
  }
  loginSubmitEl.disabled = true;
  authErrorEl.textContent = '';
  try {
    const res  = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'Login failed.');
    authToken = data.token;
    localStorage.setItem(TOKEN_KEY, authToken);
    currentUser = { username: data.username };
    // Refresh full profile data, then redirect or update chrome.
    const me = await fetchMe();
    if (me) currentUser = me;
    redirectOrStay();
  } catch (err) {
    authErrorEl.textContent = err.message;
  } finally {
    loginSubmitEl.disabled = false;
  }
}

async function performRegister(e) {
  e.preventDefault();
  const username = regUserEl.value.trim();
  const password = regPassEl.value;
  if (!username || !password) {
    authErrorEl.textContent = 'Please fill in both fields.';
    return;
  }
  regSubmitEl.disabled = true;
  authErrorEl.textContent = '';
  try {
    const regRes = await fetch('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const regData = await regRes.json();
    if (!regData.ok) throw new Error(regData.error || 'Registration failed.');
    // Auto-login
    const loginRes = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const loginData = await loginRes.json();
    if (!loginData.ok) throw new Error('Account created. Please log in.');
    authToken = loginData.token;
    localStorage.setItem(TOKEN_KEY, authToken);
    currentUser = { username: loginData.username };
    const me = await fetchMe();
    if (me) currentUser = me;
    redirectOrStay();
  } catch (err) {
    authErrorEl.textContent = err.message;
  } finally {
    regSubmitEl.disabled = false;
  }
}

function redirectOrStay() {
  const target = localStorage.getItem(PENDING_REDIRECT_KEY);
  localStorage.removeItem(PENDING_REDIRECT_KEY);
  if (target) {
    location.href = target;
    return;
  }
  hideAuthModal();
  updateChrome();
}

function performLogout() {
  authToken = null;
  currentUser = null;
  localStorage.removeItem(TOKEN_KEY);
  updateChrome();
}

// ---------------------- Card gating ----------------------

document.querySelectorAll('.play-card.needs-auth').forEach((card) => {
  card.addEventListener('click', (e) => {
    if (currentUser) return;   // logged in → let the link proceed
    e.preventDefault();
    switchAuthTab('login');
    showAuthModal(card.getAttribute('href'));
  });
});

// ---------------------- Wire UI ----------------------

loginBtn.addEventListener('click', () => { switchAuthTab('login'); showAuthModal(); });
if (logoutBtn) logoutBtn.addEventListener('click', performLogout);
profileBtn.addEventListener('click', () => { location.href = '/profile'; });
guestLogin.addEventListener('click', () => { switchAuthTab('login'); showAuthModal(); });
authModalClose.addEventListener('click', hideAuthModal);
authTabLogin.addEventListener('click', () => switchAuthTab('login'));
authTabReg.addEventListener('click',   () => switchAuthTab('register'));
authLoginForm.addEventListener('submit', performLogin);
authRegForm.addEventListener('submit',   performRegister);

// ---------------------- Boot ----------------------

(async function boot() {
  await checkAuthSilently();
  updateChrome();
  // If we landed back here with a pending redirect AND we're authed, honor it.
  const target = localStorage.getItem(PENDING_REDIRECT_KEY);
  if (target && currentUser) {
    localStorage.removeItem(PENDING_REDIRECT_KEY);
    location.href = target;
  }
})();

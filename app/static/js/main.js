// Shared UI helpers used across all pages.

// ---------- Toast ----------
export function toast(message, { type = 'info', title = '' } = {}) {
  let wrap = document.querySelector('.toast-wrap');
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.className = 'toast-wrap';
    document.body.appendChild(wrap);
  }
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const titles = { success: 'Yay!', error: 'Oops…', info: 'Heads up' };
  el.innerHTML = `
    <div style="font-size:1.2rem">${type === 'success' ? '🌸' : type === 'error' ? '💔' : '💌'}</div>
    <div>
      <b>${title || titles[type] || 'Notice'}</b>
      <small>${message}</small>
    </div>`;
  wrap.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(10px)';
    el.style.transition = 'all .25s ease';
    setTimeout(() => el.remove(), 260);
  }, 3200);
}

// Expose for templates / inline calls
window.toast = toast;

// ---------- Mobile menu ----------
document.addEventListener('click', (e) => {
  const trigger = e.target.closest('[data-menu-toggle]');
  if (trigger) {
    document.querySelector('.nav-links')?.classList.toggle('open');
  }
});

// ---------- Theme toggle ----------
const themeKey = 'pl-theme';
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem(themeKey, t);
  const btn = document.querySelector('[data-theme-toggle]');
  if (btn) btn.textContent = t === 'dark' ? '☀️' : '🌙';
}
const saved = localStorage.getItem(themeKey) || 'light';
applyTheme(saved);
document.addEventListener('click', (e) => {
  if (e.target.closest('[data-theme-toggle]')) {
    const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    applyTheme(next);
  }
});

// ---------- Flash messages from server ----------
window.flashServerMessages = function (messages) {
  for (const [category, message] of messages) {
    const type = ['success', 'error', 'info'].includes(category) ? category : 'info';
    toast(message, { type });
  }
};

// Content reveal is handled by a pure CSS keyframe animation in base.html
// so the page never depends on this module for visibility. We keep a no-op
// PLRevealAll for backward-compat with templates that may call it.
window.PLRevealAll = function () { /* CSS-only now */ };

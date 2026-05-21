// Wishlist toggle behavior for any element with [data-wishlist].
//
// Guest visitors get nudged to the registration page, just like add-to-cart.
// Signed-in buyers POST to /account/wishlist/toggle and we update the
// button's aria-pressed state from the JSON response so the heart fills
// without a page reload.
(function () {
  function currentUser() {
    return (window.__PL__ && window.__PL__.CURRENT_USER) || null;
  }

  function showToast(text, type) {
    if (window.toast) window.toast(text, { type: type || 'info' });
  }

  async function refreshSaved() {
    // Pull the current wishlist once and paint the hearts on first paint.
    if (!currentUser()) return;
    try {
      const r = await fetch('/account/wishlist/ids', { credentials: 'same-origin' });
      if (!r.ok) return;
      const data = await r.json();
      const saved = new Set(data.ids || []);
      document.querySelectorAll('[data-wishlist]').forEach((btn) => {
        const pid = btn.getAttribute('data-product-id');
        if (saved.has(pid)) {
          btn.setAttribute('aria-pressed', 'true');
          const lbl = btn.querySelector('.wishlist-label');
          if (lbl) lbl.textContent = 'Saved to wishlist';
        }
      });
    } catch (_) {}
  }

  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-wishlist]');
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();

    if (!currentUser()) {
      showToast('Create an account to save to your wishlist. ✨', 'info');
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      setTimeout(() => { window.location.href = '/auth/register?next=' + next; }, 700);
      return;
    }

    const pid = btn.getAttribute('data-product-id');
    if (!pid) return;
    btn.disabled = true;
    try {
      const res = await fetch('/account/wishlist/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product_id: pid }),
        credentials: 'same-origin',
      });
      const data = await res.json();
      if (data.ok) {
        btn.setAttribute('aria-pressed', data.saved ? 'true' : 'false');
        const lbl = btn.querySelector('.wishlist-label');
        if (lbl) lbl.textContent = data.saved ? 'Saved to wishlist' : 'Save to wishlist';
        showToast(data.saved ? 'Added to wishlist 💖' : 'Removed from wishlist', 'success');
      } else {
        showToast(data.error || 'Could not update wishlist.', 'error');
      }
    } catch (_) {
      showToast('Network hiccup. Try again.', 'error');
    } finally {
      btn.disabled = false;
    }
  });

  document.addEventListener('DOMContentLoaded', refreshSaved);
})();

// LocalStorage cart with simple pub/sub. Used by every page so adding to cart
// from the home page reflects in the navbar pill and on the cart page.
import { toast } from './main.js';

const STORAGE_KEY = 'pl-cart';
const listeners = new Set();

// Set by base.html from session — when null, the visitor is a guest and
// every "Add to cart" click should redirect to the registration page.
function currentUser() {
  return (window.__PL__ && window.__PL__.CURRENT_USER) || null;
}

function read() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); }
  catch { return []; }
}
function write(items) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  listeners.forEach((fn) => fn(items));
  updateBadge(items);
}
function updateBadge(items = read()) {
  const count = items.reduce((s, it) => s + Number(it.quantity || 0), 0);
  document.querySelectorAll('[data-cart-count]').forEach((el) => {
    el.textContent = count;
    el.style.display = count > 0 ? 'inline-flex' : 'none';
  });
}

export const cart = {
  items: () => read(),
  count: () => read().reduce((s, it) => s + Number(it.quantity || 0), 0),
  subtotal: () => read().reduce((s, it) => s + Number(it.price) * Number(it.quantity), 0),
  add(product, qty = 1, customization = '') {
    // Guard: out-of-stock items can never be added to the basket.
    const stock = product.stock !== undefined ? Number(product.stock) : null;
    if (stock !== null && stock <= 0) {
      toast(`Sorry, "${product.name}" is out of stock.`, { type: 'error' });
      return false;
    }

    const items = read();
    const idx = items.findIndex(
      (it) => it.product_id === product.id && (it.customization || '') === customization
    );
    const existingQty = idx >= 0 ? Number(items[idx].quantity) : 0;
    const newQty = existingQty + qty;
    if (stock !== null && newQty > stock) {
      toast(`Only ${stock} of "${product.name}" left in stock.`, { type: 'error' });
      return false;
    }

    if (idx >= 0) {
      items[idx].quantity = newQty;
    } else {
      items.push({
        product_id: product.id,
        name: product.name,
        slug: product.slug,
        price: Number(product.price),
        image: product.cover_image || product.image || '',
        quantity: qty,
        customization,
        stock,
      });
    }
    write(items);
    toast(`${product.name} added to your basket`, { type: 'success' });
    return true;
  },
  setQuantity(productId, qty, customization = '') {
    const items = read().map((it) => {
      if (it.product_id === productId && (it.customization || '') === customization) {
        const target = Math.max(1, Number(qty) || 1);
        const stock = it.stock != null ? Number(it.stock) : null;
        const final = stock != null ? Math.min(target, Math.max(1, stock)) : target;
        if (stock != null && target > stock) {
          toast(`Only ${stock} left in stock.`, { type: 'error' });
        }
        return { ...it, quantity: final };
      }
      return it;
    });
    write(items);
  },
  remove(productId, customization = '') {
    const items = read().filter(
      (it) => !(it.product_id === productId && (it.customization || '') === customization)
    );
    write(items);
  },
  clear() { write([]); },
  on(fn) { listeners.add(fn); return () => listeners.delete(fn); },
};

window.PLCart = cart;
updateBadge();

// Wire any data-add-to-cart buttons (cards on home/shop pages).
// • Guests are redirected to the register page (with a friendly toast).
// • Out-of-stock products are blocked at the click site so the toast
//   appears even before cart.add runs.
document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-add-to-cart]');
  if (!btn) return;
  e.preventDefault();

  // Out-of-stock guard (controlled by data-stock="0" on the button).
  const stockAttr = btn.dataset.stock;
  if (stockAttr !== undefined && stockAttr !== '' && Number(stockAttr) <= 0) {
    toast(`Sorry, "${btn.dataset.name}" is out of stock right now.`, { type: 'error' });
    return;
  }

  // Guest guard — redirect to registration with a flash-like toast.
  if (!currentUser()) {
    toast('Please create an account to add items to your basket. ✨', { type: 'info' });
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    setTimeout(() => {
      window.location.href = '/auth/register?next=' + next;
    }, 700);
    return;
  }

  const product = {
    id: btn.dataset.id,
    name: btn.dataset.name,
    slug: btn.dataset.slug,
    price: btn.dataset.price,
    cover_image: btn.dataset.image,
    stock: stockAttr,
  };
  cart.add(product, 1);
});

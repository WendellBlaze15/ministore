// LocalStorage cart with simple pub/sub. Used by every page so adding to cart
// from the home page reflects in the navbar pill and on the cart page.
import { toast } from './main.js';

const STORAGE_KEY = 'pl-cart';
const listeners = new Set();

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
    const items = read();
    const idx = items.findIndex(
      (it) => it.product_id === product.id && (it.customization || '') === customization
    );
    if (idx >= 0) {
      items[idx].quantity = Number(items[idx].quantity) + qty;
    } else {
      items.push({
        product_id: product.id,
        name: product.name,
        slug: product.slug,
        price: Number(product.price),
        image: product.cover_image || product.image || '',
        quantity: qty,
        customization,
      });
    }
    write(items);
    toast(`${product.name} added to your basket`, { type: 'success' });
  },
  setQuantity(productId, qty, customization = '') {
    const items = read().map((it) => {
      if (it.product_id === productId && (it.customization || '') === customization) {
        return { ...it, quantity: Math.max(1, Number(qty) || 1) };
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

// Wire any data-add-to-cart buttons (cards on home/shop pages)
document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-add-to-cart]');
  if (!btn) return;
  e.preventDefault();
  const product = {
    id: btn.dataset.id,
    name: btn.dataset.name,
    slug: btn.dataset.slug,
    price: btn.dataset.price,
    cover_image: btn.dataset.image,
  };
  cart.add(product, 1);
});

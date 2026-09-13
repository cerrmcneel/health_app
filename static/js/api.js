// Shared helpers: fetch wrapper, formatting, toasts, nav highlighting.

export function getActiveProfileId() {
  return localStorage.getItem('active_profile_id') || null;
}

export function setActiveProfileId(id) {
  if (id) {
    localStorage.setItem('active_profile_id', String(id));
    document.cookie = `active_profile_id=${encodeURIComponent(id)}; path=/; SameSite=Lax; max-age=31536000`;
  } else {
    localStorage.removeItem('active_profile_id');
    document.cookie = 'active_profile_id=; path=/; max-age=0';
  }
}

// Ensure active_profile_id cookie is present for direct browser requests (like img tags)
try {
  const _initPid = getActiveProfileId();
  if (_initPid) {
    document.cookie = `active_profile_id=${encodeURIComponent(_initPid)}; path=/; SameSite=Lax; max-age=31536000`;
  }
} catch { /* ignore in non-browser environments */ }

export function getProfileToken(pid) {
  const id = pid || getActiveProfileId();
  if (!id) return null;
  return sessionStorage.getItem(`profile_token_${id}`) || null;
}

export function setProfileToken(pid, token) {
  if (pid && token) {
    sessionStorage.setItem(`profile_token_${pid}`, token);
  } else if (pid) {
    sessionStorage.removeItem(`profile_token_${pid}`);
  }
}

export function clearProfileToken(pid) {
  if (pid) {
    sessionStorage.removeItem(`profile_token_${pid}`);
  }
}

export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const pid = getActiveProfileId();
  if (pid && !headers['X-Profile-ID']) {
    headers['X-Profile-ID'] = String(pid);
  }
  const token = getProfileToken(pid);
  if (token && !headers['X-Profile-Token']) {
    headers['X-Profile-Token'] = token;
  }

  const res = await fetch(path, { ...options, headers });
  if (res.status === 204) return null;
  let body = null;
  try { body = await res.json(); } catch { /* empty or non-JSON body */ }
  if (!res.ok) {
    if (res.status === 403 && typeof body?.detail === 'string' && body.detail.includes('Profile is locked')) {
      window.dispatchEvent(new CustomEvent('profile-locked', { detail: { profileId: pid } }));
    }
    // FastAPI puts validation errors in `detail` as an array of objects.
    let detail = body?.detail ?? `Request failed (${res.status})`;
    if (Array.isArray(detail)) detail = detail.map(d => d.msg || String(d)).join('; ');
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return body;
}

export const getJSON = (p) => api(p);

export const postJSON = (p, data) => api(p, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
});

export const patchJSON = (p, data) => api(p, {
  method: 'PATCH',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
});

export const putJSON = (p, data) => api(p, {
  method: 'PUT',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
});

export const del = (p) => api(p, { method: 'DELETE' });

export function postForm(path, formData) {
  return api(path, { method: 'POST', body: formData });
}

// --- formatting ---
export const round = (n, dp = 0) => {
  const v = Number(n);
  if (!Number.isFinite(v)) return 0;
  const f = 10 ** dp;
  return Math.round(v * f) / f;
};

export const fmt = (n, dp = 0) => round(n, dp).toLocaleString(undefined, {
  minimumFractionDigits: 0, maximumFractionDigits: dp,
});

export function pct(value, target) {
  if (!target || target <= 0) return 0;
  return Math.min(100, Math.max(0, (value / target) * 100));
}

export function prettyDate(iso) {
  // Parsed as local, not UTC: `new Date('2026-09-01')` would shift the day back
  // for anyone west of UTC and mislabel the whole dashboard.
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((date - today) / 86400000);
  if (diff === 0) return 'Today';
  if (diff === -1) return 'Yesterday';
  if (diff === 1) return 'Tomorrow';
  return date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

export function shiftDay(iso, days) {
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y, m - 1, d + days);
  const p = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}`;
}

export function todayISO() {
  const d = new Date(); const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// --- toast ---
let toastTimer;
export function toast(message, isError = false) {
  let el = document.getElementById('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.classList.toggle('err', isError);
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), isError ? 5200 : 2600);
}

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function markNav() {
  const here = location.pathname.replace(/\/$/, '') || '/';
  document.querySelectorAll('nav.bottom a').forEach((a) => {
    const target = new URL(a.href, location.origin).pathname.replace(/\/$/, '') || '/';
    a.classList.toggle('active', target === here);
  });
}

/** Surfaces Ollama/model problems as a banner before the user wastes a photo. */
export async function checkHealth(containerId = 'health') {
  const box = document.getElementById(containerId);
  if (!box) return null;
  try {
    const h = await getJSON('/api/health');
    if (h.ollama !== 'ok') {
      box.className = 'banner err';
      box.innerHTML = `Ollama is unreachable at <code>${esc(h.ollama_url)}</code>. `
        + `Photo analysis is unavailable; manual logging still works.`;
      box.classList.remove('hidden');
    } else if (!h.model_ready) {
      box.className = 'banner warn';
      box.textContent = h.hint || `Model ${h.configured_model} is not ready.`;
      box.classList.remove('hidden');
    } else {
      box.classList.add('hidden');
    }
    return h;
  } catch {
    return null;
  }
}

/**
 * Infer meal type from time of day tailored to Spanish schedules:
 * - Breakfast: 06:00 - 12:30
 * - Lunch: 12:30 - 16:00 (covers 13:00 - 15:30)
 * - Snack / Merienda: 16:00 - 20:00
 * - Dinner: 20:00 - 24:00 (covers 20:00 - 23:00+)
 * - Late-night: 00:00 - 06:00 -> snack
 */
export function inferMealType(date = new Date()) {
  const h = date.getHours() + date.getMinutes() / 60;
  if (h >= 6.0 && h < 12.5) return 'breakfast';
  if (h >= 12.5 && h < 16.0) return 'lunch';
  if (h >= 16.0 && h < 20.0) return 'snack';
  if (h >= 20.0 && h <= 24.0) return 'dinner';
  return 'snack';
}

/**
 * Returns an open-source visual badge icon for a food component based on keywords.
 */
export function getFoodIcon(name = '') {
  if (!name) return '🍽️';
  const n = name.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

  if (/pollo|chicken|turkey|pavo|duck|hen|wings|poultry/.test(n)) return '🍗';
  if (/beef|steak|ternera|cerdo|pork|bacon|jamon|ham|lamb|carne|meat|burger|bistec|sausage|salchicha/.test(n)) return '🥩';
  if (/salmon|tuna|atun|pescad|fish|trout|bacalao|shrimp|gamba|langostino|calamar|squid|octopus|pulpo|marisco|seafood|sardina/.test(n)) return '🐟';
  if (/egg|huevo|omelet|tortilla|scramble/.test(n)) return '🍳';
  if (/arroz|rice|quinoa|oat|avena|cereal|grain|porridge|couscous/.test(n)) return '🍚';
  if (/pasta|spaghetti|macaron|noodle|fideo|ramen|lasagna|tallarin/.test(n)) return '🍝';
  if (/pan|bread|toast|tostada|bagel|croissant|bun|wrap|pita|sandwich|bocadillo/.test(n)) return '🍞';
  if (/patata|potato|papa|fries|chip/.test(n)) return '🥔';
  if (/brocoli|broccoli|espinaca|spinach|esparrago|asparagus|calabacin|zucchini|judia|cabbage|col|kale/.test(n)) return '🥦';
  if (/ensalada|salad|lechuga|lettuce|pepino|cucumber|zanahoria|carrot|pimiento|pepper|tomate|tomato|cebolla|onion|seta|champinon|mushroom/.test(n)) return '🥗';
  if (/aguacate|avocado|guacamole|aceituna|olive|aceite|oil/.test(n)) return '🥑';
  if (/queso|cheese|mozzarella|cheddar|parmesan|gouda|feta|cottage/.test(n)) return '🧀';
  if (/yogur|yogurt/.test(n)) return '🥣';
  if (/leche|milk|batido|shake|whey|casein|protein/.test(n)) return '🥛';
  if (/manzana|apple|platano|banana|fresa|berry|orange|naranja|uva|grape|melon|sandia|watermelon|pera|pear|limon|lemon|fruit|fruta/.test(n)) return '🍎';
  if (/nuez|nut|almendra|almond|cacahuete|peanut|semilla|seed|cashew|pistacho/.test(n)) return '🥜';
  if (/lenteja|lentil|garbanzo|chickpea|alubia|bean|frijol|guisante|pea|legumbre/.test(n)) return '🫘';
  if (/sopa|soup|caldo|broth|guiso|stew/.test(n)) return '🍲';
  if (/chocolate|cookie|galleta|cake|tarta|dulce|sweet|postre|dessert|helado|ice cream/.test(n)) return '🍫';
  if (/cafe|coffee|te|tea|agua|water|zumo|juice|cerveza|beer|vino|wine/.test(n)) return '☕';

  return '🍽️';
}

document.addEventListener('DOMContentLoaded', markNav);

// Registering the worker is what makes the app installable to the home screen.
// It silently does nothing on an insecure origin, which is correct -- the camera
// does not work there either, so there is nothing worth installing yet.
if ('serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => { /* non-fatal */ });
  });
}

// Shared helpers: fetch wrapper, formatting, toasts, nav highlighting.

export function getActiveProfileId() {
  return localStorage.getItem('active_profile_id') || null;
}

export function setActiveProfileId(id) {
  if (id) localStorage.setItem('active_profile_id', String(id));
  else localStorage.removeItem('active_profile_id');
}

export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const pid = getActiveProfileId();
  if (pid && !headers['X-Profile-ID']) {
    headers['X-Profile-ID'] = String(pid);
  }

  const res = await fetch(path, { ...options, headers });
  if (res.status === 204) return null;
  let body = null;
  try { body = await res.json(); } catch { /* empty or non-JSON body */ }
  if (!res.ok) {
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

document.addEventListener('DOMContentLoaded', markNav);

// Registering the worker is what makes the app installable to the home screen.
// It silently does nothing on an insecure origin, which is correct -- the camera
// does not work there either, so there is nothing worth installing yet.
if ('serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => { /* non-fatal */ });
  });
}

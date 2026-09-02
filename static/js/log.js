import { postForm, postJSON, fmt, round, toast, esc, checkHealth, prettyDate, todayISO } from './api.js';

const $ = (id) => document.getElementById(id);

/** Working copy of the meal under review. Edits mutate this, never the DOM. */
let draft = { name: 'Meal', items: [], pendingImage: null, model: null, raw: null, source: 'manual' };
let previewURL = null;

$('today').textContent = prettyDate(todayISO());

function show(step) {
  for (const id of ['step-capture', 'step-loading', 'step-review']) {
    $(id).classList.toggle('hidden', id !== step);
  }
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// --- photo intake ---
$('btn-camera').addEventListener('click', () => $('file').click());
$('btn-library').addEventListener('click', () => $('file-lib').click());
for (const id of ['file', 'file-lib']) {
  $(id).addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    // Reset so picking the same file twice still fires a change event.
    e.target.value = '';
    if (file) analyze(file);
  });
}

$('btn-manual').addEventListener('click', () => {
  draft = { name: 'Meal', items: [blankItem()], pendingImage: null, model: null, raw: null, source: 'manual' };
  $('preview').classList.add('hidden');
  $('model-notes').classList.add('hidden');
  $('meal-name').value = '';
  renderItems();
  show('step-review');
});

async function analyze(file) {
  show('step-loading');
  $('loading-text').textContent = 'Analysing your meal…';

  if (previewURL) URL.revokeObjectURL(previewURL);
  previewURL = URL.createObjectURL(file);

  const form = new FormData();
  form.append('image', file, file.name || 'meal.jpg');

  const started = Date.now();
  const tick = setInterval(() => {
    $('loading-sub').textContent = `${Math.round((Date.now() - started) / 1000)}s elapsed`;
  }, 1000);

  try {
    const result = await postForm('/api/analyze', form);
    draft = {
      name: result.dish || 'Meal',
      items: result.items.map((i) => ({ ...i })),
      pendingImage: result.pending_image,
      model: result.model,
      raw: result.raw,
      source: 'photo',
    };
    $('meal-name').value = draft.name;
    $('preview').src = previewURL;
    $('preview').classList.remove('hidden');

    const notes = $('model-notes');
    if (result.notes) {
      notes.className = 'banner';
      notes.innerHTML = `<b>${esc(result.model)}:</b> ${esc(result.notes)}`;
      notes.classList.remove('hidden');
    } else {
      notes.classList.add('hidden');
    }

    renderItems();
    show('step-review');
  } catch (err) {
    toast(err.message, true);
    show('step-capture');
  } finally {
    clearInterval(tick);
    $('loading-sub').textContent = 'A cold model load can take a minute the first time.';
  }
}

// --- natural language text intake ---
$('text-intake-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = $('meal-description').value.trim();
  if (!text) return;
  analyzeText(text);
});

async function analyzeText(text) {
  show('step-loading');
  $('loading-text').textContent = 'Estimating macros with AI…';

  const started = Date.now();
  const tick = setInterval(() => {
    $('loading-sub').textContent = `${Math.round((Date.now() - started) / 1000)}s elapsed`;
  }, 1000);

  try {
    const result = await postJSON('/api/analyze-text', { text });
    draft = {
      name: result.dish || 'Meal',
      items: result.items.map((i) => ({ ...i })),
      pendingImage: null,
      model: result.model,
      raw: result.raw,
      source: 'text',
    };
    $('meal-name').value = draft.name;
    $('preview').classList.add('hidden');

    const notes = $('model-notes');
    if (result.notes) {
      notes.className = 'banner';
      notes.innerHTML = `<b>AI Estimate:</b> ${esc(result.notes)}`;
      notes.classList.remove('hidden');
    } else {
      notes.classList.add('hidden');
    }

    renderItems();
    show('step-review');
  } catch (err) {
    toast(err.message, true);
    show('step-capture');
  } finally {
    clearInterval(tick);
    $('loading-sub').textContent = 'A cold model load can take a minute the first time.';
  }
}

// --- editable items ---
const blankItem = () => ({
  name: '', grams: 0, calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0,
  confidence: 'high', basis: '',
});

const FIELDS = [
  ['grams', 'g'], ['calories', 'kcal'], ['protein_g', 'P'], ['carbs_g', 'C'], ['fat_g', 'F'],
];

function renderItems() {
  $('items').innerHTML = draft.items.map((item, idx) => `
    <div class="item" data-idx="${idx}">
      <div class="row1">
        <input data-field="name" value="${esc(item.name)}" placeholder="Item name" aria-label="Item name">
        ${draft.source === 'photo' && item.confidence
          ? `<span class="chip ${esc(item.confidence)}" title="Model confidence">${esc(item.confidence)}</span>`
          : ''}
        <button class="del" data-remove="${idx}" aria-label="Remove item">&times;</button>
      </div>
      <div class="grid">
        ${FIELDS.map(([field, label]) => `
          <div>
            <label>${label}</label>
            <input type="number" inputmode="decimal" step="0.1" min="0"
                   data-field="${field}" value="${round(item[field], 1)}" aria-label="${label}">
          </div>`).join('')}
      </div>
      ${item.basis ? `<div class="basis">${esc(item.basis)}</div>` : ''}
    </div>`).join('');

  $('items').querySelectorAll('input').forEach((input) => {
    input.addEventListener('input', onEdit);
  });
  $('items').querySelectorAll('[data-remove]').forEach((btn) => {
    btn.addEventListener('click', () => {
      draft.items.splice(Number(btn.dataset.remove), 1);
      if (!draft.items.length) draft.items.push(blankItem());
      renderItems();
    });
  });
  updateTotals();
}

function onEdit(e) {
  const idx = Number(e.target.closest('.item').dataset.idx);
  const field = e.target.dataset.field;
  const item = draft.items[idx];
  if (!item) return;

  if (field === 'name') {
    item.name = e.target.value;
    return; // no totals impact, and re-rendering would steal focus
  }

  const value = Math.max(0, Number(e.target.value) || 0);
  item[field] = value;

  // Editing a macro re-derives calories, so a corrected portion stays coherent.
  // Editing calories directly is respected as-is -- the user may know the label value.
  if (field !== 'calories') {
    item.calories = round(item.protein_g * 4 + item.carbs_g * 4 + item.fat_g * 9, 1);
    const calInput = e.target.closest('.item').querySelector('[data-field="calories"]');
    if (calInput && document.activeElement !== calInput) calInput.value = item.calories;
  }
  updateTotals();
}

function totals() {
  return draft.items.reduce((acc, i) => ({
    calories: acc.calories + (Number(i.calories) || 0),
    protein_g: acc.protein_g + (Number(i.protein_g) || 0),
    carbs_g: acc.carbs_g + (Number(i.carbs_g) || 0),
    fat_g: acc.fat_g + (Number(i.fat_g) || 0),
  }), { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 });
}

function updateTotals() {
  const t = totals();
  $('t-kcal').textContent = fmt(t.calories);
  $('t-pro').textContent = fmt(t.protein_g);
  $('t-car').textContent = fmt(t.carbs_g);
  $('t-fat').textContent = fmt(t.fat_g);
}

$('btn-add-item').addEventListener('click', () => {
  draft.items.push(blankItem());
  renderItems();
  $('items').lastElementChild?.querySelector('input')?.focus();
});

// --- save ---
$('btn-save').addEventListener('click', async () => {
  const items = draft.items
    .filter((i) => i.name.trim() && (i.calories > 0 || i.protein_g > 0 || i.carbs_g > 0 || i.fat_g > 0))
    .map((i) => ({
      name: i.name.trim(),
      grams: round(i.grams, 1),
      calories: round(i.calories, 1),
      protein_g: round(i.protein_g, 1),
      carbs_g: round(i.carbs_g, 1),
      fat_g: round(i.fat_g, 1),
      confidence: ['low', 'medium', 'high'].includes(i.confidence) ? i.confidence : 'medium',
    }));

  if (!items.length) {
    toast('Add at least one item with a name and some nutrition.', true);
    return;
  }

  const btn = $('btn-save');
  btn.disabled = true;
  btn.textContent = 'Saving…';
  try {
    await postJSON('/api/meals', {
      name: $('meal-name').value.trim() || 'Meal',
      meal_type: $('meal-type').value,
      source: draft.source,
      items,
      pending_image: draft.pendingImage,
      model: draft.model,
      raw_json: draft.raw,
    });
    toast('Meal saved');
    setTimeout(() => { location.href = '/'; }, 600);
  } catch (err) {
    toast(err.message, true);
    btn.disabled = false;
    btn.textContent = 'Save meal';
  }
});

$('btn-cancel').addEventListener('click', () => {
  if (!confirm('Discard this meal?')) return;
  if (previewURL) { URL.revokeObjectURL(previewURL); previewURL = null; }
  draft = { name: 'Meal', items: [], pendingImage: null, model: null, raw: null, source: 'manual' };
  show('step-capture');
});

/**
 * Pick up a photo shared into the app from the phone's camera or gallery.
 * The service worker parked the file in a cache and redirected here, so the
 * whole flow is: shoot in the normal camera app -> share -> macros. No browser.
 */
async function consumeSharedImage() {
  if (new URLSearchParams(location.search).get('share') !== '1') return false;
  // Drop the query string so a reload does not look like a second share.
  history.replaceState(null, '', '/log');
  try {
    const cache = await caches.open('shared-image');
    const res = await cache.match('/__shared-image');
    if (!res) return false;
    await cache.delete('/__shared-image');
    const blob = await res.blob();
    if (!blob.size) return false;
    const name = decodeURIComponent(res.headers.get('X-Filename') || 'shared.jpg');
    await analyze(new File([blob], name, { type: blob.type || 'image/jpeg' }));
    return true;
  } catch {
    return false;
  }
}

checkHealth();
consumeSharedImage();

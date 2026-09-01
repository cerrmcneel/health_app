import {
  getJSON, postJSON, putJSON, patchJSON, del, fmt, pct, prettyDate, shiftDay, todayISO,
  toast, esc, checkHealth, getActiveProfileId, setActiveProfileId,
} from './api.js';

let day = todayISO();
let currentProfile = null;
let currentProfilesList = [];

const MEAL_ICON = {
  breakfast: '\u2615', lunch: '\u{1F35C}', dinner: '\u{1F37D}',
  snack: '\u{1F34E}', other: '\u{1F374}',
};

const $ = (id) => document.getElementById(id);

// --- Modal Helpers ---
function openModal(id) { $(id)?.classList.remove('hidden'); }
function closeModal(id) { $(id)?.classList.add('hidden'); }

document.querySelectorAll('[data-close]').forEach((btn) => {
  btn.addEventListener('click', () => closeModal(btn.dataset.close));
});
document.querySelectorAll('.modal-overlay').forEach((overlay) => {
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) overlay.classList.add('hidden');
  });
});

// --- Profile Handling ---
async function loadProfiles() {
  try {
    const data = await getJSON('/api/profiles');
    currentProfilesList = data.profiles;
    const activeId = getActiveProfileId();
    currentProfile = currentProfilesList.find(p => String(p.id) === String(activeId))
      || currentProfilesList.find(p => p.is_default)
      || currentProfilesList[0];

    if (currentProfile) {
      setActiveProfileId(currentProfile.id);
      $('profile-name').textContent = currentProfile.name;
      $('profile-avatar').textContent = currentProfile.name.charAt(0).toUpperCase();
      $('profile-avatar').style.background = currentProfile.avatar_color || '#3b82f6';
    }

    renderProfileList();
  } catch (err) {
    console.error('Failed to load profiles:', err);
  }
}

function renderProfileList() {
  const container = $('profile-list');
  if (!container) return;
  container.innerHTML = currentProfilesList.map((p) => {
    const isActive = currentProfile && currentProfile.id === p.id;
    return `
      <div class="profile-item ${isActive ? 'active' : ''}" data-pid="${p.id}">
        <span class="avatar-circle lg" style="background:${esc(p.avatar_color)}">
          ${esc(p.name.charAt(0).toUpperCase())}
        </span>
        <div class="p-info">
          <b>${esc(p.name)} ${p.is_default ? '<small style="color:var(--muted)">(Default)</small>' : ''}</b>
          <small>${fmt(p.calorie_target)} kcal &middot; P:${fmt(p.protein_target)}g C:${fmt(p.carbs_target)}g F:${fmt(p.fat_target)}g</small>
        </div>
        ${!p.is_default && currentProfilesList.length > 1 ? `<button class="del" data-del-profile="${p.id}" title="Delete profile">&times;</button>` : ''}
      </div>
    `;
  }).join('');

  container.querySelectorAll('.profile-item').forEach((el) => {
    el.addEventListener('click', async (e) => {
      if (e.target.closest('[data-del-profile]')) return;
      const pid = el.dataset.pid;
      setActiveProfileId(pid);
      closeModal('profile-modal');
      await loadProfiles();
      await loadDay();
      await Promise.all([loadChart(), loadPhotos(), loadWeight()]);
      toast('Switched profile');
    });
  });

  container.querySelectorAll('[data-del-profile]').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const pid = btn.dataset.delProfile;
      const prof = currentProfilesList.find(p => String(p.id) === String(pid));
      if (!confirm(`Delete profile "${prof?.name}" and all associated logs?`)) return;
      try {
        await del(`/api/profiles/${pid}`);
        if (getActiveProfileId() === pid) setActiveProfileId(null);
        toast('Profile deleted');
        await loadProfiles();
        await loadDay();
      } catch (err) {
        toast(err.message, true);
      }
    });
  });
}

// Add Profile Form
let selectedAvatarColor = '#3b82f6';
$('new-p-colors')?.querySelectorAll('.color-opt').forEach((opt) => {
  opt.addEventListener('click', () => {
    $('new-p-colors').querySelectorAll('.color-opt').forEach(o => o.classList.remove('selected'));
    opt.classList.add('selected');
    selectedAvatarColor = opt.dataset.color;
  });
});

$('add-profile-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = $('new-p-name').value.trim();
  const cals = Number($('new-p-cal').value) || 2200;
  if (!name) return;

  try {
    const created = await postJSON('/api/profiles', {
      name,
      avatar_color: selectedAvatarColor,
      calorie_target: cals,
      protein_target: Math.round(cals * 0.3 / 4),
      carbs_target: Math.round(cals * 0.45 / 4),
      fat_target: Math.round(cals * 0.25 / 9),
    });
    setActiveProfileId(created.id);
    $('add-profile-form').reset();
    closeModal('profile-modal');
    toast(`Created profile "${created.name}"`);
    await loadProfiles();
    await loadDay();
    await Promise.all([loadChart(), loadPhotos(), loadWeight()]);
  } catch (err) {
    toast(err.message, true);
  }
});

$('profile-btn')?.addEventListener('click', () => openModal('profile-modal'));

// --- Weight Tracking ---
async function loadWeight() {
  try {
    const data = await getJSON('/api/weights?limit=14');
    if (data.latest_weight != null) {
      $('weight-val').textContent = fmt(data.latest_weight, 1);
      if (data.change_7d != null) {
        const deltaCls = data.change_7d < 0 ? 'down' : (data.change_7d > 0 ? 'up' : '');
        const sign = data.change_7d > 0 ? '+' : '';
        $('weight-delta').innerHTML = `<b class="${deltaCls}">${sign}${fmt(data.change_7d, 1)} kg</b>7d change`;
      } else {
        $('weight-delta').innerHTML = `<b>&mdash;</b>7d change`;
      }
    } else {
      $('weight-val').textContent = '\u2014';
      $('weight-delta').innerHTML = `<b>&mdash;</b>No logs`;
    }
  } catch (err) {
    console.error('Failed to load weight:', err);
  }
}

$('weight-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const val = Number($('w-input').value);
  if (!val) return;
  try {
    await postJSON('/api/weights', { weight_kg: val, day });
    $('w-input').value = '';
    toast('Weight logged');
    await loadWeight();
  } catch (err) {
    toast(err.message, true);
  }
});

// --- Day & Dashboard Data ---
async function loadDay() {
  $('day-label').textContent = prettyDate(day);
  $('day-iso').textContent = day;
  $('next').disabled = day >= todayISO();

  const [stats, meals] = await Promise.all([
    getJSON(`/api/stats/daily?day=${day}`),
    getJSON(`/api/meals?day=${day}`),
  ]);

  renderTotals(stats);
  renderMeals(meals.meals);
  fillTargetsModal(stats.targets);
}

function renderTotals({ totals, targets, remaining }) {
  $('kcal').textContent = fmt(totals.calories);
  $('kcal-target').textContent = fmt(targets.calorie_target);
  $('kcal-left').textContent = fmt(Math.abs(remaining.calories));
  $('kcal-left').nextSibling.textContent = remaining.calories < 0 ? 'over' : 'remaining';

  const bar = $('kcal-bar');
  bar.firstElementChild.style.width = pct(totals.calories, targets.calorie_target) + '%';
  bar.classList.toggle('over', totals.calories > targets.calorie_target);

  for (const [key, target] of [
    ['protein', 'protein_target'], ['carbs', 'carbs_target'], ['fat', 'fat_target'],
  ]) {
    $(key).textContent = fmt(totals[`${key}_g`]);
    $(`${key}-target`).textContent = fmt(targets[target]);
    $(`${key}-bar`).style.width = pct(totals[`${key}_g`], targets[target]) + '%';
  }
}

function renderMeals(meals) {
  const box = $('meals');
  if (!meals.length) {
    box.innerHTML = '<div class="empty">Nothing logged yet.</div>';
    return;
  }
  box.innerHTML = meals.map((m) => {
    const time = new Date(m.logged_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const names = m.items.map((i) => i.name).join(', ');
    const thumb = m.image_url
      ? `<img src="${esc(m.image_url)}" alt="" loading="lazy">`
      : `<span class="thumb-none" aria-hidden="true">${esc(MEAL_ICON[m.meal_type] || MEAL_ICON.other)}</span>`;
    return `<div class="meal" data-id="${m.id}">
      ${thumb}
      <div class="info">
        <b>${esc(m.name)}</b>
        <small>${time} &middot; ${esc(names).slice(0, 50)}</small>
      </div>
      <span class="kc">${fmt(m.totals.calories)}</span>
      <div class="meal-btns">
        <button class="meal-btn" data-repeat="${m.id}" title="Log again today">&#x21bb; Repeat</button>
        <button class="meal-btn" data-edit="${m.id}" title="Edit meal">&#x270e;</button>
        <button class="del" data-del="${m.id}" aria-label="Delete ${esc(m.name)}">&times;</button>
      </div>
    </div>`;
  }).join('');

  // Delete Action
  box.querySelectorAll('[data-del]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.del;
      const name = btn.closest('.meal').querySelector('b').textContent;
      if (!confirm(`Delete "${name}"?`)) return;
      try {
        await del(`/api/meals/${id}`);
        toast('Meal deleted');
        await loadDay();
        await loadChart();
      } catch (err) {
        toast(err.message, true);
      }
    });
  });

  // Repeat Action ("Log Again")
  box.querySelectorAll('[data-repeat]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.repeat;
      try {
        await postJSON(`/api/meals/${id}/duplicate`, {});
        toast('Meal copied to today');
        if (day !== todayISO()) {
          day = todayISO();
        }
        await loadDay();
        await loadChart();
      } catch (err) {
        toast(err.message, true);
      }
    });
  });

  // Edit Action
  box.querySelectorAll('[data-edit]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.edit;
      try {
        const m = await getJSON(`/api/meals/${id}`);
        openEditMealModal(m);
      } catch (err) {
        toast(err.message, true);
      }
    });
  });
}

// Edit Meal Modal Logic
function openEditMealModal(meal) {
  $('edit-meal-id').value = meal.id;
  $('edit-meal-name').value = meal.name;
  $('edit-meal-type').value = meal.meal_type || 'other';
  $('edit-meal-notes').value = meal.notes || '';

  const itemsBox = $('edit-meal-items');
  itemsBox.innerHTML = `
    <div style="font-size:12px;font-weight:600;margin-bottom:6px">Items & Macros</div>
    ${meal.items.map((it, idx) => `
      <div class="edit-item-row" data-idx="${idx}" style="background:var(--surface-2);border-radius:8px;padding:8px;margin-bottom:6px">
        <input type="text" class="it-name" value="${esc(it.name)}" placeholder="Item name" style="margin-bottom:4px" required>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:4px">
          <div><label style="font-size:10px">Grams</label><input type="number" class="it-g" value="${it.grams || 0}" min="0"></div>
          <div><label style="font-size:10px">Calories</label><input type="number" class="it-cal" value="${it.calories || 0}" min="0"></div>
          <div><label style="font-size:10px">Prot (g)</label><input type="number" class="it-p" value="${it.protein_g || 0}" min="0"></div>
          <div><label style="font-size:10px">Carb (g)</label><input type="number" class="it-c" value="${it.carbs_g || 0}" min="0"></div>
        </div>
      </div>
    `).join('')}
  `;

  openModal('edit-meal-modal');
}

$('edit-meal-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const id = $('edit-meal-id').value;
  const name = $('edit-meal-name').value.trim();
  const meal_type = $('edit-meal-type').value;
  const notes = $('edit-meal-notes').value.trim();

  const itemRows = document.querySelectorAll('.edit-item-row');
  const items = Array.from(itemRows).map((row) => ({
    name: row.querySelector('.it-name').value.trim() || 'Item',
    grams: Number(row.querySelector('.it-g').value) || 0,
    calories: Number(row.querySelector('.it-cal').value) || 0,
    protein_g: Number(row.querySelector('.it-p').value) || 0,
    carbs_g: Number(row.querySelector('.it-c').value) || 0,
    fat_g: 0,
    confidence: 'high',
  }));

  try {
    await patchJSON(`/api/meals/${id}`, { name, meal_type, notes, items });
    closeModal('edit-meal-modal');
    toast('Meal updated');
    await loadDay();
    await loadChart();
  } catch (err) {
    toast(err.message, true);
  }
});

// --- Chart & Photos ---
async function loadChart() {
  const data = await getJSON('/api/stats/range?days=14');
  const target = data.targets.calorie_target || 1;
  const peak = Math.max(target, ...data.series.map((s) => s.calories)) || 1;

  $('chart').innerHTML = data.series.map((s) => {
    const h = Math.max(2, (s.calories / peak) * 100);
    const cls = s.meal_count ? (s.calories > target ? 'col has over' : 'col has') : 'col';
    const label = s.day.slice(8);
    return `<div class="${cls}" title="${s.day}: ${fmt(s.calories)} kcal">
      <i style="height:${h}%"></i><em>${label}</em></div>`;
  }).join('');

  $('chart-avg').textContent = data.days_logged
    ? `Avg ${fmt(data.average_calories)} kcal on days logged`
    : 'No days logged yet';
  $('chart-logged').textContent = `${data.days_logged}/14 days`;
}

async function loadPhotos() {
  const [status, photos] = await Promise.all([
    getJSON('/api/photos/status'),
    getJSON('/api/photos?limit=8'),
  ]);

  $('photo-status').textContent = status.remaining.length === 0
    ? 'Both poses captured today.'
    : `Still to shoot today: ${status.remaining.join(' and ')}.`;

  const latest = {};
  for (const p of photos.photos) {
    if (!latest[p.pose]) latest[p.pose] = p;
  }
  const entries = Object.values(latest);
  $('latest-photos').innerHTML = entries.length
    ? entries.map((p) => `<figure>
        <img src="${esc(p.url)}" alt="${esc(p.pose)} on ${esc(p.day)}" loading="lazy">
        <figcaption>${esc(p.pose)} &middot; ${prettyDate(p.day)}</figcaption>
      </figure>`).join('')
    : '<div class="empty" style="grid-column:1/-1">No progress photos yet.</div>';
}

// --- Targets & Goal Calculator Modal ---
function fillTargetsModal(t) {
  $('modal-t-cal').value = t.calorie_target;
  $('modal-t-pro').value = t.protein_target;
  $('modal-t-car').value = t.carbs_target;
  $('modal-t-fat').value = t.fat_target;
}

$('btn-edit-goals')?.addEventListener('click', () => openModal('targets-modal'));

// Quick Presets
let currentBaseTDEE = 2200;
document.querySelectorAll('.preset-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const goal = btn.dataset.goal;
    let target = currentBaseTDEE;
    if (goal === 'cut') target = Math.max(1200, currentBaseTDEE - 500);
    else if (goal === 'bulk') target = currentBaseTDEE + 300;

    $('modal-t-cal').value = target;
    // Derive recommended 30P / 45C / 25F split
    $('modal-t-pro').value = Math.round((target * 0.30) / 4);
    $('modal-t-car').value = Math.round((target * 0.45) / 4);
    $('modal-t-fat').value = Math.round((target * 0.25) / 9);
  });
});

// TDEE Formula Calculation
$('btn-apply-calc')?.addEventListener('click', () => {
  const wt = Number($('calc-wt').value) || 75;
  const ht = Number($('calc-ht').value) || 178;
  const age = Number($('calc-age').value) || 30;
  const act = Number($('calc-act').value) || 1.375;

  // Mifflin-St Jeor Formula
  const bmr = (10 * wt) + (6.25 * ht) - (5 * age) + 5;
  currentBaseTDEE = Math.round(bmr * act);

  const activePreset = document.querySelector('.preset-btn.active')?.dataset.goal || 'maintain';
  let target = currentBaseTDEE;
  if (activePreset === 'cut') target = Math.max(1200, currentBaseTDEE - 500);
  else if (activePreset === 'bulk') target = currentBaseTDEE + 300;

  $('modal-t-cal').value = target;
  $('modal-t-pro').value = Math.round((target * 0.30) / 4);
  $('modal-t-car').value = Math.round((target * 0.45) / 4);
  $('modal-t-fat').value = Math.round((target * 0.25) / 9);

  toast(`Calculated TDEE: ${currentBaseTDEE} kcal`);
});

// Target Submission
$('targets-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await putJSON('/api/settings', {
      calorie_target: Number($('modal-t-cal').value) || 0,
      protein_target: Number($('modal-t-pro').value) || 0,
      carbs_target: Number($('modal-t-car').value) || 0,
      fat_target: Number($('modal-t-fat').value) || 0,
    });
    closeModal('targets-modal');
    toast('Goal targets updated');
    await loadProfiles();
    await loadDay();
    await loadChart();
  } catch (err) {
    toast(err.message, true);
  }
});

// Navigation
$('prev')?.addEventListener('click', () => { day = shiftDay(day, -1); loadDay(); });
$('next')?.addEventListener('click', () => {
  if (day < todayISO()) { day = shiftDay(day, 1); loadDay(); }
});

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { loadDay(); loadPhotos(); loadWeight(); }
});

(async function init() {
  checkHealth();
  try {
    await loadProfiles();
    await loadDay();
    await Promise.all([loadChart(), loadPhotos(), loadWeight()]);
  } catch (err) {
    toast(err.message, true);
  }
})();


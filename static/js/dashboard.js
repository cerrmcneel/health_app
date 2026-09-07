import {
  getJSON, postJSON, postForm, putJSON, patchJSON, del, fmt, pct, prettyDate, shiftDay, todayISO,
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
          <b>${esc(p.name)} ${p.is_default ? '<small style="color:var(--muted)">(Default)</small>' : ''} ${isActive ? '<small style="color:var(--accent)">&bull; Active</small>' : ''}</b>
          <small>${fmt(p.calorie_target)} kcal &middot; P:${fmt(p.protein_target)}g C:${fmt(p.carbs_target)}g F:${fmt(p.fat_target)}g</small>
        </div>
        <div style="display:flex;gap:6px;align-items:center">
          <button type="button" class="meal-btn edit-profile-btn" data-edit-pid="${p.id}" title="Edit profile name & targets" style="padding:4px 8px;font-size:11px">
            ✏️ Edit
          </button>
          ${!p.is_default && currentProfilesList.length > 1 ? `<button type="button" class="del" data-del-profile="${p.id}" title="Delete profile">&times;</button>` : ''}
        </div>
      </div>
    `;
  }).join('');

  container.querySelectorAll('.profile-item').forEach((el) => {
    el.addEventListener('click', async (e) => {
      if (e.target.closest('.edit-profile-btn') || e.target.closest('[data-del-profile]')) return;
      const pid = el.dataset.pid;
      setActiveProfileId(pid);
      closeModal('profile-modal');
      await loadProfiles();
      await loadDay();
      await Promise.all([loadChart(), loadPhotos(), loadWeight()]);
      toast('Switched profile');
    });
  });

  container.querySelectorAll('.edit-profile-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      closeModal('profile-modal');
      openEditProfileModal(btn.dataset.editPid);
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

// Edit Profile Modal
let editAvatarColor = '#3b82f6';

function openEditProfileModal(pid) {
  const p = currentProfilesList.find(x => String(x.id) === String(pid)) || currentProfile;
  if (!p) return;

  $('edit-p-id').value = p.id;
  $('edit-p-name').value = p.name;
  $('edit-p-cal').value = Math.round(p.calorie_target);
  $('edit-p-pro').value = Math.round(p.protein_target);
  $('edit-p-car').value = Math.round(p.carbs_target);
  $('edit-p-fat').value = Math.round(p.fat_target);

  editAvatarColor = p.avatar_color || '#3b82f6';
  $('edit-p-colors')?.querySelectorAll('.color-opt').forEach((opt) => {
    const isSelected = opt.dataset.color.toLowerCase() === editAvatarColor.toLowerCase();
    opt.classList.toggle('selected', isSelected);
  });

  openModal('edit-profile-modal');
}

$('edit-p-colors')?.querySelectorAll('.color-opt').forEach((opt) => {
  opt.addEventListener('click', () => {
    $('edit-p-colors').querySelectorAll('.color-opt').forEach(o => o.classList.remove('selected'));
    opt.classList.add('selected');
    editAvatarColor = opt.dataset.color;
  });
});

$('edit-profile-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const pid = $('edit-p-id').value;
  const name = $('edit-p-name').value.trim();
  if (!name) return;

  const payload = {
    name,
    avatar_color: editAvatarColor,
    calorie_target: Number($('edit-p-cal').value) || 2200,
    protein_target: Number($('edit-p-pro').value) || 160,
    carbs_target: Number($('edit-p-car').value) || 220,
    fat_target: Number($('edit-p-fat').value) || 70,
  };

  try {
    const updated = await patchJSON(`/api/profiles/${pid}`, payload);
    closeModal('edit-profile-modal');
    toast(`Profile updated: "${updated.name}"`);
    await loadProfiles();
    await loadDay();
    await Promise.all([loadChart(), loadPhotos(), loadWeight()]);
  } catch (err) {
    toast(err.message, true);
  }
});

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

  const poses = ['front', 'profile'];
  const hasAny = photos.photos.length > 0;
  if (!hasAny) {
    $('latest-photos').innerHTML = '<div class="empty" style="grid-column:1/-1">No progress photos yet.</div>';
    return;
  }

  $('latest-photos').innerHTML = poses.map((pose) => {
    const p = latest[pose];
    if (p) {
      return `<figure>
        <a href="/progress" title="View in Progress">
          <img src="${esc(p.url)}?t=${p.bytes || ''}" alt="${esc(p.pose)} on ${esc(p.day)}" loading="lazy">
        </a>
        <figcaption><span>${esc(p.pose)} &middot; ${prettyDate(p.day)}</span></figcaption>
      </figure>`;
    } else {
      return `<div class="gallery-placeholder">
        <span class="gallery-placeholder-icon">&#128247;</span>
        <span class="gallery-placeholder-title">${pose} pose</span>
        <span class="gallery-placeholder-sub">Not captured yet</span>
        <a class="btn btn-sm" href="/capture" style="margin-top:6px;font-size:11px;padding:2px 10px;height:26px;min-height:26px">Capture</a>
      </div>`;
    }
  }).join('');
}

// --- Photo Upload Modal Handlers ---
function openPhotoUploadModal() {
  const yesterday = shiftDay(todayISO(), -1);
  const dateInput = $('up-photo-date');
  if (dateInput) dateInput.value = yesterday;
  $('upload-photo-form')?.reset();
  if (dateInput) dateInput.value = yesterday;
  $('up-photo-preview')?.classList.add('hidden');
  openModal('upload-photo-modal');
}

$('btn-upload-photo')?.addEventListener('click', openPhotoUploadModal);
$('btn-upload-photo-2')?.addEventListener('click', openPhotoUploadModal);

$('up-btn-yesterday')?.addEventListener('click', () => {
  const input = $('up-photo-date');
  if (input) input.value = shiftDay(todayISO(), -1);
});

$('up-btn-today')?.addEventListener('click', () => {
  const input = $('up-photo-date');
  if (input) input.value = todayISO();
});

let photoUploadPreviewURL = null;
$('up-photo-file')?.addEventListener('change', (e) => {
  const file = e.target.files?.[0];
  if (file) {
    if (photoUploadPreviewURL) URL.revokeObjectURL(photoUploadPreviewURL);
    photoUploadPreviewURL = URL.createObjectURL(file);
    const img = $('up-preview-img');
    if (img) img.src = photoUploadPreviewURL;
    $('up-photo-preview')?.classList.remove('hidden');
  } else {
    $('up-photo-preview')?.classList.add('hidden');
  }
});

$('upload-photo-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const file = $('up-photo-file')?.files?.[0];
  if (!file) return;

  const dateVal = $('up-photo-date')?.value || todayISO();
  const poseVal = $('up-photo-pose')?.value || 'front';

  const formData = new FormData();
  formData.append('image', file, file.name || 'photo.jpg');
  formData.append('pose', poseVal);
  formData.append('day', dateVal);

  const btn = $('up-photo-submit');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Uploading…';
  }

  try {
    await postForm('/api/photos', formData);
    closeModal('upload-photo-modal');
    toast(`Progress photo uploaded for ${prettyDate(dateVal)}`);
    await loadPhotos();
  } catch (err) {
    toast(err.message, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Upload & Save';
    }
  }
});


// --- Targets & Goal Calculator Modal ---
function fillTargetsModal(t) {
  $('modal-t-cal').value = t.calorie_target;
  $('modal-t-pro').value = t.protein_target;
  $('modal-t-car').value = t.carbs_target;
  $('modal-t-fat').value = t.fat_target;
  if ($('targets-profile-name') && currentProfile) {
    $('targets-profile-name').textContent = currentProfile.name;
    const av = $('targets-profile-avatar');
    if (av) {
      av.textContent = currentProfile.name.charAt(0).toUpperCase();
      av.style.background = currentProfile.avatar_color || '#3b82f6';
    }
  }
}

$('btn-edit-goals')?.addEventListener('click', () => {
  if (currentProfile) {
    fillTargetsModal({
      calorie_target: currentProfile.calorie_target,
      protein_target: currentProfile.protein_target,
      carbs_target: currentProfile.carbs_target,
      fat_target: currentProfile.fat_target,
    });
  }
  openModal('targets-modal');
});

$('btn-edit-profile-from-targets')?.addEventListener('click', () => {
  closeModal('targets-modal');
  openEditProfileModal(currentProfile?.id);
});

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

// --- Nutrition Science & Explainer Modal ---
let cachedExplanation = null;
let cachedExplanationKey = null;

function renderSimpleMarkdown(md) {
  if (!md) return '';
  const lines = md.split('\n');
  let html = '';
  let inList = false;

  for (let line of lines) {
    line = line.trim();
    if (!line) {
      if (inList) { html += '</ul>'; inList = false; }
      continue;
    }

    if (line.startsWith('#### ')) {
      if (inList) { html += '</ul>'; inList = false; }
      html += `<h4>${esc(line.slice(5))}</h4>`;
    } else if (line.startsWith('### ')) {
      if (inList) { html += '</ul>'; inList = false; }
      html += `<h3>${esc(line.slice(4))}</h3>`;
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      if (!inList) { html += '<ul>'; inList = true; }
      const itemText = line.slice(2);
      html += `<li>${formatInlineMd(itemText)}</li>`;
    } else {
      if (inList) { html += '</ul>'; inList = false; }
      html += `<p>${formatInlineMd(line)}</p>`;
    }
  }
  if (inList) html += '</ul>';
  return html;
}

function formatInlineMd(text) {
  let safe = esc(text);
  // Bold: **text**
  safe = safe.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Inline code / metric: `code`
  safe = safe.replace(/`([^`]+)`/g, '<code style="background:rgba(255,255,255,0.08);padding:1px 4px;border-radius:4px">$1</code>');
  return safe;
}

async function openKnowledgeModal() {
  openModal('knowledge-modal');

  // Render snapshot pill
  const pill = $('km-snapshot-pill');
  if (pill && currentProfile) {
    const cp = currentProfile;
    const wVal = $('weight-val')?.textContent;
    const hasWeight = wVal && wVal !== '—' && !isNaN(Number(wVal));
    const gKg = hasWeight ? (Number(cp.protein_target) / Number(wVal)).toFixed(2) : null;

    pill.innerHTML = `
      <span>Target: <b>${fmt(cp.calorie_target)} kcal</b></span>
      <span>&middot;</span>
      <span>Protein: <b>${fmt(cp.protein_target)}g</b> ${gKg ? `<small>(${gKg} g/kg)</small>` : ''}</span>
      <span>&middot;</span>
      <span>Carbs: <b>${fmt(cp.carbs_target)}g</b></span>
      <span>&middot;</span>
      <span>Fat: <b>${fmt(cp.fat_target)}g</b></span>
      ${hasWeight ? `<span>&middot;</span><span>Weight: <b>${wVal} kg</b></span>` : ''}
    `;
  }

  // Load rationale if not already cached for current profile & day
  const key = `${currentProfile?.id || 1}_${day}`;
  if (cachedExplanationKey !== key || !cachedExplanation) {
    await fetchBalanceExplanation();
  }
}

async function fetchBalanceExplanation() {
  const loading = $('km-rationale-loading');
  const content = $('km-rationale-content');
  const sources = $('km-rationale-sources');

  loading?.classList.remove('hidden');
  if (content) content.innerHTML = '';
  if (sources) sources.innerHTML = '';

  try {
    const data = await getJSON(`/api/knowledge/balance-explanation?day=${day}`);
    cachedExplanation = data;
    cachedExplanationKey = `${currentProfile?.id || 1}_${day}`;

    if (content) {
      content.innerHTML = renderSimpleMarkdown(data.explanation);
    }
    if (sources && data.sources?.length) {
      sources.innerHTML = `<span style="font-size:11px;color:var(--muted);width:100%">Consulted Scientific Sources:</span>`
        + data.sources.map(s => `<span class="km-source-tag">${esc(s)}</span>`).join('');
    }
  } catch (err) {
    if (content) {
      content.innerHTML = `<p style="color:var(--danger)">Failed to load balance explanation: ${esc(err.message)}</p>`;
    }
  } finally {
    loading?.classList.add('hidden');
  }
}

// Tab Switching
$('km-tab-rationale')?.addEventListener('click', () => {
  $('km-tab-rationale').classList.add('active');
  $('km-tab-qa').classList.remove('active');
  $('km-section-rationale').classList.remove('hidden');
  $('km-section-qa').classList.add('hidden');
});

$('km-tab-qa')?.addEventListener('click', () => {
  $('km-tab-qa').classList.add('active');
  $('km-tab-rationale').classList.remove('active');
  $('km-section-qa').classList.remove('hidden');
  $('km-section-rationale').classList.add('hidden');
  $('km-qa-input')?.focus();
});

// Trigger modal button
$('btn-why-balanced')?.addEventListener('click', openKnowledgeModal);

// Quick question chips
document.querySelectorAll('.km-chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    const q = chip.dataset.q;
    if ($('km-qa-input')) $('km-qa-input').value = q;
    submitQuestion(q);
  });
});

// Q&A Submission
$('km-qa-form')?.addEventListener('submit', (e) => {
  e.preventDefault();
  const input = $('km-qa-input');
  const q = input.value.trim();
  if (!q) return;
  submitQuestion(q);
  input.value = '';
});

async function submitQuestion(question) {
  const loading = $('km-qa-loading');
  const submitBtn = $('km-qa-submit');
  const thread = $('km-qa-thread');

  loading?.classList.remove('hidden');
  if (submitBtn) submitBtn.disabled = true;

  try {
    const res = await postJSON('/api/knowledge/ask', { question, day });
    const itemEl = document.createElement('div');
    itemEl.className = 'km-qa-item';
    itemEl.innerHTML = `
      <div class="km-qa-q">${esc(question)}</div>
      <div class="km-qa-a">${renderSimpleMarkdown(res.answer)}</div>
      ${res.sources?.length ? `
        <div class="km-qa-meta">
          <span>Sources: ${res.sources.map(s => esc(s)).join(', ')}</span>
          ${res.model ? `<span>&middot; ${esc(res.model)}</span>` : ''}
        </div>
      ` : ''}
    `;
    thread.prepend(itemEl);
  } catch (err) {
    toast(`Q&A failed: ${err.message}`, true);
  } finally {
    loading?.classList.add('hidden');
    if (submitBtn) submitBtn.disabled = false;
  }
}

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



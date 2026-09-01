import {
  getJSON, putJSON, del, fmt, pct, prettyDate, shiftDay, todayISO,
  toast, esc, checkHealth,
} from './api.js';

let day = todayISO();

const MEAL_ICON = {
  breakfast: '\u2615', lunch: '\u{1F35C}', dinner: '\u{1F37D}',
  snack: '\u{1F34E}', other: '\u{1F374}',
};

const $ = (id) => document.getElementById(id);

async function loadDay() {
  $('day-label').textContent = prettyDate(day);
  $('day-iso').textContent = day;
  // Browsing into the future is meaningless for a food log.
  $('next').disabled = day >= todayISO();

  const [stats, meals] = await Promise.all([
    getJSON(`/api/stats/daily?day=${day}`),
    getJSON(`/api/meals?day=${day}`),
  ]);

  renderTotals(stats);
  renderMeals(meals.meals);
  fillTargets(stats.targets);
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
    // Manually-logged meals have no photo; a labelled tile reads better than an
    // empty image box.
    const thumb = m.image_url
      ? `<img src="${esc(m.image_url)}" alt="" loading="lazy">`
      : `<span class="thumb-none" aria-hidden="true">${esc(MEAL_ICON[m.meal_type] || MEAL_ICON.other)}</span>`;
    return `<div class="meal" data-id="${m.id}">
      ${thumb}
      <div class="info">
        <b>${esc(m.name)}</b>
        <small>${time} &middot; ${esc(names).slice(0, 60)}</small>
      </div>
      <span class="kc">${fmt(m.totals.calories)}</span>
      <button class="del" data-del="${m.id}" aria-label="Delete ${esc(m.name)}">&times;</button>
    </div>`;
  }).join('');

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
}

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
    if (!latest[p.pose]) latest[p.pose] = p;  // list is already newest-first
  }
  const entries = Object.values(latest);
  $('latest-photos').innerHTML = entries.length
    ? entries.map((p) => `<figure>
        <img src="${esc(p.url)}" alt="${esc(p.pose)} on ${esc(p.day)}" loading="lazy">
        <figcaption>${esc(p.pose)} &middot; ${prettyDate(p.day)}</figcaption>
      </figure>`).join('')
    : '<div class="empty" style="grid-column:1/-1">No progress photos yet.</div>';
}

function fillTargets(t) {
  $('t-cal').value = t.calorie_target;
  $('t-pro').value = t.protein_target;
  $('t-car').value = t.carbs_target;
  $('t-fat').value = t.fat_target;
}

$('targets').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await putJSON('/api/settings', {
      calorie_target: Number($('t-cal').value) || 0,
      protein_target: Number($('t-pro').value) || 0,
      carbs_target: Number($('t-car').value) || 0,
      fat_target: Number($('t-fat').value) || 0,
    });
    toast('Targets saved');
    await loadDay();
    await loadChart();
  } catch (err) {
    toast(err.message, true);
  }
});

$('prev').addEventListener('click', () => { day = shiftDay(day, -1); loadDay(); });
$('next').addEventListener('click', () => {
  if (day < todayISO()) { day = shiftDay(day, 1); loadDay(); }
});

// Returning from the camera or the logger should show fresh numbers.
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { loadDay(); loadPhotos(); }
});

(async function init() {
  checkHealth();
  try {
    await loadDay();
    await Promise.all([loadChart(), loadPhotos()]);
  } catch (err) {
    toast(err.message, true);
  }
})();

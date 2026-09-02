import { getJSON, postForm, prettyDate, shiftDay, todayISO, toast, esc } from './api.js';

const $ = (id) => document.getElementById(id);

let all = [];

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

async function load() {
  const { photos } = await getJSON('/api/photos?limit=400');
  all = photos;
  $('count').textContent = photos.length
    ? `${photos.length} photo${photos.length === 1 ? '' : 's'}`
    : 'No photos yet';

  $('gallery').innerHTML = photos.length
    ? photos.map((p) => `<figure>
        <img src="${esc(p.url)}" alt="${esc(p.pose)} on ${esc(p.day)}" loading="lazy">
        <figcaption>${esc(p.pose)} &middot; ${esc(p.day)}</figcaption>
      </figure>`).join('')
    : '<div class="empty" style="grid-column:1/-1">Nothing captured yet.</div>';

  renderCompare();
}

function forPose() {
  // Ascending by day so "earlier" and "later" read naturally in the pickers.
  return all.filter((p) => p.pose === $('pose-select').value)
            .sort((a, b) => a.day.localeCompare(b.day));
}

function renderCompare() {
  const list = forPose();
  const enough = list.length >= 2;
  $('compare-wrap').classList.toggle('hidden', !enough);
  $('compare-empty').classList.toggle('hidden', enough);
  if (!enough) return;

  const options = (selected) => list.map((p) =>
    `<option value="${esc(p.url)}" data-day="${esc(p.day)}" ${p.url === selected ? 'selected' : ''}>
      ${esc(p.day)}</option>`).join('');

  // Default to the widest span available: first shot vs most recent.
  $('pick-before').innerHTML = options(list[0].url);
  $('pick-after').innerHTML = options(list[list.length - 1].url);
  applyPicks();
}

function applyPicks() {
  const before = $('pick-before');
  const after = $('pick-after');
  $('img-before').src = before.value;
  $('img-after').src = after.value;
  $('label-before').textContent = prettyDate(before.selectedOptions[0].dataset.day);
  $('label-after').textContent = prettyDate(after.selectedOptions[0].dataset.day);
}

function applySplit() {
  const value = $('split').value;
  $('compare').style.setProperty('--split', `${value}%`);
}

// --- Upload Progress Photo Modal Handlers ---
function openPhotoUploadModal() {
  const yesterday = shiftDay(todayISO(), -1);
  const dateInput = $('up-photo-date');
  if (dateInput) dateInput.value = yesterday;
  $('upload-photo-form')?.reset();
  if (dateInput) dateInput.value = yesterday;
  $('up-photo-preview')?.classList.add('hidden');
  openModal('upload-photo-modal');
}

$('btn-upload-progress')?.addEventListener('click', openPhotoUploadModal);

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
    await load();
  } catch (err) {
    toast(err.message, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Upload & Save';
    }
  }
});

$('split').addEventListener('input', applySplit);
$('pose-select').addEventListener('change', renderCompare);
$('pick-before').addEventListener('change', applyPicks);
$('pick-after').addEventListener('change', applyPicks);

applySplit();
load().catch((err) => toast(err.message, true));

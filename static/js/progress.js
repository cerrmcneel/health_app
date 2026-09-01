import { getJSON, prettyDate, toast, esc } from './api.js';

const $ = (id) => document.getElementById(id);

let all = [];

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

$('split').addEventListener('input', applySplit);
$('pose-select').addEventListener('change', renderCompare);
$('pick-before').addEventListener('change', applyPicks);
$('pick-after').addEventListener('change', applyPicks);

applySplit();
load().catch((err) => toast(err.message, true));

import { getJSON, postJSON, postForm, prettyDate, shiftDay, todayISO, toast, esc, fmt } from './api.js';

const $ = (id) => document.getElementById(id);

let allPhotos = [];
let allWeights = [];
let activePose = 'front';
let activeRange = 30; // 14, 30, 90, 365

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

/* ============================================================
   WEIGHT TRACKING & INTERACTIVE SVG GRAPH
   ============================================================ */

async function loadWeights() {
  try {
    const data = await getJSON('/api/weights?limit=365');
    allWeights = data.weights || [];
    renderWeightSection();
  } catch (err) {
    console.error('Failed to load weights:', err);
  }
}

function daysBetween(d1, d2) {
  const t1 = new Date(d1 + 'T00:00:00').getTime();
  const t2 = new Date(d2 + 'T00:00:00').getTime();
  return Math.round((t2 - t1) / (1000 * 60 * 60 * 24));
}

function renderWeightSection() {
  // Determine cutoff day for active range
  const today = todayISO();
  let filtered = [];
  if (activeRange >= 365) {
    filtered = [...allWeights];
  } else {
    const cutoff = shiftDay(today, -activeRange);
    filtered = allWeights.filter((w) => w.day >= cutoff);
  }

  // Chronological order (oldest to newest)
  const chron = [...filtered].sort((a, b) => a.day.localeCompare(b.day));

  // 1. Stat boxes
  const latest = allWeights[0]; // allWeights is newest first from API
  if (latest) {
    $('w-stat-current').innerHTML = `${fmt(latest.weight_kg, 1)} <small>kg</small>`;
  } else {
    $('w-stat-current').innerHTML = `&mdash; <small>kg</small>`;
  }

  // 7-day change
  if (latest) {
    const cutoff7d = shiftDay(latest.day, -7);
    const prior7d = allWeights.find((w) => w.day <= cutoff7d);
    if (prior7d && prior7d !== latest) {
      const diff7d = latest.weight_kg - prior7d.weight_kg;
      const sign7d = diff7d > 0 ? '+' : '';
      const cls7d = diff7d < 0 ? 'down' : diff7d > 0 ? 'up' : '';
      $('w-stat-7d').innerHTML = `<span class="${cls7d}">${sign7d}${fmt(diff7d, 1)} kg</span>`;
    } else {
      $('w-stat-7d').innerHTML = '&mdash;';
    }
  } else {
    $('w-stat-7d').innerHTML = '&mdash;';
  }

  // Range change
  const rangeLbl = $('w-stat-range-lbl');
  if (rangeLbl) {
    rangeLbl.textContent = activeRange >= 365 ? 'All Time' : `${activeRange}d Change`;
  }
  if (chron.length >= 2) {
    const diffRange = chron[chron.length - 1].weight_kg - chron[0].weight_kg;
    const signR = diffRange > 0 ? '+' : '';
    const clsR = diffRange < 0 ? 'down' : diffRange > 0 ? 'up' : '';
    $('w-stat-range').innerHTML = `<span class="${clsR}">${signR}${fmt(diffRange, 1)} kg</span>`;
  } else {
    $('w-stat-range').innerHTML = '&mdash;';
  }

  // 2. SVG Chart
  renderWeightChart(chron);
}

function renderWeightChart(chron) {
  const svg = $('weight-svg');
  const empty = $('weight-empty');
  const tooltip = $('chart-tooltip');
  if (!svg) return;

  if (chron.length === 0) {
    svg.classList.add('hidden');
    empty?.classList.remove('hidden');
    tooltip?.classList.add('hidden');
    return;
  }

  svg.classList.remove('hidden');
  empty?.classList.add('hidden');

  const width = 500;
  const height = 190;
  const padLeft = 40;
  const padRight = 16;
  const padTop = 22;
  const padBottom = 26;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  // Min and max bounds
  let minW = Infinity;
  let maxW = -Infinity;
  chron.forEach((pt) => {
    if (pt.weight_kg < minW) minW = pt.weight_kg;
    if (pt.weight_kg > maxW) maxW = pt.weight_kg;
    if (pt.moving_avg_7d != null) {
      if (pt.moving_avg_7d < minW) minW = pt.moving_avg_7d;
      if (pt.moving_avg_7d > maxW) maxW = pt.moving_avg_7d;
    }
  });

  // Add margin to min/max
  let span = maxW - minW;
  if (span < 1.2) {
    minW -= 0.6;
    maxW += 0.6;
    span = maxW - minW;
  } else {
    minW -= span * 0.08;
    maxW += span * 0.08;
    span = maxW - minW;
  }

  const firstDay = chron[0].day;
  const lastDay = chron[chron.length - 1].day;
  const totalDays = Math.max(daysBetween(firstDay, lastDay), 1);

  const getX = (day) => {
    if (chron.length === 1) return padLeft + plotW / 2;
    const d = daysBetween(firstDay, day);
    return padLeft + (d / totalDays) * plotW;
  };

  const getY = (val) => {
    return padTop + plotH - ((val - minW) / span) * plotH;
  };

  // Map coordinates
  const points = chron.map((pt) => ({
    ...pt,
    x: getX(pt.day),
    y: getY(pt.weight_kg),
    avgY: pt.moving_avg_7d != null ? getY(pt.moving_avg_7d) : null,
  }));

  // Build Gridlines (3 levels: min, mid, max)
  const steps = 3;
  let gridMarkup = '';
  for (let s = 0; s <= steps; s++) {
    const val = minW + (span / steps) * s;
    const y = getY(val);
    gridMarkup += `
      <line x1="${padLeft}" y1="${y}" x2="${width - padRight}" y2="${y}" stroke="var(--line)" stroke-width="1" stroke-dasharray="3,3" />
      <text x="${padLeft - 6}" y="${y + 3.5}" text-anchor="end" font-size="10" fill="var(--muted)" font-family="inherit">${val.toFixed(1)}</text>
    `;
  }

  // Date labels at bottom
  gridMarkup += `
    <text x="${padLeft}" y="${height - 6}" text-anchor="start" font-size="9.5" fill="var(--muted)" font-family="inherit">${prettyDate(firstDay)}</text>
    <text x="${width - padRight}" y="${height - 6}" text-anchor="end" font-size="9.5" fill="var(--muted)" font-family="inherit">${prettyDate(lastDay)}</text>
  `;

  // Raw weight polyline
  let rawLineMarkup = '';
  if (points.length > 1) {
    const ptsStr = points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
    rawLineMarkup = `<polyline fill="none" stroke="rgba(231, 233, 238, 0.32)" stroke-width="1.5" stroke-linejoin="round" points="${ptsStr}" />`;
  }

  // Raw dots
  const dotsMarkup = points.map((p, idx) => `
    <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="3" fill="var(--surface-2)" stroke="var(--muted)" stroke-width="1.8" data-idx="${idx}" />
  `).join('');

  // Moving average path and gradient area
  let avgMarkup = '';
  const avgPoints = points.filter((p) => p.avgY != null);
  if (avgPoints.length > 1) {
    const avgLineStr = avgPoints.map((p) => `${p.x.toFixed(1)},${p.avgY.toFixed(1)}`).join(' ');
    const firstAvg = avgPoints[0];
    const lastAvg = avgPoints[avgPoints.length - 1];
    const bottomY = padTop + plotH;
    const areaStr = `${firstAvg.x.toFixed(1)},${bottomY} ` + avgLineStr + ` ${lastAvg.x.toFixed(1)},${bottomY}`;

    avgMarkup = `
      <polygon fill="url(#weightTrendGrad)" points="${areaStr}" />
      <polyline fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" points="${avgLineStr}" />
    `;
  } else if (avgPoints.length === 1) {
    avgMarkup = `<circle cx="${avgPoints[0].x.toFixed(1)}" cy="${avgPoints[0].avgY.toFixed(1)}" r="4" fill="var(--accent)" />`;
  }

  // Scrubber elements (initially hidden)
  const scrubberMarkup = `
    <g id="svg-scrubber" class="hidden">
      <line id="scrub-line" x1="0" y1="${padTop}" x2="0" y2="${padTop + plotH}" stroke="rgba(255,255,255,0.4)" stroke-width="1.5" stroke-dasharray="2,2" />
      <circle id="scrub-dot" cx="0" cy="0" r="5" fill="var(--accent)" stroke="#fff" stroke-width="2" />
    </g>
    <rect id="svg-overlay" x="${padLeft}" y="${padTop}" width="${plotW}" height="${plotH}" fill="transparent" style="cursor:crosshair" />
  `;

  svg.innerHTML = `
    <defs>
      <linearGradient id="weightTrendGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#4ade80" stop-opacity="0.25"/>
        <stop offset="100%" stop-color="#4ade80" stop-opacity="0.0"/>
      </linearGradient>
    </defs>
    ${gridMarkup}
    ${rawLineMarkup}
    ${avgMarkup}
    ${dotsMarkup}
    ${scrubberMarkup}
  `;

  // Attach pointer scrubber
  const overlay = $('svg-overlay');
  const scrubber = $('svg-scrubber');
  const scrubLine = $('scrub-line');
  const scrubDot = $('scrub-dot');

  function handlePointer(clientX) {
    const rect = svg.getBoundingClientRect();
    const svgX = ((clientX - rect.left) / rect.width) * width;

    // Find nearest point
    let closest = null;
    let closestDist = Infinity;
    points.forEach((pt) => {
      const dist = Math.abs(pt.x - svgX);
      if (dist < closestDist) {
        closestDist = dist;
        closest = pt;
      }
    });

    if (!closest) return;

    scrubber?.classList.remove('hidden');
    scrubLine?.setAttribute('x1', closest.x.toFixed(1));
    scrubLine?.setAttribute('x2', closest.x.toFixed(1));
    scrubDot?.setAttribute('cx', closest.x.toFixed(1));
    scrubDot?.setAttribute('cy', closest.y.toFixed(1));

    if (tooltip) {
      tooltip.classList.remove('hidden');
      $('tt-date').textContent = prettyDate(closest.day);
      $('tt-val').textContent = `${closest.weight_kg.toFixed(1)} kg`;
      $('tt-avg').textContent = closest.moving_avg_7d ? `Avg: ${closest.moving_avg_7d.toFixed(1)} kg` : '';
    }
  }

  overlay?.addEventListener('pointermove', (e) => handlePointer(e.clientX));
  overlay?.addEventListener('pointerdown', (e) => handlePointer(e.clientX));
  overlay?.addEventListener('pointerleave', () => {
    scrubber?.classList.add('hidden');
    tooltip?.classList.add('hidden');
  });
}

// Range pill clicks
$('weight-range-pills')?.addEventListener('click', (e) => {
  const btn = e.target.closest('.range-pill');
  if (!btn) return;
  document.querySelectorAll('#weight-range-pills .range-pill').forEach((b) => b.classList.remove('active'));
  btn.classList.add('active');
  activeRange = parseInt(btn.dataset.range, 10) || 30;
  renderWeightSection();
});

// Quick weight log form
$('quick-weight-date').value = todayISO();
$('quick-weight-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const dateInput = $('quick-weight-date');
  const valInput = $('quick-weight-val');
  const day = dateInput?.value || todayISO();
  const val = parseFloat(valInput?.value);

  if (isNaN(val) || val <= 0) return;

  try {
    await postJSON('/api/weights', { weight_kg: val, day });
    toast(`Weight logged: ${fmt(val, 1)} kg for ${prettyDate(day)}`);
    valInput.value = '';
    await loadWeights();
  } catch (err) {
    toast(err.message, true);
  }
});


/* ============================================================
   PHOTO COMPARISON & GALLERY
   ============================================================ */

async function loadPhotos() {
  const { photos } = await getJSON('/api/photos?limit=400');
  allPhotos = photos;
  $('count').textContent = photos.length
    ? `${photos.length} photo${photos.length === 1 ? '' : 's'}`
    : 'No photos yet';

  $('gallery').innerHTML = photos.length
    ? photos.map((p) => `<figure class="gallery-item">
        <img src="${esc(p.url)}?t=${p.bytes || ''}" alt="${esc(p.pose)} on ${esc(p.day)}" loading="lazy">
        <figcaption>
          <span>${esc(p.pose)} &middot; ${esc(p.day)}</span>
          <button type="button" class="btn-rotate-photo" data-id="${p.id}" title="Rotate 90° clockwise" aria-label="Rotate 90° clockwise">&#8635;</button>
        </figcaption>
      </figure>`).join('')
    : '<div class="empty" style="grid-column:1/-1">Nothing captured yet.</div>';

  renderCompare();
}

function forPose() {
  return allPhotos.filter((p) => p.pose === activePose)
                  .sort((a, b) => a.day.localeCompare(b.day));
}

function renderCompare() {
  const list = forPose();
  const enough = list.length >= 2;
  $('compare-wrap').classList.toggle('hidden', !enough);
  $('compare-empty').classList.toggle('hidden', enough);
  if (!enough) return;

  const curBefore = $('pick-before')?.value;
  const curAfter = $('pick-after')?.value;

  const options = (selected) => list.map((p) =>
    `<option value="${esc(p.url)}" data-id="${p.id}" data-bytes="${p.bytes || 0}" data-day="${esc(p.day)}" ${p.url === selected ? 'selected' : ''}>
      ${esc(p.day)}</option>`).join('');

  // Default to earliest (first) and latest (last)
  const bVal = list.some((p) => p.url === curBefore) ? curBefore : list[0].url;
  const aVal = list.some((p) => p.url === curAfter) ? curAfter : list[list.length - 1].url;

  $('pick-before').innerHTML = options(bVal);
  $('pick-after').innerHTML = options(aVal);
  applyPicks();
}

let alignMode = false;
let alignState = { scale: 100, x: 0, y: 0 };
let currentAfterPhotoId = null;

function getStoredAlignment(photoId) {
  if (!photoId) return null;
  try {
    const raw = localStorage.getItem(`photo_align_${photoId}`);
    if (raw) return JSON.parse(raw);
  } catch {}
  return null;
}

function saveStoredAlignment(photoId, align) {
  if (!photoId) return;
  try {
    localStorage.setItem(`photo_align_${photoId}`, JSON.stringify(align));
  } catch {}
}

function applyAlignment(align = {}, save = true) {
  alignState = { ...alignState, ...align };
  const pane = $('compare-after-pane');
  if (pane) {
    pane.style.setProperty('--after-scale', (alignState.scale / 100).toFixed(3));
    pane.style.setProperty('--after-x', `${Math.round(alignState.x)}px`);
    pane.style.setProperty('--after-y', `${Math.round(alignState.y)}px`);
  }

  const slider = $('align-scale-slider');
  if (slider && align.scale !== undefined) slider.value = alignState.scale;
  const scaleVal = $('align-scale-val');
  if (scaleVal) scaleVal.textContent = `${alignState.scale}%`;

  const isDefault = alignState.scale === 100 && Math.round(alignState.x) === 0 && Math.round(alignState.y) === 0;
  const badge = $('align-status-badge');
  if (badge) {
    badge.textContent = isDefault ? 'Default' : 'Adjusted';
    badge.style.color = isDefault ? 'var(--muted)' : 'var(--accent)';
  }

  if (save && currentAfterPhotoId) {
    saveStoredAlignment(currentAfterPhotoId, alignState);
  }
}

async function autoAlignSilhouette() {
  const imgB = $('img-before');
  const imgA = $('img-after');
  if (!imgB || !imgA) return;

  const btn = $('btn-auto-align');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Analyzing…';
  }

  try {
    if (!imgB.complete) await new Promise((r) => imgB.onload = r);
    if (!imgA.complete) await new Promise((r) => imgA.onload = r);

    const analyzeImage = (img) => {
      const canvas = document.createElement('canvas');
      const w = 120;
      const h = 160;
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(img, 0, 0, w, h);
      const data = ctx.getImageData(0, 0, w, h).data;

      // Compute horizontal brightness & contrast variance per column
      const colVariance = new Float32Array(w);
      const yStart = Math.floor(h * 0.15);
      const yEnd = Math.floor(h * 0.85);
      for (let x = 0; x < w; x++) {
        let sum = 0;
        let sumSq = 0;
        let count = 0;
        for (let y = yStart; y < yEnd; y++) {
          const idx = (y * w + x) * 4;
          const lum = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
          sum += lum;
          sumSq += lum * lum;
          count++;
        }
        const mean = sum / count;
        colVariance[x] = (sumSq / count) - (mean * mean);
      }

      // Weighted horizontal centroid (center of silhouette)
      let weightedSum = 0;
      let totalWeight = 0;
      for (let x = 0; x < w; x++) {
        const weight = Math.max(0, colVariance[x]);
        weightedSum += x * weight;
        totalWeight += weight;
      }
      const centerX = totalWeight > 0 ? (weightedSum / totalWeight) / w : 0.5;

      // Vertical row variance to locate top and bottom of torso
      const rowVariance = new Float32Array(h);
      for (let y = 0; y < h; y++) {
        let sum = 0;
        let sumSq = 0;
        for (let x = 0; x < w; x++) {
          const idx = (y * w + x) * 4;
          const lum = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
          sum += lum;
          sumSq += lum * lum;
        }
        const mean = sum / w;
        rowVariance[y] = (sumSq / w) - (mean * mean);
      }

      let topY = Math.floor(h * 0.1);
      let bottomY = Math.floor(h * 0.9);
      const avgRowVar = rowVariance.reduce((a, b) => a + b, 0) / h;
      for (let y = 5; y < h - 10; y++) {
        if (rowVariance[y] > avgRowVar * 0.65) {
          topY = y;
          break;
        }
      }
      for (let y = h - 5; y > topY + 15; y--) {
        if (rowVariance[y] > avgRowVar * 0.65) {
          bottomY = y;
          break;
        }
      }

      const centerY = ((topY + bottomY) / 2) / h;
      const height = Math.max(0.2, (bottomY - topY) / h);

      return { centerX, centerY, height };
    };

    const bMetrics = analyzeImage(imgB);
    const aMetrics = analyzeImage(imgA);

    let scaleRatio = 1.0;
    if (aMetrics.height > 0.1 && bMetrics.height > 0.1) {
      scaleRatio = bMetrics.height / aMetrics.height;
    }
    scaleRatio = Math.max(0.85, Math.min(1.25, scaleRatio));

    const rect = $('compare')?.getBoundingClientRect() || { width: 350, height: 466 };
    let dx = (bMetrics.centerX - aMetrics.centerX) * rect.width;
    let dy = (bMetrics.centerY - aMetrics.centerY * scaleRatio) * rect.height * 0.6;

    dx = Math.max(-50, Math.min(50, dx));
    dy = Math.max(-50, Math.min(50, dy));

    const finalScale = Math.round(scaleRatio * 100);
    const finalX = Math.round(dx);
    const finalY = Math.round(dy);

    applyAlignment({ scale: finalScale, x: finalX, y: finalY }, true);
    toast('Auto-aligned silhouette & scale');
  } catch (err) {
    console.error('Auto align error:', err);
    toast('Auto-align failed', true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '✨ Auto-Align';
    }
  }
}

function applyPicks() {
  const before = $('pick-before');
  const after = $('pick-after');
  if (!before || !after || !before.selectedOptions.length || !after.selectedOptions.length) return;
  const bOpt = before.selectedOptions[0];
  const aOpt = after.selectedOptions[0];
  $('img-before').src = `${before.value}?t=${bOpt.dataset.bytes || ''}`;
  $('img-after').src = `${after.value}?t=${aOpt.dataset.bytes || ''}`;
  $('label-before').textContent = `Earlier: ${prettyDate(bOpt.dataset.day)}`;
  $('label-after').textContent = `Later: ${prettyDate(aOpt.dataset.day)}`;

  // Load and apply stored alignment for the selected comparison photo
  currentAfterPhotoId = aOpt.dataset.id;
  const stored = getStoredAlignment(currentAfterPhotoId);
  if (stored) {
    applyAlignment(stored, false);
  } else {
    applyAlignment({ scale: 100, x: 0, y: 0 }, false);
  }
}

function applySplit() {
  const value = $('split').value;
  $('compare').style.setProperty('--split', `${value}%`);
}

// Interactive Touch & Mouse Dragging for Alignment
let isPanning = false;
let panStartX = 0;
let panStartY = 0;
let panOrigX = 0;
let panOrigY = 0;

const panOverlay = $('align-pan-overlay');
panOverlay?.addEventListener('pointerdown', (e) => {
  if (!alignMode) return;
  isPanning = true;
  panStartX = e.clientX;
  panStartY = e.clientY;
  panOrigX = alignState.x;
  panOrigY = alignState.y;
  panOverlay.setPointerCapture(e.pointerId);
});

panOverlay?.addEventListener('pointermove', (e) => {
  if (!isPanning) return;
  const dx = e.clientX - panStartX;
  const dy = e.clientY - panStartY;
  applyAlignment({ x: panOrigX + dx, y: panOrigY + dy }, false);
});

const endPan = () => {
  if (isPanning) {
    isPanning = false;
    applyAlignment({}, true);
  }
};
panOverlay?.addEventListener('pointerup', endPan);
panOverlay?.addEventListener('pointercancel', endPan);

// Alignment Toolbar Button Listeners
$('btn-toggle-align')?.addEventListener('click', () => {
  alignMode = !alignMode;
  $('compare')?.classList.toggle('align-mode', alignMode);
  $('align-toolbar')?.classList.toggle('hidden', !alignMode);
  const btn = $('btn-toggle-align');
  if (btn) {
    btn.textContent = alignMode ? '✓ Done Aligning' : '📐 Adjust Alignment';
    btn.style.background = alignMode ? 'var(--accent)' : 'var(--surface-2)';
    btn.style.color = alignMode ? '#06240f' : 'var(--text)';
    btn.style.fontWeight = alignMode ? '600' : 'normal';
  }
});

$('btn-close-align')?.addEventListener('click', () => {
  alignMode = false;
  $('compare')?.classList.remove('align-mode');
  $('align-toolbar')?.classList.add('hidden');
  const btn = $('btn-toggle-align');
  if (btn) {
    btn.textContent = '📐 Adjust Alignment';
    btn.style.background = 'var(--surface-2)';
    btn.style.color = 'var(--text)';
    btn.style.fontWeight = 'normal';
  }
});

$('align-scale-slider')?.addEventListener('input', (e) => {
  applyAlignment({ scale: parseInt(e.target.value, 10) || 100 }, true);
});
$('btn-scale-minus')?.addEventListener('click', () => {
  applyAlignment({ scale: Math.max(70, alignState.scale - 1) }, true);
});
$('btn-scale-plus')?.addEventListener('click', () => {
  applyAlignment({ scale: Math.min(140, alignState.scale + 1) }, true);
});
$('btn-nudge-up')?.addEventListener('click', () => {
  applyAlignment({ y: alignState.y - 2 }, true);
});
$('btn-nudge-down')?.addEventListener('click', () => {
  applyAlignment({ y: alignState.y + 2 }, true);
});
$('btn-nudge-left')?.addEventListener('click', () => {
  applyAlignment({ x: alignState.x - 2 }, true);
});
$('btn-nudge-right')?.addEventListener('click', () => {
  applyAlignment({ x: alignState.x + 2 }, true);
});
$('btn-reset-align')?.addEventListener('click', () => {
  applyAlignment({ scale: 100, x: 0, y: 0 }, true);
  toast('Alignment reset to default');
});
$('btn-auto-align')?.addEventListener('click', autoAlignSilhouette);

// Pose segmented buttons
$('pose-seg')?.addEventListener('click', (e) => {
  const btn = e.target.closest('.seg-btn');
  if (!btn) return;
  document.querySelectorAll('#pose-seg .seg-btn').forEach((b) => b.classList.remove('active'));
  btn.classList.add('active');
  activePose = btn.dataset.pose || 'front';
  renderCompare();
});

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

async function rotatePhoto(id, btn) {
  if (!id) return;
  if (btn) {
    btn.disabled = true;
    btn.style.opacity = '0.5';
  }
  try {
    await postForm(`/api/photos/${id}/rotate`, new FormData());
    toast('Photo rotated 90°');
    await loadPhotos();
  } catch (err) {
    toast(err.message, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.style.opacity = '1';
    }
  }
}

$('gallery').addEventListener('click', (e) => {
  const btn = e.target.closest('.btn-rotate-photo');
  if (btn && btn.dataset.id) {
    rotatePhoto(btn.dataset.id, btn);
  }
});

$('btn-rotate-before')?.addEventListener('click', (e) => {
  const sel = $('pick-before');
  const id = sel?.selectedOptions[0]?.dataset.id;
  rotatePhoto(id, e.currentTarget);
});

$('btn-rotate-after')?.addEventListener('click', (e) => {
  const sel = $('pick-after');
  const id = sel?.selectedOptions[0]?.dataset.id;
  rotatePhoto(id, e.currentTarget);
});

$('split').addEventListener('input', applySplit);
$('pick-before').addEventListener('change', applyPicks);
$('pick-after').addEventListener('change', applyPicks);

applySplit();

// Initialize both photos and weights
Promise.all([loadPhotos(), loadWeights()]).catch((err) => toast(err.message, true));

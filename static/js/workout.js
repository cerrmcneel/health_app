// Training Studio & Equipment Inventory Management
import {
  getJSON,
  postJSON,
  del,
  toast,
  markNav,
  todayISO,
  prettyDate,
  esc,
} from './api.js';

const $ = (id) => document.getElementById(id);

let currentOwnedKeys = new Set();
let currentEquipmentList = [];
let activeRoutineData = null;
let timerInterval = null;
let timerSecondsRemaining = 45;
let timerTotalSeconds = 45;
let timerIsRunning = false;

// Equipment emoji icons mapping
const EQUIP_ICONS = {
  yoga_mat: '🧘',
  jump_rope: '🪢',
  pull_up_bar: '🏋️',
  resistance_bands: '🎗️',
  dumbbells: '💪',
  kettlebell: '🔔',
  bench: '🛋️',
  barbell: '🏋️‍♂️',
  dip_station: '🪜',
  ab_wheel: '🎡',
  foam_roller: '🪵',
  bodyweight: '🤸',
  calisthenics: '🤸',
};

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
  markNav();
  if ($('today')) $('today').textContent = prettyDate(todayISO());

  initEquipment();
  initPills();
  initGenerator();
  initTimer();
  initModals();
  loadHistory();
});

// --- Modal Helpers ---
function openModal(id) {
  const el = $(id);
  if (el) el.classList.remove('hidden');
}

function closeModal(id) {
  const el = $(id);
  if (el) el.classList.add('hidden');
}

function initModals() {
  document.querySelectorAll('.modal-close').forEach((b) => {
    b.addEventListener('click', () => {
      const target = b.dataset.close;
      if (target) closeModal(target);
    });
  });

  document.querySelectorAll('.modal-overlay').forEach((ov) => {
    ov.addEventListener('click', (e) => {
      if (e.target === ov) ov.classList.add('hidden');
    });
  });

  $('btn-add-custom-gear')?.addEventListener('click', () => {
    openModal('add-gear-modal');
  });

  $('add-gear-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = $('custom-gear-name').value.trim();
    const notes = $('custom-gear-notes').value.trim();
    if (!name) return;

    const item_key = name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    try {
      await postJSON('/api/workouts/equipment', { item_key, name, notes });
      toast(`Added "${name}" to inventory`);
      closeModal('add-gear-modal');
      $('add-gear-form').reset();
      await initEquipment();
    } catch (err) {
      toast(err.message, true);
    }
  });
}

// --- Equipment Management ---
async function initEquipment() {
  const grid = $('equip-grid');
  try {
    const data = await getJSON('/api/workouts/equipment');
    currentEquipmentList = data.equipment || [];
    currentOwnedKeys = new Set(currentEquipmentList.map((e) => e.item_key));

    const catalog = data.standard_catalog || [];
    $('equip-count-badge').textContent = `${currentOwnedKeys.size} active`;

    grid.innerHTML = '';
    // Combine standard catalog items with any custom items owned
    const allItems = [...catalog];
    for (const owned of currentEquipmentList) {
      if (!allItems.some((item) => item.key === owned.item_key)) {
        allItems.push({
          key: owned.item_key,
          name: owned.name,
          category: 'custom',
          icon: '✨',
          custom: true,
        });
      }
    }

    allItems.forEach((item) => {
      const isOwned = currentOwnedKeys.has(item.key);
      const icon = item.icon || EQUIP_ICONS[item.key] || '📦';
      const chip = document.createElement('div');
      chip.className = `equip-chip ${isOwned ? 'active' : ''}`;
      chip.dataset.key = item.key;
      chip.dataset.name = item.name;

      chip.innerHTML = `
        <div class="chip-top">
          <span class="chip-icon">${icon}</span>
          <span class="chip-status">${isOwned ? '✓' : ''}</span>
        </div>
        <div class="chip-name" title="${esc(item.name)}">${esc(item.name)}</div>
        <div class="chip-sub">${isOwned ? 'Available' : 'Tap to add'}</div>
      `;

      chip.addEventListener('click', () => toggleEquipment(item.key, item.name, isOwned));
      grid.appendChild(chip);
    });
  } catch (err) {
    grid.innerHTML = `<div class="banner err">Failed to load equipment: ${esc(err.message)}</div>`;
  }
}

async function toggleEquipment(key, name, currentlyOwned) {
  try {
    if (currentlyOwned) {
      await del(`/api/workouts/equipment/${encodeURIComponent(key)}`);
      currentOwnedKeys.delete(key);
      toast(`Removed ${name}`);
    } else {
      await postJSON('/api/workouts/equipment', { item_key: key, name });
      currentOwnedKeys.add(key);
      toast(`Added ${name}`);
    }
    await initEquipment();
  } catch (err) {
    toast(err.message, true);
  }
}

// --- Generator UI Pill Controls ---
async function initPills() {
  const groups = ['focus-pills', 'duration-pills', 'level-pills'];
  groups.forEach((groupId) => {
    const el = $(groupId);
    if (!el) return;
    el.querySelectorAll('.pill-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        el.querySelectorAll('.pill-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
      });
    });
  });

  try {
    const pData = await getJSON('/api/profiles');
    const active = (pData.profiles || []).find(p => p.is_active);
    if (active) {
      if (active.preferred_duration_min) {
        const durEl = $('duration-pills');
        if (durEl) {
          const match = durEl.querySelector(`.pill-btn[data-val="${active.preferred_duration_min}"]`);
          if (match) {
            durEl.querySelectorAll('.pill-btn').forEach(b => b.classList.remove('active'));
            match.classList.add('active');
          }
        }
      }
      if (active.preferred_level) {
        const lvlEl = $('level-pills');
        if (lvlEl) {
          const match = lvlEl.querySelector(`.pill-btn[data-val="${active.preferred_level}"]`);
          if (match) {
            lvlEl.querySelectorAll('.pill-btn').forEach(b => b.classList.remove('active'));
            match.classList.add('active');
          }
        }
      }
    }
  } catch (err) {}
}

function getPillValue(groupId, fallback) {
  const el = $(groupId);
  if (!el) return fallback;
  const active = el.querySelector('.pill-btn.active');
  return active ? active.dataset.val : fallback;
}

// --- Workout Generation ---
function initGenerator() {
  const genBtn = $('btn-generate-workout');
  if (!genBtn) return;

  genBtn.addEventListener('click', async () => {
    const category = getPillValue('focus-pills', 'full_body');
    const duration_min = parseInt(getPillValue('duration-pills', '25'), 10);
    // The API field is `level`. Posting `intensity` here meant Pydantic silently
    // dropped it and every routine came out at the default difficulty.
    const level = getPillValue('level-pills', 'intermediate');
    const useAi = $('toggle-ai-coach')?.checked || false;

    genBtn.disabled = true;
    genBtn.textContent = useAi ? 'Consulting AI Coach...' : 'Designing Routine...';

    try {
      const endpoint = useAi ? '/api/workouts/ai-generate' : '/api/workouts/generate';
      const res = await postJSON(endpoint, {
        category,
        duration_min,
        level,
      });

      renderRoutine(res);
      $('routine-card').classList.remove('hidden');
      $('routine-card').scrollIntoView({ behavior: 'smooth', block: 'start' });

      // Falling back silently after a 3-minute wait looks like the AI ran.
      if (useAi && res.generator === 'offline-fallback') {
        toast('AI coach unavailable — used the offline designer.', true);
      } else {
        toast('Routine designed successfully!');
      }
    } catch (err) {
      toast(`Generation error: ${err.message}`, true);
    } finally {
      genBtn.disabled = false;
      genBtn.textContent = 'Generate Workout';
    }
  });

  $('btn-reroll-routine')?.addEventListener('click', () => {
    $('btn-generate-workout').click();
  });

  $('btn-dismiss-workout')?.addEventListener('click', () => {
    if (confirm('Dismiss this workout routine?')) {
      $('routine-card').classList.add('hidden');
      activeRoutineData = null;
    }
  });

  $('btn-complete-workout')?.addEventListener('click', async () => {
    if (!activeRoutineData) return;
    const btn = $('btn-complete-workout');
    btn.disabled = true;
    btn.textContent = 'Saving...';

    try {
      await postJSON('/api/workouts', {
        day: todayISO(),
        title: activeRoutineData.title,
        category: activeRoutineData.category,
        duration_min: activeRoutineData.duration_min,
        intensity: activeRoutineData.intensity,
        equipment_used: activeRoutineData.equipment_used,
        routine_json: activeRoutineData,
        completed: true,
        notes: activeRoutineData.description || 'Completed studio workout',
      });

      toast('🎉 Great job! Workout completed and logged.');
      $('routine-card').classList.add('hidden');
      activeRoutineData = null;
      await loadHistory();
    } catch (err) {
      toast(err.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Log & Complete Workout';
    }
  });
}

// --- Render Workout Routine ---
//
// Every field read here must exist on the payload from /api/workouts/generate.
// An exercise is:
//   { id, name, category, equipment: string, phase, type: 'time'|'reps',
//     default_target: string, target_muscles: string, instructions }
// Note `equipment` and `target_muscles` are single strings, not arrays, and the
// prescription is the pre-formatted `default_target` -- there are no per-exercise
// sets/reps/duration fields. tests/test_workout_contract.py enforces this.
function renderRoutine(routine) {
  activeRoutineData = routine;

  $('routine-title').textContent = routine.title || 'Your Workout';
  $('routine-description').textContent = routine.coaching_advice || routine.description || '';

  // The AI path is free-form enough that any of these can be absent; the
  // deterministic generator always supplies them.
  const category = String(routine.category || 'workout').replace(/_/g, ' ').toUpperCase();
  const equipUsed = Array.isArray(routine.equipment_used) && routine.equipment_used.length
    ? routine.equipment_used.map(prettyEquip).join(', ')
    : 'Bodyweight only';

  const tagsContainer = $('routine-tags');
  tagsContainer.innerHTML = `
    <span class="workout-tag accent">${esc(category)}</span>
    ${routine.duration_min ? `<span class="workout-tag">⏱️ ${esc(routine.duration_min)} min</span>` : ''}
    ${routine.intensity ? `<span class="workout-tag">⚡ ${esc(routine.intensity)}</span>` : ''}
    <span class="workout-tag">🛠️ ${esc(equipUsed)}</span>
    ${routine.work_rest ? `<span class="workout-tag">🔁 ${esc(routine.work_rest)}</span>` : ''}
  `;

  // Only the main circuit is performed for multiple rounds. Warm-ups and
  // cool-downs are done once -- offering "Set 1 / Set 2 / Set 3" against a
  // hamstring stretch is nonsense.
  const rounds = Number(routine.rounds) > 0 ? Number(routine.rounds) : 3;
  const restSec = restSecondsFor(routine);
  renderExercisePhase('warmup', routine.warmup || [], 1, restSec);
  renderExercisePhase('main', routine.main || [], rounds, restSec);
  renderExercisePhase('cooldown', routine.cooldown || [], 1, restSec);
}

/** Rest between sets, read off the routine's work/rest prescription.
 *
 * There is no per-exercise rest field; the API describes the whole circuit with
 * a string like "45s work / 15s rest". Fall back to a sane default when the
 * routine does not specify one (non-HIIT sessions say "3 rounds" instead).
 */
function restSecondsFor(routine) {
  const match = /(\d+)\s*s(?:ec)?\s*rest/i.exec(String(routine.work_rest || ''));
  if (match) return Number(match[1]);
  return routine.category === 'hiit' ? 20 : 45;
}

/** 'jump_rope' -> 'jump rope'; used for both equipment keys and display names. */
function prettyEquip(key) {
  return String(key || '').replace(/_/g, ' ');
}

function renderExercisePhase(phase, exercises, rounds = 1, restSec = 45) {
  const countEl = $(`${phase}-count`);
  const listEl = $(`${phase}-list`);
  if (countEl) countEl.textContent = `${exercises.length} exercise${exercises.length === 1 ? '' : 's'}`;
  if (!listEl) return;

  listEl.innerHTML = '';
  if (!exercises.length) {
    listEl.innerHTML = '<div class="muted" style="font-size:12px;padding:6px 0">No exercises in this phase.</div>';
    return;
  }

  exercises.forEach((ex, idx) => {
    const item = document.createElement('div');
    item.className = 'exercise-item';
    item.id = `ex-${phase}-${idx}`;

    // `equipment` is a single key ('none' means bodyweight), not an array.
    const equipLabel = (ex.equipment && ex.equipment !== 'none')
      ? `${EQUIP_ICONS[ex.equipment] || '📦'} ${prettyEquip(ex.equipment)}`
      : '🤸 Bodyweight';

    // The API sends a ready-made prescription string ('45s', '10-15 reps').
    const prescription = ex.default_target || (ex.type === 'time' ? '45s' : '10 reps');

    // Rounds come from the routine, not the exercise.
    let setsButtonsHtml = '';
    for (let s = 1; s <= rounds; s++) {
      setsButtonsHtml += `<button type="button" class="set-dot-btn" data-set="${s}">Set ${s}</button>`;
    }

    item.innerHTML = `
      <div class="exercise-top">
        <div class="exercise-name">${esc(ex.name)}</div>
        <span class="exercise-prescription">${esc(prescription)}</span>
      </div>
      <div class="exercise-sub">
        <span>${esc(equipLabel)}</span>
        ${ex.target_muscles ? `<span>&bull; ${esc(ex.target_muscles)}</span>` : ''}
      </div>
      ${ex.instructions ? `
        <span class="instructions-toggle" data-target="inst-${phase}-${idx}">ℹ️ Instructions</span>
        <div class="instructions-box hidden" id="inst-${phase}-${idx}">${esc(ex.instructions)}</div>
      ` : ''}
      <div class="exercise-sets-row">
        <span style="font-size:11px;color:var(--muted);margin-right:4px">Sets:</span>
        ${setsButtonsHtml}
      </div>
    `;

    // Toggle instructions
    const toggleBtn = item.querySelector('.instructions-toggle');
    if (toggleBtn) {
      toggleBtn.addEventListener('click', () => {
        const box = item.querySelector(`#${toggleBtn.dataset.target}`);
        if (box) box.classList.toggle('hidden');
      });
    }

    // Set buttons toggle
    item.querySelectorAll('.set-dot-btn').forEach((sBtn) => {
      sBtn.addEventListener('click', () => {
        sBtn.classList.toggle('done');
        // Trigger short interval timer on completing a set if not already running
        if (sBtn.classList.contains('done') && !timerIsRunning) {
          setTimerPreset(restSec);
          startTimer();
        }
        // Check if all sets for this exercise are done
        const allDone = Array.from(item.querySelectorAll('.set-dot-btn')).every((b) => b.classList.contains('done'));
        item.classList.toggle('completed', allDone);
      });
    });

    listEl.appendChild(item);
  });
}

// --- Rest & Interval Timer with Web Audio Chime ---
function initTimer() {
  updateTimerDisplay();

  $('btn-timer-toggle')?.addEventListener('click', () => {
    if (timerIsRunning) pauseTimer();
    else startTimer();
  });

  $('btn-timer-reset')?.addEventListener('click', () => {
    resetTimer();
  });

  document.querySelectorAll('.timer-preset-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const sec = parseInt(btn.dataset.sec, 10);
      if (sec) {
        setTimerPreset(sec);
        startTimer();
      }
    });
  });
}

function updateTimerDisplay() {
  const m = Math.floor(timerSecondsRemaining / 60);
  const s = timerSecondsRemaining % 60;
  const disp = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  const el = $('timer-digits');
  if (el) el.textContent = disp;
}

function startTimer() {
  if (timerIsRunning) return;
  timerIsRunning = true;
  const toggleBtn = $('btn-timer-toggle');
  if (toggleBtn) toggleBtn.textContent = 'Pause';
  $('timer-digits')?.classList.add('active');

  timerInterval = setInterval(() => {
    if (timerSecondsRemaining > 0) {
      timerSecondsRemaining -= 1;
      updateTimerDisplay();
    } else {
      pauseTimer();
      playChime();
      toast('🔔 Time up! Ready for next set.');
      resetTimer();
    }
  }, 1000);
}

function pauseTimer() {
  timerIsRunning = false;
  clearInterval(timerInterval);
  timerInterval = null;
  const toggleBtn = $('btn-timer-toggle');
  if (toggleBtn) toggleBtn.textContent = 'Start';
  $('timer-digits')?.classList.remove('active');
}

function resetTimer() {
  pauseTimer();
  timerSecondsRemaining = timerTotalSeconds;
  updateTimerDisplay();
}

function setTimerPreset(sec) {
  pauseTimer();
  timerTotalSeconds = sec;
  timerSecondsRemaining = sec;
  updateTimerDisplay();
}

// Synthesizes a pleasant two-tone offline chime using HTML5 Web Audio API
function playChime() {
  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;
    const ctx = new AudioContextClass();
    const now = ctx.currentTime;

    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = 'sine';
    osc1.frequency.setValueAtTime(587.33, now); // D5
    gain1.gain.setValueAtTime(0.25, now);
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(now);
    osc1.stop(now + 0.25);

    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = 'sine';
    osc2.frequency.setValueAtTime(880, now + 0.15); // A5
    gain2.gain.setValueAtTime(0.3, now + 0.15);
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.45);
    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.start(now + 0.15);
    osc2.stop(now + 0.45);
  } catch (err) {
    console.debug('Audio chime playback omitted:', err);
  }
}

// --- History List ---
async function loadHistory() {
  const container = $('workout-history-list');
  if (!container) return;

  try {
    const data = await getJSON('/api/workouts?limit=15');
    const workouts = data.workouts || [];
    if (!workouts.length) {
      container.innerHTML = '<div class="empty">No workouts logged yet. Generate one above!</div>';
      return;
    }

    container.innerHTML = '';
    workouts.forEach((w) => {
      const item = document.createElement('div');
      item.className = 'workout-log-item';

      const equipTxt = w.equipment_used?.length ? w.equipment_used.join(', ') : 'Bodyweight';

      item.innerHTML = `
        <div class="w-info">
          <div class="w-title">${esc(w.title)}</div>
          <div class="w-meta">
            <span>📅 ${prettyDate(w.day)}</span> &bull;
            <span>⏱️ ${w.duration_min} min</span> &bull;
            <span>🛠️ ${esc(equipTxt)}</span>
          </div>
        </div>
        <button type="button" class="del" data-del-id="${w.id}" title="Delete log">&times;</button>
      `;

      item.querySelector('[data-del-id]').addEventListener('click', async () => {
        if (!confirm(`Delete workout "${w.title}"?`)) return;
        try {
          await del(`/api/workouts/${w.id}`);
          toast('Workout removed');
          await loadHistory();
        } catch (err) {
          toast(err.message, true);
        }
      });

      container.appendChild(item);
    });
  } catch (err) {
    container.innerHTML = `<div class="banner err">Failed to load history: ${esc(err.message)}</div>`;
  }
}

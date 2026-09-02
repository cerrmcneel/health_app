// Ghost-overlay progress photo capture.
//
// Alignment contract: the live video, the ghost image and the saved JPEG are all
// full camera frames of the same aspect ratio, displayed with `object-fit: cover`.
// Because every layer is cropped identically, what lines up on screen lines up in
// the stored file -- so tomorrow's ghost is a faithful reference for today's shot.

import { getJSON, postForm, toast, esc } from './api.js';

const $ = (id) => document.getElementById(id);

const POSE_ORDER = ['front', 'profile'];
const POSE_HINT = {
  front: 'Face the camera square-on, arms relaxed at your sides.',
  profile: 'Turn 90°. Same spot, same distance, same posture.',
};

let stream = null;
let facing = 'environment';
let pose = 'front';
let queue = [...POSE_ORDER];
let timerSeconds = 0;
let busy = false;
let terminal = false;  // a fatal error or the finished state; do not restart the camera

// --- camera ---
async function startCamera() {
  if (!window.isSecureContext) {
    // getUserMedia is gated behind a secure context. http:// over a LAN IP is not
    // one, which is the single most common way this page fails on a homelab.
    return fail(
      'Camera blocked: insecure origin',
      `The browser only exposes the camera on <code>https://</code> or
       <code>localhost</code>. You are on <code>${esc(location.origin)}</code>.<br><br>
       Run the server with a TLS certificate (see <code>README.md</code>), reach it
       over a Tailscale/WireGuard hostname, or open it via an SSH tunnel on localhost.`,
    );
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return fail('Camera unsupported', 'This browser does not expose <code>getUserMedia</code>.');
  }

  stopCamera();
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: facing,
        width: { ideal: 1920 },
        height: { ideal: 1920 },
      },
      audio: false,
    });
  } catch (err) {
    const reason = {
      NotAllowedError: 'Camera permission was denied. Allow it in your browser’s site settings and reload.',
      NotFoundError: 'No camera was found on this device.',
      NotReadableError: 'The camera is already in use by another app.',
      OverconstrainedError: 'No camera matches the requested resolution.',
    }[err.name] || `${err.name}: ${err.message}`;
    return fail('Camera unavailable', esc(reason));
  }

  const video = $('video');
  video.srcObject = stream;
  // Selfie cameras are mirrored so the preview reads naturally; the capture is
  // mirrored to match, otherwise the saved photo would flip between sessions.
  video.style.transform = facing === 'user' ? 'scaleX(-1)' : '';
  $('ghost').style.transform = video.style.transform;
  await video.play().catch(() => {});
  hideMsg();
}

function stopCamera() {
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
}

// --- pose flow ---
async function loadPose(next) {
  pose = next;
  const index = POSE_ORDER.indexOf(pose) + 1;
  $('pose-label').textContent = pose === 'front' ? 'Front' : 'Profile';
  $('pose-sub').textContent = `Pose ${index} of ${POSE_ORDER.length} · ${POSE_HINT[pose]}`;

  const ghost = $('ghost');
  ghost.classList.add('hidden');
  try {
    const { photo } = await getJSON(`/api/photos/ghost?pose=${pose}`);
    if (photo) {
      ghost.src = photo.url;
      ghost.classList.remove('hidden');
      $('opacity-row').classList.remove('hidden');
      applyOpacity();
    } else {
      // No prior shot for this pose: the thirds grid is the only alignment aid.
      ghost.removeAttribute('src');
      $('opacity-row').classList.add('hidden');
      toast(`No previous ${pose} photo — this one becomes the reference.`);
    }
  } catch (err) {
    toast(err.message, true);
  }
}

function applyOpacity() {
  const value = Number($('opacity').value);
  $('ghost').style.opacity = value / 100;
  $('opacity-val').textContent = `${value}%`;
}

$('opacity').addEventListener('input', applyOpacity);

// --- capture ---
$('shutter').addEventListener('click', async () => {
  if (busy) return;
  if (timerSeconds > 0) await countdown(timerSeconds);
  await capture();
});

function countdown(seconds) {
  return new Promise((resolve) => {
    busy = true;
    let left = seconds;
    showMsg(`<div style="font-size:76px;font-weight:600" id="tick">${left}</div>`);
    const iv = setInterval(() => {
      left -= 1;
      if (left <= 0) {
        clearInterval(iv);
        hideMsg();
        busy = false;
        resolve();
      } else {
        const tick = $('tick');
        if (tick) tick.textContent = left;
      }
    }, 1000);
  });
}

async function capture() {
  const video = $('video');
  if (!video.videoWidth) {
    toast('Camera is not ready yet.', true);
    return;
  }

  busy = true;
  $('shutter').disabled = true;
  $('flash').classList.add('fire');
  setTimeout(() => $('flash').classList.remove('fire'), 360);

  const canvas = $('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext('2d');
  if (facing === 'user') {
    ctx.translate(canvas.width, 0);
    ctx.scale(-1, 1);
  }
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.94));
  if (!blob) {
    toast('Could not encode the photo.', true);
    busy = false;
    $('shutter').disabled = false;
    return;
  }

  const form = new FormData();
  form.append('image', blob, `${pose}.jpg`);
  form.append('pose', pose);

  try {
    const result = await postForm('/api/photos', form);
    toast(`${pose} photo saved`);
    queue = queue.filter((p) => p !== pose);
    if (queue.length) {
      await loadPose(queue[0]);   // auto-advance front -> profile
    } else {
      finish(result.photo);
    }
  } catch (err) {
    toast(err.message, true);
  } finally {
    busy = false;
    $('shutter').disabled = false;
  }
}

// --- controls ---
$('btn-flip').addEventListener('click', async () => {
  facing = facing === 'environment' ? 'user' : 'environment';
  await startCamera();
});

$('btn-timer').addEventListener('click', () => {
  timerSeconds = { 0: 3, 3: 10, 10: 0 }[timerSeconds];
  $('btn-timer').textContent = `${timerSeconds}s`;
});

// --- file upload fallback ---
$('btn-upload')?.addEventListener('click', () => {
  $('file-upload')?.click();
});

$('file-upload')?.addEventListener('change', async (e) => {
  const file = e.target.files?.[0];
  e.target.value = '';
  if (!file) return;

  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  const today = new Date().toISOString().slice(0, 10);

  const useYesterday = confirm(`Upload "${file.name}" for Yesterday (${yesterday})?\n\n- Click OK for Yesterday (${yesterday})\n- Click Cancel for Today (${today})`);
  const chosenDay = useYesterday ? yesterday : today;

  const form = new FormData();
  form.append('image', file, file.name || `${pose}.jpg`);
  form.append('pose', pose);
  form.append('day', chosenDay);

  try {
    const result = await postForm('/api/photos', form);
    toast(`${pose} photo saved for ${chosenDay}`);
    queue = queue.filter((p) => p !== pose);
    if (queue.length) {
      await loadPose(queue[0]);
    } else {
      finish(result.photo);
    }
  } catch (err) {
    toast(err.message, true);
  }
});

// --- overlays ---
function showMsg(html) {
  $('msg-inner').innerHTML = html;
  $('msg').classList.remove('hidden');
}
function hideMsg() { $('msg').classList.add('hidden'); }

function fail(title, html) {
  terminal = true;
  stopCamera();
  showMsg(`<h2 style="text-transform:none;font-size:17px;color:var(--text);letter-spacing:0">${esc(title)}</h2>
    <p class="muted" style="font-size:13.5px">${html}</p>
    <a class="btn" href="/" style="margin-top:10px">Back to today</a>`);
}

function finish(photo) {
  terminal = true;
  stopCamera();
  showMsg(`<div style="font-size:44px;margin-bottom:8px">✓</div>
    <h2 style="text-transform:none;font-size:18px;color:var(--text);letter-spacing:0">Both poses captured</h2>
    <p class="muted" style="font-size:13px">Saved to <code>${esc(photo.path)}</code></p>
    <div class="btn-row" style="margin-top:14px">
      <a class="btn" href="/progress">See progress</a>
      <a class="btn btn-primary" href="/">Done</a>
    </div>`);
}

// Release the camera when the tab is backgrounded; some phones will not hand it
// back to another app otherwise. Resume on return, unless we ended on a terminal
// screen (fatal error, or both poses finished) that deliberately stopped it.
document.addEventListener('visibilitychange', () => {
  if (document.hidden) stopCamera();
  else if (!terminal) startCamera();
});
window.addEventListener('pagehide', stopCamera);

(async function init() {
  try {
    const status = await getJSON('/api/photos/status');
    queue = status.remaining.length ? status.remaining : [...POSE_ORDER];
    if (!status.remaining.length) {
      toast('Both poses already shot today — new photos will replace them.');
    }
  } catch {
    queue = [...POSE_ORDER];
  }
  await loadPose(queue[0]);
  await startCamera();
})();

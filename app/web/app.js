'use strict';

/* Face ID + Blockchain Verification — front-end controller.
 *
 * Talks to the FastAPI backend:
 *   POST /api/jobs                 -> stage the upload, get a job id
 *   GET  /api/jobs/{id}/stream     -> Server-Sent Events for one run
 *   POST /api/verify               -> re-verify / tamper test (JSON)
 *
 * The stream is read with fetch()+ReadableStream rather than EventSource on
 * purpose: EventSource auto-reconnects, and every reconnect would launch a
 * fresh pipeline run (and a fresh on-chain write). fetch() gives us one shot.
 */

// ---- short stage labels (the rail); the console shows the server's own text.
const STAGES = [
  'Load image',
  'Detect faces',
  'Encode face',
  'Reverse image search',
  'Verify candidates',
  'Write to blockchain',
  'Re-verify record',
];

const $ = (id) => document.getElementById(id);

const el = {
  fileInput: $('fileInput'),
  dropzone: $('dropzone'),
  dropPrompt: $('dropPrompt'),
  dropPreview: $('dropPreview'),
  previewImg: $('previewImg'),
  previewName: $('previewName'),
  previewSize: $('previewSize'),
  clearBtn: $('clearBtn'),
  uploadForm: $('uploadForm'),
  runBtn: $('runBtn'),

  pipelineCard: $('pipelineCard'),
  pipelineStatus: $('pipelineStatus'),
  stageRail: $('stageRail'),
  console: $('console'),
  liveBadge: $('liveBadge'),

  resultCard: $('resultCard'),
  verdictBadge: $('verdictBadge'),
  inputFrame: $('inputFrame'),
  inputImg: $('inputImg'),
  boxLayer: $('boxLayer'),
  matchImg: $('matchImg'),
  matchImgFallback: $('matchImgFallback'),
  simValue: $('simValue'),
  gaugeFill: $('gaugeFill'),
  gaugeThreshold: $('gaugeThreshold'),
  thresholdLabel: $('thresholdLabel'),
  matchSource: $('matchSource'),
  evidenceLink: $('evidenceLink'),
  pageLink: $('pageLink'),
  pageStatus: $('pageStatus'),
  recordHash: $('recordHash'),
  hashChip: $('hashChip'),
  txLink: $('txLink'),
  blockNum: $('blockNum'),
  gasUsed: $('gasUsed'),
  chainNet: $('chainNet'),
  integrityBadge: $('integrityBadge'),

  verifyCard: $('verifyCard'),
  reverifyBtn: $('reverifyBtn'),
  tamperBtn: $('tamperBtn'),
  verifyResult: $('verifyResult'),
  verifyVerdict: $('verifyVerdict'),
  vRecomputed: $('vRecomputed'),
  vOnChain: $('vOnChain'),
  verifyExplain: $('verifyExplain'),

  errorCard: $('errorCard'),
  errorKind: $('errorKind'),
  errorMessage: $('errorMessage'),
  errorHint: $('errorHint'),
  errorRetry: $('errorRetry'),

  toast: $('toast'),
};

const MAX_BYTES = 15 * 1024 * 1024;

let selectedFile = null;
let inputObjectURL = null;
let facesPayload = null;   // {faces, target_index} for the box overlay
let streamActive = false;

// ===========================================================================
// Upload & selection
// ===========================================================================

function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function selectFile(file) {
  if (!file) return;
  if (file.size > MAX_BYTES) {
    toast(`That image is ${humanSize(file.size)} — the limit is 15 MB.`);
    return;
  }
  selectedFile = file;
  if (inputObjectURL) URL.revokeObjectURL(inputObjectURL);
  inputObjectURL = URL.createObjectURL(file);

  el.previewImg.src = inputObjectURL;
  el.previewName.textContent = file.name || 'image';
  el.previewSize.textContent = `${humanSize(file.size)} · ${file.type || 'image'}`;
  el.dropPrompt.hidden = true;
  el.dropPreview.hidden = false;
  el.runBtn.disabled = false;
}

function clearSelection() {
  selectedFile = null;
  el.fileInput.value = '';
  el.dropPrompt.hidden = false;
  el.dropPreview.hidden = true;
  el.runBtn.disabled = true;
}

el.fileInput.addEventListener('change', (e) => selectFile(e.target.files[0]));
el.clearBtn.addEventListener('click', (e) => { e.preventDefault(); clearSelection(); });

['dragenter', 'dragover'].forEach((evt) =>
  el.dropzone.addEventListener(evt, (e) => { e.preventDefault(); el.dropzone.classList.add('dragover'); })
);
['dragleave', 'drop'].forEach((evt) =>
  el.dropzone.addEventListener(evt, (e) => { e.preventDefault(); el.dropzone.classList.remove('dragover'); })
);
el.dropzone.addEventListener('drop', (e) => {
  const file = e.dataTransfer.files && e.dataTransfer.files[0];
  if (file) selectFile(file);
});

// ===========================================================================
// Run
// ===========================================================================

el.uploadForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!selectedFile || streamActive) return;
  startRun();
});

el.errorRetry.addEventListener('click', () => {
  hide(el.errorCard);
  clearSelection();
  window.scrollTo({ top: 0, behavior: 'smooth' });
});

async function startRun() {
  resetRunUI();
  el.runBtn.disabled = true;
  setLive(true);

  // Mirror the upload into the result panel's "input face" frame.
  el.inputImg.src = inputObjectURL;
  el.inputImg.style.objectFit = 'contain';

  let jobId;
  try {
    const fd = new FormData();
    fd.append('image', selectedFile);
    const r = await fetch('/api/jobs', { method: 'POST', body: fd });
    if (!r.ok) {
      const body = await safeJson(r);
      return showError(body.kind || `HTTP ${r.status}`, body.detail || body.message || 'Upload failed.', body.hint);
    }
    jobId = (await r.json()).job_id;
  } catch (err) {
    return showError('NETWORK ERROR', 'Could not reach the server to upload the image.', String(err));
  }

  show(el.pipelineCard);
  await streamJob(jobId);
  el.runBtn.disabled = false;
}

async function streamJob(jobId) {
  let resp;
  try {
    resp = await fetch(`/api/jobs/${jobId}/stream`, { headers: { Accept: 'text/event-stream' } });
  } catch (err) {
    return showError('NETWORK ERROR', 'Could not open the live progress stream.', String(err));
  }
  if (!resp.ok || !resp.body) {
    const body = await safeJson(resp);
    return showError(body.kind || `HTTP ${resp.status}`, body.message || body.detail || 'The server refused to start the run.', body.hint);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  streamActive = true;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let sep;
      while ((sep = buf.indexOf('\n\n')) !== -1) {
        const raw = buf.slice(0, sep);
        buf = buf.slice(sep + 2);
        const dataLine = raw.split('\n').find((l) => l.startsWith('data:'));
        if (!dataLine) continue; // ": heartbeat" comment
        const json = dataLine.slice(5).trim();
        if (!json) continue;
        let ev;
        try { ev = JSON.parse(json); } catch { continue; }
        handleEvent(ev);
      }
    }
  } catch (err) {
    if (streamActive) showError('STREAM ERROR', 'The live connection dropped mid-run.', String(err));
  } finally {
    streamActive = false;
    setLive(false);
  }
}

// ===========================================================================
// Event handling
// ===========================================================================

function handleEvent(ev) {
  switch (ev.type) {
    case 'hello': break;
    case 'step':
      setStage(ev.index, 'active');
      logLine('step', `[${ev.index}/${ev.total}]`, ev.title, 'step-line');
      break;
    case 'log': logLine(ev.level, tagFor(ev.level), ev.message); break;
    case 'kv': logKv(ev.key, ev.value); break;
    case 'section': logLine('info', '::', ev.title); break;
    case 'banner': break;
    case 'verdict': logLine(ev.passed ? 'ok' : 'fail', ev.passed ? 'PASS' : 'FAIL', `${ev.label}`); break;
    case 'milestone': handleMilestone(ev.kind, ev.payload || {}); break;
    case 'result': onResult(ev.result || {}); break;
    case 'error':
      streamActive = false;
      markCurrentStageFailed();
      showError(ev.kind || 'ERROR', ev.message || 'The pipeline failed.', ev.hint);
      break;
  }
}

function handleMilestone(kind, p) {
  switch (kind) {
    case 'faces_detected':
      facesPayload = p;
      drawBoxes();
      break;
    case 'candidate_matched':
      populateMatch(p);
      show(el.resultCard);
      break;
    case 'record_hashed':
      if (p.record_hash) el.recordHash.textContent = p.record_hash;
      break;
    case 'chain_confirmed':
      populateChain(p);
      break;
    case 'integrity':
      setIntegrity(!!p.match);
      break;
  }
}

function onResult(result) {
  finishStages();
  el.pipelineStatus.textContent = 'complete';
  el.pipelineStatus.className = 'status-chip done';
  setLive(false);
  if (result.record_hash) el.recordHash.textContent = result.record_hash;
  if (typeof result.integrity_match === 'boolean') setIntegrity(result.integrity_match);
  show(el.resultCard);
  show(el.verifyCard);
}

// ===========================================================================
// Result rendering
// ===========================================================================

function verdictClass(verdict) {
  const v = (verdict || '').toUpperCase();
  if (v === 'MATCH') return 'match';
  if (v === 'REVIEW') return 'review';
  return 'nomatch';
}

function populateMatch(p) {
  const cls = verdictClass(p.verdict);
  el.verdictBadge.textContent = p.verdict || 'MATCH';
  el.verdictBadge.className = `verdict-badge ${cls}`;

  // Matched candidate image — the verified image URL, which reliably renders.
  if (p.image_url_used) {
    el.matchImg.src = p.image_url_used;
    el.matchImg.hidden = false;
    el.matchImgFallback.hidden = true;
    el.matchImg.onerror = () => { el.matchImg.hidden = true; el.matchImgFallback.hidden = false; };
  }

  // Similarity gauge.
  const sim = Number(p.similarity) || 0;
  const thr = Number(p.threshold) || 0;
  el.simValue.textContent = sim.toFixed(4);
  el.thresholdLabel.textContent = `threshold ${thr}`;
  el.gaugeThreshold.style.left = `${clamp01(thr) * 100}%`;
  requestAnimationFrame(() => { el.gaugeFill.style.width = `${clamp01(sim) * 100}%`; });
  el.gaugeFill.style.background = cls === 'match'
    ? 'linear-gradient(90deg, var(--accent), var(--success))'
    : cls === 'review' ? 'var(--warn)' : 'var(--danger)';

  const source = p.source || (p.page_url ? hostOf(p.page_url) : 'web');
  el.matchSource.textContent = p.platform ? `${source} · ${p.platform}` : source;

  // Evidence image link (reliable) + labelled source page link.
  if (p.image_url_used) { el.evidenceLink.href = p.image_url_used; el.evidenceLink.parentElement.style.display = ''; }
  if (p.page_url) {
    el.pageLink.href = p.page_url;
    el.pageLink.style.display = '';
  } else {
    el.pageLink.style.display = 'none';
  }
  setLinkStatus(p.page_link_status);
}

function setLinkStatus(status) {
  const map = {
    live: ['live', 'live'],
    login_wall: ['requires login', 'login'],
    dead: ['unavailable', 'dead'],
    unknown: ['unverified', ''],
  };
  const [label, cls] = map[status] || ['unverified', ''];
  el.pageStatus.textContent = label;
  el.pageStatus.className = `link-status ${cls}`;
}

function populateChain(p) {
  if (p.tx_hash) {
    el.txLink.textContent = shortHash(p.tx_hash);
    el.txLink.href = p.explorer_url || '#';
  }
  if (p.block != null) el.blockNum.textContent = String(p.block);
  if (p.gas_used != null) el.gasUsed.textContent = Number(p.gas_used).toLocaleString();
  if (p.network) el.chainNet.textContent = p.chain_id ? `${p.network} (${p.chain_id})` : p.network;
}

function setIntegrity(pass) {
  el.integrityBadge.textContent = `INTEGRITY: ${pass ? 'PASS' : 'FAIL'}`;
  el.integrityBadge.className = `integrity-badge ${pass ? 'pass' : 'fail'}`;
}

// --- detected-face box overlay (input frame uses object-fit: contain) -------
function drawBoxes() {
  if (!facesPayload || !el.inputImg.naturalWidth) return;
  const frame = el.inputFrame.getBoundingClientRect();
  const nW = el.inputImg.naturalWidth;
  const nH = el.inputImg.naturalHeight;
  const scale = Math.min(frame.width / nW, frame.height / nH);
  const dispW = nW * scale;
  const dispH = nH * scale;
  const offX = (frame.width - dispW) / 2;
  const offY = (frame.height - dispH) / 2;

  el.boxLayer.innerHTML = '';
  (facesPayload.faces || []).forEach((f) => {
    const box = document.createElement('div');
    const isTarget = f.index === facesPayload.target_index;
    box.className = `face-box${isTarget ? ' target' : ''}`;
    box.style.left = `${offX + f.x * scale}px`;
    box.style.top = `${offY + f.y * scale}px`;
    box.style.width = `${f.width * scale}px`;
    box.style.height = `${f.height * scale}px`;
    if (isTarget) {
      const tag = document.createElement('span');
      tag.className = 'box-tag';
      tag.textContent = `target ${(f.confidence * 100).toFixed(0)}%`;
      box.appendChild(tag);
    }
    el.boxLayer.appendChild(box);
  });
}

el.inputImg.addEventListener('load', drawBoxes);
window.addEventListener('resize', () => { if (facesPayload) drawBoxes(); });

// ===========================================================================
// Verify / tamper
// ===========================================================================

el.reverifyBtn.addEventListener('click', () => runVerify(false));
el.tamperBtn.addEventListener('click', () => runVerify(true));

async function runVerify(tamper) {
  el.reverifyBtn.disabled = true;
  el.tamperBtn.disabled = true;
  try {
    const fd = new FormData();
    fd.append('tamper', tamper ? 'true' : 'false');
    const r = await fetch('/api/verify', { method: 'POST', body: fd });
    const data = await safeJson(r);
    if (!r.ok) {
      renderVerify({ verdict: data.kind || 'ERROR', _explain: data.message, _error: true });
      return;
    }
    renderVerify(data);
  } catch (err) {
    renderVerify({ verdict: 'ERROR', _explain: String(err), _error: true });
  } finally {
    el.reverifyBtn.disabled = false;
    el.tamperBtn.disabled = false;
  }
}

function renderVerify(d) {
  show(el.verifyResult);
  const verdict = d.verdict || '—';
  let cls = 'neutral';
  if (verdict === 'PASS') cls = 'pass';
  else if (verdict === 'TAMPER DETECTED' || verdict === 'FAIL') cls = 'tamper';
  el.verifyVerdict.textContent = verdict;
  el.verifyVerdict.className = `verify-verdict ${cls}`;

  el.vRecomputed.textContent = d.recomputed_hash ? shortHash(d.recomputed_hash) : '—';
  el.vOnChain.textContent = d.on_chain_hash ? shortHash(d.on_chain_hash) : (d._error ? '—' : 'not found on-chain');

  let explain = d._explain || '';
  if (!explain) {
    if (verdict === 'PASS') explain = 'The recomputed hash matches the record anchored on-chain. The artifact is intact.';
    else if (verdict === 'TAMPER DETECTED') explain = 'One field was altered, so the recomputed hash no longer matches the on-chain record — exactly how tampering is caught. The chain was not modified.';
    else if (verdict === 'UNCHANGED') explain = 'The tampered value happened to collide; try again.';
    else explain = 'No matching record was found on-chain for this hash.';
  }
  el.verifyExplain.textContent = explain;
}

// ===========================================================================
// Stage rail + console
// ===========================================================================

function renderStages() {
  el.stageRail.innerHTML = '';
  STAGES.forEach((title, i) => {
    const li = document.createElement('li');
    li.className = 'stage pending';
    li.dataset.index = String(i + 1);
    li.innerHTML = `
      <span class="stage-icon">${i + 1}</span>
      <span class="stage-title">${title}</span>
      <span class="stage-spin"></span>`;
    el.stageRail.appendChild(li);
  });
}

function setStage(index, state) {
  const items = [...el.stageRail.children];
  items.forEach((li) => {
    const idx = Number(li.dataset.index);
    li.classList.remove('pending', 'active', 'done', 'failed');
    if (idx < index) li.classList.add('done');
    else if (idx === index) li.classList.add(state);
    else li.classList.add('pending');
    if (li.classList.contains('done')) li.querySelector('.stage-icon').textContent = '✓';
    else li.querySelector('.stage-icon').textContent = String(idx);
  });
}

function finishStages() {
  [...el.stageRail.children].forEach((li) => {
    li.classList.remove('pending', 'active', 'failed');
    li.classList.add('done');
    li.querySelector('.stage-icon').textContent = '✓';
  });
}

function markCurrentStageFailed() {
  const active = el.stageRail.querySelector('.stage.active');
  if (active) { active.classList.remove('active'); active.classList.add('failed'); active.querySelector('.stage-icon').textContent = '×'; }
  el.pipelineStatus.textContent = 'failed';
  el.pipelineStatus.className = 'status-chip failed';
}

function tagFor(level) {
  return { ok: 'OK', info: '..', warn: 'WARN', fail: 'FAIL' }[level] || '..';
}

function logLine(level, tag, msg, extraClass = '') {
  const line = document.createElement('div');
  line.className = `log-line ${extraClass}`;
  line.innerHTML = `<span class="log-tag ${level}">${escapeHtml(tag)}</span><span class="log-msg">${escapeHtml(msg)}</span>`;
  el.console.appendChild(line);
  el.console.scrollTop = el.console.scrollHeight;
}

function logKv(key, value) {
  const line = document.createElement('div');
  line.className = 'log-line';
  line.innerHTML = `<span class="log-tag kv"></span><span class="log-msg"><span class="log-kv-key">${escapeHtml(key)}:</span> ${escapeHtml(String(value))}</span>`;
  el.console.appendChild(line);
  el.console.scrollTop = el.console.scrollHeight;
}

// ===========================================================================
// UI helpers
// ===========================================================================

function resetRunUI() {
  hide(el.errorCard);
  hide(el.resultCard);
  hide(el.verifyCard);
  hide(el.verifyResult);
  facesPayload = null;
  el.boxLayer.innerHTML = '';
  el.console.innerHTML = '';
  el.matchImg.hidden = false;
  el.matchImgFallback.hidden = true;
  el.gaugeFill.style.width = '0';
  renderStages();
  el.pipelineStatus.textContent = 'running…';
  el.pipelineStatus.className = 'status-chip running';
  el.verdictBadge.textContent = '—';
  el.verdictBadge.className = 'verdict-badge';
  el.integrityBadge.textContent = 'INTEGRITY: —';
  el.integrityBadge.className = 'integrity-badge';
}

function showError(kind, message, hint) {
  streamActive = false;
  setLive(false);
  markCurrentStageFailed();
  el.errorKind.textContent = kind || 'ERROR';
  el.errorMessage.textContent = message || 'Something went wrong.';
  if (hint) { el.errorHint.textContent = hint; el.errorHint.hidden = false; }
  else el.errorHint.hidden = true;
  show(el.errorCard);
  el.errorCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function setLive(on) { el.liveBadge.hidden = !on; }
function show(node) { node.hidden = false; }
function hide(node) { node.hidden = true; }
function clamp01(x) { return Math.max(0, Math.min(1, x)); }

function shortHash(h) {
  const s = String(h).replace(/^0x/, '');
  return s.length > 20 ? `${h.slice(0, 10)}…${h.slice(-8)}` : h;
}
function hostOf(url) { try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return 'web'; } }
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function safeJson(resp) { try { return await resp.json(); } catch { return {}; } }

// --- copy record hash -------------------------------------------------------
function copyHash() {
  const text = el.recordHash.textContent.trim();
  if (!text || text === '—') return;
  navigator.clipboard?.writeText(text).then(() => toast('Record hash copied')).catch(() => toast('Copy failed'));
}
el.hashChip.addEventListener('click', copyHash);
el.hashChip.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); copyHash(); } });

let toastTimer = null;
function toast(msg) {
  el.toast.textContent = msg;
  el.toast.hidden = false;
  requestAnimationFrame(() => el.toast.classList.add('show'));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.toast.classList.remove('show');
    setTimeout(() => { el.toast.hidden = true; }, 300);
  }, 2200);
}

// init
renderStages();

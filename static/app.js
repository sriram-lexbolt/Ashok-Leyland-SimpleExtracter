'use strict';
const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
let selectedFiles = [];
let job = null;
let selectedDocument = null;
let currentResult = null;
let currentPage = 1;
let currentTab = 'fields';
let pollTimer = null;
let pollFailures = 0;
let loadingDocument = null;
const resultCache = new Map();

function showError(message = '') {
  $('error').textContent = message;
  $('error').hidden = !message;
}
async function api(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(typeof payload.detail === 'string' ? payload.detail : `Request failed (${response.status}).`);
  }
  return response.status === 204 ? null : response.json();
}
function addFiles(files) {
  showError();
  const incoming = Array.from(files);
  if (selectedFiles.length + incoming.length > 10) return showError('Select up to 10 PDFs in one batch.');
  for (const file of incoming) {
    if (!file.name.toLowerCase().endsWith('.pdf')) return showError(`${file.name}: choose a PDF file.`);
    if (file.size > 25 * 1024 * 1024) return showError(`${file.name} exceeds the 25 MB limit.`);
  }
  if ([...selectedFiles, ...incoming].reduce((sum, f) => sum + f.size, 0) > 100 * 1024 * 1024) return showError('Select a batch smaller than 100 MB.');
  selectedFiles.push(...incoming);
  renderSelection();
}
function renderSelection() {
  $('selected-files').innerHTML = selectedFiles.map((file, index) => `<div class="file-chip"><span class="pdf-badge">PDF</span><span class="name">${escapeHtml(file.name)}</span><small>${(file.size / 1024 / 1024).toFixed(2)} MB</small><button data-remove="${index}" aria-label="Remove ${escapeHtml(file.name)}">×</button></div>`).join('');
  $('extract-button').disabled = !selectedFiles.length;
}
$('drop-zone').addEventListener('click', () => $('file-input').click());
$('drop-zone').addEventListener('keydown', event => {
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); $('file-input').click(); }
});
$('file-input').addEventListener('change', event => { addFiles(event.target.files); event.target.value = ''; });
for (const name of ['dragenter', 'dragover']) $('drop-zone').addEventListener(name, event => { event.preventDefault(); $('drop-zone').classList.add('dragging'); });
for (const name of ['dragleave', 'drop']) $('drop-zone').addEventListener(name, event => { event.preventDefault(); $('drop-zone').classList.remove('dragging'); });
$('drop-zone').addEventListener('drop', event => addFiles(event.dataTransfer.files));
document.addEventListener('dragover', event => event.preventDefault());
document.addEventListener('drop', event => event.preventDefault());
$('selected-files').addEventListener('click', event => {
  const button = event.target.closest('[data-remove]');
  if (button) { selectedFiles.splice(Number(button.dataset.remove), 1); renderSelection(); }
});
$('extract-button').addEventListener('click', async () => {
  if (!selectedFiles.length) return;
  showError();
  $('extract-button').disabled = true;
  $('extract-button').textContent = 'Uploading…';
  const form = new FormData();
  selectedFiles.forEach(file => form.append('files', file));
  try {
    job = await api('/api/jobs', {method: 'POST', body: form});
    sessionStorage.setItem('spec-extract-job', job.id);
    selectedDocument = null;
    currentResult = null;
    resultCache.clear();
    selectedFiles = [];
    renderSelection();
    await renderBatch();
    pollFailures = 0;
    schedulePoll();
  } catch (error) { showError(error.message); renderSelection(); }
  finally { $('extract-button').innerHTML = 'Extract JSON <span>↗</span>'; }
});

function schedulePoll() {
  clearTimeout(pollTimer);
  if (job && !['complete', 'failed'].includes(job.status)) pollTimer = setTimeout(poll, 700);
}
async function poll() {
  if (!job) return;
  const id = job.id;
  try {
    const updated = await api(`/api/jobs/${id}`);
    if (!job || job.id !== id) return;
    job = updated;
    pollFailures = 0;
    showError();
    await renderBatch();
    schedulePoll();
  } catch (error) {
    pollFailures++;
    showError(`${error.message} ${pollFailures < 5 ? 'Retrying connection…' : 'Reload this page to retry.'}`);
    if (pollFailures < 5) pollTimer = setTimeout(poll, 2000);
  }
}
async function renderBatch() {
  if (!job) return;
  document.body.classList.add('compact');
  $('empty-state').hidden = true;
  $('results').hidden = false;
  $('batch-nav').hidden = false;
  const done = job.documents.filter(d => d.status === 'complete');
  const failed = job.documents.filter(d => d.status === 'failed');
  const finished = ['complete', 'failed'].includes(job.status);
  $('results-title').textContent = finished ? (done.length ? 'Your data is ready.' : 'Documents need attention.') : 'Reading every detail…';
  const pages = done.reduce((sum, d) => sum + d.page_count, 0);
  const fields = done.reduce((sum, d) => sum + d.field_count, 0);
  $('results-summary').textContent = finished ? `${done.length} document${done.length === 1 ? '' : 's'} extracted · ${pages} page${pages === 1 ? '' : 's'} · ${fields.toLocaleString()} fields${failed.length ? ` · ${failed.length} failed` : ''}` : `${done.length + failed.length} of ${job.documents.length} documents processed. You can review completed files while the rest are running.`;
  $('clear-button').disabled = !finished;
  $('batch-download').classList.toggle('disabled', !finished || !done.length);
  $('batch-download').setAttribute('aria-disabled', String(!finished || !done.length));
  $('batch-download').href = `/api/jobs/${job.id}/download`;
  $('batch-progress').hidden = finished;
  const active = job.documents.find(d => d.status === 'processing');
  const fraction = job.documents.reduce((sum, d) => sum + (['complete', 'failed'].includes(d.status) ? 1 : d.page_count ? d.pages_done / d.page_count : 0), 0) / job.documents.length;
  const percent = Math.round(fraction * 100);
  $('progress-label').textContent = active ? `${active.filename} · ${active.pages_done} / ${active.page_count ?? '?'} pages` : 'Waiting in the local queue…';
  $('progress-percent').textContent = `${percent}%`;
  $('progress-bar').style.width = `${percent}%`;
  $('document-list').innerHTML = job.documents.map(d => `<button class="doc-nav ${d.id === selectedDocument ? 'selected' : ''}" data-document="${d.id}" title="${escapeHtml(d.error || d.filename)}"><span class="doc-indicator ${d.status === 'failed' ? 'failed' : ''}"></span><div><strong>${escapeHtml(d.filename)}</strong><small>${d.status === 'complete' ? `${d.page_count} pages · ${d.field_count} fields` : escapeHtml(d.status)}</small></div></button>`).join('');
  if (finished && failed.length) showError(failed.map(d => `${d.filename}: ${d.error}`).join(' '));
  if (selectedDocument === null && done.length) await selectDocument(done[0].id);
  else if (selectedDocument !== null && !currentResult && done.some(d => d.id === selectedDocument)) await selectDocument(selectedDocument);
}
$('document-list').addEventListener('click', event => {
  const button = event.target.closest('[data-document]');
  if (button) selectDocument(button.dataset.document);
});
async function selectDocument(id) {
  selectedDocument = id;
  currentResult = null;
  document.querySelectorAll('[data-document]').forEach(button => button.classList.toggle('selected', button.dataset.document === id));
  const doc = job.documents.find(d => d.id === id);
  $('review').hidden = true;
  if (doc.status === 'failed') return showError(`${doc.filename}: ${doc.error}`);
  if (doc.status !== 'complete') return;
  if (loadingDocument === id) return;
  loadingDocument = id;
  const jobId = job.id;
  try {
    const result = resultCache.get(id) || await api(`/api/jobs/${jobId}/documents/${id}`);
    if (!job || job.id !== jobId || selectedDocument !== id) return;
    resultCache.set(id, result);
    currentResult = result;
    currentPage = 1;
    $('document-name').textContent = doc.filename;
    $('document-summary').textContent = `${doc.page_count} pages · ${doc.field_count} fields · ${doc.table_count} tables${result.document.standard ? ` · ${result.document.standard}` : ''}`;
    $('field-count').textContent = doc.field_count;
    $('json-download').href = `/api/jobs/${jobId}/documents/${id}/download`;
    $('page-select').innerHTML = result.pages.map(p => `<option value="${p.page_number}">Page ${p.page_number} of ${doc.page_count}</option>`).join('');
    const warnings = result.extraction.warnings;
    const multipleValues = result.fields.some(f => f.values.length > 1);
    $('review-notes').hidden = !warnings.length && !multipleValues;
    $('review-notes').innerHTML = (multipleValues ? '<div>For multiple values, verify variant names and empty cells against the original table.</div>' : '') + (warnings.length ? `<details><summary>${warnings.length} review note${warnings.length === 1 ? '' : 's'} · Check pages with images, limited text, or unruled content.</summary><ul>${warnings.map(w => `<li>Page ${w.source_page}: ${escapeHtml(w.message)}</li>`).join('')}</ul></details>` : '');
    $('field-search').value = '';
    $('review').hidden = false;
    showPage(1);
  } catch (error) { showError(error.message); }
  finally { if (loadingDocument === id) loadingDocument = null; }
}
function showPage(page) {
  if (!currentResult) return;
  currentPage = Math.max(1, Math.min(page, currentResult.pages.length));
  $('page-select').value = String(currentPage);
  $('previous-page').disabled = currentPage === 1;
  $('next-page').disabled = currentPage === currentResult.pages.length;
  $('source-image').hidden = false;
  $('image-error').hidden = true;
  $('source-image').alt = `${currentResult.document.filename}, page ${currentPage}`;
  $('source-image').src = `/api/jobs/${job.id}/documents/${selectedDocument}/pages/${currentPage}`;
  renderData();
}
$('source-image').addEventListener('error', () => { $('source-image').hidden = true; $('image-error').hidden = false; });
$('previous-page').addEventListener('click', () => showPage(currentPage - 1));
$('next-page').addEventListener('click', () => showPage(currentPage + 1));
$('page-select').addEventListener('change', event => showPage(Number(event.target.value)));
$('field-search').addEventListener('input', renderData);
$('current-page-only').addEventListener('change', renderData);
function setTab(tab) {
  currentTab = tab;
  document.querySelectorAll('[data-tab]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.tab === tab)));
  $('data-view').setAttribute('aria-labelledby', `tab-${tab}`);
  $('field-tools').hidden = tab !== 'fields';
  renderData();
}
document.querySelectorAll('[data-tab]').forEach(button => {
  button.addEventListener('click', () => setTab(button.dataset.tab));
  button.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const tabs = Array.from(document.querySelectorAll('[data-tab]'));
    const index = (tabs.indexOf(button) + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tabs[index].focus();
    setTab(tabs[index].dataset.tab);
  });
});
function renderData() {
  if (!currentResult) return;
  const view = $('data-view');
  if (currentTab === 'json' || currentTab === 'text') {
    const pre = document.createElement('pre');
    pre.className = `code-view ${currentTab === 'text' ? 'raw-text' : ''}`;
    pre.textContent = currentTab === 'json' ? JSON.stringify(currentResult, null, 2) : currentResult.pages[currentPage - 1].raw_text || 'No selectable text on this page. OCR is required.';
    view.replaceChildren(pre);
    return;
  }
  if (currentTab === 'tables') {
    const tables = currentResult.pages[currentPage - 1].tables;
    if (!tables.length) { view.innerHTML = '<div class="no-data">No ruled table was detected on this page. Check the Text view and original page.</div>'; return; }
    view.innerHTML = `<div class="table-picker"><label for="table-select">Table</label><select id="table-select">${tables.map((t, i) => `<option value="${i}">${escapeHtml(t.id)} · ${t.row_count} rows × ${t.column_count} columns${t.role === 'footer' ? ' · footer' : ''}</option>`).join('')}</select></div><div id="raw-table-view"></div>`;
    const renderTable = index => {
      const t = tables[index];
      $('raw-table-view').innerHTML = `<div class="table-scroll"><table class="raw-table" aria-label="${escapeHtml(t.id)}">${t.rows.map((row, r) => `<tr>${t.cells.filter(c => c.row === r).map(c => `<td rowspan="${c.row_span}" colspan="${c.column_span}">${escapeHtml(c.text)}</td>`).join('')}</tr>`).join('')}</table></div><div class="table-caption">Original cell layout, including merged rows and columns. Empty cells and placeholders are preserved in the JSON.</div>`;
    };
    $('table-select').addEventListener('change', event => renderTable(Number(event.target.value)));
    renderTable(0);
    return;
  }
  const query = $('field-search').value.toLocaleLowerCase();
  const thisPage = $('current-page-only').checked;
  const fields = currentResult.fields.filter(f => (!thisPage || f.source_page === currentPage || f.values.some(v => v.source_page === currentPage)) && (!query || `${f.field_id || ''} ${f.description} ${f.values.map(v => v.text).join(' ')}`.toLocaleLowerCase().includes(query)));
  if (!fields.length) { view.innerHTML = `<div class="no-data">${currentResult.fields.length ? 'No fields match your search or page filter.' : 'No structured fields were detected. Review the original page, tables, and text.'}</div>`; return; }
  view.innerHTML = `<table class="fields-table"><thead><tr><th>FIELD ID</th><th>DESCRIPTION</th><th>VALUE</th><th>PAGE</th></tr></thead><tbody>${fields.map(f => `<tr class="${f.kind === 'section' ? 'section' : ''}"><td>${escapeHtml(f.field_id || '—')}</td><td>${escapeHtml(f.description)}${f.continuation_rows.length ? `<div class="continuation">+ ${f.continuation_rows.length} continuation row${f.continuation_rows.length === 1 ? '' : 's'} in JSON / tables</div>` : ''}</td><td>${f.values.length ? f.values.map(v => `<div class="value">${v.column_label || v.row_label ? `<span class="value-label">${escapeHtml([v.row_label, v.column_label].filter(Boolean).join(' · '))}</span>` : ''}${v.text ? escapeHtml(v.text) : '<span class="blank-value">Empty cell</span>'}</div>`).join('') : '<span class="blank-value">No value cell</span>'}</td><td><button class="field-page" data-page="${f.source_page}" aria-label="Show source page ${f.source_page}">${f.source_page}</button></td></tr>`).join('')}</tbody></table>`;
}
$('data-view').addEventListener('click', event => {
  const button = event.target.closest('[data-page]');
  if (button) showPage(Number(button.dataset.page));
});
$('clear-button').addEventListener('click', async () => {
  if (!job) return;
  $('clear-button').disabled = true;
  try { await api(`/api/jobs/${job.id}`, {method: 'DELETE'}); }
  catch (error) { showError(error.message); $('clear-button').disabled = false; return; }
  clearTimeout(pollTimer);
  sessionStorage.removeItem('spec-extract-job');
  job = null; currentResult = null; selectedDocument = null; resultCache.clear();
  $('results').hidden = true; $('review').hidden = true; $('batch-nav').hidden = true; $('empty-state').hidden = false;
  document.body.classList.remove('compact');
  showError();
  $('file-input').value = '';
  renderSelection();
});
async function restore() {
  const id = sessionStorage.getItem('spec-extract-job');
  if (!id) return;
  try { job = await api(`/api/jobs/${id}`); await renderBatch(); schedulePoll(); }
  catch { sessionStorage.removeItem('spec-extract-job'); }
}
restore();

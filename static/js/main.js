'use strict';
document.querySelectorAll('[data-print]').forEach(button => button.addEventListener('click', () => window.print()));
document.querySelectorAll('[data-back]').forEach(button => button.addEventListener('click', () => window.history.back()));
document.querySelectorAll('[data-autosubmit]').forEach(select => select.addEventListener('change', () => select.form.requestSubmit()));
document.querySelectorAll('[data-confirm-link]').forEach(link => link.addEventListener('click', event => {
  if (!window.confirm(link.dataset.confirmLink)) event.preventDefault();
}));
document.querySelectorAll('form').forEach(form => form.addEventListener('submit', event => {
  const confirmation = event.submitter?.dataset.confirmButton || form.dataset.confirm;
  if (confirmation && !window.confirm(confirmation)) { event.preventDefault(); return; }
  if (event.defaultPrevented || !form.dataset.loading) return;
  // Let all validation listeners and the browser build form data first. This also
  // preserves the clicked operation button's name/value in the POST body.
  const button = event.submitter;
  window.setTimeout(() => {
    if (event.defaultPrevented) return;
    form.setAttribute('aria-busy', 'true');
    if (button) { button.disabled = true; button.textContent = form.dataset.loading; }
  }, 0);
}));
const selection = [];
const help = document.getElementById('selection-help');
function renderSelection() {
  document.querySelectorAll('[data-seat]').forEach(button => {
    const selected = selection.includes(button.dataset.seat);
    button.classList.toggle('selected', selected); button.setAttribute('aria-pressed', String(selected));
  });
  const source = document.getElementById('source-seat'), target = document.getElementById('target-seat');
  if (!source) return;
  source.value = selection[0] || ''; target.value = selection[1] || '';
  document.getElementById('swap-seats').disabled = selection.length !== 2;
  document.getElementById('lock-seat').disabled = selection.length !== 1;
  help.textContent = selection.length ? `Selected: ${selection.join(' ↔ ')}` : 'Select one seat to lock/unlock, or two seats to swap. Select an occupied source first.';
}
document.querySelectorAll('[data-seat]:not(:disabled)').forEach(button => button.addEventListener('click', () => {
  const key = button.dataset.seat, index = selection.indexOf(key);
  if (index >= 0) selection.splice(index, 1);
  else { if (selection.length === 2) selection.shift(); selection.push(key); }
  renderSelection();
}));
document.getElementById('clear-seats')?.addEventListener('click', () => { selection.length = 0; renderSelection(); });
window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });

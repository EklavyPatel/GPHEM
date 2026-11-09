'use strict';
const field = document.getElementById('layout-data');
let layout = JSON.parse(field.value);
const grid = document.getElementById('room-grid');
function updateLayout() {
  field.value = JSON.stringify(layout);
  const physical = layout.rows * layout.columns * layout.seats_per_bench;
  const excluded = Object.values(layout.seats).filter(s => ['blocked', 'reserved'].includes(s)).length;
  document.getElementById('capacity').textContent = `${physical - excluded} available seats`;
  document.getElementById('bench-count').textContent = `${layout.rows * layout.columns} benches`;
  document.getElementById('layout-summary').textContent = `${layout.rows} rows × ${layout.columns} columns · ${layout.seats_per_bench} seat(s) per bench`;
  grid.replaceChildren();
  for (let row = 1; row <= layout.rows; row++) {
    const strip = document.createElement('div'); strip.className = 'layout-row';
    const label = document.createElement('span'); label.className = 'row-label'; label.textContent = row; strip.append(label);
    for (let column = 1; column <= layout.columns; column++) {
      const bench = document.createElement('div'); bench.className = 'editor-bench';
      for (let position = 1; position <= layout.seats_per_bench; position++) {
        const key = `${row}/${column}/${position}`, status = layout.seats[key] || 'available';
        const seat = document.createElement('button'); seat.type = 'button'; seat.className = `editor-seat ${status}`;
        seat.textContent = `${column}.${position}`;
        seat.setAttribute('aria-label', `Row ${row}, column ${column}, seat ${position}: ${status}`);
        seat.title = seat.getAttribute('aria-label');
        seat.addEventListener('click', () => {
          const state = document.getElementById('paint-mode').value;
          if (state === 'available') delete layout.seats[key]; else layout.seats[key] = state;
          updateLayout();
          grid.querySelector(`[data-key="${key}"]`)?.focus();
        });
        seat.dataset.key = key; bench.append(seat);
      }
      strip.append(bench);
    }
    grid.append(strip);
  }
}
document.getElementById('resize-room').addEventListener('click', () => {
  const values = ['rows', 'columns', 'seats_per_bench'].map(id => Number(document.getElementById(id).value));
  if (!values.every(Number.isInteger) || values.some(v => v < 1) || values[0]>50 || values[1]>50 || values[2]>6 || values.reduce((a,b)=>a*b,1)>10000) {
    window.alert('Use 1–50 rows, 1–50 columns, 1–6 seats per bench, and at most 10,000 seats.'); return;
  }
  const [rows, columns, seats_per_bench] = values;
  const removed = Object.keys(layout.seats).filter(key => { const [r,c,p]=key.split('/').map(Number); return r>rows || c>columns || p>seats_per_bench; });
  if (removed.length && !window.confirm(`Remove ${removed.length} seat state(s) outside the new dimensions?`)) return;
  removed.forEach(key => delete layout.seats[key]);
  layout = {...layout, rows, columns, seats_per_bench}; updateLayout();
});
document.getElementById('room-form').addEventListener('submit', event => {
  if (['rows','columns','seats_per_bench'].some(k => Number(document.getElementById(k).value)!==layout[k])) {
    event.preventDefault(); window.alert('Apply the changed dimensions before saving.');
  }
});
updateLayout();

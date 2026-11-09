'use strict';
const list=document.getElementById('floor-list');
list?.addEventListener('click',event=> {
  const button=event.target.closest('[data-remove-floor]');
  if(!button)return;
  if(list.children.length<=1) {window.alert('Keep at least one floor.');return;}
  if(window.confirm('Remove this floor and its rooms from this configuration? Save to apply.'))button.closest('.gtu-floor-row').remove();
});
document.getElementById('add-floor')?.addEventListener('click',()=> {
  const row=document.createElement('div');row.className='gtu-floor-row';
  const next=Math.max(0,...Array.from(list.querySelectorAll('[name="floor_order"]'),el=>Number(el.value)||0))+1;
  [['Fill order','floor_order','number',next],['Floor name','floor_name','text',''],['Rooms, comma-separated','floor_rooms','text','']].forEach(([text,name,type,value])=>{
    const group=document.createElement('div'),label=document.createElement('label'),input=document.createElement('input');
    label.textContent=text;input.name=name;input.type=type;input.value=value;input.required=true;
    if(type==='number')input.min='1';label.append(input);group.append(label);row.append(group);
  });
  const remove=document.createElement('button');remove.type='button';remove.className='button danger-ghost small';remove.dataset.removeFloor='';remove.textContent='Remove floor';row.append(remove);list.append(row);
});
const mode=document.getElementById('exam-mode');
function showShift(){document.querySelectorAll('[data-gtu-fields]').forEach(el=>{
  el.hidden=mode.value!=='gtu';el.querySelectorAll('select').forEach(input=>{input.required=mode.value==='gtu';});
});}
mode?.addEventListener('change',showShift);
if(mode)showShift();

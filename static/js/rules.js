'use strict';
const textarea = document.getElementById('rules-json');
let policy = JSON.parse(textarea.value);
const context = document.getElementById('rule-context');
const branches = JSON.parse(context.dataset.branches), roomIds = JSON.parse(context.dataset.rooms);
const list = document.getElementById('rule-list');
const input = id => document.getElementById(id).value.trim();
const lines = id => input(id).split(/\r?\n/).map(v=>v.trim()).filter(Boolean);
function render() {
  textarea.value = JSON.stringify(policy, null, 2); list.replaceChildren();
  document.getElementById('rule-count').textContent = `${policy.length} rules`;
  if (!policy.length) { const p=document.createElement('p'); p.className='muted'; p.textContent='No policy rules. Students will use the engine’s deterministic default order; physical blocks still apply.'; list.append(p); }
  policy.forEach((rule, index) => {
    const row=document.createElement('div'); row.className='rule-item';
    const content=document.createElement('div'), name=document.createElement('strong'), detail=document.createElement('small');
    name.textContent=rule.id;
    detail.textContent=`${rule.type} · ${rule.mode || rule.axis || rule.field || 'physical'} · ${Object.entries(rule.scope || {}).map(([k,v])=>`${k} ${v}`).join(', ') || 'entire examination'}`;
    const code=document.createElement('code'); code.textContent=JSON.stringify(rule);
    content.append(name,detail,code);
    const remove=document.createElement('button'); remove.type='button'; remove.className='icon-button'; remove.textContent='×';
    remove.setAttribute('aria-label',`Remove rule ${rule.id}`);
    remove.addEventListener('click',()=> { if(window.confirm(`Remove rule ${rule.id}?`)) { policy.splice(index,1); render(); } });
    row.append(content,remove); list.append(row);
  });
}
function showFields() {
  const type=input('rule-type');
  document.querySelectorAll('[data-for]').forEach(el=> { el.hidden=!el.dataset.for.split(' ').includes(type); });
}
document.getElementById('rule-type').addEventListener('change',showFields);
document.getElementById('apply-json').addEventListener('click',()=> {
  try { const value=JSON.parse(textarea.value); if(!Array.isArray(value)) throw Error('Rules must be a JSON array.'); policy=value; render(); document.getElementById('json-error').textContent=''; }
  catch(error) { document.getElementById('json-error').textContent=error.message; }
});
document.getElementById('apply-preset').addEventListener('click',()=> {
  if(policy.length && !window.confirm('Replace the current policy with this preset? Save your changes first if needed.')) return;
  const preset=document.getElementById('preset'), name=preset.value;
  const order=mode=>[{id:mode,type:'order',mode}];
  const options={sequential:order('ascending_sid'),random:order('random'),columns:[{id:'branch-columns',type:'uniform',axis:'column'}],rows:[{id:'branch-rows',type:'uniform',axis:'row'}],alternating:[{id:'branch-columns',type:'uniform',axis:'column'},{id:'neighbor-columns',type:'distinct_neighbors',axis:'column'}],batch:[{id:'batch-neighbors',type:'distinct_neighbors',axis:'bench',field:'batch'}],custom:[]};
  if(name==='mixed') {
    if(!branches.length || !roomIds.length) { window.alert('Import students and select classrooms before applying the mixed preset.'); return; }
    policy=roomIds.flatMap(id=>branches.map((branch,i)=>({id:`mixed-R${id}-${i}`,type:'quota',scope:{room:`R${id}`},value:branch,minimum:1})));
  } else if(name.startsWith('saved-')) policy=JSON.parse(preset.selectedOptions[0].dataset.rules);
  else policy=options[name];
  render();
});
document.getElementById('add-rule').addEventListener('click',()=> {
  const error=document.getElementById('builder-error'); error.textContent='';
  try {
    const type=input('rule-type'), id=input('rule-id');
    if(!id || policy.some(r=>r.id===id)) throw Error('Enter a unique rule name.');
    if(policy.length>=250) throw Error('Use at most 250 rules.');
    const scope={};
    if(input('scope-room')) scope.room=input('scope-room');
    for(const coordinate of ['row','column','position']) if(input(`scope-${coordinate}`)) { const n=Number(input(`scope-${coordinate}`)); if(!Number.isInteger(n)||n<1) throw Error('Scope coordinates must be positive integers.'); scope[coordinate]=n; }
    if(scope.position && !(scope.row && scope.column)) throw Error('Seat position requires a row and column.');
    const rule={id,type,scope,layer:input('rule-layer')};
    if(type==='order') {
      rule.mode=input('order-mode'); rule.traversal=input('order-traversal'); rule.group_by=input('order-group'); rule.priority=Number(input('order-priority'));
      if(rule.mode==='explicit') { rule.sids=lines('order-sids'); if(!rule.sids.length) throw Error('Enter at least one full SID for custom ordering.'); }
      if(rule.mode==='suffix') rule.suffixes=input('order-suffixes')?input('order-suffixes').split(',').map(Number):[];
    }
    if(['allow','cycle','uniform','distinct_neighbors','quota'].includes(type)) { rule.field=input('rule-field'); if(rule.field==='sid' && type!=='allow') throw Error('Full SID is supported only by allow rules.'); }
    if(['cycle','uniform','distinct_neighbors'].includes(type)) { rule.axis=input('rule-axis'); if((type==='cycle' && rule.axis==='bench') || (type!=='cycle' && rule.axis==='position')) throw Error('Select an axis supported by this operator.'); }
    if(['allow','cycle'].includes(type)) { rule.values=lines('rule-values'); if(!rule.values.length) throw Error('Enter at least one allowed/cycle value.'); }
    if(type==='quota') { rule.value=input('quota-value'); rule.minimum=Number(input('quota-min')); if(input('quota-max')) rule.maximum=Number(input('quota-max')); if(!rule.value) throw Error('Enter a quota branch or batch value.'); }
    policy.push(rule); render(); document.getElementById('rule-id').value='';
  } catch(exc) { error.textContent=exc.message; }
});
render();showFields();

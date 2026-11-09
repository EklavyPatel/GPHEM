'use strict';
const board=document.getElementById('arrangement-board');
const form=document.getElementById('board-edit-form');
let moving=null;
if(board?.dataset.editable==='yes' && form){
  const operation=document.getElementById('board-operation');
  const source=document.getElementById('board-source');
  const targetSelect=document.getElementById('board-target');
  function optionsForOperation(){
    if(board.dataset.mode!=='gtu')return;
    for(const [select,kind] of [[source,operation.value==='swap_rooms'?'room':'block'],[targetSelect,operation.value==='swap_blocks'?'block':'room']]){
      for(const option of select.options){option.disabled=option.dataset.kind!==kind;option.hidden=option.disabled;}
      if(!select.selectedOptions.length || select.selectedOptions[0].disabled)select.value=[...select.options].find(o=>!o.disabled)?.value||'';
    }
  }
  operation.addEventListener('change',optionsForOperation);optionsForOperation();
  function destination(event){
    if(board.dataset.mode!=='gtu'){
      const seat=event.target.closest('[data-seat]:not(:disabled)');
      return seat?{element:seat,operation:'swap',target:seat.dataset.seat}:null;
    }
    const block=event.target.closest('[data-block]');
    if(moving?.kind==='block' && block)return {element:block,operation:'swap_blocks',target:block.dataset.block};
    const room=event.target.closest('[data-room]');
    return room?{element:room,operation:moving?.kind==='block'?'move_block':'swap_rooms',target:room.dataset.room}:null;
  }
  function clearDrag(){moving=null;board.querySelectorAll('.dragging,.drop-ready').forEach(el=>el.classList.remove('dragging','drop-ready'));}
  board.addEventListener('dragstart',event=>{
    const item=event.target.closest('[data-drag-kind]');if(!item)return;
    moving={kind:item.dataset.dragKind,source:item.dataset.source};
    event.dataTransfer.effectAllowed='move';
    event.dataTransfer.setData('application/x-gtu-arrangement',JSON.stringify(moving));
    event.dataTransfer.setData('text/plain',moving.source);
    item.classList.add('dragging');
  });
  board.addEventListener('dragover',event=>{
    if(!moving)return;const target=destination(event);if(!target)return;
    event.preventDefault();event.dataTransfer.dropEffect='move';target.element.classList.add('drop-ready');
  });
  board.addEventListener('dragleave',event=>event.target.closest('.drop-ready')?.classList.remove('drop-ready'));
  board.addEventListener('dragend',clearDrag);
  board.addEventListener('drop',event=>{
    if(!moving)return;const target=destination(event);if(!target)return;
    event.preventDefault();
    if(target.operation!=='move_block' && moving.source===target.target){clearDrag();return;}
    const effect=form.dataset.approved==='yes'?' A new draft will be created; existing approved and published results stay unchanged.':'';
    if(!window.confirm(`Validate and save ${target.operation.replaceAll('_',' ')}: ${moving.source} → ${target.target}? Emergency students keep their confirmed seats.${effect}`)){clearDrag();return;}
    operation.value=target.operation;optionsForOperation();source.value=moving.source;targetSelect.value=target.target;
    document.getElementById('drag-feedback').textContent='Checking all rules on the server…';
    clearDrag();form.requestSubmit();
  });
}

// An emergency card may be placed on an approved/published board without enabling
// ordinary seat moves. The backend independently validates and commits the revision.
const admission=document.getElementById('emergency-placement-form');
if(admission && board){
  const card=document.getElementById('emergency-student-card');
  const sid=admission.elements.sid;
  const target=admission.elements.target;
  const feedback=document.getElementById('emergency-feedback');
  let draggingEmergency=false;
  let submitting=false;
  function clearHighlights(){board.querySelectorAll('.drop-ready').forEach(el=>el.classList.remove('drop-ready'));}
  function prepare(){
    if(!admission.reportValidity())return;
    document.getElementById('emergency-card-sid').textContent=sid.value;
    card.hidden=false;
    feedback.textContent='Ready. Drag the student card onto an empty seat, or select/tap an empty seat.';
  }
  function placeOn(seat){
    if(!seat || card.hidden || submitting)return;
    target.value=seat.dataset.emptySeat;
    if(!target.value)return;
    admission.requestSubmit();
  }
  document.getElementById('prepare-emergency').addEventListener('click',prepare);
  admission.addEventListener('input',()=>{
    document.getElementById('emergency-card-sid').textContent=sid.value;
    admission.elements.confirmed.value='';
  });
  document.getElementById('cancel-emergency-card').addEventListener('click',()=>{
    card.hidden=true;target.value='';draggingEmergency=false;clearHighlights();
    admission.elements.confirmed.value='';feedback.textContent='Placement cancelled. No student was saved.';
  });
  card.addEventListener('dragstart',event=>{
    if(event.target.closest('button')){event.preventDefault();return;}
    if(!admission.reportValidity()){event.preventDefault();return;}
    draggingEmergency=true;
    event.dataTransfer.effectAllowed='move';
    event.dataTransfer.setData('application/x-gtu-emergency','pending');
    event.dataTransfer.setData('text/plain',sid.value);
  });
  card.addEventListener('dragend',()=>{draggingEmergency=false;clearHighlights();});
  board.addEventListener('dragover',event=>{
    if(!draggingEmergency)return;
    const seat=event.target.closest('[data-empty-seat]');
    if(seat){event.preventDefault();event.dataTransfer.dropEffect='move';seat.classList.add('drop-ready');}
  });
  board.addEventListener('drop',event=>{
    if(!draggingEmergency)return;
    event.preventDefault();event.stopImmediatePropagation();
    const seat=event.target.closest('[data-empty-seat]');
    draggingEmergency=false;clearHighlights();placeOn(seat);
  },true);
  board.addEventListener('click',event=>{
    const seat=event.target.closest('[data-empty-seat]');
    if(seat && !card.hidden){event.preventDefault();placeOn(seat);}
  });
  board.addEventListener('keydown',event=>{
    if((event.key==='Enter'||event.key===' ') && event.target.matches('[data-empty-seat]:not(button)') && !card.hidden){event.preventDefault();placeOn(event.target);}
  });
  admission.addEventListener('submit',event=>{
    if(submitting){event.preventDefault();return;}
    if(!target.value){event.preventDefault();feedback.textContent='Choose an empty seat before confirming.';target.focus();return;}
    const effect=admission.dataset.stage==='published'?'Update the approved arrangement and its student publication, keeping the existing release time.':admission.dataset.stage==='approved'?'Update the approved arrangement. Student publication settings stay unchanged.':'Save this placement to the draft. Approval and publication remain separate.';
    if(!window.confirm(`Add student ${sid.value} to empty seat ${target.value}?\n${effect}\nExisting students keep their seats. Capacity, availability, identity and the emergency policy shown on the form will be checked.`)){
      event.preventDefault();admission.elements.confirmed.value='';feedback.textContent='Placement cancelled. No student was saved.';return;
    }
    admission.elements.confirmed.value='yes';submitting=true;
    feedback.textContent='Checking the selected seat and saving the confirmed revision…';
  });
}

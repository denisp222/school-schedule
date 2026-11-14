'use strict';
function renderBaseOverview() {
  const day=Number(S.baseWeekday??0),kind=S.baseKind||'classes',field={classes:'classIds',teachers:'teacherIds',rooms:'roomIds'}[kind];
  const date=addDays(mondayOf(S.date),day),lessons=S.data.baseLessons.filter(l=>Number(l.day)===day);
  const editable=S.workspace==='draft',query=(S.baseQuery||'').toLocaleLowerCase('ru');
  const rows=S.data[kind].filter(r=>!r.archived && r.name.toLocaleLowerCase('ru').includes(query));
  return `<div class="page base-overview">${pageHead('','Базовая неделя',editable?'Двойной щелчок: изменить урок. Перетаскивание: перенести или обменять.':'Постоянная неделя школы. Для изменений откройте редактор.',`${editable?'':button('Редактировать неделю','base-edit','primary')}${button('По одному классу или учителю','base-individual','ghost')}`)}
  <div class="toolbar"><div class="segmented">${DAYS.map((d,i)=>`<button data-action="base-day" data-day="${i}" class="${day===i?'active':''}">${esc(d)}</button>`).join('')}</div></div>
  <div class="filter-bar"><div class="segmented">${[['classes','Классы'],['teachers','Учителя'],['rooms','Кабинеты']].map(([k,n])=>`<button data-action="base-kind" data-kind="${k}" class="${kind===k?'active':''}">${n}</button>`).join('')}</div><input class="input" id="base-query" aria-label="Поиск в общей таблице" placeholder="Найти…" value="${esc(S.baseQuery||'')}"></div>
  <div class="table-card"><div class="table-scroll"><table class="base-table"><thead><tr><th>${{classes:'Класс',teachers:'Учитель',rooms:'Кабинет'}[kind]}</th>${S.data.school.bells.map((b,i)=>`<th>${i+1}<small>${esc(b)}</small></th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr><th><button class="text-btn" data-action="base-row" data-id="${esc(r.id)}" data-kind="${kind}">${esc(r.name)}</button></th>${S.data.school.bells.map((b,i)=>{
    const list=lessons.filter(l=>l[field].includes(r.id)&&Number(l.period)===i+1);
    return `<td><button class="week-edit" ${editable?'data-week-edit="1"':''} data-scope="base" data-date="${date}" data-period="${i+1}" data-row-kind="${kind}" data-row="${esc(r.id)}" data-lesson="${esc(list[0]?.id||'')}" draggable="${editable&&list.length?'true':'false'}" aria-label="${esc(r.name)}, урок ${i+1}">${list.map(l=>`<div class="week-subject">${esc(kind==='classes'?subjectShort(l.subjectId):namesOf('classes',l.classIds)+' · '+subjectShort(l.subjectId))}</div><div class="week-meta">${esc(kind==='teachers'?namesOf('rooms',l.roomIds):namesOf('teachers',l.teacherIds)+(kind==='rooms'?'':' · '+namesOf('rooms',l.roomIds)))}</div>`).join('<hr>')||'<span class="week-empty">—</span>'}</button></td>`;
  }).join('')}</tr>`).join('')}</tbody></table></div></div>${editable?renderLoadLocator(kind==='rooms'?'classes':kind,''):''}</div>`;
}

async function showSchoolAdvisor() {
  const editable=S.workspace==='draft';
  openSheet({title:'Помощь с учебным планом',sub:'Проверка и предложения перед изменением базовой недели',body:`<p>Можно попросить объяснить ошибки или изменить часы существующих строк плана. Помощник получает учебный план и результаты проверки, без истории диалогов и полной сетки уроков.</p><label class="field"><span>Задача</span><textarea class="input" name="message" rows="4" required maxlength="2000">Проверь учебный план, объясни проблемы и что нужно исправить.</textarea></label><p class="muted">Для изменения плана сначала откройте редактор базовой недели. Предложения применяются только в черновике.</p>`,foot:button('Закрыть','close-sheet','ghost')+'<button class="btn primary" type="submit">Спросить помощника</button>',submit:async form=>{
    const submit=form.querySelector('[type="submit"]');submit.disabled=true;submit.textContent='Проверяем…';
    try{
      const r=await api('/annual/advice',{revision:S.revision,workspace:S.workspace||'live',message:new FormData(form).get('message')});S.planAdvice=r;
      openSheet({title:'Предложение помощника',body:`<p class="advisor-reply">${esc(r.reply)}</p>${r.changes.length?`<table class="data"><thead><tr><th>Строка плана</th><th>Было</th><th>Будет</th></tr></thead><tbody>${r.changes.map(c=>{const p=S.data.plan.find(p=>p.id===c.planId);return `<tr><td>${esc(namesOf('classes',p.classIds)+' · '+subjectName(p.subjectId)+' · '+namesOf('teachers',p.teacherIds))}</td><td>${c.before}</td><td>${c.hours}</td></tr>`;}).join('')}</tbody></table>`:''}`,foot:button('Закрыть','close-sheet','ghost')+(editable&&r.changes.length?button('Применить в черновике','advisor-apply','primary'):'')});
    }catch(e){submit.disabled=false;submit.textContent='Спросить помощника';throw e;}
  }});
}

document.addEventListener('click',async e=>{
  const n=e.target.closest('[data-action]');if(!n)return;
  try {
    const a=n.dataset.action;
    if(a==='base-overview'){S.weekOverview=true;render();}
    if(a==='base-individual'){S.weekOverview=false;render();}
    if(a==='base-edit'){if(S.workspace!=='draft')await openAnnualDraft();S.weekOverview=true;S.page='week';render();}
    if(a==='base-day'){S.baseWeekday=Number(n.dataset.day);render();}
    if(a==='base-kind'){S.baseKind=n.dataset.kind;render();}
    if(a==='base-row'){S.weekKind=n.dataset.kind==='rooms'?'teachers':n.dataset.kind;S.weekId=n.dataset.kind==='rooms'?'':n.dataset.id;S.weekOverview=false;render();}
    if(a==='absence-reset'){S.absenceTeacher='';S.absenceFrom='';S.absenceTo='';render();}
    if(a==='chat-toggle'){S.chatHidden=!S.chatHidden;render();}
    if(a==='school-advisor')await showSchoolAdvisor();
    if(a==='advisor-apply'){
      const r=await api('/annual/advice/apply',{revision:S.planAdvice.revision,previewId:S.planAdvice.previewId});S.data=r.state;S.revision=r.revision;closeSheet();S.page='plan';render();toast('Предложение сохранено в черновике. Проверьте расстановку уроков.');
    }
    if(a==='draft-undo'||a==='draft-redo'){
      const r=await api('/annual/history',{revision:S.revision,direction:a==='draft-undo'?'undo':'redo'});S.data=r.state;S.revision=r.revision;await loadDay();render();
    }
  }catch(error){toast(error.message,'error');}
});
document.addEventListener('change',e=>{const key=e.target.dataset.absenceFilter;if(key){S[key]=e.target.value;render();}});
document.addEventListener('input',e=>{
  if(e.target.id==='base-query'){const pos=e.target.selectionStart;S.baseQuery=e.target.value;render();const field=document.querySelector('#base-query');field.focus();field.setSelectionRange(pos,pos);}
});

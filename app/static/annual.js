'use strict';

function annualDraftBanner() {
  return `<div class="annual-draft-bar"><div><strong>Черновик базового расписания</strong><small>Рабочее расписание не меняется. Черновик сохраняется автоматически.</small></div><div class="assistant-actions">${button('Проверить и ввести с даты','annual-review','primary')}${button('Закрыть черновик','annual-close','ghost')}</div></div>`;
}

async function ensureAnnualStatus() {
  if(S.annualLoading)return;S.annualLoading=true;
  try{S.annual=await api('/annual/status');}catch(error){toast(error.message,'error');}
  finally{S.annualLoading=false;if(S.page==='annual')render();}
}

function renderAnnual() {
  if(!S.annual)ensureAnnualStatus();
  const status=S.annual;
  return `<div class="page narrow">${pageHead('Подготовка','Базовое расписание','Учебный план и постоянная неделя. Изменения вводятся с выбранной даты.')}
    <section class="annual-start"><h2>${status?.hasDraft?'Подготовка уже начата':'Подготовить новое расписание'}</h2><p>Измените часы, классы, преподавателей и уроки в отдельном черновике. Затем составьте неделю автоматически или расставьте её вручную.</p><div class="assistant-actions">${button(status?.hasDraft?'Продолжить черновик':'Создать черновик','annual-open','primary','grid')}${status?.hasDraft?button('Удалить черновик','annual-discard','ghost'):''}</div></section>
    ${S.workspace==='draft'?`<section class="annual-start"><h2>Редактор</h2><div class="assistant-actions"><button class="btn" data-action="nav" data-page="plan">Учебный план</button><button class="btn" data-action="nav" data-page="week">Расставить уроки вручную</button>${button('Составить неделю автоматически','build-week','ghost','spark')}${button('Очистить сетку','annual-clear','ghost')}</div></section>`:''}
    <section class="annual-start"><h2>Действующие редакции</h2>${status?.versions?.length?status.versions.map(v=>`<p>С ${fmtDate(v.start)}</p>`).join(''):'<p class="muted">Сейчас используется исходная базовая неделя.</p>'}</section></div>`;
}

async function openAnnualDraft() {
  const result=await api('/annual/start',{revision:S.revision});
  S.workspace='draft';S.weekActual=false;S.data=result.state;S.revision=result.revision;S.annual=null;S.report=null;
  S.page='annual';history.replaceState(null,'','#annual');await loadDay();render();
}

async function closeAnnualDraft() {
  S.workspace='live';S.annual=null;S.page='annual';await loadState();await loadDay();render();
}

async function reviewAnnualDraft() {
  const result=await api('/annual/review');const errors=result.issues.filter(i=>i.level==='error');
  const incomplete=result.report.missing.length+result.report.extra.length;
  const next=addDays(mondayOf(S.today),7);
  openSheet({title:'Ввести базовое расписание',sub:'Предыдущие даты сохранят прежнюю неделю',body:`<div class="form-grid">${errors.length?notice(esc(`Нужно исправить ошибок: ${errors.length}. ${errors[0].message}`),'warn'):notice('Пересечений и запрещённых уроков нет.','success')}
    <label class="field"><span>Действует с даты</span><input class="input" type="date" name="start" value="${next}" required></label>
    <label class="check"><input type="checkbox" name="keepDays" checked>Сохранить уже подготовленные изменения на конкретные даты</label>
    ${incomplete?`<p>Часов не по плану: строк ${incomplete}. Проверьте распределение в учебном плане.</p><label class="check"><input type="checkbox" name="acceptIncomplete">Подтверждаю ввод с этими отклонениями учебного плана</label>`:''}
    <p class="muted">До выбранной даты останется прежнее расписание. Полная прежняя версия сохранится в истории.</p></div>`,foot:`${button('Вернуться к редактированию','close-sheet','ghost')}<button class="btn primary" type="submit" ${errors.length?'disabled':''}>Ввести расписание</button>`,submit:async form=>{
      const data=new FormData(form);const saved=await api('/annual/publish',{revision:S.revision,start:data.get('start'),keepDays:data.has('keepDays'),acceptIncomplete:data.has('acceptIncomplete')});
      S.workspace='live';S.data=saved.state;S.revision=saved.revision;S.annual=null;S.date=data.get('start');S.page='day';
      closeSheet();await loadDay();render();toast('Новое базовое расписание введено с выбранной даты.');
    }});
}

document.addEventListener('click',async event=>{
  const n=event.target.closest('[data-action^="annual-"]');if(!n)return;
  try {
    if(n.dataset.action==='annual-open')await openAnnualDraft();
    if(n.dataset.action==='annual-close')await closeAnnualDraft();
    if(n.dataset.action==='annual-review')await reviewAnnualDraft();
    if(n.dataset.action==='annual-discard') {
      if(!await askConfirm({title:'Удалить черновик?',text:'Рабочее расписание останется прежним.',yes:'Удалить черновик'}))return;
      await api('/annual/discard',{revision:S.revision});await closeAnnualDraft();
    }
    if(n.dataset.action==='annual-clear') {
      if(!await askConfirm({title:'Очистить сетку черновика?',text:'Учебный план и рабочее расписание останутся. Можно заново расставить уроки вручную или автоматически.',yes:'Очистить сетку'}))return;
      const r=await api('/annual/clear',{revision:S.revision});S.data=r.state;S.revision=r.revision;await loadDay();render();
    }
  }catch(error){toast(error.message,'error');}
});

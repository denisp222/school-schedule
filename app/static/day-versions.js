'use strict';

function dayVersionTime(value) {
  return new Date(value).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
}

async function openDayVersions() {
  const date=S.date;
  const current=await api(`/day/${date}/versions`);
  if(S.date!==date)return;
  const versions=current.versions.map(row=>`<li class="day-version-row">
    <div class="day-version-label"><strong>${esc(row.title)}</strong>
      <small>${row.active?'Текущий вариант':esc(dayVersionTime(row.created))}</small></div>
    <div class="day-version-actions">
      ${row.active?'':button('Посмотреть','day-version-preview','small','',`data-id="${esc(row.id)}"`)}
      ${button('Удалить','day-version-delete','small ghost','',`data-id="${esc(row.id)}" aria-label="Удалить ${esc(row.title)}"`)}
    </div>
  </li>`).join('');
  openSheet({
    title:'Варианты дня',
    sub:fmtLongCap(date),
    body:`<label class="field"><span>Название текущего варианта</span><input class="input" name="title" maxlength="100" required placeholder="Например, обычный день" value="Текущий вариант"></label>
      ${versions?`<h3 class="day-version-heading">Сохранённые варианты</h3><ul class="day-version-list">${versions}</ul>`:'<p class="day-version-empty">Сохраните текущее расписание, чтобы к нему можно было вернуться.</p>'}`,
    foot:`${button('Закрыть','close-sheet','ghost')}<button type="submit" class="btn primary">Сохранить текущее</button>`,
    submit:async form=>{
      const result=await api(`/day/${date}/versions/save`,{revision:current.revision,title:new FormData(form).get('title')});
      S.data=result.state;S.revision=result.revision;S.day=result.day;
      render();await openDayVersions();toast('Текущий вариант сохранён.');
    },
  });
}

function openSavePreviewVersion() {
  const preview=S.preview;
  const selected=previewSelected();
  openSheet({
    title:'Сохранить запасной вариант',
    sub:fmtLongCap(preview.date),
    body:'<label class="field"><span>Название варианта</span><input class="input" name="title" maxlength="100" required value="Запасной вариант"></label>',
    foot:`${button('Отмена','close-sheet','ghost')}<button type="submit" class="btn primary">Сохранить запасной</button>`,
    submit:async form=>{
      const result=await api(`/day/${preview.date}/versions/save`,{
        revision:preview.revision,title:new FormData(form).get('title'),previewId:selected.previewId,
        channel:preview.kind==='repair'?'repair':'assistant',
      });
      S.data=result.state;S.revision=result.revision;S.day=result.day;
      S.preview=null;S.ai.preview=null;S.repairResult=null;
      closeSheet();render();toast('Запасной вариант сохранён.');
    },
  });
}

document.addEventListener('click',async event=>{
  const action=event.target.closest('[data-action^="day-version"]');
  if(!action)return;
  const date=S.date;
  try {
    if(action.dataset.action==='day-versions'){await openDayVersions();return;}
    if(action.dataset.action==='day-version-preview'){
      const result=await api(`/day/${date}/versions/preview`,{revision:S.revision,id:action.dataset.id});
      await showSchedulePreview('saved-day',date,result.variants,0,result.revision,S.view);
      return;
    }
    if(action.dataset.action==='day-version-delete'){
      const confirmed=await askConfirm({title:'Удалить сохранённый вариант?',text:'Запись исчезнет из списка вариантов дня.',yes:'Удалить вариант',danger:true});
      if(!confirmed)return;
      const result=await api(`/day/${date}/versions/delete`,{revision:S.revision,id:action.dataset.id});
      S.data=result.state;S.revision=result.revision;
      render();await openDayVersions();toast('Вариант удалён.');
    }
  } catch(error) {
    if($('#sheet').open)sheetError(error.message);
    else toast(error.message,'error');
  }
});

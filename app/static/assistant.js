'use strict';

S.ai = { status: null, loading: false, date: '', messages: [], text: '', response: null,
  preview:null,selected:0,pending:'',error:'',connectionMessage:'',connectionError:'',providerChoice:'',
  threadId:null,history:null,historyOpen:false,historyLoading:false };

function assistantProvider() { return S.ai.providerChoice || S.ai.status?.provider || 'openrouter'; }

async function ensureAssistantStatus() {
  const a = S.ai;
  if (a.loading || a.status) return;
  a.loading = true;
  try {
    a.status=await api('/assistant/settings');
    if(!a.draftRestored) {
      a.draftRestored=true;
      try {const draft=JSON.parse(localStorage.getItem('assistant-draft') || 'null');if(draft?.date && draft?.text && !isWeekend(draft.date)) {a.date=draft.date;a.text=draft.text;}}catch(error){}
    }
  }
  catch (error) { a.status = { configured: false }; a.connectionError = error.message; }
  finally { a.loading = false; if (['assistant', 'settings'].includes(S.page)) render(); }
}

function renderAssistantSettings() {
  const a=S.ai;
  if(!a.status) {ensureAssistantStatus();return '<p class="assistant-note">Загружаем настройки…</p>';}
  const provider=assistantProvider(),direct=provider==='deepseek',name=direct?'DeepSeek':'OpenRouter';
  const active=provider===(a.status.provider || 'openrouter'),configured=active?a.status.configured:!!a.status.connections?.[provider];
  const model=direct?'deepseek-flash':(a.status.openrouterModel || a.status.model || 'openrouter/free');
  const disabled=!active || !configured || a.pending;
  return `<section class="assistant-settings" aria-labelledby="assistant-settings-title">
    <h2 id="assistant-settings-title">AI-помощник</h2>
    <form id="assistant-settings-form">
      <label class="field"><span>Ключ ${name}${configured?' (сохранён)':''}</span><input class="input" type="password" name="routerApiKey" autocomplete="off" spellcheck="false" maxlength="512" placeholder="${configured?'Введите новый ключ для замены':direct?'sk-…':'sk-or-…'}"></label>
      <div class="assistant-actions"><button class="btn primary" type="submit" ${a.pending?'disabled':''}>Сохранить</button><button class="btn" type="button" data-action="assistant-check" ${disabled?'disabled':''}>Проверить подключение</button><button class="btn ghost" type="button" data-action="assistant-balance" ${disabled?'disabled':''}>Баланс и расходы</button></div>
      ${a.showSpending?`<section class="assistant-finance"><h3>Баланс и расходы</h3><p>${esc(a.balanceText || '')}</p><p>Учтено за месяц: $${Number(a.status.budget?.spentUSD || 0).toFixed(3)}</p><label class="field assistant-budget"><span>Лимит в месяц, $</span><input class="input" name="routerBudget" type="number" min="0.01" max="100" step="0.01" value="${esc(a.status.budget?.limitUSD || '1')}"></label><button type="button" class="text-btn" data-action="assistant-hide-spending">Скрыть расходы</button></section>`:`<input type="hidden" name="routerBudget" value="${esc(a.status.budget?.limitUSD || '1')}">`}
      <div class="assistant-links">${button('Создать ключ','assistant-open-keys','ghost')}${button('Пополнить баланс','assistant-open-balance','ghost')}</div>
      <details class="assistant-advanced" ${!active?'open':''}><summary>Дополнительно</summary>
        <label class="field"><span>Сервис</span><select class="input" id="assistant-provider" name="provider" ${a.pending?'disabled':''}><option value="deepseek" ${direct?'selected':''}>DeepSeek</option><option value="openrouter" ${!direct?'selected':''}>OpenRouter</option></select></label>
        ${direct?'<input type="hidden" name="routerModel" value="deepseek-flash">':`<label class="field"><span>Модель</span><select class="input" name="routerModel">${[['deepseek/deepseek-v4.1-flash-1017','DeepSeek'],['nvidia/nemotron-3.5-super-vl:free','NVIDIA (бесплатно)'],['openrouter/free','Автовыбор (бесплатно)'],...(!['deepseek/deepseek-v4.1-flash-1017','nvidia/nemotron-3.5-super-vl:free','openrouter/free'].includes(model)?[[model,model]]:[])].map(([id,label])=>`<option value="${esc(id)}" ${id===model?'selected':''}>${esc(label)}</option>`).join('')}</select></label>`}
        <p class="assistant-note">Запросы с расписанием отправляются в ${name}. Лимит расходов действует на этом компьютере.</p>
        <div class="assistant-actions"><button class="btn ghost" type="button" data-action="assistant-probe" ${disabled?'disabled':''}>Проверить модель</button>${active && configured?button('Удалить ключ','assistant-remove-key','ghost'):''}</div>
      </details>
    </form>
    ${a.connectionMessage?`<p role="status" class="assistant-note assistant-status">${esc(a.connectionMessage)}</p>`:''}
    ${a.connectionError?`<div role="alert">${notice(a.connectionError,'error')}</div>`:''}
  </section>`;
}

function assistantSelected() {
  return S.ai.preview?.variants?.find(v => v.id === S.ai.selected);
}

function assistantConditionLabel(row) {
  if(row.type==='class_hour')return `${nameOf('classes',row.classId)}: Кл/ч ${row.period||1}-м уроком у классного руководителя`;
  if(row.type==='allow_class_gaps')return 'Резервный вариант: окна у учеников показаны для проверки';
  if(row.type==='join_technology')return `Совместная технология, ${row.period}-й урок: ${nameOf('teachers',row.teacherId)}`;
  if(row.type==='allow_technology')return `Разрешены исключения для технологии у ${nameOf('teachers',row.teacherId)}`;
  if(row.type==='group_day')return `${nameOf('classes',row.classId)}, ${subgroupName(row.classId,row.groupIndex)}: начало ${row.first}-м уроком, окончание не позже ${row.last}-го`;
  if(row.type==='join_lessons') return `Совместный урок ${row.period}: ${nameOf('teachers',row.teacherId)}`;
  if(row.type==='allow_eighth') return 'Разрешён восьмой урок для указанного занятия на эту дату';
  if (row.type === 'teacher_absence') return `${nameOf('teachers', row.teacherId)}: отсутствие, уроки ${row.first}–${row.last}`;
  if (row.type === 'class_day') return `${nameOf('classes', row.classId)}: начало ${row.first}-м уроком, окончание не позже ${row.last}-го`;
  if (row.type === 'room_unavailable') return `Кабинет ${nameOf('rooms', row.roomId)} недоступен, уроки ${row.first}–${row.last}`;
  const lesson = [...lessonsFor(S.ai.date), ...S.data.baseLessons, ...(S.data.dayBases[S.ai.date] || [])].find(l => l.id === row.lessonId);
  return `${lesson ? describe(lesson) : 'Занятие'}: ${row.type === 'pin_lesson' ? `закрепить ${row.period}-м уроком` : 'отменить'}`;
}

function assistantPreview() {
  const a=S.ai;if(!a.preview)return '';
  if(!a.preview.variants?.length)return notice(a.preview.message,'warn');
  return `<div class="assistant-actions">${button('Посмотреть варианты в расписании','assistant-show-preview','primary')}</div>`;
}

function renderAssistant() {
  const a = S.ai;
  if (!a.date) a.date = S.date;
  if (!a.status) { ensureAssistantStatus(); return `<div class="page">${pageHead('', 'AI-помощник', 'Загружаем подключение…')}</div>`; }
  const ready = a.status.configured;
  const response = a.response;
  const currentConditions = S.data.assistantConditions?.[a.date] || [];
  return `<div class="page assistant-page">
    ${pageHead('', 'AI-помощник', 'Что изменить в расписании?', button('Настройки', 'assistant-settings', 'ghost', 'settings'))}
    <div class="assistant-layout">${assistantHistoryList()}<div class="assistant-workspace">
      <label class="field assistant-date"><span>День изменений</span><input class="input" id="assistant-date" type="date" value="${esc(a.date)}" ${a.pending ? 'disabled' : ''}></label>
      ${!ready ? notice(`Для начала добавьте ключ ${a.status.providerName || 'OpenRouter'} в настройках помощника.`) : ''}
      ${currentConditions.length ? `<div class="assistant-existing"><p>Сохранённые условия этого дня учитываются и при обычном подборе.</p><ul>${currentConditions.map(row => `<li>${esc(assistantConditionLabel(row))}</li>`).join('')}</ul>${button('Снять условия дня', 'assistant-clear-conditions', 'ghost')}</div>` : ''}
      <div class="assistant-conversation" aria-label="Диалог с помощником">
        ${a.messages.map(m => `<article class="assistant-message ${m.role === 'user' ? 'from-user' : ''}"><strong>${m.role === 'user' ? 'Вы' : 'AI-помощник'}</strong><p>${esc(m.text || m.content)}</p></article>`).join('')}
      </div>
      ${response ? `<section class="assistant-understood" aria-labelledby="assistant-understood-title">
        <h2 id="assistant-understood-title">${response.questions.length || response.unsupported.length?'Нужно уточнить':'Проверьте условия'}</h2>
        ${response.questions.map(s => notice(s, 'warn')).join('')}
        ${response.unsupported.map(s => notice('Пока не поддерживается: ' + s, 'warn')).join('')}
        ${response.labels.length ? `<details ${response.labels.length<6?'open':''}><summary>Условия: ${response.labels.length}</summary><ul>${response.labels.map(s => `<li>${esc(s)}</li>`).join('')}</ul></details>` : ''}
        ${response.draftId && !a.preview ? `<button class="btn primary" type="button" data-action="assistant-preview" ${a.pending ? 'disabled' : ''}>Условия верны, подобрать варианты</button>` : ''}
      </section>` : ''}
      ${assistantPreview()}
      <form id="assistant-request-form" class="assistant-composer">
        <label class="field"><span class="sr-only">${a.messages.length ? 'Уточнение или исправление условий' : 'Ваше сообщение'}</span>
          <textarea class="input assistant-input" id="assistant-message" name="message" rows="4" maxlength="4000" placeholder="Например: учитель отсутствует на втором уроке. Укажите фамилию и класс, для которого нужно изменить расписание." ${a.pending ? 'disabled' : ''}>${esc(a.text)}</textarea>
        </label>
        ${voiceControls()}
      </form>
      ${voice.error ? `<div role="alert" class="voice-error">${notice(voice.error,voice.warning?'warn':'error')}</div>` : ''}
      <div class="assistant-note assistant-request-status" role="status" aria-live="polite">${esc(a.pending || '')}</div>
      ${a.error ? `<div role="alert">${notice(a.error, 'error')}</div>` : ''}
      <details class="assistant-capabilities"><summary>Что помощник умеет сейчас</summary>
        <p>Отсутствие учителя на весь день или отдельные уроки, точное время начала и предельное время окончания занятий класса, закрепление существующего урока, закрытие кабинета, явная отмена урока.</p>
        <p>Спаренные уроки идут подряд у каждой подгруппы. «Разговоры о важном» — только первым уроком понедельника, в том числе совместные. Если класс приходит ко второму, этот урок можно отменить.</p>
        <p>Совместный урок двух классов у одного из их преподавателей. Для технологии можно отдельно согласовать объединение подгрупп и время их прихода. У каждой подгруппы занятия идут без окон; окна учителей допускаются. Восьмой урок только по явному разрешению на выбранную дату.</p>
        <p>Микрофон рядом с отправкой записывает голос. Речь распознаётся на компьютере, затем выбранный AI-сервис оформляет текст. Перед отправкой сообщения его можно проверить и исправить.</p>
      </details>
    </div></div>
  </div>`;
}

function assistantReset() {
  if(typeof stopVoiceCapture==='function' && isVoiceBusy())stopVoiceCapture(false);
  Object.assign(S.ai,{messages:[],text:'',response:null,preview:null,selected:0,error:'',threadId:null});
  localStorage.removeItem('assistant-draft');
}

async function assistantWork(message, callback, connection = false) {
  const a = S.ai;
  if (a.pending) return;
  a.pending = message; a.error = ''; a.connectionError = ''; a.connectionMessage = '';
  render();
  try { await callback(); }
  catch(error) {if(connection)a.connectionError=error.message;else {a.error=error.message;if(S.page==='day')toast(error.message,'error');}}
  finally {
    a.pending='';a.history=null;
    if(['assistant','settings','day'].includes(S.page))render();
    if(S.page==='assistant' && a.response && !connection)requestAnimationFrame(()=>$('.assistant-understood')?.scrollIntoView({block:'nearest'}));
  }
}

async function sendAssistant(form) {
  if(isVoiceBusy()) {toast('Сначала остановите запись.');return;}
  const a = S.ai;
  const message = String(new FormData(form).get('message') || '').trim();
  if (!message) { a.error = 'Напишите, что нужно изменить.'; render(); return; }
  await assistantWork('Помощник разбирает просьбу. Расписание пока не меняется…', async () => {
    const result=await api('/assistant/interpret',{revision:S.revision,date:a.date,message,threadId:a.threadId,
      history:a.messages.filter(m=>!m.error && !m.notice).slice(-10).map(({role,content})=>({role,content}))});
    a.threadId=result.threadId;
    a.messages.push({role: 'user', content: message});
    const content = JSON.stringify({ date: result.date, reply: result.reply, actions: result.actions,
      questions: result.questions, unsupported: result.unsupported });
    a.messages.push({role: 'assistant', content, text: result.reply});
    a.text = ''; a.response = result; a.preview = null;
    if(typeof voice!=='undefined') {voice.error='';voice.warning=false;}
    localStorage.removeItem('assistant-draft');
    a.status = await api('/assistant/settings');
  });
}

document.addEventListener('input',e=>{if(e.target.id==='assistant-message') {
  S.ai.text=e.target.value;
  localStorage.setItem('assistant-draft',JSON.stringify({date:S.ai.date,text:S.ai.text}));
}});

async function ensureAssistantHistory() {
  const a=S.ai;if(a.historyLoading || a.history)return;
  a.historyLoading=true;
  try { const result=await api('/assistant/conversations');a.history=result.conversations;a.historyMore=result.hasMore; }
  catch(error) { a.error=error.message; a.history=[]; }
  finally { a.historyLoading=false; if(S.page==='assistant')render(); }
}

function assistantHistoryList() {
  const a=S.ai;
  if(!a.history)ensureAssistantHistory();
  const groups=new Map();for(const row of a.history||[]) {if(!groups.has(row.date))groups.set(row.date,[]);groups.get(row.date).push(row);}
  const rows=[...groups.entries()].sort(([a],[b])=>b.localeCompare(a)).map(([date,items])=>`<section aria-label="Диалоги на ${fmtDate(date)}"><h3 class="conversation-date">${fmtDate(date)}</h3>${items.map(row=>`<div class="conversation-entry"><button class="assistant-history-row ${row.id===a.threadId?'active':''}" data-action="assistant-open-thread" data-id="${esc(row.id)}" aria-current="${row.id===a.threadId?'true':'false'}"><span title="${esc(row.title)}">${esc(row.title)}</span></button><button class="conversation-delete" data-action="assistant-delete-thread" data-id="${esc(row.id)}" aria-label="Удалить диалог: ${esc(row.title)}" title="Удалить диалог">${icon('trash',14)}</button></div>`).join('')}</section>`).join('');
  return `<aside class="conversation-sidebar" aria-label="Диалоги"><div class="conversation-heading"><h2>Диалоги</h2>${button('Новый диалог','assistant-new','ghost','plus')}</div><div class="conversation-list">${!a.history?'<p class="assistant-note">Загружаем диалоги…</p>':rows||'<p class="assistant-note">Здесь появятся ваши диалоги.</p>'}${a.historyMore?button('Показать ещё','assistant-more-history','ghost'):''}</div></aside>`;
}

async function openAssistantThread(id) {
  const a=S.ai;const thread=await api('/assistant/conversations/'+encodeURIComponent(id));
  assistantReset();a.threadId=thread.id;a.date=thread.date;a.historyOpen=false;
  for(const turn of thread.turns) {
    a.messages.push({role:'user',content:turn.request});
    if(turn.response) {const r=turn.response;a.messages.push({role:'assistant',content:JSON.stringify({date:r.date,reply:r.reply,actions:r.actions,questions:r.questions,unsupported:r.unsupported}),text:r.reply+(turn.status==='applied'?'\nВариант сохранён.':'')});}
    else a.messages.push({role:'assistant',content:turn.error || 'Запрос не завершён.',error:true,text:turn.error || 'Запрос не завершён.'});
  }
  render();
}

function previewSelected() {
  const p=S.preview;
  return p?.variants.find(v=>v.id===p.selected) || p?.variants[0];
}

function previewDay() {
  const v=previewSelected();if(!v)return S.day;
  return v.day || {...S.day,lessons:v.after,base:S.day.lessons,changes:v.changes,issues:[],stats:{...S.day.stats,lessons:v.after.length,errors:0,gaps:0}};
}

async function applyAssistantVariant() {
  const technology=['technology','class-hour'].includes(S.preview?.kind), date=S.preview?.date || S.ai.date;
  return assistantWork('Сохраняем выбранный вариант…',async()=>{
    const a=S.ai;
    const result=await api('/assistant/apply',{revision:a.preview.revision,previewId:assistantSelected().previewId});
    S.data=result.state;S.revision=result.revision;S.day=result.day;S.date=date;S.preview=null;
    a.preview=null;a.error='';
    if(!technology) {
      a.response=null;a.text='';localStorage.removeItem('assistant-draft');
      a.messages.push({role:'assistant',notice:true,text:'Вариант сохранён.',content:'Вариант сохранён.'});
    }
    S.page='day';history.replaceState(null,'','#day');render();
    toast('Вариант сохранён. Изменения отмечены красным.');
  });
}

document.addEventListener('click',async e=>{
  const node=e.target.closest('[data-action^="preview-"]');if(!node || !S.preview)return;
  if(node.dataset.action==='preview-variant') {S.preview.selected=Number(node.dataset.id);render();return;}
  if(node.dataset.action==='preview-cancel') {
    const kind=S.preview.kind;S.preview=null;
    if(kind==='assistant') {S.page='assistant';history.replaceState(null,'','#assistant');}
    if(kind==='technology')S.ai.preview=null;
    if(kind==='class-hour') {S.ai.preview=null;S.page='extras';history.replaceState(null,'','#extras');}
    render();if(kind==='technology')openTechnology();return;
  }
  if(node.dataset.action==='preview-apply') {
    const selected=previewSelected();
    if(['assistant','technology','class-hour'].includes(S.preview.kind)) {S.ai.selected=selected.id;await applyAssistantVariant();}
    else {S.selectedVariant=selected.id;node.dataset.variant=selected.id;await applyRepair(node);}
  }
});

async function showSchedulePreview(kind,date,variants,selected=0) {
  S.date=date;await loadDay();closeModal();closeSheet();
  S.preview={kind,date,variants,selected};S.page='day';S.view='classes';S.changesOnly=false;S.query='';
  history.replaceState(null,'','#day');render();$('#main').scrollTop=0;
}

function schedulePreviewBar() {
  const p=S.preview,v=previewSelected();if(!p || !v)return '';
  const main=v.id===p.variants[0].id;
  const proof=main?`<p class="assistant-note">${v.search?.primaryProven && v.search?.scope==='all-rooms'?'Лучший вариант по заданным условиям.':'Лучший найденный вариант.'}</p>`:'';
  const classHours=v.stats?.classHours?`<p class="assistant-note">Классных часов: ${v.stats.classHours}${v.stats.classHourClasses>v.stats.classHours?' · классов: '+v.stats.classHourClasses:''}</p>`:'';
  const alerts=(v.warnings || []).filter(text=>text.startsWith('Классный час') || text.startsWith('Резервный вариант'));
  if(v.stats?.classGapDetails?.length)alerts.push('Окна: '+v.stats.classGapDetails.map(row=>`${row.className} — ${row.periods.join(', ')} ур.`).join('; '));
  if(v.stats?.youngerLate)alerts.push('В этом варианте у 5–6 классов остаются уроки позже обычного окончания дня.');
  const warnings=alerts.map(text=>notice(text,'warn')).join('');
  return `<section class="schedule-preview-bar" aria-label="Предпросмотр расписания"><div class="preview-heading"><h2>Выберите вариант</h2><span>Изменения ещё не применены</span></div>${proof}${classHours}${warnings}<div class="variant-strip">${p.variants.map((row,i)=>`<button class="variant-card ${row.id===v.id?'active':''}" data-action="preview-variant" data-id="${row.id}" aria-pressed="${row.id===v.id}"><span class="v-title">${i===0?'Основной вариант':'Вариант '+(i+1)}</span><span>${row.stats?.moved || 0} переставлено · ${row.stats?.cancelled || 0} отменено${row.stats?.groupLosses ? ' · занятий подгрупп отменено: '+row.stats.groupLosses : ''}${row.stats?.classGapsAfter?' · есть окна':''}${row.stats?.youngerLate?' · есть поздние уроки у 5–6':''}${row.stats?.joined?' · совместных: '+row.stats.joined:''}</span></button>`).join('')}</div><div class="assistant-actions"><button class="btn primary" data-action="preview-apply" ${S.ai.pending?'disabled':''}>${v.stats?.classGapsAfter?'Сохранить вариант с окнами':'Сохранить этот вариант'}</button><button class="btn ghost" data-action="preview-cancel">${p.kind==='assistant'?'Вернуться к просьбе':p.kind==='technology'?'Вернуться к условиям':'Отменить просмотр'}</button></div></section>`;
}
document.addEventListener('change', e => {
  if(e.target.id==='assistant-provider') {
    S.ai.providerChoice=e.target.value; S.ai.connectionError=''; S.ai.connectionMessage=''; render(); return;
  }
  if (e.target.id !== 'assistant-date') return;
  if (!e.target.value || isWeekend(e.target.value)) { e.target.value = S.ai.date; toast('Выберите будний день.'); return; }
  S.ai.date = e.target.value; assistantReset(); render();
});

document.addEventListener('submit', async e => {
  if (e.target.id === 'assistant-request-form') { e.preventDefault(); await sendAssistant(e.target); }
  if (e.target.id === 'assistant-settings-form') {
    e.preventDefault();
    const data = new FormData(e.target);
    const body = { provider:data.get('provider'),apiKey:data.get('routerApiKey'),model:data.get('routerModel'),
      paidEnabled:data.get('routerModel')==='deepseek/deepseek-v4.1-flash-1017',monthlyLimitUSD:data.get('routerBudget') };
    await assistantWork('Сохраняем подключение…', async () => {
      S.ai.status = await api('/assistant/settings', body);
      S.ai.providerChoice=''; assistantReset();
      S.ai.connectionMessage = 'Подключение сохранено.';
    }, true);
    body.apiKey = '';
  }
});

document.addEventListener('click', async e => {
  const node = e.target.closest('[data-action^="assistant-"]');
  if (!node) return;
  const a = S.ai;
  const action = node.dataset.action;
  if(a.pending && ['assistant-open-thread','assistant-new','assistant-delete-thread'].includes(action))return;
  if(action==='assistant-delete-thread') {
    if(!await askConfirm({title:'Удалить диалог?',text:'Переписка будет удалена. Уже сохранённое расписание останется без изменений.',yes:'Удалить диалог'}))return;
    try {await api('/assistant/conversations/'+encodeURIComponent(node.dataset.id)+'/delete',{});if(a.threadId===node.dataset.id)assistantReset();a.history=null;render();toast('Диалог удалён.');}catch(error){toast(error.message,'error');}return;
  }
  if(action==='assistant-more-history') {try {const result=await api('/assistant/conversations?offset='+a.history.length);a.history.push(...result.conversations);a.historyMore=result.hasMore;render();}catch(error){toast(error.message,'error');}return;}
  if(action==='assistant-hide-spending') {a.showSpending=false;render();return;}
  if(action==='assistant-open-thread') {try{await openAssistantThread(node.dataset.id);}catch(error){toast(error.message,'error');}return;}
  if(action==='assistant-show-preview') {await showSchedulePreview('assistant',a.date,a.preview.variants,a.selected);return;}
  if (action === 'assistant-settings') {
    await setPage('settings'); history.replaceState(null, '', '#settings');
    $('.assistant-settings')?.scrollIntoView({block: 'start'});
    return;
  }
  if (action === 'assistant-new') { assistantReset(); render(); $('#assistant-message')?.focus(); return; }
  if (action === 'assistant-variant') { a.selected = Number(node.dataset.id); render(); return; }
  if (action === 'assistant-open-keys') {
    try { await api('/assistant/open-keys', {provider:assistantProvider()}); } catch (error) { toast(error.message, 'error'); }
    return;
  }
  if (action === 'assistant-open-balance') {
    try { await api('/assistant/open-balance',{provider:assistantProvider()}); } catch(error) { toast(error.message,'error'); }
    return;
  }
  if (action === 'assistant-balance') return assistantWork('Проверяем баланс…',async()=>{
    const result=await api('/assistant/balance',{});
    const balances=result.balances?.map(row=>`${Number(row.amount).toFixed(3)} ${row.currency}`).join(' · ') || `$${Number(result.balanceUSD).toFixed(3)}`;
    a.balanceText=`Баланс ${a.status.providerName || 'OpenRouter'}: ${balances}.`;a.showSpending=true;a.status=await api('/assistant/settings');
  },true);
  if (action === 'assistant-check') return assistantWork('Проверяем подключение…', async () => {
    const result = await api('/assistant/check', {});
    a.connectionMessage = 'Подключение работает.' +
      (a.status.paidEnabled || result.remaining == null ? '' : ` Осталось бесплатных обращений: ${result.remaining} из ${result.limit}.`);
  }, true);
  if (action === 'assistant-probe') return assistantWork('Проверяем модель на вымышленных данных…', async () => {
    const result = await api('/assistant/probe', {});
    if (result.modelReady) a.connectionMessage = result.message + ` Модель: ${result.model}.`;
    else a.connectionError = result.message;
    a.status = await api('/assistant/settings');
  }, true);
  if (action === 'assistant-remove-key') return assistantWork('Удаляем ключ…', async () => {
    a.status = await api('/assistant/settings', {removeKey: true, model: a.status.model});
    a.connectionMessage = 'Ключ удалён с этого компьютера.';
  }, true);
  if (action === 'assistant-preview') return assistantWork('Алгоритм подбирает варианты без окон…', async () => {
    a.preview = await api('/assistant/preview', {revision: a.response.revision, draftId: a.response.draftId});
    a.selected = a.preview.variants[0]?.id ?? 0;
    if(a.preview.variants.length)await showSchedulePreview('assistant',a.date,a.preview.variants,a.selected);
  });
  if (action === 'assistant-apply') return assistantWork('Сохраняем выбранный вариант…', async () => {
    const result = await api('/assistant/apply', {revision: a.preview.revision, previewId: assistantSelected().previewId});
    S.data = result.state; S.revision = result.revision; S.day = result.day; S.date = a.date;
    S.preview=null;
    assistantReset(); a.messages.push({role: 'assistant', content: 'Выбранный вариант сохранён. Изменённые уроки выделены красным в расписании и Word.'});
    S.page = 'day'; history.replaceState(null, '', '#day'); render();
    toast('Вариант сохранён. Изменения отмечены красным.');
  });
  if (action === 'assistant-clear-conditions') {
    if (!await askConfirm({title: 'Снять условия дня?', text: 'Расставленные уроки останутся на местах. Ограничения по времени, кабинетам и закрепления помощника будут сняты. Отсутствия удаляются отдельно в разделе «Отсутствия».', yes: 'Снять условия'})) return;
    return assistantWork('Снимаем условия…', async () => {
      const result = await api('/assistant/clear-conditions', {revision: S.revision, date: a.date});
      S.data = result.state; S.revision = result.revision; assistantReset();
    });
  }
});

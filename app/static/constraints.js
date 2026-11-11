'use strict';

const CONSTRAINT_KINDS={teachers:'Преподаватель',classes:'Класс',rooms:'Кабинет',subjects:'Предмет'};

function availableSlots(record) {
  const blocked=new Set((record.unavailable||[]).map(s=>Array.isArray(s)?s.join(':'):`${s.day}:${s.period}`));
  return DAYS.flatMap((_,d)=>S.data.school.bells.slice(0,8).map((_,p)=>[d,p+1])).filter(s=>!blocked.has(s.join(':')));
}

function availabilityText(record) {
  const allowed=availableSlots(record);
  if(allowed.length===5*Math.min(8,S.data.school.bells.length))return 'Все учебные часы';
  if(!allowed.length)return 'Занятия запрещены всю неделю';
  return DAYS.map((day,d)=>{
    const periods=allowed.filter(s=>s[0]===d).map(s=>s[1]);
    return periods.length?`${day}: ${periods.join(', ')} ${periods.length===1?'урок':'уроки'}`:'';
  }).filter(Boolean).join(' · ');
}

function renderConstraints() {
  const sections=Object.entries(CONSTRAINT_KINDS).map(([kind,title])=>{
    const rows=S.data[kind].filter(r=>(r.unavailable||[]).length || kind==='teachers' && (r.maxDays<5 || r.maxDaily<8 || r.homeroomRoomId) || kind==='classes' && (r.firstPeriod>1 || r.maxDaily<8));
    if(!rows.length)return '';
    return `<section class="constraint-group"><h2>${title==='Преподаватель'?'Преподаватели':title==='Класс'?'Классы':title==='Кабинет'?'Кабинеты':'Предметы'}</h2>${rows.map(r=>`<div class="constraint-row"><div><strong>${esc(r.name)}</strong><p>${esc(availabilityText(r))}${kind==='teachers' && r.homeroomRoomId?`<br>Классный час: кабинет ${esc(nameOf('rooms',r.homeroomRoomId))}`:''}${r.maxDaily<8?`<br>Не более ${r.maxDaily} уроков в день`:''}${r.maxDays<5?`<br>Не более ${r.maxDays} рабочих дней в неделю`:''}${r.firstPeriod>1?`<br>Приход не раньше ${r.firstPeriod}-го урока`:''}</p></div><button class="btn ghost" data-action="constraint-edit" data-kind="${kind}" data-id="${esc(r.id)}">Изменить</button></div>`).join('')}</section>`;
  }).join('');
  const rov=S.data.subjects.filter(s=>/разговор.*важн/i.test(s.name));
  const tech=S.data.subjects.filter(s=>/труд|технол/i.test(s.name));
  const exception=S.data.school.eighthPeriodException;
  return `<div class="page narrow">${pageHead('Школа','Ограничения','Постоянные правила для редактора, подбора на день и создания недели.',button('Добавить ограничение','constraint-new','primary','plus'))}
    <section class="constraint-group"><div class="section-head"><h2>Общие правила</h2>${button('Изменить','constraint-general','ghost')}</div>
      <ul class="rule-summary"><li>«Разговоры о важном»: ${rov.every(s=>s.firstMonday!==false)?'первый урок понедельника':'время не закреплено'}</li><li>Технология: ${tech.every(s=>s.pairedTechnology!==false)?'парные занятия подряд у каждой подгруппы':'по настройкам учебного плана'}</li><li>Сначала подбор без окон у учеников. Резервный вариант с окнами требует подтверждения.</li><li>Сохранение часов, отсутствие лишнего седьмого урока у 5–6 классов, минимум перестановок.</li><li>По возможности приход первым уроком. Окна учителей допускаются.</li><li>Классный час: выбранный урок, свой руководитель и его кабинет.</li><li>Обычные уроки сохраняют своего преподавателя. Исключения для объединений задаются на конкретную дату.</li><li>Недельные часы и спаренные блоки задаются в учебном плане. Занятость началкой и индивидуальными занятиями учитывается отдельно.</li></ul>
      <div class="constraint-row"><div><strong>Восьмой урок</strong><p>${exception?`${esc(DAYS[exception.day])}, ${esc(namesOf('classes',exception.classIds))}, ${esc(namesOf('teachers',exception.teacherIds))}, ${esc(subjectName(exception.subjectId))}`:'Постоянных исключений нет'}. Для остальных занятий требуется отдельное разрешение на дату.</p></div>${button('Изменить','constraint-eighth','ghost')}</div>
    </section>${sections || '<p class="muted">Добавьте часы доступности преподавателя, класса, кабинета или предмета.</p>'}</div>`;
}

function openConstraintSheet(kind='teachers',id='') {
  const r=S.data[kind]?.find(row=>row.id===id);
  const selected=new Set(r?availableSlots(r).map(s=>s.join(':')):[]);
  const body=`<div class="form-grid"><label class="field"><span>Для кого</span><select class="input" id="constraint-kind">${Object.entries(CONSTRAINT_KINDS).map(([k,v])=>`<option value="${k}" ${kind===k?'selected':''}>${v}</option>`).join('')}</select></label>
    <label class="field"><span>${CONSTRAINT_KINDS[kind]}</span><select class="input" id="constraint-record" required><option value="">Выберите из списка</option>${S.data[kind].map(row=>`<option value="${esc(row.id)}" ${row.id===id?'selected':''}>${esc(row.name)}</option>`).join('')}</select></label>
    ${r?`<fieldset class="availability-fieldset"><legend>Когда можно проводить занятия</legend><p class="muted">Отметьте разрешённые часы. Восьмой урок дополнительно требует исключения.</p><div class="assistant-actions"><button class="text-btn" type="button" data-constraint-slots="all">Разрешить все</button><button class="text-btn" type="button" data-constraint-slots="none">Снять все отметки</button></div><table class="availability-editor"><thead><tr><th>Урок</th>${DAYS.map(d=>`<th>${d.slice(0,2)}</th>`).join('')}</tr></thead><tbody>${S.data.school.bells.slice(0,8).map((_,p)=>`<tr><th>${p+1}</th>${DAYS.map((d,n)=>`<td><input type="checkbox" name="allowedSlot" value="${n}:${p+1}" ${selected.has(`${n}:${p+1}`)?'checked':''} aria-label="${d}, ${p+1} урок разрешён"></td>`).join('')}</tr>`).join('')}</tbody></table></fieldset>
      ${['teachers','classes'].includes(kind)?`<label class="field"><span>Не более уроков в день</span><input class="input" type="number" name="maxDaily" min="1" max="8" value="${r.maxDaily||8}" required></label>`:''}
      ${kind==='teachers'?`<label class="field"><span>Не более рабочих дней в неделю</span><input class="input" type="number" name="maxDays" min="1" max="5" value="${r.maxDays||5}" required></label><label class="field"><span>Кабинет для классного часа</span><select class="input" name="homeroomRoomId"><option value="">Не указан</option>${S.data.rooms.map(room=>`<option value="${esc(room.id)}" ${room.id===r.homeroomRoomId?'selected':''}>${esc(room.name)}</option>`).join('')}</select></label>`:''}
      ${kind==='classes'?`<label class="field"><span>Приход не раньше урока</span><input class="input" name="firstPeriod" type="number" min="1" max="7" value="${r.firstPeriod||1}"></label>`:''}`:''}
    <p class="muted">Правило сохраняется отдельно. Уже расставленные уроки автоматически не переставляются.</p></div>`;
  openSheet({title:r?`Ограничения: ${r.name}`:'Новое ограничение',body,foot:`${button('Отмена','close-sheet','ghost')}<button type="submit" class="btn primary" ${r?'':'disabled'}>Сохранить правило</button>`,submit:async form=>{
    const data=new FormData(form),record={revision:S.revision,kind,id,allowed:data.getAll('allowedSlot').map(v=>v.split(':').map(Number))};
    for(const key of ['maxDaily','maxDays','firstPeriod'])if(data.has(key))record[key]=Number(data.get(key));
    if(data.has('homeroomRoomId'))record.homeroomRoomId=data.get('homeroomRoomId');
    await saveConstraint('/constraints/availability',record);
  }});
  $('#constraint-kind').onchange=e=>openConstraintSheet(e.target.value);
  $('#constraint-record').onchange=e=>openConstraintSheet(kind,e.target.value);
  $$('#sheet-form [data-constraint-slots]').forEach(b=>b.onclick=()=>$$('#sheet-form [name="allowedSlot"]').forEach(n=>{n.checked=b.dataset.constraintSlots==='all';}));
}

async function saveConstraint(path,body) {
  const result=await api(path,body);S.data=result.state;S.revision=result.revision;
  S.preview=null;S.ai.preview=null;S.report=null;closeSheet();await loadDay();render();toast('Ограничение сохранено.');
}

function openGeneralConstraints() {
  openSheet({title:'Общие правила',body:`<div class="form-grid"><label class="check"><input type="checkbox" name="rovFirst" ${S.data.subjects.filter(s=>/разговор.*важн/i.test(s.name)).every(s=>s.firstMonday!==false)?'checked':''}>«Разговоры о важном» только первым уроком понедельника</label><label class="check"><input type="checkbox" name="technologyPairs" ${S.data.subjects.filter(s=>/труд|технол/i.test(s.name)).every(s=>s.pairedTechnology!==false)?'checked':''}>Технология идёт парой, если в учебном плане чётное число часов</label><p class="muted">Пары, заданные прямо в учебном плане, сохраняются независимо от этой настройки.</p></div>`,foot:`${button('Отмена','close-sheet','ghost')}<button class="btn primary" type="submit">Сохранить правила</button>`,submit:form=>saveConstraint('/constraints/general',{revision:S.revision,rovFirst:form.elements.rovFirst.checked,technologyPairs:form.elements.technologyPairs.checked})});
}

function openEighthConstraint() {
  const r=S.data.school.eighthPeriodException;
  const select=(name,title,kind,value)=>`<label class="field"><span>${title}</span><select class="input" name="${name}">${S.data[kind].map(row=>`<option value="${esc(row.id)}" ${row.id===value?'selected':''}>${esc(row.name)}</option>`).join('')}</select></label>`;
  openSheet({title:'Исключение восьмого урока',body:`<div class="form-grid"><label class="check"><input type="checkbox" name="enabled" ${r?'checked':''}>Разрешить один постоянный восьмой урок</label><label class="field"><span>День недели</span><select class="input" name="day">${DAYS.map((d,n)=>`<option value="${n}" ${n===r?.day?'selected':''}>${d}</option>`).join('')}</select></label>${select('classId','Класс','classes',r?.classIds[0])}${select('teacherId','Преподаватель','teachers',r?.teacherIds[0])}${select('subjectId','Предмет','subjects',r?.subjectId)}</div>`,foot:`${button('Отмена','close-sheet','ghost')}<button class="btn primary" type="submit">Сохранить исключение</button>`,submit:form=>{const d=new FormData(form);return saveConstraint('/constraints/eighth',{revision:S.revision,enabled:d.has('enabled'),day:Number(d.get('day')),classId:d.get('classId'),teacherId:d.get('teacherId'),subjectId:d.get('subjectId')});}});
}

document.addEventListener('click',e=>{
  const n=e.target.closest('[data-action^="constraint-"]');if(!n)return;
  if(n.dataset.action==='constraint-new')openConstraintSheet();
  if(n.dataset.action==='constraint-edit')openConstraintSheet(n.dataset.kind,n.dataset.id);
  if(n.dataset.action==='constraint-general')openGeneralConstraints();
  if(n.dataset.action==='constraint-eighth')openEighthConstraint();
});

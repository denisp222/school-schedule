'use strict';

const TECHNOLOGY_UI={teacherId:'',sameClass:true,girlsClasses:false,boysClasses:false,safetyApproved:false,classIds:[],pending:false};

function technologyTeachers() {
  const ids=new Set(S.data.plan.filter(p=>/технолог|труд/i.test(subjectName(p.subjectId)) && p.teacherIds.length===2).flatMap(p=>p.teacherIds));
  return S.data.teachers.filter(t=>ids.has(t.id));
}

function openTechnology() {
  const teachers=technologyTeachers(), t=TECHNOLOGY_UI;
  if(!teachers.some(row=>row.id===t.teacherId))t.teacherId=teachers[0]?.id || '';
  const classes=S.data.classes.filter(c=>S.data.plan.some(p=>p.classIds.includes(c.id) && p.teacherIds.length===2 && /технолог|труд/i.test(subjectName(p.subjectId))));
  const form=teachers.length?`<form id="technology-form" class="technology-form">
    <label class="field"><span>Кто проведёт совместное занятие</span><select class="input" name="teacherId" required>${teachers.map(row=>`<option value="${esc(row.id)}" ${t.teacherId===row.id?'selected':''}>${esc(row.name)}</option>`).join('')}</select></label>
    <fieldset class="technology-permissions"><legend>Какие исключения разрешены на ${esc(fmtDate(S.date))}</legend>
      <label class="check"><input name="sameClass" type="checkbox" ${t.sameClass?'checked':''}>Взять обе подгруппы своего класса</label>
      <label class="check"><input name="girlsClasses" type="checkbox" ${t.girlsClasses?'checked':''}>Объединить девочек из двух классов</label>
      <details class="technology-advanced" ${t.boysClasses?'open':''}><summary>Объединение мальчиков из двух классов</summary>
        <p class="muted">Нужны численность подгрупп, вместимость кабинета и подтверждение преподавателя.</p>
        <label class="check"><input name="boysClasses" type="checkbox" ${t.boysClasses?'checked':''}>Разрешить такой вариант</label>
        <label class="check"><input name="safetyApproved" type="checkbox" ${t.safetyApproved?'checked':''}>Преподаватель подтвердил, что может безопасно провести занятие</label>
      </details>
    </fieldset>
    <details class="technology-scope" ${t.classIds.length?'open':''}><summary>Ограничить выбор классами</summary><p class="muted">Если ничего не отмечено, учитываются все подходящие классы.</p><div class="technology-classes">${classes.map(c=>`<label class="check"><input type="checkbox" name="classId" value="${esc(c.id)}" ${t.classIds.includes(c.id)?'checked':''}>${esc(c.name)}</label>`).join('')}</div></details>
    <p class="muted">Состав подгрупп и число учеников задаются в «Дополнительных занятиях». Изменения сначала появятся в предпросмотре.</p>
    <div id="technology-error" role="alert"></div>
  </form>`:notice('В учебном плане пока нет технологии с двумя подгруппами.','warn');
  openModal({title:'Исключения для технологии',sub:fmtLongCap(S.date),body:form,
    foot:button('Отмена','close-modal','ghost')+(teachers.length?'<button type="submit" form="technology-form" class="btn primary" id="technology-submit">Посмотреть варианты</button>':'')});
}

document.addEventListener('click',event=>{
  if(event.target.closest('[data-action="technology"]'))openTechnology();
});

document.addEventListener('submit',async event=>{
  if(event.target.id!=='technology-form')return;
  event.preventDefault();const t=TECHNOLOGY_UI;if(t.pending)return;
  const form=event.target,data=new FormData(form);
  Object.assign(t,{teacherId:String(data.get('teacherId') || ''),sameClass:data.has('sameClass'),girlsClasses:data.has('girlsClasses'),boysClasses:data.has('boysClasses'),safetyApproved:data.has('safetyApproved'),classIds:data.getAll('classId').map(String)});
  const error=document.querySelector('#technology-error');
  error.innerHTML='';
  if(!t.sameClass && !t.girlsClasses && !t.boysClasses) {error.innerHTML=notice('Выберите хотя бы одно разрешённое исключение.','warn');return;}
  if(t.boysClasses && !t.safetyApproved) {error.innerHTML=notice('Для объединения мальчиков нужно подтверждение преподавателя.','warn');return;}
  t.pending=true;const submit=document.querySelector('#technology-submit');
  submit.disabled=true;submit.textContent='Подбираем варианты…';
  try {
    const {pending,...permissions}=t;
    const result=await api('/assistant/technology-preview',{revision:S.revision,date:S.date,...permissions});
    if(!result.variants?.length) {error.innerHTML=notice(result.message || 'Вариант без окон у учеников не найден. Проверьте занятость преподавателя и состав подгрупп.','warn');return;}
    S.ai.preview=result;S.ai.selected=result.variants[0].id;
    await showSchedulePreview('technology',result.date,result.variants,S.ai.selected);
  }catch(problem) {error.innerHTML=notice(esc(problem.message),'error');}
  finally {t.pending=false;if(submit.isConnected) {submit.disabled=false;submit.textContent='Посмотреть варианты';}}
});

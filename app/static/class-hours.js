'use strict';

function classHourEligible(lesson) {
  if(lesson.period!==1 || lesson.classIds.length!==1 || lesson.teacherIds.length!==1 ||
     'groupIndex' in lesson || lesson.joint || lesson.technologyJoint)return false;
  const cid=lesson.classIds[0];
  if(by('classes',cid)?.homeroomTeacherId!==lesson.teacherIds[0])return false;
  return !S.data.plan.some(p=>p.classIds.includes(cid) && p.subjectId===lesson.subjectId &&
    (p.doubleLessons || /труд|технол/i.test(subjectName(p.subjectId)) && p.hours>=2 && p.hours%2===0));
}

function openClassHourSheet() {
  const body=`<div class="form-grid"><label class="field"><span>Дата</span><input class="input" type="date" name="date" value="${esc(S.date)}" required></label>
    <p class="assistant-note">Классный час заменит обычный первый урок только на эту дату. Спаренный блок сохранится для перестановки целиком. Классы одного руководителя проведут классный час совместно.</p>
    <label class="check"><input type="checkbox" data-class-hour-all checked>Все классы</label>
    <div class="class-hour-classes">${S.data.classes.map(c=>`<label class="check"><input type="checkbox" name="classHourClass" value="${esc(c.id)}" checked><span>${esc(c.name)}<small>${esc(c.homeroomTeacherId?nameOf('teachers',c.homeroomTeacherId):'Классный руководитель не указан')}</small></span></label>`).join('')}</div>
    <div role="alert" id="class-hour-error"></div></div>`;
  openSheet({title:'Классный час',sub:'Первым уроком у классных руководителей',body,
    foot:`${button('Отмена','close-sheet','ghost')}<button type="submit" class="btn primary">Посмотреть расписание</button>`,
    submit:async form=>{
      const data=new FormData(form),classIds=data.getAll('classHourClass');
      if(!classIds.length)throw new Error('Выберите хотя бы один класс.');
      const submit=form.querySelector('[type="submit"]');submit.disabled=true;submit.textContent='Подбираем…';
      try {
        const result=await api('/assistant/class-hour-preview',{revision:S.revision,date:data.get('date'),classIds});
        if(!result.variants.length)throw new Error(result.message);
        S.ai.preview=result;S.ai.selected=result.variants[0].id;
        await showSchedulePreview('class-hour',result.date,result.variants,0);
      } finally {submit.disabled=false;submit.textContent='Посмотреть расписание';}
    }});
  const all=$('#sheet-form [data-class-hour-all]');
  all.addEventListener('change',()=>{$$('#sheet-form [name="classHourClass"]').forEach(n=>{n.checked=all.checked;});});
  $$('#sheet-form [name="classHourClass"]').forEach(n=>n.addEventListener('change',()=>{
    const choices=$$('#sheet-form [name="classHourClass"]');all.checked=choices.every(n=>n.checked);
    all.indeterminate=!all.checked && choices.some(n=>n.checked);
  }));
}

document.addEventListener('click',event=>{
  if(event.target.closest('[data-action="class-hour"]'))openClassHourSheet();
});

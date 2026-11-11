'use strict';

async function openFullBackup() {
  try {
    const status=await api('/assistant/settings');
    const hasKeys=Object.values(status.connections||{}).some(Boolean);
    openSheet({title:'Резервная копия',body:`<div class="form-grid"><p>Расписание, ограничения, классное руководство, кабинеты, диалоги, история версий, настройки и шаблоны отчётов сохранятся в один файл.</p>${hasKeys?'<label class="field"><span>Пароль для переноса подключения AI</span><input class="input" name="password" type="password" minlength="8" maxlength="256" autocomplete="new-password" required></label><p class="muted">Не менее 8 символов. Этот пароль понадобится при загрузке копии на другом компьютере.</p>':''}</div>`,foot:`${button('Отмена','close-sheet','ghost')}<button class="btn primary" type="submit">Сохранить копию</button>`,submit:async form=>{
      const body=hasKeys?{password:new FormData(form).get('password')}:{};
      const response=await fetch('/api/backup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(!response.ok){const e=await response.json();throw new Error(e.detail||'Не удалось подготовить копию.');}
      const saved=await savePreparedFile(await response.blob(),'Расписание-полная-копия.json');showExportResult(saved);
    }});
  } catch(error){toast(error.message,'error');}
}

document.addEventListener('click',e=>{if(e.target.closest('[data-action="backup-full"]'))openFullBackup();});

'use strict';
const AppUpdate={timer:null,quiet:true,shown:false};

async function checkAppUpdates(automatic=false) {
  try {AppUpdate.quiet=automatic;const value=await api('/updates/check',{automatic});trackAppUpdate(value);}
  catch(error){if(!automatic)toast(error.message,'error');}
}

function trackAppUpdate(value) {
  clearTimeout(AppUpdate.timer);
  const busy=['checking','downloading','installing'].includes(value.stage);
  if(value.stage==='idle' && value.message && AppUpdate.quiet){toast(value.message,'error');return;}
  if(value.stage==='available' && AppUpdate.quiet && document.querySelector('dialog[open]')) {
    AppUpdate.timer=setTimeout(()=>trackAppUpdate(value),2000);return;
  }
  if(value.stage==='available' && !AppUpdate.shown || !AppUpdate.quiet)showAppUpdate(value);
  if(busy)AppUpdate.timer=setTimeout(async()=>{try{trackAppUpdate(await api('/updates/status'));}catch(error){if(!AppUpdate.quiet)toast(error.message,'error');}},500);
}

function showAppUpdate(value) {
  AppUpdate.shown=true;
  if(value.stage==='available')AppUpdate.quiet=false;
  const downloading=value.stage==='downloading';
  const percent=value.total?Math.round(value.done/value.total*100):0;
  const progress=downloading?`<progress class="update-progress" max="100" ${value.done?`value="${percent}"`:''}></progress><p class="muted">${value.done?`${(value.done/1048576).toFixed(1)} из ${(value.total/1048576).toFixed(1)} МБ`:''}</p>`:'';
  let actions=button('Закрыть','close-modal','ghost');
  if(value.stage==='available')actions=button('Позже','update-later','ghost')+button('Загрузить обновление','update-download','primary','download');
  if(downloading)actions=button('Отменить загрузку','update-cancel','ghost');
  if(value.stage==='ready')actions=button('Позже','update-later','ghost')+button('Установить и перезапустить','update-install','primary');
  openModal({title:value.version?`Обновление ${value.version}`:'Обновления',sub:`Ваша версия ${value.currentVersion}`,body:`<div class="update-dialog"><p>${esc(value.message)}</p>${progress}${value.stage==='available'?'<p class="muted">Расписание, настройки и подключение AI сохранятся. Установка начнётся только после вашего подтверждения.</p>':''}</div>`,foot:actions});
}

document.addEventListener('click',async event=>{
  const node=event.target.closest('[data-action^="update-"]');if(!node)return;
  try {
    if(node.dataset.action==='update-check') {AppUpdate.shown=false;return checkAppUpdates(false);}
    if(node.dataset.action==='update-later') {AppUpdate.quiet=true;closeModal();return;}
    if(node.dataset.action==='update-download')trackAppUpdate(await api('/updates/download',{confirmed:true}));
    if(node.dataset.action==='update-cancel'){await api('/updates/cancel',{});AppUpdate.quiet=true;closeModal();}
    if(node.dataset.action==='update-install') {
      if(S.ai?.pending || typeof isVoiceBusy==='function' && isVoiceBusy())throw new Error('Сначала завершите работу с помощником, затем устанавливайте обновление.');
      node.disabled=true;
      trackAppUpdate(await api('/updates/install',{confirmed:true}));
    }
  }catch(error){modalError(error.message);}
});

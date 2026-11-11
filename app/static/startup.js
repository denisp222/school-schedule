/* Keep this small and compatible with old WebView engines: it must still run
   when a feature script cannot be parsed. No timetable data is collected. */
(function () {
  'use strict';
  var ready=false,started=Date.now(),lastStage='loading-scripts',timer;
  function host(message) {
    try {if(window.chrome && window.chrome.webview)window.chrome.webview.postMessage(message);}catch(ignore){}
  }
  function stage(value,detail) {
    lastStage=value;
    host({kind:'ui-startup',stage:value,message:String(detail || '').slice(0,500)});
  }
  function show(failed) {
    if(ready)return;
    var main=document.getElementById('main');if(!main)return;
    var panel=document.getElementById('startup-help');
    if(!panel) {panel=document.createElement('div');panel.id='startup-help';panel.className='page';main.appendChild(panel);}
    panel.innerHTML='<div class="startup-panel" role="status"><h1>'+(failed?'Не удалось открыть расписание':'Расписание открывается дольше обычного')+'</h1><p>Можно подождать ещё немного или повторить запуск. Ваши данные сохранены.</p><div class="startup-actions"><button class="btn primary" id="startup-retry" type="button">Повторить загрузку</button><button class="btn" id="startup-report" type="button">Сохранить диагностику</button></div><p id="startup-result" class="muted"></p></div>';
    var loading=main.querySelector('.loading');if(loading)loading.style.display='none';
    document.getElementById('startup-retry').onclick=function(){window.location.reload();};
    document.getElementById('startup-report').onclick=function(){
      if(window.chrome && window.chrome.webview) {
        host({kind:'startup-diagnostics',id:'startup-diagnostics'});
      } else document.getElementById('startup-result').textContent='Откройте программу своим ярлыком и сохраните диагностику из её окна.';
    };
  }
  window.ScheduleStartup={
    stage:stage,
    ready:function(){ready=true;clearTimeout(timer);stage('ready',String(Date.now()-started)+' ms');var node=document.getElementById('startup-help');if(node)node.remove();},
    failed:function(detail){stage('failed',detail);show(true);}
  };
  window.addEventListener('error',function(event){
    if(ready)return;
    var source=event.target;
    stage('script-error',event.message || (source && (source.src || source.href)) || 'script failed');
    show(true);
  },true);
  window.addEventListener('unhandledrejection',function(){if(!ready){stage('startup-promise-error');show(true);}});
  function watch() {timer=setTimeout(function(){if(!ready){stage('waiting',lastStage);show(false);}},25000);}
  // Start before DOMContentLoaded: a stalled deferred script can prevent that
  // event altogether, which is precisely when this recovery screen is needed.
  watch();
  if(window.chrome && window.chrome.webview)window.chrome.webview.addEventListener('message',function(event){
    var message=event.data;
    if(message && message.kind==='save-export-result' && message.id==='startup-diagnostics') {
      var node=document.getElementById('startup-result');
      if(node)node.textContent=message.saved?'Диагностика сохранена. Этот файл можно передать разработчику.':message.error || '';
    }
  });
  stage('loading-scripts',navigator.userAgent);
}());

'use strict';

const voice={state:'idle',error:'',warning:false,seconds:0,chunks:[],samples:0,rate:0,stream:null,context:null,node:null,source:null,timer:null,generation:0,undoText:null,formattedText:''};
function isVoiceBusy() {return voice.state!=='idle';}
function voiceControls() {
  const recording=voice.state==='recording';
  const text=recording?`Идёт запись: ${voice.seconds} сек.`:voice.state==='starting'?'Включаем микрофон…':voice.state==='working'?'Распознаём речь…':voice.state==='formatting'?'Оформляем сообщение…':'';
  const label=recording?'Завершить запись':'Записать голосовое сообщение';
  const undo=voice.undoText!==null && S.ai.text===voice.formattedText && !isVoiceBusy() && !S.ai.pending;
  const microphone=S.features?.voice!==false?`<button type="button" class="composer-icon ${recording?'recording':''}" data-action="voice-toggle" title="${label}" aria-label="${label}" aria-pressed="${recording}" ${voice.state!=='idle' && !recording || S.ai.pending?'disabled':''}>${icon(recording?'check':'mic')}</button>`:'';
  return `<div class="composer-toolbar"><div class="composer-status"><span id="voice-status" role="status" aria-live="polite">${esc(text)}</span>${undo?`<button type="button" class="composer-icon" data-action="voice-undo" title="Вернуть исходный текст" aria-label="Вернуть исходный текст">${icon('undo')}</button>`:''}</div><div class="composer-actions">${recording?`<button type="button" class="composer-icon" data-action="voice-cancel" title="Отменить запись" aria-label="Отменить запись">${icon('close')}</button>`:''}${microphone}<button id="assistant-send" class="btn primary" type="submit" title="Отправить сообщение (Enter)" ${!S.ai.status?.configured || S.ai.pending || isVoiceBusy() || !S.ai.text.trim() || S.ai.text.length>4000?'disabled':''}>Отправить сообщение</button></div></div>`;
}

function microphoneError(error) {
  if(error.name==='NotAllowedError' || error.name==='PermissionDeniedError')return 'Нет доступа к микрофону. Разрешите доступ и повторите запись.';
  if(error.name==='NotFoundError' || error.name==='DevicesNotFoundError')return 'Микрофон не найден. Подключите его и повторите запись.';
  if(error.name==='NotReadableError')return 'Микрофон занят другим приложением. Освободите его и повторите запись.';
  return error.message || 'Не удалось включить микрофон. Просьбу можно ввести текстом.';
}

async function nativeMicrophoneReady() {
  if(!window.chrome?.webview)return;
  const id=crypto.randomUUID();
  await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{window.chrome.webview.removeEventListener('message',receive);reject(new Error('Перезапустите приложение, чтобы включить голосовой ввод.'));},4000);
    const receive=event=>{
      if(event.data?.kind!=='voice-permission-ready' || event.data.id!==id)return;
      clearTimeout(timer);window.chrome.webview.removeEventListener('message',receive);resolve();
    };
    window.chrome.webview.addEventListener('message',receive);
    window.chrome.webview.postMessage({kind:'voice-permission',id});
  });
}

async function startVoiceCapture() {
  if(S.features?.voice===false)return;
  if(isVoiceBusy() || S.ai.pending)return;
  voice.state='starting';voice.error='';voice.warning=false;voice.undoText=null;voice.seconds=0;voice.chunks=[];voice.samples=0;
  const generation=++voice.generation;
  render();
  try {
    if(!navigator.mediaDevices?.getUserMedia || !window.AudioContext)throw new Error('Голосовой ввод недоступен в этом окне. Откройте приложение своим ярлыком.');
    const context=new AudioContext();voice.context=context;await context.resume();
    if(generation!==voice.generation)return;
    await nativeMicrophoneReady();
    if(generation!==voice.generation)return;
    const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true},video:false});
    if(generation!==voice.generation) {stream.getTracks().forEach(t=>t.stop());await context.close();return;}
    voice.stream=stream;voice.rate=context.sampleRate;
    const take=samples=>{if(voice.state==='recording') {voice.chunks.push(new Float32Array(samples));voice.samples+=samples.length;}};
    const source=context.createMediaStreamSource(stream);voice.source=source;
    const silence=context.createGain();silence.gain.value=0;silence.connect(context.destination);
    if(context.audioWorklet) {
      await context.audioWorklet.addModule('/static/voice-worklet.js');
      const node=new AudioWorkletNode(context,'schedule-recorder');voice.node=node;node.port.onmessage=e=>take(e.data);source.connect(node);node.connect(silence);
    } else {
      const node=context.createScriptProcessor(4096,1,1);voice.node=node;node.onaudioprocess=e=>take(e.inputBuffer.getChannelData(0));source.connect(node);node.connect(silence);
    }
    if(generation!==voice.generation) {await stopVoiceCapture(false);return;}
    voice.state='recording';render();
    voice.timer=setInterval(()=>{
      voice.seconds++;
      const status=document.querySelector('#voice-status');if(status)status.textContent=`Идёт запись: ${voice.seconds} сек.`;
      if(voice.seconds>=90)stopVoiceCapture(true);
    },1000);
  } catch(error) {
    if(generation!==voice.generation)return;
    await stopVoiceCapture(false);voice.error=microphoneError(error);if(S.page==='assistant')render();
  }
}

function encodeVoice(chunks,length,rate) {
  const all=new Float32Array(length);let position=0;
  for(const chunk of chunks) {all.set(chunk,position);position+=chunk.length;}
  const size=Math.floor(length*16000/rate),buffer=new ArrayBuffer(size*2),view=new DataView(buffer);
  for(let i=0;i<size;i++) {
    const first=Math.floor(i*rate/16000),last=Math.min(length,Math.floor((i+1)*rate/16000));
    let sum=0;for(let j=first;j<last;j++)sum+=all[j];
    const value=Math.max(-1,Math.min(1,sum/Math.max(1,last-first)));
    view.setInt16(i*2,value<0?value*32768:value*32767,true);
  }
  const bytes=new Uint8Array(buffer);let binary='';
  for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
  return btoa(binary);
}

async function stopVoiceCapture(transcribe=false) {
  const generation=++voice.generation;
  const chunks=voice.chunks,length=voice.samples,rate=voice.rate;
  clearInterval(voice.timer);voice.timer=null;
  voice.stream?.getTracks().forEach(t=>t.stop());voice.stream=null;
  try {voice.source?.disconnect();voice.node?.disconnect();await voice.context?.close();}catch(error){}
  voice.context=null;voice.node=null;voice.source=null;voice.chunks=[];voice.samples=0;
  voice.state=transcribe?'working':'idle';
  if(S.page==='assistant')render();
  if(!transcribe)return;
  try {
    if(!length || length/rate<0.1)throw new Error('Запись слишком короткая. Попробуйте ещё раз.');
    const result=await api('/assistant/voice',{pcm:encodeVoice(chunks,length,rate),rate:16000});
    if(generation!==voice.generation || S.page!=='assistant')return;
    const original=result.text;
    let finalText=original,wasFormatted=false;
    if(S.ai.status?.configured) {
      voice.state='formatting';render();
      try {
        const formatted=await api('/assistant/voice/format',{text:original});
        if(generation!==voice.generation || S.page!=='assistant')return;
        finalText=formatted.text;wasFormatted=formatted.formatted;
        if(formatted.warning) {voice.error=formatted.warning;voice.warning=true;}
      }catch(error) {
        if(generation!==voice.generation || S.page!=='assistant')return;
        voice.error='Текст распознан. Не удалось оформить его автоматически, проверьте сообщение перед отправкой.';voice.warning=true;
      }
    }
    // Publish once, after editing has finished. Keep anything typed while the
    // recording was being processed, and retain the raw result for Undo.
    const prefix=S.ai.text.trim(),rawText=[prefix,original].filter(Boolean).join('\n');
    S.ai.text=[prefix,finalText].filter(Boolean).join('\n');
    if(wasFormatted) {voice.undoText=rawText;voice.formattedText=S.ai.text;}
    if(S.ai.text.length>4000) {voice.error='Сократите сообщение до 4000 символов перед отправкой.';voice.warning=true;}
    localStorage.setItem('assistant-draft',JSON.stringify({date:S.ai.date,text:S.ai.text}));
  } catch(error) {if(generation===voice.generation)voice.error=error.message;}
  finally {if(generation===voice.generation) {voice.state='idle';if(S.page==='assistant') {render();document.querySelector('#assistant-message')?.focus({preventScroll:true});}}}
}

document.addEventListener('click',e=>{
  const action=e.target.closest('[data-action^="voice-"]')?.dataset.action;
  if(action==='voice-toggle') {if(voice.state==='recording')stopVoiceCapture(true);else startVoiceCapture();}
  if(action==='voice-cancel')stopVoiceCapture(false);
  if(action==='voice-undo' && voice.undoText!==null && S.ai.text===voice.formattedText) {
    S.ai.text=voice.undoText;voice.undoText=null;
    localStorage.setItem('assistant-draft',JSON.stringify({date:S.ai.date,text:S.ai.text}));render();
  }
});
document.addEventListener('input',e=>{if(e.target.id==='assistant-message') {
  if(voice.error && voice.state==='idle') {voice.error='';voice.warning=false;document.querySelector('.voice-error')?.remove();}
  const send=document.querySelector('#assistant-send');
  if(send)send.disabled=!S.ai.status?.configured || isVoiceBusy() || !!S.ai.pending || !e.target.value.trim() || e.target.value.length>4000;
  if(voice.undoText!==null && e.target.value!==voice.formattedText) {voice.undoText=null;document.querySelector('[data-action="voice-undo"]')?.remove();}
}});
document.addEventListener('keydown',e=>{
  if(e.target.id==='assistant-message' && e.key==='Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault();const send=document.querySelector('#assistant-send');if(send && !send.disabled)e.target.form.requestSubmit();
  }
});
document.addEventListener('visibilitychange',()=>{if(document.hidden && isVoiceBusy())stopVoiceCapture(false);});
window.addEventListener('pagehide',()=>{voice.stream?.getTracks().forEach(t=>t.stop());});

'use strict';

/* ==========================================================================
   Расписание — client
   ========================================================================== */

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]));

const DAYS = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница'];
const DAYS_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт'];
const DAYS_GEN = ['понедельник', 'вторник', 'среду', 'четверг', 'пятницу'];
const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля',
  'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];

const ICONS = {
  calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 9.5h17M8 3v4M16 3v4"/><path d="M7.5 13h2M11 13h2M14.5 13h2M7.5 16.5h2M11 16.5h2"/>',
  grid: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M3.5 9.5h17M3.5 14.5h17M9 4.5v15M15 4.5v15"/>',
  plan: '<rect x="5" y="3.5" width="14" height="17" rx="2"/><path d="M8.5 8h7M8.5 11.5h7M8.5 15h4"/>',
  users: '<circle cx="9" cy="8" r="3.2"/><path d="M3.5 20c.4-3.2 2.6-5 5.5-5s5.1 1.8 5.5 5"/><path d="M16 5.2a3.2 3.2 0 0 1 0 5.6M17.5 15c2 .5 3.2 2.2 3.5 5"/>',
  absent: '<circle cx="12" cy="12" r="8.5"/><path d="M6.5 6.5l11 11"/>',
  book: '<path d="M4 4.5h11a3 3 0 0 1 3 3V20H7a3 3 0 0 1-3-3z"/><path d="M4 16.5h14M8 8h6"/>',
  chart: '<path d="M4 20V4M4 20h17"/><path d="M8 16v-4M12.5 16V7M17 16v-7"/>',
  settings: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7"/>',
  history: '<path d="M3.5 11a8.5 8.5 0 1 1 2.2 6.4"/><path d="M3.5 4.5V11H10"/><path d="M12 7.5V12l3 1.8"/>',
  help: '<circle cx="12" cy="12" r="8.5"/><path d="M9.2 9.2a2.8 2.8 0 0 1 5.5.7c0 1.9-2.7 2.1-2.7 4"/><path d="M12 17h.01"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  spark: '<path d="M12 3.2l2.1 5.6 5.7 2.1-5.7 2.1L12 18.6l-2.1-5.6-5.7-2.1 5.7-2.1z"/><path d="M19 3.2v3M17.5 4.7h3"/>',
  download: '<path d="M12 3.5v11M7.5 10l4.5 4.5L16.5 10"/><path d="M4.5 17v3h15v-3"/>',
  search: '<circle cx="10.8" cy="10.8" r="6.3"/><path d="M15.5 15.5L20 20"/>',
  left: '<path d="M14.5 5.5L8 12l6.5 6.5"/>',
  right: '<path d="M9.5 5.5L16 12l-6.5 6.5"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 6.5"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  alert: '<path d="M12 3.5l9 16H3z"/><path d="M12 9v4.5M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8h.01"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5.3l3.2 2"/>',
  swap: '<path d="M4 8h14M14 4l4 4-4 4M20 16H6M10 12l-4 4 4 4"/>',
  undo: '<path d="M4 9h10a5 5 0 0 1 0 10"/><path d="M4 9l4-4M4 9l4 4"/>',
  printer: '<path d="M7 8V3.5h10V8"/><rect x="4" y="8" width="16" height="8" rx="2"/><path d="M7 16h10v4.5H7z"/>',
  filter: '<path d="M3.5 5h17l-6.5 8v6l-4 2v-8z"/>',
  arrow: '<path d="M5 12h14M14 7l5 5-5 5"/>',
  dots: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  school: '<path d="M3 20h18M5 20V9l7-4 7 4v11"/><path d="M9.5 20v-5h5v5M12 5V2.5"/>',
  closeCircle: '<circle cx="12" cy="12" r="8.5"/><path d="M9 9l6 6M15 9l-6 6"/>',
  sun: '<circle cx="12" cy="12" r="3.5"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5"/>',
  lock: '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  file: '<path d="M6 3.5h8l4 4V20H6z"/><path d="M14 3.5V8h4M9 12h6M9 15.5h6"/>',
  mic: '<rect x="9" y="2.5" width="6" height="12" rx="3"/><path d="M5.5 10.5v1a6.5 6.5 0 0 0 13 0v-1M12 18v3.5M8.5 21.5h7"/>',
  trash: '<path d="M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7"/>',
};

function icon(name, size = 18) {
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ICONS.calendar}</svg>`;
}

/* --------------------------------------------------------------------------
   dates
   -------------------------------------------------------------------------- */

const parseDate = (value) => new Date(`${value}T12:00:00`);
const isoDate = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
const dayIndex = (value) => (parseDate(value).getDay() + 6) % 7;
const addDays = (value, days) => {
  const date = parseDate(value);
  date.setDate(date.getDate() + days);
  return isoDate(date);
};
const mondayOf = (value) => addDays(value, -dayIndex(value));
const fmtDate = (value) => {
  const date = parseDate(value);
  return `${String(date.getDate()).padStart(2, '0')}.${String(date.getMonth() + 1).padStart(2, '0')}.${date.getFullYear()}`;
};
const fmtLong = (value) => {
  const date = parseDate(value);
  return `${DAYS_GEN[dayIndex(value)]}, ${date.getDate()} ${MONTHS[date.getMonth()]}`;
};
const fmtLongCap = (value) => {
  const text = fmtLong(value);
  return text.charAt(0).toUpperCase() + text.slice(1);
};
const fmtShort = (value) => {
  const date = parseDate(value);
  return `${date.getDate()} ${MONTHS_SHORT[date.getMonth()]}`;
};
const isWeekend = (value) => dayIndex(value) > 4;
const nextSchoolDay = (value) => {
  let date = value;
  while (isWeekend(date)) date = addDays(date, 1);
  return date;
};

/* --------------------------------------------------------------------------
   app state
   -------------------------------------------------------------------------- */

const S = {
  data: null,
  revision: 0,
  today: null,
  date: null,
  page: 'day',
  view: 'teachers',
  query: '',
  changesOnly: false,
  day: null,
  weekKind: 'classes',
  weekId: '',
  weekActual: false,
  planClass: '',
  planQuery: '',
  dirKind: 'teachers',
  dirQuery: '',
  journalAll: false,
  report: null,
  history: null,
  sheetSubmit: null,
  absenceId: '',
  lessonContext: null,
  repairResult: null,
  repairContext: null,
  selectedVariant: 0,
  dragLesson: null,
  suppressClickUntil: 0,
  confirmResolve: null,
  busy: false,
};

/* --------------------------------------------------------------------------
   api
   -------------------------------------------------------------------------- */

function setSave(status, text) {
  if(status==='error') toast('Не удалось получить расписание. Попробуйте открыть приложение снова.','error');
}

function showSaved(value) {
  if(!value)return;
  if(S.savedAt && new Date(value)<new Date(S.savedAt))return;
  S.savedAt=value;
  const date=new Date(value);
  const node=$('#last-saved');
  if(node) {
    node.textContent=`Сохранено ${date.toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit'})} в ${date.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}`;
    node.title='Подтверждённые изменения сохраняются автоматически. Кнопка «Сохранить» создаёт дополнительную сохранённую версию.';
  }
}

function toast(text, kind = '') {
  const node = $('#toast');
  node.textContent = text;
  node.className = kind === 'error' ? 'show error' : 'show';
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.className = ''; }, kind === 'error' ? 7000 : 4200);
}

async function api(path, body, timeoutMs=0) {
  const options = body === undefined
    ? {}
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  let response;
  const controller=timeoutMs?new AbortController():null;
  const timeout=controller?setTimeout(()=>controller.abort(),timeoutMs):null;
  if(controller)options.signal=controller.signal;
  try { response = await fetch(`/api${path}`, options); }
  catch (error) { if(error.name==='AbortError')throw new Error('Открытие расписания занимает слишком много времени. Повторите загрузку или сохраните диагностику.');throw new Error('Нет связи с приложением. Изменение не сохранено. Закройте и снова откройте «Расписание», затем повторите действие.'); }
  finally {if(timeout)clearTimeout(timeout);}
  let data = null;
  try { data = await response.json(); } catch (error) { data = null; }
  if (!response.ok) {
    if (response.status === 409 && body !== undefined) {
      S.preview=null;
      if(S.ai) {S.ai.preview=null;if(S.ai.response)S.ai.response.draftId=null;}
      await loadState(); await loadDay(); render();
      throw new Error('Расписание изменилось и уже обновлено на экране. Повторите действие с обновлёнными данными.');
    }
    const detail = data && data.detail;
    throw new Error(typeof detail === 'string' ? detail : 'Не удалось выполнить действие.');
  }
  showSaved(response.headers.get('X-Schedule-Saved-At'));
  return data;
}

async function loadState() {
  setSave('busy', 'Обновляем…');
  try {
    const result = await api('/state');
    S.data = result.state;
    S.revision = result.revision;
    showSaved(result.savedAt);
    S.today = result.today;
    if (!S.date) S.date = result.today;
    if (isWeekend(S.date)) S.date = result.today;
    setSave('', 'Сохранено');
  } catch (error) {
    setSave('error', 'Нет связи');
    throw error;
  }
}

async function loadDay() {
  S.day = await api(`/day/${S.date}`);
}

/* --------------------------------------------------------------------------
   model helpers
   -------------------------------------------------------------------------- */

const by = (kind, id) => (S.data?.[kind] || []).find((item) => item.id === id);
const nameOf = (kind, id) => by(kind, id)?.name || '—';
const namesOf = (kind, ids) => (ids || []).map((id) => nameOf(kind, id)).filter(Boolean).join(' / ');
const subjectShort = (id) => id==='school-class-hour'?'Кл/ч':by('subjects', id)?.short || by('subjects', id)?.name || '—';
const subjectName = (id) => id==='school-class-hour'?'Классный час':by('subjects', id)?.name || '—';

function lessonsFor(date) {
  const weekday = dayIndex(date);
  if (S.data.days[date]) return S.data.days[date];
  return S.data.baseLessons.filter((lesson) => Number(lesson.day) === weekday);
}

function baseFor(date) {
  if (S.data.dayBases[date]) return S.data.dayBases[date];
  const weekday = dayIndex(date);
  return S.data.baseLessons.filter((lesson) => Number(lesson.day) === weekday);
}

function cellAt(lessons, field, id, period) {
  return lessons.filter((lesson) => (lesson[field] || []).includes(id) && Number(lesson.period) === Number(period));
}

const signature = (lesson) => (lesson ? JSON.stringify([
  lesson.day, lesson.period, [...(lesson.classIds || [])].sort(), lesson.subjectId,
  [...(lesson.teacherIds || [])].sort(), [...(lesson.roomIds || [])].sort(),
  [...(lesson.classIds || [])].sort().map(c=>[c,lessonGroups(lesson,c)]),
]) : '');

const sameCell = (first, second) => {
  const key = (lessons) => lessons.map(signature).sort().join('|');
  return key(first) === key(second);
};

function diffCount(date) {
  const current = lessonsFor(date);
  const base = baseFor(date);
  const before = new Map(base.map((lesson) => [lesson.id, lesson]));
  const after = new Map(current.map((lesson) => [lesson.id, lesson]));
  let count = 0;
  for (const id of new Set([...before.keys(), ...after.keys()])) {
    if (signature(before.get(id)) !== signature(after.get(id))) count += 1;
  }
  return count;
}

function describe(lesson) {
  if (!lesson) return 'нет занятия';
  const classes = namesOf('classes', lesson.classIds);
  const subject = subjectShort(lesson.subjectId);
  const teachers = namesOf('teachers', lesson.teacherIds);
  const rooms = namesOf('rooms', lesson.roomIds);
  return [classes, subject, teachers, rooms ? `каб. ${rooms}` : ''].filter(Boolean).join(' · ');
}

function fullLesson(lesson) {
  if (!lesson) return 'нет занятия';
  const classes = namesOf('classes', lesson.classIds);
  const subject = subjectName(lesson.subjectId);
  const teachers = namesOf('teachers', lesson.teacherIds);
  const rooms = namesOf('rooms', lesson.roomIds);
  return [classes, subject, teachers, rooms ? `каб. ${rooms}` : ''].filter(Boolean).join(' · ');
}

function lessonMoment(lesson) {
  if (!lesson) return '';
  return `${DAYS[Number(lesson.day)]}, ${lesson.period} урок`;
}

function initials(name) {
  const parts = String(name || '').replace(/\./g, ' ').trim().split(/\s+/);
  return (parts[0]?.[0] || '') + (parts[1]?.[0] || '');
}

function surnameOf(name) {
  return String(name || '').split(/\s+/)[0] || '';
}

function teacherSurnames(ids) {
  return (ids || []).map((id) => surnameOf(nameOf('teachers', id))).filter(Boolean).join(' / ');
}

const AVATAR_TONES = ['#e8ddc8', '#dce7dd', '#ead9d2', '#dfe3ec', '#e9e2d3', '#d9e6e4'];
function avatarTone(name) {
  let hash = 0;
  for (const char of String(name || '')) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return AVATAR_TONES[hash % AVATAR_TONES.length];
}

function plural(number, one, few, many) {
  const value = Math.abs(number) % 100;
  const last = value % 10;
  if (value > 10 && value < 20) return many;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}

/* --------------------------------------------------------------------------
   navigation / shell
   -------------------------------------------------------------------------- */

const NAV = [
  { title: 'День', items: [['day', 'Расписание на день', 'calendar'], ['assistant', 'AI-помощник', 'spark'], ['week', 'Неделя', 'grid']] },
  { title: 'Работа', items: [['plan', 'Учебный план', 'plan'], ['rules', 'Ограничения', 'settings'], ['absences', 'Отсутствия', 'absent'], ['journal', 'Журнал изменений', 'book']] },
  { title: 'Школа', items: [['directory', 'Справочники', 'users'], ['extras', 'Дополнительные занятия', 'calendar'], ['reports', 'Нагрузка', 'chart'], ['settings', 'Настройки', 'settings']] },
  { title: '', items: [['history', 'История и копии', 'history'], ['help', 'Как пользоваться', 'help']] },
];

const PAGE_TITLES = {
  assistant: 'AI-помощник',
  rules: 'Ограничения',
  day: 'Расписание на день', week: 'Неделя', plan: 'Учебный план', absences: 'Отсутствия',
  journal: 'Журнал изменений', directory: 'Справочники', reports: 'Нагрузка',
  extras: 'Дополнительные занятия',
  settings: 'Настройки', history: 'История и копии', help: 'Как пользоваться',
};

function renderNav() {
  const node = $('#nav');
  if (!node || !S.data) return;
  node.innerHTML = NAV.map((group) => `
    ${group.title ? `<div class="nav-label">${esc(group.title)}</div>` : ''}
    ${group.items.map(([id, label, iconName]) => `
      <button type="button" class="nav-link ${S.page === id ? 'active' : ''}" data-action="nav" data-page="${id}" ${S.page === id ? 'aria-current="page"' : ''} title="${esc(label)}">
        ${icon(iconName)}<span>${esc(label)}</span>
        ${id === 'journal' && S.data.journal?.length ? `<span class="count">${S.data.journal.filter((r) => r.active).length}</span>` : ''}
      </button>`).join('')}
  `).join('');
  $('#brand-sub').textContent = `${S.data.school.year} · пятидневка`;
}

function renderCrumb() {
  const school = S.data.school;
  $('#crumb').innerHTML = `
    <strong>${esc(school.year)}</strong><span class="sep">·</span>
    <span>${esc(school.name)}</span><span class="sep">·</span>
    <span>${esc(PAGE_TITLES[S.page] || '')}</span>`;
}

/* --------------------------------------------------------------------------
   shared fragments
   -------------------------------------------------------------------------- */

function pageHead(kicker, title, sub, actions = '') {
  return `
    <div class="page-head">
      <div>
        <div class="kicker">${kicker}</div>
        <h1>${title}</h1>
        ${sub ? `<div class="sub">${sub}</div>` : ''}
      </div>
      <div class="head-actions">${actions}</div>
    </div>`;
}

function dateStrip() {
  const monday = mondayOf(S.date);
  const cards = DAYS_SHORT.map((label, index) => {
    const date = addDays(monday, index);
    const changes = diffCount(date);
    const active = date === S.date;
    return `<button type="button" class="day-card ${active ? 'active' : ''}" data-action="goto-date" data-date="${date}" aria-pressed="${active}">
      <span class="wd">${label}</span>
      <span class="num">${parseDate(date).getDate()}</span>
      ${changes ? '<span class="mark" title="Есть изменения"></span>' : ''}
    </button>`;
  }).join('');
  return `
    <div class="datestrip">
      <div class="day-cards">${cards}</div>
      <div class="week-nav">
        <span class="week-label">${fmtShort(monday)} — ${fmtShort(addDays(monday, 4))}</span>
        <input class="input date-jump" id="date-input" type="date" value="${S.date}" aria-label="Выбрать дату">
        <button type="button" class="btn icon ghost" data-action="prev-week" aria-label="Предыдущая неделя">${icon('left')}</button>
        <button type="button" class="btn icon ghost" data-action="next-week" aria-label="Следующая неделя">${icon('right')}</button>
        <button type="button" class="btn small ghost" data-action="today">Сегодня</button>
      </div>
    </div>`;
}

function statLine(items) {
  return `<div class="stat-row">${items.filter(Boolean).map((item) => `<span>${item}</span>`).join('<span class="sep"></span>')}</div>`;
}

function emptyState(title, text, iconName = 'calendar') {
  return `<div class="empty-state">
    <div class="glyph">${icon(iconName, 24)}</div>
    <h2>${esc(title)}</h2>
    <p>${esc(text)}</p>
  </div>`;
}

function notice(text, kind = '', iconName = 'info') {
  return `<div class="notice ${kind}">${icon(iconName)}<div class="grow">${text}</div></div>`;
}

/* --------------------------------------------------------------------------
   day page
   -------------------------------------------------------------------------- */

function rowList() {
  const kind = S.view;
  let rows = [...(S.data[kind] || [])];
  const query = S.query.trim().toLowerCase();
  if (query) rows = rows.filter((row) => row.name.toLowerCase().includes(query));
  if (S.changesOnly) {
    const current=S.preview?previewDay().lessons:lessonsFor(S.date);
    const base=S.preview?previewDay().base:baseFor(S.date);
    const field = S.view === 'teachers' ? 'teacherIds' : S.view === 'classes' ? 'classIds' : 'roomIds';
    rows = rows.filter((row) => !sameCell(
      current.filter((lesson) => (lesson[field] || []).includes(row.id)),
      base.filter((lesson) => (lesson[field] || []).includes(row.id)),
    ));
  }
  return rows;
}

function rowHead(row) {
  if (S.view === 'teachers') {
    return `<div class="rowhead">
      <span class="avatar" style="background:${avatarTone(row.name)}">${esc(initials(row.name))}</span>
      <div class="who">
        <strong title="${esc(row.name)}">${esc(row.name)}</strong>
        <small>${row.weeklyTarget ? `${row.weeklyTarget} ч в неделю` : 'нагрузка не задана'}</small>
      </div>
    </div>`;
  }
  if (S.view === 'classes') {
    const times=classGroupTimes(row.id);
    return `<div class="rowhead">
      <span class="class-mark">${esc(row.name)}</span>
      <div class="who">
        <strong>${esc(row.name)}</strong>
        <small>${row.size ? `${row.size} учеников` : 'класс'}</small>
        ${times}
      </div>
    </div>`;
  }
  return `<div class="rowhead">
    <span class="class-mark">${esc(row.name)}</span>
    <div class="who">
      <strong>Кабинет ${esc(row.name)}</strong>
      <small>${row.capacity ? `${row.capacity} мест` : 'вместимость не указана'}</small>
    </div>
  </div>`;
}

const GRID_ALIASES = {
  'Физкультура': 'Физ-ра',
  'Экол. культура': 'Экология',
  'Обществозн.': 'Общество',
  'Вероятн. и стат.': 'Вероятность',
  'Разг. о важном': 'Разговоры',
  'Россия: гориз.': 'Россия',
  'Осн. фин. грам.': 'Фин. грам.',
  'Практикум хим.': 'Химия',
  'Инд. проект': 'Проект',
  'Родная лит.': 'Род. лит.',
};

function gridShort(id) {
  const short = subjectShort(id);
  return GRID_ALIASES[short] || short;
}

function lessonGroups(lesson,classId) {
  const groups=lesson.technologyJoint?.classGroups?.[classId];
  return groups ? [...groups].sort() : 'groupIndex' in lesson ? [lesson.groupIndex] : [0,1];
}

function subgroupName(classId,group) {
  return by('classes',classId)?.groupNames?.[group] || `Подгруппа ${group+1}`;
}

function classGroupTimes(classId) {
  const shown=S.preview?previewDay():S.day;
  const periods=[0,1].map(g=>(shown?.lessons || []).filter(l=>l.classIds.includes(classId) && lessonGroups(l,classId).includes(g)).map(l=>l.period));
  const bounds=periods.map(ps=>ps.length ? [Math.min(...ps),Math.max(...ps)] : null);
  if(JSON.stringify(bounds[0])===JSON.stringify(bounds[1]))return '';
  return `<small class="group-times">${bounds.map((range,g)=>`<span>${esc(subgroupName(classId,g))}: ${range?range[0]+(range[0]!==range[1]?'–'+range[1]:'')+' ур.':'нет занятий'}</span>`).join('')}</small>`;
}

function lessonGroupLabel(lesson,row) {
  if(S.view!=='classes')return '';
  const groups=lessonGroups(lesson,row.id);
  if(groups.length===2)return '';
  return `<small class="group-label">${groups.map(g=>esc(subgroupName(row.id,g))).join(', ')}</small>`;
}

function cellContent(view, lesson, room) {
  if (view === 'teachers') {
    return `<span class="subj">${esc(gridShort(lesson.subjectId))}</span>
      <span class="meta"><span class="class-chip">${esc(namesOf('classes', lesson.classIds))}</span>${room ? `каб. ${esc(room)}` : 'кабинет не указан'}</span>`;
  }
  if (view === 'classes') {
    return `<span class="subj">${esc(gridShort(lesson.subjectId))}</span>
      <span class="meta">${esc(teacherSurnames(lesson.teacherIds))}${room ? ` · ${esc(room)}` : ''}</span>`;
  }
  return `<span class="subj"><span class="class-chip">${esc(namesOf('classes', lesson.classIds))}</span>${esc(gridShort(lesson.subjectId))}</span>
    <span class="meta">${esc(teacherSurnames(lesson.teacherIds))}</span>`;
}

function lessonCell(row, period, current, base) {
  const red=!sameCell(current,base);
  if(current.length>1) {
    return `<div class="cell-stack" aria-label="${esc(row.name)}, ${period}-й урок: занятия подгрупп">${current.map(lesson=>lessonCellSingle(row,period,[lesson],base,red)).join('')}</div>`;
  }
  return lessonCellSingle(row,period,current,base,red);
}

function lessonCellSingle(row, period, current, base, red) {
  const lesson = current[0];
  const shown=S.preview?previewDay():S.day;
  if(!lesson && ['teachers','rooms'].includes(S.view)) {
    const busy=(shown.externalActivities || []).filter(activity=>activity.first<=period && period<=activity.last &&
      (S.view==='teachers'?activity.teacherId===row.id:activity.roomId===row.id));
    if(busy.length) {
      const title=busy.map(activity=>`${activity.kind==='primary'?'Начальные классы':'Индивидуальные занятия'}: ${activity.label}`).join('; ');
      return `<button type="button" class="cell external-activity" data-action="nav" data-page="extras" data-row-kind="${S.view}" data-row="${row.id}" data-period="${period}" data-date="${S.date}" title="${esc(title)}" aria-label="${esc(row.name)}, ${period}-й урок: ${esc(title)}. Открыть дополнительные занятия">${busy.map(activity=>`<span class="subj">${activity.kind==='primary'?'Начальные классы':'Индивидуальные занятия'}</span><span class="meta">${esc(activity.label)}${S.view==='teachers' && activity.roomId?' · каб. '+esc(nameOf('rooms',activity.roomId)):S.view==='rooms'?' · '+esc(nameOf('teachers',activity.teacherId)):''}</span>`).join('')}<span class="lock" aria-hidden="true">${icon('lock',10)}</span></button>`;
    }
  }
  const absent=(shown.absences || []).filter(a=>period>=a.first && period<=a.last && (lesson ? lesson.teacherIds.includes(a.teacherId) : S.view==='teachers' && row.id===a.teacherId));
  const relocated=!lesson && base.some(old=>shown.lessons.some(actual=>actual.id===old.id || actual.splitFrom===old.id || actual.joint?.sources.some(source=>source.id===old.id) || actual.technologyJoint?.sourceRefs.some(source=>source.lessonId===old.id)));
  const room = lesson ? namesOf('rooms', lesson.roomIds) : '';
  const partners=lesson?.classIds.filter(c=>c!==row.id) || [];
  const jointLabel=(lesson?.joint || lesson?.technologyJoint) && S.view==='classes' && partners.length?`<small class="joint-label">С ${esc(namesOf('classes',partners))}</small>`:'';
  const title = lesson
    ? `${namesOf('classes', lesson.classIds)} · ${subjectName(lesson.subjectId)} · ${namesOf('teachers', lesson.teacherIds)}${room ? ` · каб. ${room}` : ''}`
    : red ? (relocated?'Занятие перенесено':'Занятие отменено') : 'Нет занятия';
  const attrs=`${S.preview?'data-preview-cell="true"':'data-action="lesson"'} draggable="${lesson && !S.preview?'true':'false'}" data-row-kind="${S.view}" data-row="${row.id}" data-period="${period}" data-date="${S.date}" data-lesson="${lesson?.id || ''}" title="${esc(title)}"`;
  const pupilGap=!lesson && S.view==='classes' && (shown.classGapDetails || []).some(item=>item.classId===row.id && item.periods.includes(period));
  if(pupilGap)return `<button type="button" class="cell pupil-gap" ${attrs} aria-label="${esc(row.name)}, ${period} урок: окно"><span class="subj">Окно</span><span class="meta">Проверьте вариант</span></button>`;
  if (absent.length && !red) {
    return `<button type="button" class="cell absent-cell" ${attrs} aria-label="${esc(row.name)}, ${period} урок: учитель отсутствует"><span class="flag">отсутствие</span>${lesson?cellContent(S.view,lesson,room)+lessonGroupLabel(lesson,row):''}<span class="absence-label">${lesson?'Урок требует перестановки':'Учитель отсутствует'}</span></button>`;
  }
  if (!lesson && !red) {
    return `<button type="button" class="cell empty" ${attrs} aria-label="${esc(`${row.name}, ${period} урок: нет занятия`)}"></button>`;
  }
  if (!lesson && red) {
    return `<button type="button" class="cell changed cancelled" ${attrs} aria-label="${esc(`${row.name}, ${period} урок: ${relocated?'перенесено':'отменено'}`)}">
      <span class="flag">изм.</span>
      <span class="cancelled-mark">—</span>
      <span class="cancelled-label">${relocated?'перенесено':'отменено'}</span>
    </button>`;
  }
  return `<button type="button" class="cell ${red ? 'changed' : ''}" ${attrs} aria-label="${esc(`${row.name}, ${period} урок: ${title}${red ? ', изменено' : ''}`)}">
    ${red ? '<span class="flag">изм.</span>' : ''}
    ${cellContent(S.view, lesson, room)}
    ${lessonGroupLabel(lesson,row)}
    ${jointLabel}
    ${lesson.locked ? `<span class="lock" title="Закреплено">${icon('lock', 10)}</span>` : ''}
  </button>`;
}

function renderGrid() {
  const periods = S.data.school.bells.length;
  const rows = rowList();
  const current=S.preview?previewDay().lessons:lessonsFor(S.date);
  const base=S.preview?previewDay().base:baseFor(S.date);
  const field = S.view === 'teachers' ? 'teacherIds' : S.view === 'classes' ? 'classIds' : 'roomIds';
  const header = `<div class="grid-head corner">${S.view === 'teachers' ? 'Преподаватель' : S.view === 'classes' ? 'Класс' : 'Кабинет'}</div>` +
    S.data.school.bells.map((bell, index) => `
      <div class="grid-head">
        <span class="pnum">${index + 1}</span>
        <span class="ptime">${esc(bell)}</span>
      </div>`).join('');
  const body = rows.map((row) => `
    ${rowHead(row)}
    ${Array.from({ length: periods }, (_, index) => {
      const period = index + 1;
      return lessonCell(row, period, cellAt(current, field, row.id, period), cellAt(base, field, row.id, period));
    }).join('')}
  `).join('');
  return `<div class="grid-wrap"><div class="grid" style="--periods:${periods}">${header}${body}</div></div>`;
}

function renderDay() {
  const day=S.preview?previewDay():S.day;
  if (!day) return `<div class="loading"><span class="skeleton wide"></span><span class="skeleton tall"></span></div>`;
  const changes = day.changes || [];
  const errors = (day.issues || []).filter((item) => item.level === 'error');
  const seenAbsences = new Set();
  const absences = (day.absences || []).filter((item) => {
    const key = JSON.stringify([item.teacherId, item.first, item.last]);
    if (seenAbsences.has(key)) return false;
    seenAbsences.add(key);
    return true;
  });
  const actions = S.preview?'':`
    <button type="button" class="btn" data-action="nav" data-page="assistant">${icon('spark')}Описать изменения</button>
    <button type="button" class="btn" data-action="absence">${icon('plus')}Отметить отсутствие</button>
    <button type="button" class="btn primary" data-action="repair">${icon('spark')}Подобрать замены</button>
    <button type="button" class="btn ghost" data-action="export">${icon('download')}Выгрузить отчёт</button>`;
  const sub = `
    <span>${day.stats.lessons} ${plural(day.stats.lessons, 'занятие', 'занятия', 'занятий')}</span>
    <span class="dot"></span>
    <span>${S.data.teachers.length} ${plural(S.data.teachers.length, 'учитель', 'учителя', 'учителей')}</span>
    <span class="dot"></span>
    <span class="pill ${changes.length ? 'terra' : 'green'}">${changes.length ? `Изменений: ${changes.length}` : 'Без изменений'}</span>
    ${errors.length ? `<span class="pill red">${errors.length} ${plural(errors.length, 'конфликт', 'конфликта', 'конфликтов')}</span>` : ''}`;
  const absenceStrip = absences.length ? `
    <div class="absence-strip">
      ${icon('absent', 16)}
      <span>Отсутствуют:</span>
      ${absences.map((item) => `<span class="who">${esc(item.name)}</span><span class="when">${item.first === item.last ? `${item.first} урок` : `${item.first}–${item.last} уроки`}</span>`).join(', ')}
      ${S.preview?'':'<button type="button" class="text-btn" data-action="repair">подобрать замены</button>'}
    </div>` : '';
  const changedActions = changes.length && !S.preview
    ? `<button type="button" class="text-btn" data-action="changes">Показать изменения (${changes.length})</button>
       <button type="button" class="text-btn" data-action="reset-day">Вернуть день</button>`
    : '';
  return `
    <div class="page">
      ${pageHead('Рабочий день', fmtLongCap(S.date), sub, actions)}
      ${S.preview?schedulePreviewBar():dateStrip()}
      ${!S.preview?(S.day.notices || []).map(text=>notice(text,'warn')).join(''):''}
      ${absenceStrip}
      <div class="toolbar">
        <div class="toolbar-left">
          <div class="segmented" role="group" aria-label="Вид расписания">
            ${[['teachers', 'Учителя'], ['classes', 'Классы'], ['rooms', 'Кабинеты']].map(([value, label]) => `
              <button type="button" data-action="view" data-value="${value}" class="${S.view === value ? 'active' : ''}" aria-pressed="${S.view === value}">${label}</button>`).join('')}
          </div>
          <label class="search">${icon('search')}<input id="search" type="search" placeholder="Найти ${S.view === 'teachers' ? 'учителя' : S.view === 'classes' ? 'класс' : 'кабинет'}" value="${esc(S.query)}" autocomplete="off"></label>
          <label class="check"><input type="checkbox" id="changes-only" ${S.changesOnly ? 'checked' : ''}>Только изменения</label>
        </div>
        <div class="toolbar-right">
          ${changedActions}
          ${S.preview?'':'<button type="button" class="btn small ghost" data-action="show-load">Распределение часов</button>'}
          <button type="button" class="btn small ghost" data-action="issues">${icon('alert')}Проверка</button>
        </div>
      </div>
      ${renderGrid()}
      ${S.preview?'':'<div class="drag-legend">Перетащите урок в нужную клетку. <span id="drag-feedback" role="status"></span></div>'}
      <div style="margin-top:10px">${statLine([
        `<b>${day.stats.errors || 0}</b> конфликтов`,
        changes.length ? `<span class="pill red">Красным отмечено изменённое</span>` : '',
      ])}</div>
      ${S.preview?'':renderDayLoadLocator()}
    </div>`;
}

function renderDayLoadLocator() {
  const kind=S.view==='classes'?'classes':'teachers';
  const id=S.loadId && by(kind,S.loadId) ? S.loadId : (S.data[kind][0]?.id || '');
  return `<div class="load-picker"><label>Часы базовой недели <select class="input" id="load-entity">${S.data[kind].map(r=>`<option value="${r.id}" ${r.id===id?'selected':''}>${esc(r.name)}</option>`).join('')}</select></label></div>${renderLoadLocator(kind,id)}`;
}

/* --------------------------------------------------------------------------
   modal / sheet plumbing
   -------------------------------------------------------------------------- */

function openModal({ title, sub = '', body = '', foot = '', wide = false, small = false }) {
  const modal = $('#modal');
  $('#modal-title').textContent = title;
  $('#modal-sub').textContent = sub;
  $('#modal-body').innerHTML = body;
  $('#modal-foot').innerHTML = foot;
  modal.classList.toggle('wide', Boolean(wide));
  modal.classList.toggle('small', Boolean(small));
  if (!modal.open) modal.showModal();
  modal.querySelector('.modal-body').scrollTop = 0;
}

function closeModal() {
  const modal = $('#modal');
  if (modal.open) modal.close();
}

function askConfirm({ title, text, sub = '', yes = 'Продолжить', danger = false }) {
  return new Promise((resolve) => {
    const dialog = $('#confirm');
    S.confirmResolve = resolve;
    $('#confirm-title').textContent = title;
    $('#confirm-sub').textContent = sub;
    $('#confirm-body').innerHTML = `<div class="notice ${danger ? 'error' : 'info'}">${icon(danger ? 'alert' : 'info')}<div class="grow">${esc(text)}</div></div>`;
    const button = $('#confirm-yes');
    button.className = `btn ${danger ? 'danger' : 'primary'}`;
    button.textContent = yes;
    if (!dialog.open) dialog.showModal();
  });
}

function resolveConfirm(value) {
  const dialog = $('#confirm');
  const resolve = S.confirmResolve;
  S.confirmResolve = null;
  if (dialog.open) dialog.close();
  if (resolve) resolve(value);
}

function openSheet({ title, sub = '', body = '', foot = '', submit = null }) {
  const sheet = $('#sheet');
  $('#sheet-title').textContent = title;
  $('#sheet-sub').textContent = sub;
  $('#sheet-body').innerHTML = body;
  $('#sheet-foot').innerHTML = foot;
  $('#sheet-error')?.remove();
  S.sheetSubmit = submit;
  if (!sheet.open) sheet.showModal();
  sheet.querySelector('.modal-body').scrollTop = 0;
}

function closeSheet() {
  const sheet = $('#sheet');
  if (sheet.open) sheet.close();
  S.sheetSubmit = null;
}

function sheetError(message) {
  let node = $('#sheet-error');
  if (!node) {
    node = document.createElement('div');
    node.id = 'sheet-error';
    node.className = 'form-error';
    $('#sheet-body').appendChild(node);
  }
  node.textContent = message;
  node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function modalError(message) {
  let node = $('#modal-error');
  if (!node) {
    node = document.createElement('div');
    node.id = 'modal-error';
    node.className = 'form-error';
    $('#modal-body').appendChild(node);
  }
  node.textContent = message;
}

function button(label, action, kind = '', iconName = '', attrs = '') {
  return `<button type="button" class="btn ${kind}" data-action="${action}" ${attrs}>${iconName ? icon(iconName) : ''}${esc(label)}</button>`;
}

/* --------------------------------------------------------------------------
   changes / issues
   -------------------------------------------------------------------------- */

function changeRow(change) {
  const before = change.before;
  const after = change.after;
  if (!after) {
    const moved = change.movedTo ? `Перенесено на ${DAYS[dayIndex(change.movedTo)]}, ${fmtDate(change.movedTo)}` : 'Отменено';
    return `<div class="change-row">
      <div class="old">${esc(fullLesson(before))}</div>
      <div class="arrow">→</div>
      <div class="new ${change.movedTo ? '' : 'cancel'}">${esc(moved)}<small>${esc(lessonMoment(before))}</small></div>
    </div>`;
  }
  if (!before) {
    return `<div class="change-row">
      <div class="old">Добавлено</div>
      <div class="arrow">→</div>
      <div class="new">${esc(fullLesson(after))}<small>${esc(lessonMoment(after))}</small></div>
    </div>`;
  }
  return `<div class="change-row">
    <div class="old">${esc(fullLesson(before))}<small>${esc(lessonMoment(before))}</small></div>
    <div class="arrow">→</div>
    <div class="new">${esc(fullLesson(after))}<small>${esc(lessonMoment(after))}</small></div>
  </div>`;
}

function openChanges() {
  const changes = S.day.changes || [];
  if (!changes.length) {
    openModal({ title: 'Изменений нет', body: notice('Этот день совпадает с базовым расписанием.', 'success'), foot: button('Закрыть', 'close-modal', 'ghost') });
    return;
  }
  openModal({
    title: `Изменения на ${fmtLong(S.date)}`,
    sub: `${changes.length} ${plural(changes.length, 'запись', 'записи', 'записей')}`,
    body: `<div class="change-list">${changes.slice(0, 80).map(changeRow).join('')}</div>`,
    foot: `<span class="left">${button('Вернуть день', 'reset-day', 'danger')}</span>${button('Закрыть', 'close-modal', 'primary')}`,
    wide: true,
  });
}

function openIssues() {
  const list = S.day.issues || [];
  const errors = list.filter((item) => item.level === 'error');
  openModal({
    title: 'Проверка расписания',
    sub: errors.length ? `${errors.length} конфликтов` : 'Конфликтов нет',
    body: list.length
      ? `<div class="change-list">${list.map((item) => `<div class="notice ${item.level === 'error' ? 'error' : 'warn'}">${icon(item.level === 'error' ? 'alert' : 'clock')}<div class="grow">${esc(item.message)}</div></div>`).join('')}</div>`
      : notice('Пересечений, отсутствующих учителей и окон не найдено.', 'success'),
    foot: button('Закрыть', 'close-modal', 'primary'),
    wide: true,
  });
}

/* --------------------------------------------------------------------------
   repair
   -------------------------------------------------------------------------- */

function openRepair() {
  const absences = S.day.absences || [];
  const nameList = absences.map((item) => item.name).join(', ');
  const body = `
    ${absences.length
      ? `<div class="notice info">${icon('absent')}<div class="grow"><strong>Отсутствуют:</strong> ${esc(nameList)}. Программа сохранит уроки с их учителями, поменяет местами занятия и, если урок провести некем, отменит его.</div></div>`
      : `<div class="notice warn">${icon('alert')}<div class="grow">На этот день нет отмеченных отсутствий. Сначала отметьте учителя, который заболел.</div></div>`}
    <div class="form-grid" style="margin-top:16px">
      <label class="field"><span>Причина</span><input class="input" id="repair-reason" value="${esc(absences.length ? `Болезнь: ${nameList}` : 'Изменение расписания')}"></label>
      <div class="notice">${icon('info')}<div class="grow">Перестановки выполняются только сегодня, каждый урок сохраняет своего учителя. Если провести его сегодня невозможно, урок отменяется.</div></div>
    </div>`;
  const foot = `${absences.length ? '' : button('Отметить отсутствие', 'absence-from-repair', 'ghost')}${button('Закрыть', 'close-modal', 'ghost')}${button('Подобрать', 'run-repair', 'primary', 'spark')}`;
  openModal({ title: 'Подобрать замены', sub: fmtLongCap(S.date), body, foot });
}

async function runRepair() {
  const otherDays = false;
  const reason = $('#repair-reason')?.value || 'Изменение расписания';
  const foot = $('#modal-foot');
  const oldFoot = foot.innerHTML;
  foot.innerHTML = `${button('Отмена', 'close-modal', 'ghost')}<span class="btn primary" aria-disabled="true">${icon('spark')}Подбираем…</span>`;
  try {
    const result = await api('/repair', { revision: S.revision, date: S.date, allowOtherDays: otherDays, reason });
    S.repairResult = result;
    S.repairContext = { otherDays, reason };
    S.selectedVariant = result.recommended ?? result.variants?.[0]?.id ?? 0;
    renderRepairPreview();
  } catch (error) {
    foot.innerHTML = oldFoot;
    modalError(error.message);
  }
}

function mergedChanges(result) {
  const out = [];
  const others = Object.values(result.otherChanges || {}).flat();
  for (const change of result.changes || []) {
    if (change.movedTo) {
      const target = others.find((row) => row.id === change.id && row.after);
      out.push({ ...change, after: target?.after || change.after });
    } else {
      out.push(change);
    }
  }
  for (const row of others) {
    if (row.after && !row.before && !out.some((item) => item.id === row.id)) out.push(row);
  }
  return out;
}

function selectedVariant() {
  const variants = S.repairResult?.variants || [];
  return variants.find((item) => item.id === S.selectedVariant) || variants[0] || S.repairResult;
}

function renderRepairPreview() {
  const result = S.repairResult;
  if (!result) return;
  const variants = result.variants || [result];
  const selected = selectedVariant();
  if (!selected) return;
  if(['ok','unchanged'].includes(selected.status) && selected.after) {
    showSchedulePreview('repair',S.date,variants,S.selectedVariant).catch(error=>toast(error.message,'error'));
    return;
  }
  if (selected.status === 'unchanged') {
    openModal({
      title: 'Изменения не нужны',
      sub: fmtLongCap(S.date),
      body: notice('Все уроки уже стоят правильно. У учеников нет окон.', 'success'),
      foot: button('Закрыть', 'close-modal', 'primary'),
    });
    return;
  }
  const stats = selected.stats || {};
  const rows = mergedChanges(selected);
  const warnings = (selected.warnings || []).map((text) => `<div class="notice warn">${icon('alert')}<div class="grow">${esc(text)}</div></div>`).join('');
  const movedCount = rows.filter((row) => row.before && row.after).length;
  const cancelledCount = rows.filter((row) => !row.after).length;
  const cards = variants.length > 1 ? `
    <div class="variant-strip">
      ${variants.map((item, index) => `
        <button type="button" class="variant-card ${item.id === selected.id ? 'active' : ''}" data-action="select-variant" data-id="${item.id}">
          <span class="v-name">${item.id === result.recommended ? 'Основной вариант' : `Другой вариант ${index + 1}`}</span>
          <span class="v-title">${esc(item.title)}</span>
          <span class="v-stats">${item.stats?.moved || 0} переставлено · ${item.stats?.cancelled || 0} отменено${item.stats?.groupLosses ? ' · занятий подгрупп отменено: '+item.stats.groupLosses : ''}${item.stats?.groupSplits ? ` · ${item.stats.groupSplits} группа` : ''}</span>
        </button>`).join('')}
    </div>` : '';
  const body = `
    ${cards}
    <div class="facts">
      <div class="green"><strong>${movedCount}</strong><span>${plural(movedCount, 'урок переставлен', 'урока переставлено', 'уроков переставлено')}</span></div>
      <div class="${cancelledCount ? 'red' : ''}"><strong>${cancelledCount}</strong><span>${plural(cancelledCount, 'урок отменён', 'урока отменено', 'уроков отменено')}</span></div>
      <div><strong>${Math.round((stats.seconds || 0) * 1000)}</strong><span>миллисекунд</span></div>
      <div><strong>${stats.classGapsAfter ?? 0}</strong><span>окон у классов</span></div>
    </div>
    ${warnings}
    ${rows.length ? `<div class="change-list" style="margin-top:14px">${rows.map(changeRow).join('')}</div>` : notice('Изменений нет.', 'success')}
    ${selected.status !== 'ok' ? notice('Полный вариант не найден. Исходное расписание не изменено.', 'error') : ''}`;
  const apply = selected.status === 'ok'
    ? button('Применить', 'apply-repair', 'primary', 'check', `data-other="${S.repairContext?.otherDays ? 1 : 0}" data-reason="${esc(S.repairContext?.reason || '')}" data-variant="${selected.id}"`)
    : '';
  const selectedIndex = variants.findIndex((item) => item.id === selected.id) + 1;
  openModal({
    title: selected.status === 'ok' ? (variants.length > 1 ? 'Варианты готовы' : 'Вариант готов') : 'Нужна проверка',
    sub: `${fmtLongCap(S.date)} · вариант ${selectedIndex} · ${rows.length} ${plural(rows.length, 'изменение', 'изменения', 'изменений')}`,
    body,
    foot: `${button('Назад', 'repair', 'ghost')}${apply || button('Закрыть', 'close-modal', 'primary')}`,
    wide: true,
  });
}

async function applyRepair(buttonNode) {
  const otherDays = buttonNode.dataset.other === '1';
  const reason = buttonNode.dataset.reason || 'Автоматический подбор';
  const variant = Number(buttonNode.dataset.variant || 0);
  buttonNode.disabled = true;
  buttonNode.innerHTML = `${icon('spark')}Применяем…`;
  try {
    const result = await api('/repair/apply', {
      revision: S.repairResult.revision, previewId: selectedVariant().previewId, date: S.date, allowOtherDays: otherDays, reason, variant,
    });
    S.data = result.state;
    S.revision = result.revision;
    S.day = result.day;
    S.repairResult = null;
    S.preview=null;
    closeModal();
    render();
    toast('Изменения применены. Красным отмечено, что поменялось.');
  } catch (error) {
    buttonNode.disabled = false;
    buttonNode.innerHTML = `${icon('check')}Применить`;
    if(S.preview)toast(error.message,'error');else modalError(error.message);
  }
}

/* --------------------------------------------------------------------------
   export
   -------------------------------------------------------------------------- */

function openExport() {
  openModal({title:'Выгрузить отчёт',sub:fmtLongCap(S.date),
    body:`<label class="field"><span>Расписание</span><select class="input" id="export-mode"><option value="changes">Текущее, изменения красным</option><option value="clean">Текущее, без выделений</option><option value="base">Базовое</option></select></label>`,
    foot:`${button('Для учеников','download-export','ghost','download','data-audience="students"')}${button('Для учителей','download-export','primary','download','data-audience="teachers"')}`});
}

async function savePreparedFile(blob, filename) {
  if(window.chrome?.webview) {
    const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(blob);});
    const id=crypto.randomUUID();
    return await new Promise((resolve,reject)=>{
      const receive=event=>{
        if(event.data?.kind!=='save-export-result' || event.data.id!==id)return;
        window.chrome.webview.removeEventListener('message',receive);
        if(event.data.error)reject(new Error(event.data.error));
        else resolve(event.data);
      };
      window.chrome.webview.addEventListener('message',receive);
      window.chrome.webview.postMessage({kind:'save-export',id,name:filename,content});
    });
  }
  const link=document.createElement('a');
  const objectUrl=URL.createObjectURL(blob);
  link.href=objectUrl;link.download=filename;document.body.appendChild(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(objectUrl),60000);
  return {browser:true}; // Browser cannot confirm whether its download was saved.
}

function showExportResult(result) {
  if(!result?.saved)return;
  if(result.fallback) {
    openModal({title:'Отчёт сохранён',body:`<p>Windows не разрешила запись в выбранную папку. Файл сохранён в папке «${esc(result.folder || 'Готовые отчёты')}».</p><p style="margin-top:12px">${esc(result.name)}</p>`,foot:`<button type="button" class="btn" data-action="open-export-folder" data-token="${esc(result.token)}">Открыть папку</button><button type="button" class="btn primary" data-action="open-export" data-token="${esc(result.token)}">Открыть файл</button>`});
  } else {closeModal();toast('Файл сохранён.');}
}

if(window.chrome?.webview)window.chrome.webview.addEventListener('message',event=>{
  if(event.data?.kind==='export-open-error')askConfirm({title:'Отчёт сохранён, но не открыт',text:event.data.error,yes:'Понятно'});
});

async function downloadFile(url, filename) {
  const response = await fetch(url);
  if (!response.ok) throw new Error('Не удалось скачать файл.');
  const blob = await response.blob();
  showExportResult(await savePreparedFile(blob,filename || 'Расписание.json'));
}

async function downloadExport(buttonNode) {
  const audience = buttonNode.dataset.audience;
  const names=1;
  const mode=$('#export-mode')?.value || 'changes';
  buttonNode.disabled = true;
  const label = buttonNode.innerHTML;
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),60000);
  buttonNode.innerHTML = `${icon('clock')}Готовим…`;
  try {
    const response = await fetch(`/api/export/${audience}/${S.date}?names=${names}&mode=${mode}`,{signal:controller.signal});
    if (!response.ok) {
      let detail = 'Не удалось подготовить отчёт.';
      try { const data = await response.json(); if (typeof data.detail === 'string') detail = data.detail; } catch (error) { /* ignore */ }
      throw new Error(detail);
    }
    const blob = await response.blob();
    const disposition=response.headers.get('Content-Disposition') || '';
    const encoded=disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const filename=encoded?decodeURIComponent(encoded[1]):'Расписание.docx';
    const saved=await savePreparedFile(blob,filename);
    showExportResult(saved);
  } catch (error) {
    await askConfirm({title:'Не удалось сохранить документ',text:error.name==='AbortError'?'Подготовка отчёта заняла слишком много времени. Повторите сохранение.':error.message,yes:'Понятно'});
  } finally {
    clearTimeout(timer);
    buttonNode.disabled = false;
    buttonNode.innerHTML = label;
  }
}

/* --------------------------------------------------------------------------
   lesson sheet
   -------------------------------------------------------------------------- */

function teacherChecks(subjectId, selected = []) {
  let teachers = S.data.teachers.filter((teacher) => (teacher.subjectIds || []).includes(subjectId));
  let note = '';
  if (!teachers.length) {
    teachers = S.data.teachers;
    note = `<div class="notice warn" style="margin-top:6px">${icon('alert')}<div class="grow">В карточках учителей этот предмет не отмечен. Показаны все учителя — проверьте, пожалуйста.</div></div>`;
  }
  return `<div class="check-grid">${teachers.map((teacher) => `
    <label class="check"><input type="checkbox" name="teacherIds" value="${teacher.id}" ${selected.includes(teacher.id) ? 'checked' : ''}>${esc(teacher.name)}</label>`).join('')}</div>${note}`;
}

function roomChecks(selected = []) {
  return `<div class="check-grid">${S.data.rooms.map((room) => `
    <label class="check"><input type="checkbox" name="roomIds" value="${room.id}" ${selected.includes(room.id) ? 'checked' : ''}>${esc(room.name)}</label>`).join('')}</div>`;
}

function accessChecks(kind, selected = []) {
  const items = S.data[kind] || [];
  return `<div class="check-grid">${items.map((item) => `
    <label class="check"><input type="checkbox" name="${kind === 'subjects' ? 'subjectIds' : 'classIds'}" value="${item.id}" ${selected.includes(item.id) ? 'checked' : ''}>${esc(item.name)}</label>`).join('')}</div>`;
}

function openLessonSheet(dataset) {
  const scope = dataset.scope || 'day';
  const date = dataset.date || S.date;
  const source = scope === 'base'
    ? S.data.baseLessons.filter((lesson) => Number(lesson.day) === dayIndex(date))
    : lessonsFor(date);
  const existing = source.find((lesson) => lesson.id === dataset.lesson);
  const rowKind = dataset.rowKind || 'classes';
  const row = dataset.row;
  const period = Number(dataset.period) || 1;
  const eighth=S.data.school.eighthPeriodException;
  const special=existing && eighth && existing.subjectId===eighth.subjectId && JSON.stringify([...existing.classIds].sort())===JSON.stringify([...eighth.classIds].sort()) && JSON.stringify([...existing.teacherIds].sort())===JSON.stringify([...eighth.teacherIds].sort());
  const datedEighth=scope==='day' && existing?.eighthOn===date;
  if(period>7 && !(special && dayIndex(date)===eighth.day) && !datedEighth) {toast('Для восьмого урока нужно явное исключение на эту дату. Его можно задать через AI-помощника.','error');return;}
  const firstClass = rowKind === 'classes' ? row : (existing?.classIds?.[0] || S.data.classes[0]?.id);
  const firstSubject = rowKind === 'teachers'
    ? (by('teachers', row)?.subjectIds?.[0] || S.data.subjects[0]?.id)
    : (existing?.subjectId || S.data.subjects[0]?.id);
  const lesson = existing || {
    id: '', day: dayIndex(date), period, classIds: firstClass ? [firstClass] : [],
    subjectId: firstSubject, teacherIds: rowKind === 'teachers' ? [row] : [],
    roomIds: rowKind === 'rooms' ? [row] : [], locked: false,
  };
  const swaps = existing
    ? source.filter((item) => item.id !== existing.id && item.period !== existing.period
      && JSON.stringify([...(item.classIds || [])].sort()) === JSON.stringify([...(existing.classIds || [])].sort()))
    : [];
  const body = `
    <div class="form-grid">
      <div class="form-grid two">
        <label class="field"><span>Класс</span><select class="input" name="classId" required>
          ${S.data.classes.map((item) => `<option value="${item.id}" ${item.id === lesson.classIds?.[0] ? 'selected' : ''}>${esc(item.name)}</option>`).join('')}
        </select></label>
        <label class="field"><span>Предмет</span><select class="input" name="subjectId" required>
          ${S.data.subjects.map((item) => `<option value="${item.id}" ${item.id === lesson.subjectId ? 'selected' : ''}>${esc(item.name)}</option>`).join('')}
        </select></label>
      </div>
      <div>
        <span class="field-label">Преподаватель</span>
        <div id="lesson-teachers">${teacherChecks(lesson.subjectId, lesson.teacherIds || [])}</div>
      </div>
      <div class="notice">${icon('info')}<div class="grow">Обычные уроки сохраняют своих преподавателей. Исключения для совместных занятий и технологии согласуются отдельно. Постоянные назначения меняются в разделе «Неделя».</div></div>
      ${scope==='day' && existing && (existing.classHour || classHourEligible(existing))?`<label class="check"><input type="checkbox" name="classHour" ${existing.classHour?'checked':''}>Классный час (Кл/ч)${existing.classIds.length>1?' · '+esc(namesOf('classes',existing.classIds)):''}</label>`:''}
      <div class="form-grid two">
        <label class="field"><span>Номер урока</span><select class="input" name="period">
          ${S.data.school.bells.map((bell,index)=>({bell,period:index+1})).filter(slot=>lesson.classHour?slot.period===lesson.period:special?slot.period===8:slot.period<=7 || datedEighth).map(slot=>`<option value="${slot.period}" ${slot.period===lesson.period?'selected':''}>${slot.period} · ${esc(slot.bell)}</option>`).join('')}
        </select></label>
        <label class="field"><span>Обменять с уроком этого класса</span><select class="input" name="swapId">
          <option value="">Без обмена</option>
          ${swaps.map((item) => `<option value="${item.id}">${item.period} урок · ${esc(subjectShort(item.subjectId))}</option>`).join('')}
        </select></label>
      </div>
      <div>
        <span class="field-label">Кабинет</span>
        ${roomChecks(lesson.roomIds || [])}
      </div>
      <div class="form-grid two">
        <label class="check"><input type="checkbox" name="locked" ${lesson.locked ? 'checked' : ''}>Закрепить занятие</label>
        <label class="field"><span>Причина изменения</span><input class="input" name="reason" value="Ручная правка"></label>
      </div>
    </div>`;
  const foot = `${existing ? `<button type="button" class="btn danger" data-action="remove-lesson">${icon('closeCircle')}Отменить занятие</button>` : ''}
    <span class="left"></span>${button('Отмена', 'close-sheet', 'ghost')}<button type="submit" class="btn primary">${icon('check')}Сохранить</button>`;
  openSheet({
    title: existing ? 'Изменить занятие' : 'Добавить занятие',
    sub: `${fmtLongCap(date)} · ${scope === 'base' ? 'постоянное расписание' : 'только этот день'}`,
    body,
    foot,
    submit: async (form) => { await submitLesson(form, { existing, date, scope }); },
  });
  S.lessonContext = { existing, date, scope };
  if (existing && scope === 'day') {
    for (const node of $$('#sheet-form [name=classId], #sheet-form [name=subjectId], #sheet-form [name=teacherIds]')) node.disabled = true;
    $('#lesson-teachers').insertAdjacentHTML('beforeend', '<small class="muted">Переставляется этот урок со своим учителем. Постоянные назначения меняются в разделе «Неделя».</small>');
  }
  $('#sheet-form [name=subjectId]').addEventListener('change', (event) => {
    const selected = [...formChecked('teacherIds')];
    $('#lesson-teachers').innerHTML = teacherChecks(event.target.value, selected);
  });
  $('#sheet-form [name=swapId]').addEventListener('change', (event) => {
    const other = swaps.find((item) => item.id === event.target.value);
    if (other) $('#sheet-form [name=period]').value = other.period;
  });
  const hourBox=$('#sheet-form [name=classHour]');
  if(hourBox) {
    const update=()=>{
      const period=$('#sheet-form [name=period]'),swap=$('#sheet-form [name=swapId]');
      for(const option of period.options)option.disabled=hourBox.checked && option.value!=='1';
      swap.disabled=hourBox.checked;
      if(hourBox.checked) {period.value='1';swap.value='';}
    };
    hourBox.addEventListener('change',update);update();
  }
}

function formChecked(name) {
  return $$(`#sheet-form [name="${name}"]:checked`).map((node) => node.value);
}

document.addEventListener('dblclick', event => {
  const cell = event.target.closest('[data-week-edit]');
  if (cell) openLessonSheet(cell.dataset);
});
document.addEventListener('keydown', event => {
  if (event.key === 'Enter' && event.target.matches('[data-week-edit]')) {
    event.preventDefault(); openLessonSheet(event.target.dataset);
  }
});

async function submitLesson(form, context) {
  const data = new FormData(form);
  if (context.scope==='day' && context.existing && data.has('classHour')!==!!context.existing.classHour) {
    if(Number(data.get('period'))!==context.existing.period || data.get('swapId'))throw new Error('Сначала сохраните перестановку, затем назначьте классный час на выбранном месте.');
    const result=await api('/lesson/class-hour',{revision:S.revision,date:context.date,lessonId:context.existing.id,enabled:data.has('classHour'),roomIds:formChecked('roomIds')});
    S.data=result.state;S.revision=result.revision;S.day=result.day;closeSheet();render();toast('Сохранено.');return;
  }
  const teacherIds = formChecked('teacherIds');
  if (!teacherIds.length) throw new Error('Выберите преподавателя.');
  const lesson = {
    ...(context.existing || {}),
    id: context.existing?.id || '',
    day: dayIndex(context.date),
    period: Number(data.get('period')),
    classIds: context.existing && context.scope === 'day' ? context.existing.classIds : [data.get('classId')],
    subjectId: context.existing && context.scope === 'day' ? context.existing.subjectId : data.get('subjectId'),
    teacherIds,
    roomIds: formChecked('roomIds'),
    locked: data.has('locked'),
  };
  const result = await api('/lesson', {
    revision: S.revision,
    scope: context.scope,
    date: context.date,
    lesson,
    swapId: data.get('swapId') || '',
    remove: false,
    reason: data.get('reason') || 'Ручная правка',
  });
  S.data = result.state;
  S.revision = result.revision;
  if (context.scope === 'day') S.day = result.day;
  else { await loadDay(); }
  closeSheet();
  render();
  toast('Занятие сохранено.');
}

async function removeLesson() {
  const context = S.lessonContext;
  if (!context?.existing) return;
  if (!(await askConfirm({ title: 'Отменить занятие?', text: 'Изменение попадёт в журнал, клетка останется красной.', yes: 'Отменить занятие', danger: true }))) return;
  try {
    const result = await api('/lesson', {
      revision: S.revision,
      scope: context.scope,
      date: context.date,
      lesson: { ...context.existing, day: dayIndex(context.date) },
      remove: true,
      reason: 'Отмена занятия',
    });
    S.data = result.state;
    S.revision = result.revision;
    if (context.scope === 'day') S.day = result.day;
    else await loadDay();
    closeSheet();
    render();
    toast('Занятие отменено. Клетка останется красной.');
  } catch (error) {
    sheetError(error.message);
  }
}

/* --------------------------------------------------------------------------
   absence sheet
   -------------------------------------------------------------------------- */

function openAbsenceSheet(id = '') {
  const existing = id ? by('absences', id) : null;
  const record = existing || {
    id: '', teacherId: '', start: S.date, end: S.date,
    first: 1, last: S.data.school.bells.length, reason: 'Болезнь',
  };
  const body = `
    <div class="form-grid">
      <label class="field"><span>Преподаватель</span><select class="input" name="teacherId" required>
        <option value="">Выберите…</option>
        ${S.data.teachers.map((teacher) => `<option value="${teacher.id}" ${teacher.id === record.teacherId ? 'selected' : ''}>${esc(teacher.name)}</option>`).join('')}
      </select></label>
      <div class="form-grid two">
        <label class="field"><span>С даты</span><input class="input" type="date" name="start" value="${record.start}" required></label>
        <label class="field"><span>По дату включительно</span><input class="input" type="date" name="end" value="${record.end}" required></label>
      </div>
      <div class="form-grid two">
        <label class="field"><span>С урока</span><input class="input" type="number" min="1" max="12" name="first" value="${record.first}"></label>
        <label class="field"><span>По урок</span><input class="input" type="number" min="1" max="12" name="last" value="${record.last}"></label>
      </div>
      <label class="field"><span>Причина</span><input class="input" name="reason" value="${esc(record.reason)}"></label>
      <div class="notice info">${icon('info')}<div class="grow">Отсутствие само не меняет расписание. После сохранения нажмите «Сохранить и подобрать» — программа переставит уроки и покажет вариант.</div></div>
    </div>`;
  const foot = `${existing ? `<button type="button" class="btn danger" data-action="delete-absence" data-id="${existing.id}">Удалить</button>` : ''}
    ${button('Только сохранить', 'save-absence', 'ghost')}<button type="button" class="btn primary" data-action="save-absence" data-repair="1">${icon('spark')}Сохранить и подобрать</button>`;
  openSheet({
    title: existing ? 'Изменить отсутствие' : 'Учитель отсутствует',
    sub: 'Отсутствие учитывается при подборе на выбранные даты',
    body,
    foot,
  });
  S.absenceId = id;
}

async function saveAbsence(repairAfter) {
  const form = $('#sheet-form');
  const data = new FormData(form);
  if (!data.get('teacherId')) { sheetError('Выберите учителя.'); return; }
  try {
    const record = {
      id: S.absenceId || '',
      teacherId: data.get('teacherId'),
      start: data.get('start'),
      end: data.get('end'),
      first: Number(data.get('first')),
      last: Number(data.get('last')),
      reason: data.get('reason') || 'Отсутствие',
    };
    const result = await api('/entity/absences', { revision: S.revision, record });
    S.data = result.state;
    S.revision = result.revision;
    S.date = nextSchoolDay(record.start);
    await loadDay();
    closeSheet();
    render();
    if (repairAfter) setTimeout(openRepair, 180);
    else toast('Отсутствие сохранено. Теперь можно подобрать замены.');
  } catch (error) {
    sheetError(error.message);
  }
}

async function deleteAbsence(id) {
  if (!(await askConfirm({ title: 'Удалить отсутствие?', text: 'Учитель снова появится в проверке этого дня.', yes: 'Удалить', danger: true }))) return;
  try {
    const result = await api('/entity/absences/delete', { revision: S.revision, id });
    S.data = result.state;
    S.revision = result.revision;
    await loadDay();
    closeSheet();
    render();
    toast('Отсутствие удалено.');
  } catch (error) {
    sheetError(error.message);
  }
}

/* --------------------------------------------------------------------------
   entity sheet (directories and plan)
   -------------------------------------------------------------------------- */

const KIND_TITLES = { teachers: 'учителя', classes: 'класс', subjects: 'предмет', rooms: 'кабинет', plan: 'строку плана' };

function openEntitySheet(kind, id = '') {
  const existing = id ? by(kind, id) : null;
  const record = existing || {};
  let body = '';
  if (kind === 'teachers') {
    body = `
      <div class="form-grid">
        <label class="field"><span>Фамилия и инициалы</span><input class="input" name="name" value="${esc(record.name || '')}" required></label>
        <div class="form-grid two">
          <label class="field"><span>Недельная норма, ч</span><input class="input" type="number" min="0" max="60" name="weeklyTarget" value="${record.weeklyTarget ?? ''}"></label>
          <label class="field"><span>Не более уроков в день</span><input class="input" type="number" min="1" max="12" name="maxDaily" value="${record.maxDaily || 8}"></label>
        </div>
        <div>
          <span class="field-label">Может преподавать</span>
          ${accessChecks('subjects', record.subjectIds || [])}
        </div>
        <div class="form-grid two">
          <label class="field"><span>Классное руководство</span><input class="input" name="homeroom" value="${esc(S.data.classes.filter(c=>c.homeroomTeacherId===record.id).map(c=>c.name).join(', '))}" placeholder="Например: 5г, 6д"></label>
          <label class="field"><span>Кабинет</span><input class="input" name="note" value="${esc(record.note || '')}"></label>
        </div>
      </div>`;
  } else if (kind === 'classes') {
    body = `
      <div class="form-grid">
        <label class="field"><span>Название класса</span><input class="input" name="name" value="${esc(record.name || '')}" required></label>
        <label class="field"><span>Классный руководитель</span><select class="input" name="homeroomTeacherId"><option value="">Не указан</option>${S.data.teachers.map(t=>`<option value="${esc(t.id)}" ${t.id===record.homeroomTeacherId?'selected':''}>${esc(t.name)}</option>`).join('')}</select></label>
        <div class="form-grid three">
          <label class="field"><span>Учеников</span><input class="input" type="number" min="0" max="100" name="size" value="${record.size || 0}"></label>
          <label class="field"><span>Уроков в день</span><input class="input" type="number" min="1" max="12" name="maxDaily" value="${record.maxDaily || 8}"></label>
          <label class="field"><span>С какого урока</span><input class="input" type="number" min="1" max="12" name="firstPeriod" value="${record.firstPeriod || 1}"></label>
        </div>
      </div>`;
  } else if (kind === 'subjects') {
    body = `
      <div class="form-grid">
        <label class="field"><span>Название предмета</span><input class="input" name="name" value="${esc(record.name || '')}" required></label>
        <div class="form-grid two">
          <label class="field"><span>Короткое имя для Word</span><input class="input" name="short" value="${esc(record.short || '')}" maxlength="30" required><small>Именно оно попадает в клетку таблицы. Например: «Англ. яз.».</small></label>
          <label class="field"><span>Код в таблице учителей</span><input class="input" name="teacherCode" value="${esc(record.teacherCode || '')}" maxlength="12"><small>Например: р, л, э. Можно оставить пустым.</small></label>
        </div>
        <label class="field"><span>Трудность, 1–12</span><input class="input" type="number" min="1" max="12" name="difficulty" value="${record.difficulty || 5}"></label>
      </div>`;
  } else if (kind === 'rooms') {
    body = `
      <div class="form-grid">
        <label class="field"><span>Номер или название</span><input class="input" name="name" value="${esc(record.name || '')}" required></label>
        <div class="form-grid two">
          <label class="field"><span>Вместимость</span><input class="input" type="number" min="0" max="300" name="capacity" value="${record.capacity || 0}"></label>
          <label class="field"><span>Этаж</span><input class="input" name="floor" value="${esc(record.floor || '')}"></label>
        </div>
        <div>
          <span class="field-label">Разрешённые предметы</span>
          ${accessChecks('subjects', record.subjectIds || [])}
        </div>
        <div class="form-grid two">
          <label class="field"><span>Закреплённый класс</span><select class="input" name="classId"><option value="">Нет</option>${S.data.classes.map((item) => `<option value="${item.id}" ${item.id === record.classId ? 'selected' : ''}>${esc(item.name)}</option>`).join('')}</select></label>
          <label class="field"><span>Закреплённый учитель</span><select class="input" name="teacherId"><option value="">Нет</option>${S.data.teachers.map((item) => `<option value="${item.id}" ${item.id === record.teacherId ? 'selected' : ''}>${esc(item.name)}</option>`).join('')}</select></label>
        </div>
      </div>`;
  } else if (kind === 'plan') {
    body = `
      <div class="form-grid">
        <div class="form-grid two">
          <label class="field"><span>Класс</span><select class="input" name="classId">${S.data.classes.map((item) => `<option value="${item.id}" ${item.id === record.classIds?.[0] ? 'selected' : ''}>${esc(item.name)}</option>`).join('')}</select></label>
          <label class="field"><span>Предмет</span><select class="input" name="subjectId">${S.data.subjects.map((item) => `<option value="${item.id}" ${item.id === record.subjectId ? 'selected' : ''}>${esc(item.name)}</option>`).join('')}</select></label>
        </div>
        <div>
          <span class="field-label">Учитель</span>
          <div id="plan-teachers">${planTeacherChecks(record.subjectId, record.teacherIds || [])}</div>
        </div>
        <div class="form-grid two">
          <label class="field"><span>Часов в неделю</span><input class="input" type="number" min="0" max="40" name="hours" value="${record.hours ?? ''}" required></label>
          <label class="field"><span>Не более в день</span><input class="input" type="number" min="1" max="8" name="maxPerDay" value="${record.maxPerDay || 2}"></label>
        </div>
        <div>
          <span class="field-label">Кабинет для планирования</span>
          ${roomChecks(record.roomIds || [])}
        </div>
        <label class="check"><input type="checkbox" name="confirmed" ${record.confirmed !== false ? 'checked' : ''}>Часы проверены</label>
      </div>`;
  }
  if (['teachers','classes','rooms'].includes(kind)) {
    body += `<details class="form-section"><summary>Постоянная недоступность по дням и урокам</summary><p class="muted">Отметьте часы, в которые занятия запрещены.</p><table class="availability-editor"><thead><tr><th>Урок</th>${DAYS.map(d => `<th>${d.slice(0,2)}</th>`).join('')}</tr></thead><tbody>${S.data.school.bells.map((_,p) => `<tr><th>${p+1}</th>${DAYS.map((d,n) => `<td><input type="checkbox" name="unavailable" value="${n}:${p+1}" aria-label="${d}, урок ${p+1}: недоступно" ${(record.unavailable||[]).some(s => s.day===n && s.period===p+1) ? 'checked' : ''}></td>`).join('')}</tr>`).join('')}</tbody></table></details>`;
  }
  if (kind === 'plan') {
    const mandatoryPair=/труд|технол/i.test(subjectName(record.subjectId)) && Number(record.hours)>=2 && Number(record.hours)%2===0;
    body += `<label class="check" ${mandatoryPair?'title="Два урока труда всегда проводятся подряд"':''}><input type="checkbox" name="doubleLessons" ${record.doubleLessons || mandatoryPair ? 'checked' : ''} ${mandatoryPair?'disabled':''}>Проводить спаренными уроками</label>`;
  }
  if (kind === 'teachers') body += `<label class="field"><span>Не более рабочих дней в неделю</span><input class="input" name="maxDays" type="number" min="1" max="5" value="${record.maxDays||5}"></label>`;
  const foot = `${existing ? `<button type="button" class="btn danger" data-action="delete-entity" data-kind="${kind}" data-id="${existing.id}">Удалить</button>` : ''}<span class="left"></span>${button('Отмена', 'close-sheet', 'ghost')}<button type="submit" class="btn primary">${icon('check')}Сохранить</button>`;
  openSheet({
    title: existing ? `Изменить ${KIND_TITLES[kind]}` : `Добавить ${KIND_TITLES[kind]}`,
    sub: kind === 'plan' ? 'Плановая нагрузка на неделю' : 'Справочник школы',
    body,
    foot,
    submit: async (form) => { await submitEntity(form, kind, existing); },
  });
  if (kind === 'plan') {
    $('#sheet-form [name=subjectId]').addEventListener('change', (event) => {
      $('#plan-teachers').innerHTML = planTeacherChecks(event.target.value, []);
    });
  }
}

function planTeacherChecks(subjectId, selected = []) {
  const teachers = S.data.teachers.filter((teacher) => (teacher.subjectIds || []).includes(subjectId));
  const list = teachers.length ? teachers : S.data.teachers;
  return `<div class="check-grid">${list.map((teacher) => `<label class="check"><input type="checkbox" name="teacherIds" value="${teacher.id}" ${selected.includes(teacher.id) ? 'checked' : ''}>${esc(teacher.name)}</label>`).join('')}</div>`;
}

async function submitEntity(form, kind, existing) {
  const data = new FormData(form);
  let record = { ...(existing || {}), id: existing?.id || '' };
  if (kind === 'teachers') {
    record = { ...record, name: data.get('name'), weeklyTarget: data.get('weeklyTarget') === '' ? null : Number(data.get('weeklyTarget')), maxDaily: Number(data.get('maxDaily')), subjectIds: formChecked('subjectIds'), homeroom: data.get('homeroom'), note: data.get('note') };
  } else if (kind === 'classes') {
    record = { ...record, name: data.get('name'), homeroomTeacherId:data.get('homeroomTeacherId') || '', size: Number(data.get('size')), maxDaily: Number(data.get('maxDaily')), firstPeriod: Number(data.get('firstPeriod')) };
  } else if (kind === 'subjects') {
    record = { ...record, name: data.get('name'), short: data.get('short'), teacherCode: data.get('teacherCode'), difficulty: Number(data.get('difficulty')) };
  } else if (kind === 'rooms') {
    record = { ...record, name: data.get('name'), capacity: Number(data.get('capacity')), floor: data.get('floor'), subjectIds: formChecked('subjectIds'), classId: data.get('classId'), teacherId: data.get('teacherId') };
  } else if (kind === 'plan') {
    const teacherIds = formChecked('teacherIds');
    if (!teacherIds.length) throw new Error('Выберите учителя.');
    record = { ...record, classIds: [data.get('classId')], subjectId: data.get('subjectId'), teacherIds, roomIds: formChecked('roomIds'), hours: Number(data.get('hours')), maxPerDay: Number(data.get('maxPerDay')), confirmed: data.has('confirmed') };
  }
  if (['teachers','classes','rooms'].includes(kind)) record.unavailable = formChecked('unavailable').map(v => {const [day,period]=v.split(':').map(Number);return {day,period}});
  if (kind === 'teachers') record.maxDays = Number(data.get('maxDays'));
  if (kind === 'plan') record.doubleLessons = data.has('doubleLessons');
  const result = await api(`/entity/${kind}`, { revision: S.revision, record });
  S.data = result.state;
  S.revision = result.revision;
  await loadDay();
  closeSheet();
  render();
  toast('Сохранено.');
}

async function deleteEntity(kind, id) {
  if (!(await askConfirm({ title: 'Удалить запись?', text: 'Данные справочника будут удалены.', yes: 'Удалить', danger: true }))) return;
  try {
    const result = await api(`/entity/${kind}/delete`, { revision: S.revision, id });
    S.data = result.state;
    S.revision = result.revision;
    await loadDay();
    closeSheet();
    closeModal();
    render();
    toast('Удалено.');
  } catch (error) {
    if ($('#sheet').open) sheetError(error.message);
    else modalError(error.message);
  }
}

/* --------------------------------------------------------------------------
   week
   -------------------------------------------------------------------------- */

function weekEntityId() {
  const kind = S.weekKind;
  if (!S.weekId || !by(kind, S.weekId)) S.weekId = S.data[kind][0]?.id || '';
  return S.weekId;
}

function weekCell(lesson) {
  if (!lesson) return '';
  if (S.weekKind === 'classes') {
    return `<div class="week-subject">${esc(subjectShort(lesson.subjectId))}</div><div class="week-meta">${esc(namesOf('teachers', lesson.teacherIds))}${lesson.roomIds?.length ? ` · ${esc(namesOf('rooms', lesson.roomIds))}` : ''}</div>`;
  }
  return `<div class="week-subject">${esc(namesOf('classes', lesson.classIds))} ${esc(subjectShort(lesson.subjectId))}</div><div class="week-meta">${esc(namesOf('rooms', lesson.roomIds) || '')}</div>`;
}

function renderWeek() {
  const kind = S.weekKind;
  const id = weekEntityId();
  const field = kind === 'classes' ? 'classIds' : 'teacherIds';
  const monday = mondayOf(S.date);
  const days = [0, 1, 2, 3, 4].map((offset) => addDays(monday, offset));
  const source = S.weekActual
    ? Object.fromEntries(days.map((date) => [date, lessonsFor(date)]))
    : Object.fromEntries(days.map((date) => [date, S.data.baseLessons.filter(l => Number(l.day) === dayIndex(date))]));
  const gaps = [];
  const rows = S.data.school.bells.map((bell, index) => {
    const period = index + 1;
    const cells = days.map((date) => {
      const lessons = (source[date] || []).filter((lesson) => (lesson[field] || []).includes(id) && Number(lesson.period) === period);
      const allPeriods = (source[date] || []).filter((lesson) => (lesson[field] || []).includes(id)).map((lesson) => Number(lesson.period));
      const first = Math.min(...allPeriods);
      const last = Math.max(...allPeriods);
      const gap = !lessons.length && allPeriods.length && period > first && period < last;
      return `<td class="${gap ? 'week-gap' : ''}"><button type="button" class="week-edit" draggable="${lessons.length ? 'true' : 'false'}" data-week-edit="1" data-lesson="${lessons[0]?.id || ''}" data-date="${date}" data-scope="${S.weekActual ? 'day' : 'base'}" data-row-kind="${kind}" data-row="${id}" data-period="${period}" aria-label="${esc(DAYS[dayIndex(date)] + ', урок ' + period + ': ' + (lessons[0] ? describe(lessons[0]) : 'добавить занятие'))}">${lessons.map(weekCell).join('') || '<span class="week-empty">—</span>'}</button></td>`;
    }).join('');
    return `<tr><th><span class="pnum">${period}</span><small>${esc(bell)}</small></th>${cells}</tr>`;
  }).join('');
  const total = days.reduce((sum, date) => sum + (source[date] || []).filter((lesson) => (lesson[field] || []).includes(id)).length, 0);
  const actions = `
    <label class="check"><input type="checkbox" id="week-actual" ${S.weekActual ? 'checked' : ''}>С учётом изменений</label>
    <button type="button" class="btn ghost" data-action="show-load">Распределение часов</button>
    <button type="button" class="btn ghost" data-action="plan-check">${icon('alert')}Проверить план</button>`;
  return `
    <div class="page">
      ${pageHead('Постоянное расписание', 'Неделя', `${total} ${plural(total, 'занятие', 'занятия', 'занятий')} · ${kind === 'classes' ? 'для класса' : 'для учителя'}`, actions)}
      ${S.weekActual ? dateStrip() : ''}
      <div class="toolbar">
        <div class="segmented">
          <button type="button" data-action="week-kind" data-value="classes" class="${kind === 'classes' ? 'active' : ''}">Классы</button>
          <button type="button" data-action="week-kind" data-value="teachers" class="${kind === 'teachers' ? 'active' : ''}">Учителя</button>
        </div>
        <select class="input" id="week-entity" style="max-width:320px">${S.data[kind].map((item) => `<option value="${item.id}" ${item.id === id ? 'selected' : ''}>${esc(item.name)}</option>`).join('')}</select>
        <span class="muted">Двойной щелчок по клетке — изменить или добавить урок</span>
      </div>
      <div class="table-card">
        <div class="table-scroll">
          <table class="week-table">
            <thead><tr><th>Урок</th>${days.map((date) => `<th>${DAYS[dayIndex(date)]}<small>${fmtShort(date)}</small></th>`).join('')}</tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
      ${renderLoadLocator(kind,id)}
      <div style="margin-top:12px">${notice('Это постоянное расписание на учебный год. Ежедневные замены и отсутствия находятся на странице «Расписание на день» и не меняют эту неделю.', 'info')}</div>
    </div>`;
}

/* --------------------------------------------------------------------------
   plan
   -------------------------------------------------------------------------- */

function planKey(lesson) {
  return JSON.stringify([[...(lesson.classIds || [])].sort(), lesson.subjectId, [...(lesson.teacherIds || [])].sort()]);
}

function planPlaced() {
  const counts = new Map();
  for (const lesson of S.data.baseLessons) {
    const key = planKey(lesson);
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return counts;
}

function renderLoadLocator(kind, id) {
  const field=kind==='teachers'?'teacherIds':'classIds';
  const plans=S.data.plan.filter(p=>!id || p[field].includes(id));
  const counts=planPlaced();
  return `<section class="load-locator" aria-label="Распределение часов"><h2>Распределение часов</h2>
    <p class="muted"><span class="load-dot"></span> ещё нужно поставить · <span class="load-dot placed"></span> уже стоит в базовой неделе. Одна точка — один урок.</p>
    ${plans.map(plan=>{const placed=counts.get(planKey(plan))||0;const hours=Number(plan.hours)||0;
      return `<div class="load-locator-row"><span class="load-locator-name">${esc(namesOf('classes',plan.classIds))} · ${esc(subjectName(plan.subjectId))}<small> ${esc(namesOf('teachers',plan.teacherIds))}</small></span>
        <span class="load-dots" aria-label="Расставлено ${placed} из ${hours}">${Array.from({length:Math.max(hours,placed)},(_,i)=>`<span class="load-dot ${i<placed?'placed':''}" title="${i<placed?'Урок расставлен':'Урок ещё не расставлен'}"></span>`).join('')}</span>
        <span>${placed} / ${hours} ч${placed>hours?' · лишние часы':''}</span></div>`;}).join('') || '<p>Для этой строки пока нет учебного плана.</p>'}</section>`;
}

function renderPlan() {
  const placed = planPlaced();
  const query = S.planQuery.trim().toLowerCase();
  let rows = S.data.plan.filter((row) => !S.planClass || row.classIds.includes(S.planClass));
  if (query) {
    rows = rows.filter((row) => [namesOf('classes', row.classIds), subjectName(row.subjectId), namesOf('teachers', row.teacherIds)]
      .join(' ').toLowerCase().includes(query));
  }
  const totalHours = rows.reduce((sum, row) => sum + Number(row.hours || 0), 0);
  const placedHours = rows.reduce((sum, row) => sum + (placed.get(planKey(row)) || 0), 0);
  const missing = rows.filter((row) => (placed.get(planKey(row)) || 0) < Number(row.hours || 0));
  const table = rows.map((row) => {
    const count = placed.get(planKey(row)) || 0;
    const hours = Number(row.hours || 0);
    const delta = hours - count;
    const percent = hours ? Math.min(100, Math.round((count / hours) * 100)) : 100;
    return `<tr>
      <td class="title">${esc(namesOf('classes', row.classIds))}</td>
      <td>${esc(subjectName(row.subjectId))}${row.doubleLessons ? '<small>спаренные</small>' : ''}</td>
      <td>${esc(namesOf('teachers', row.teacherIds))}</td>
      <td class="num">${hours} ч</td>
      <td class="num ${delta ? 'danger' : 'positive'}">${count} ч</td>
      <td style="min-width:120px"><div class="progress ${delta ? 'warn' : ''}"><i style="width:${percent}%"></i></div></td>
      <td><button type="button" class="text-btn" data-action="edit-entity" data-kind="plan" data-id="${row.id}">Изменить</button></td>
    </tr>`;
  }).join('');
  const actions = `${button('Составить всю неделю', 'build-week', 'ghost', 'spark')}${button('Достроить недостающие часы', 'fill-missing', 'ghost', 'plus')}${button('Проверить план', 'plan-check', 'ghost', 'alert')}${button('Добавить', 'new-entity', 'primary', 'plus', 'data-kind="plan"')}`;
  return `
    <div class="page">
      ${pageHead('Учебный план', 'Нагрузка на неделю', `${rows.length} ${plural(rows.length, 'строка', 'строки', 'строк')} · ${totalHours} ч по плану · ${placedHours} ч расставлено`, actions)}
      <div class="cards" style="margin-bottom:16px">
        <div class="stat-card"><div class="k">Часов по плану</div><div class="v">${totalHours}</div><div class="h">для выбранных классов</div></div>
        <div class="stat-card"><div class="k">Расставлено</div><div class="v">${placedHours}</div><div class="h">в базовой неделе</div></div>
        <div class="stat-card ${missing.length ? 'accent' : ''}"><div class="k">Не хватает</div><div class="v">${Math.max(0, totalHours - placedHours)}</div><div class="h">${missing.length} ${plural(missing.length, 'строка', 'строки', 'строк')}</div></div>
        <div class="stat-card"><div class="k">Учителей</div><div class="v">${S.data.teachers.length}</div><div class="h">в справочнике</div></div>
      </div>
      <div class="filter-bar">
        <select class="input" id="plan-class" style="max-width:220px"><option value="">Все классы</option>${S.data.classes.map((item) => `<option value="${item.id}" ${S.planClass === item.id ? 'selected' : ''}>${esc(item.name)}</option>`).join('')}</select>
        <label class="search">${icon('search')}<input id="plan-search" type="search" placeholder="Найти предмет или учителя" value="${esc(S.planQuery)}"></label>
        <span class="spacer"></span>
        <span class="muted">${rows.length} строк</span>
      </div>
      <div class="table-card"><div class="table-scroll"><table class="data">
        <thead><tr><th>Класс</th><th>Предмет</th><th>Учитель</th><th class="num">В плане</th><th class="num">Стоит</th><th>Заполнение</th><th></th></tr></thead>
        <tbody>${table || `<tr><td colspan="7" class="table-empty">Ничего не найдено.</td></tr>`}</tbody>
      </table></div></div>
      <div style="margin-top:12px">${notice('Плановая нагрузка — это часы конкретного учителя в конкретном классе. По ней программа проверяет, что каждый урок стоит в неделе и ни один час не потерян.', 'info')}</div>
    </div>`;
}

async function checkPlan() {
  try {
    const result = await api('/plan/check');
    const report = result.report;
    const missing = report.missing || [];
    const extra = report.extra || [];
    const teacherShort = report.teacherShort || [];
    const body = `
      <div class="facts">
        <div><strong>${report.rows.length}</strong><span>строк плана</span></div>
        <div class="${missing.length ? 'red' : 'green'}"><strong>${missing.length}</strong><span>недостаёт</span></div>
        <div class="${extra.length ? 'red' : 'green'}"><strong>${extra.length}</strong><span>лишних</span></div>
        <div><strong>${teacherShort.length}</strong><span>отклонений у учителей</span></div>
      </div>
      ${missing.length ? `<div class="section-head"><h2>Не хватает часов</h2></div><div class="change-list">${missing.map((row) => `<div class="change-row"><div class="old">${esc(namesOf('classes', row.classIds))}</div><div class="arrow">→</div><div class="new">${esc(subjectName(row.subjectId))}<small>${esc(namesOf('teachers', row.teacherIds))} · план ${row.hours}, стоит ${row.placed}</small></div></div>`).join('')}</div>` : ''}
      ${extra.length ? `<div class="section-head" style="margin-top:18px"><h2>Стоит больше плана</h2></div><div class="change-list">${extra.slice(0, 30).map((row) => `<div class="change-row"><div class="old">${esc(namesOf('classes', row.classIds))}</div><div class="arrow">→</div><div class="new">${esc(subjectName(row.subjectId))}<small>${esc(namesOf('teachers', row.teacherIds))} · план ${row.hours}, стоит ${row.placed}</small></div></div>`).join('')}</div>` : ''}
      ${teacherShort.length ? `<div class="section-head" style="margin-top:18px"><h2>Отклонения по учителям</h2></div><div class="change-list">${teacherShort.map((row) => `<div class="change-row"><div class="old">${esc(row.name)}</div><div class="arrow">→</div><div class="new ${row.delta < 0 ? 'cancel' : ''}">${row.delta > 0 ? `не хватает ${row.delta} ч` : `лишних ${-row.delta} ч`}<small>норма ${row.target ?? '—'}, стоит ${row.base}</small></div></div>`).join('')}</div>` : ''}
      ${!missing.length && !extra.length && !teacherShort.length ? notice('План и базовая неделя сходятся.', 'success') : ''}`;
    openModal({ title: 'Проверка учебного плана', sub: 'Сравнение плана и базовой недели', body, foot: button('Закрыть', 'close-modal', 'primary'), wide: true });
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function previewFillMissing() {
  try {
    const result = await api('/fill-missing', { revision: S.revision, apply: false });
    const added = result.added || [];
    const unresolved = result.unresolved || [];
    const body = `
      ${added.length ? `<div class="notice success">${icon('check')}<div class="grow">Можно добавить ${added.length} ${plural(added.length, 'занятие', 'занятия', 'занятий')} в свободные места без новых окон.</div></div>` : notice('Свободных мест без новых окон не найдено.', 'warn')}
      ${added.length ? `<div class="change-list" style="margin-top:12px">${added.map((lesson) => `<div class="change-row"><div class="old">${DAYS[lesson.day]}, ${lesson.period} урок</div><div class="arrow">→</div><div class="new">${esc(namesOf('classes', lesson.classIds))} · ${esc(subjectShort(lesson.subjectId))}<small>${esc(namesOf('teachers', lesson.teacherIds))}</small></div></div>`).join('')}</div>` : ''}
      ${unresolved.length ? `<div class="notice warn" style="margin-top:12px">${icon('alert')}<div class="grow">Не удалось добавить без перестановки существующих занятий: ${unresolved.length} ${plural(unresolved.length, 'строка', 'строки', 'строк')} плана. Можно уточнить условия или воспользоваться кнопкой «Составить всю неделю».</div></div>` : ''}`;
    openModal({
      title: 'Достроить недостающие часы',
      sub: 'Добавление в базовую неделю',
      body,
      foot: `${button('Закрыть', 'close-modal', 'ghost')}${added.length ? button('Добавить', 'apply-fill', 'primary', 'check') : ''}`,
      wide: true,
    });
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function applyFillMissing(buttonNode) {
  buttonNode.disabled = true;
  try {
    const result = await api('/fill-missing', { revision: S.revision, apply: true });
    S.data = result.state;
    S.revision = result.revision;
    await loadDay();
    closeModal();
    render();
    toast('Недостающие часы добавлены в базовую неделю.');
  } catch (error) {
    buttonNode.disabled = false;
    modalError(error.message);
  }
}

/* --------------------------------------------------------------------------
   directory
   -------------------------------------------------------------------------- */

const DIR_TITLES = { teachers: 'Учителя', classes: 'Классы', subjects: 'Предметы', rooms: 'Кабинеты' };

function renderDirectory() {
  const kind = S.dirKind;
  const query = S.dirQuery.trim().toLowerCase();
  let rows = [...(S.data[kind] || [])];
  if (query) rows = rows.filter((row) => row.name.toLowerCase().includes(query));
  let head = '';
  let body = '';
  if (kind === 'teachers') {
    head = '<tr><th>Учитель</th><th>Предметы</th><th class="num">Норма</th><th class="num">В день</th><th></th></tr>';
    body = rows.map((row) => `<tr>
      <td class="title">${esc(row.name)}<small>${esc(row.homeroom ? `классное руководство: ${row.homeroom}` : '')}</small></td>
      <td><div class="subject-tags">${(row.subjectIds || []).slice(0, 5).map((id) => `<span>${esc(subjectShort(id))}</span>`).join('')}${(row.subjectIds || []).length > 5 ? `<span>+${row.subjectIds.length - 5}</span>` : ''}</div></td>
      <td class="num">${row.weeklyTarget ?? '—'}</td>
      <td class="num">${row.maxDaily ?? 8}</td>
      <td><button type="button" class="text-btn" data-action="edit-entity" data-kind="teachers" data-id="${row.id}">Изменить</button></td>
    </tr>`).join('');
  } else if (kind === 'classes') {
    head = '<tr><th>Класс</th><th class="num">Учеников</th><th class="num">Уроков в день</th><th class="num">С какого урока</th><th></th></tr>';
    body = rows.map((row) => `<tr>
      <td class="title">${esc(row.name)}</td><td class="num">${row.size || '—'}</td><td class="num">${row.maxDaily}</td><td class="num">${row.firstPeriod}</td>
      <td><button type="button" class="text-btn" data-action="edit-entity" data-kind="classes" data-id="${row.id}">Изменить</button></td>
    </tr>`).join('');
  } else if (kind === 'subjects') {
    head = '<tr><th>Предмет</th><th>В Word</th><th>Код</th><th class="num">Трудность</th><th></th></tr>';
    body = rows.map((row) => `<tr>
      <td class="title">${esc(row.name)}</td><td>${esc(row.short)}</td><td>${esc(row.teacherCode || '—')}</td><td class="num">${row.difficulty}</td>
      <td><button type="button" class="text-btn" data-action="edit-entity" data-kind="subjects" data-id="${row.id}">Изменить</button></td>
    </tr>`).join('');
  } else {
    head = '<tr><th>Кабинет</th><th class="num">Мест</th><th>Предметы</th><th></th></tr>';
    body = rows.map((row) => `<tr>
      <td class="title">${esc(row.name)}</td><td class="num">${row.capacity || '—'}</td>
      <td>${(row.subjectIds || []).length ? (row.subjectIds || []).map((id) => esc(subjectShort(id))).join(', ') : '<span class="muted">любой предмет</span>'}</td>
      <td><button type="button" class="text-btn" data-action="edit-entity" data-kind="rooms" data-id="${row.id}">Изменить</button></td>
    </tr>`).join('');
  }
  return `
    <div class="page">
      ${pageHead('Справочники', 'Школа', 'Учителя, классы, предметы и кабинеты. Эти данные используются в расписании и отчётах.', button('Добавить', 'new-entity', 'primary', 'plus', `data-kind="${kind}"`))}
      <div class="tabs">${Object.entries(DIR_TITLES).map(([value, label]) => `<button type="button" data-action="dir-kind" data-value="${value}" class="${kind === value ? 'active' : ''}">${label} <span class="muted">${S.data[value].length}</span></button>`).join('')}</div>
      <div class="filter-bar">
        <label class="search">${icon('search')}<input id="dir-search" type="search" placeholder="Найти в справочнике" value="${esc(S.dirQuery)}"></label>
        <span class="spacer"></span>
        <span class="muted">${rows.length} ${plural(rows.length, 'запись', 'записи', 'записей')}</span>
      </div>
      <div class="table-card"><div class="table-scroll"><table class="data"><thead>${head}</thead><tbody>${body || `<tr><td colspan="5" class="table-empty">Ничего не найдено.</td></tr>`}</tbody></table></div></div>
    </div>`;
}

/* --------------------------------------------------------------------------
   absences
   -------------------------------------------------------------------------- */

function renderAbsences() {
  const rows = [...S.data.absences].sort((a, b) => String(b.start).localeCompare(String(a.start)) || String(a.end).localeCompare(String(b.end)) || nameOf('teachers',a.teacherId).localeCompare(nameOf('teachers',b.teacherId),'ru'));
  const groups=new Map();for(const row of rows){const key=row.start+'/'+row.end;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
  const cards = [...groups.values()].map(items=>`<section class="date-section"><h2>${fmtDate(items[0].start)}${items[0].end!==items[0].start?' – '+fmtDate(items[0].end):''}</h2><div class="absence-list">${items.map((row) => `
    <div class="absence-card">
      <div class="who">${esc(nameOf('teachers', row.teacherId))}</div>
      <div class="why">${row.first === row.last ? `${row.first} урок` : `${row.first}–${row.last} уроки`}${row.reason ? ` · ${esc(row.reason)}` : ''}</div>
      <button type="button" class="text-btn" data-action="edit-absence" data-id="${row.id}">Изменить</button>
    </div>`).join('')}</div></section>`).join('');
  return `
    <div class="page">
      ${pageHead('Отсутствия', 'Кто отсутствует', 'Болезнь, приём у врача, курсы. Отсутствие учитывается при подборе замен.', button('Отметить отсутствие', 'absence', 'primary', 'plus'))}
      ${rows.length ? `<div class="absence-list">${cards}</div>` : emptyState('Отсутствий нет', 'Когда учитель заболел, отметьте его здесь — программа подберёт перестановки на нужный день.', 'absent')}
      <div style="margin-top:16px">${notice('Отсутствие не меняет расписание автоматически. После отметки откройте «Расписание на день» и нажмите «Подобрать замены»: программа сохранит уроки с их учителями, переставит занятия и отменит только невозможные.', 'info')}</div>
    </div>`;
}

/* --------------------------------------------------------------------------
   journal
   -------------------------------------------------------------------------- */

function renderJournal() {
  const monday = mondayOf(S.date);
  const end = addDays(monday, 4);
  const rows = [...S.data.journal]
    .filter((row) => S.journalAll || (row.date >= monday && row.date <= end))
    .sort((a, b) => b.date.localeCompare(a.date)
      || ((a.before || a.after)?.period || 0) - ((b.before || b.after)?.period || 0)
      || String(b.created).localeCompare(String(a.created)));
  const table = rows.map((row) => {
    const lesson = row.after || row.before || {};
    const moved = row.movedTo ? `перенесено на ${fmtDate(row.movedTo)}` : '';
    return `<tr>
      <td>${fmtDate(row.date)}<small>${lesson.period || '—'} урок · ${esc(namesOf('classes', lesson.classIds))}</small></td>
      <td>${esc(subjectName(lesson.subjectId))}<small>${esc(row.kind === 'cancel' ? 'отмена' : row.kind === 'group_cancel' ? 'отмена группы' : row.kind === 'move' ? 'перестановка' : 'правка')}</small></td>
      <td>${esc(row.before ? fullLesson(row.before) : '—')}${row.before ? `<small>${row.before.period} урок</small>` : ''}</td>
      <td>${esc(row.after ? fullLesson(row.after) : '—')}${row.after ? `<small>${row.after.period} урок</small>` : ''}${moved ? `<small>${esc(moved)}</small>` : ''}</td>
      <td>${esc(row.reason || '')}<small>${!row.after ? 'Отмена занятия' : row.confirmed ? 'Проведение отмечено' : 'Проведение пока не отмечено'}</small></td>
      <td>${row.active === false ? '<span class="muted">пересмотрено</span>' : !row.after ? '<span class="muted">Урок отменён</span>' : row.confirmed ? '<span class="muted">Урок проведён</span>' : `<button type="button" class="btn small" data-action="journal-confirm" data-id="${row.id}">Отметить проведение урока</button>`}</td>
    </tr>`;
  }).join('');
  return `
    <div class="page">
      ${pageHead('Журнал изменений', 'Что менялось', `${rows.length} ${plural(rows.length, 'запись', 'записи', 'записей')}`, `<button type="button" class="btn ghost" data-action="download" data-url="/api/report-csv/journal" data-name="Журнал изменений.csv">${icon('download')}Скачать CSV</button>`)}
      ${dateStrip()}
      <div class="filter-bar"><label class="check"><input type="checkbox" id="journal-all" ${S.journalAll ? 'checked' : ''}>За всё время</label><span class="spacer"></span><span class="muted">Все изменения уже сохранены. Отметка проведения — только для учёта проведённых уроков.</span></div>
      <div class="table-card"><div class="table-scroll"><table class="data">
        <thead><tr><th>Дата и урок</th><th>Предмет</th><th>Было</th><th>Стало</th><th>Причина</th><th>Проведение</th></tr></thead>
        <tbody>${table || `<tr><td colspan="6" class="table-empty">На этой неделе изменений нет.</td></tr>`}</tbody>
      </table></div></div>
    </div>`;
}

/* --------------------------------------------------------------------------
   reports
   -------------------------------------------------------------------------- */

function renderReports() {
  if (!S.report) {
    return `<div class="page">${pageHead('Нагрузка', 'Проверка недели', 'Считаем плановые и фактические часы…')}<div class="loading"><span class="skeleton wide"></span><span class="skeleton tall"></span></div></div>`;
  }
  const report = S.report;
  const summary = report.summary || {};
  const short = report.teachers.filter((row) => row.weekDelta !== 0);
  const table = report.teachers.map((row) => `<tr>
    <td class="title">${esc(row.name)}</td>
    <td class="num">${row.target ?? '—'}</td>
    <td class="num">${row.plan}</td>
    <td class="num">${row.base}</td>
    <td class="num">${row.week ?? '—'}</td>
    <td class="num ${row.weekDelta ? 'danger' : 'positive'}">${row.weekDelta > 0 ? '+' : ''}${row.weekDelta} ч</td>
  </tr>`).join('');
  return `
    <div class="page">
      ${pageHead('Нагрузка и проверка', 'Неделя в цифрах', `${fmtDate(mondayOf(S.date))} — ${fmtDate(addDays(mondayOf(S.date), 4))}`, `<button type="button" class="btn ghost" data-action="download" data-url="/api/report-csv/load" data-name="Нагрузка учителей.csv">${icon('download')}Скачать нагрузку</button>`)}
      <div class="cards" style="margin-bottom:16px">
        <div class="stat-card"><div class="k">Учителей</div><div class="v">${summary.teachers || 0}</div><div class="h">в школе</div></div>
        <div class="stat-card"><div class="k">Классов</div><div class="v">${summary.classes || 0}</div><div class="h">в расписании</div></div>
        <div class="stat-card"><div class="k">Занятий в неделе</div><div class="v">${summary.weekLessons || 0}</div><div class="h">с учётом изменений</div></div>
        <div class="stat-card ${short.length ? 'accent' : ''}"><div class="k">Отклонения</div><div class="v">${short.length}</div><div class="h">учителей с разницей</div></div>
      </div>
      <div class="section-head"><h2>Часы учителей</h2><span class="hint">Норма — учебный план — базовая неделя — эта неделя</span></div>
      <div class="table-card"><div class="table-scroll"><table class="data">
        <thead><tr><th>Учитель</th><th class="num">Норма</th><th class="num">В плане</th><th class="num">База</th><th class="num">Эта неделя</th><th class="num">Отклонение</th></tr></thead>
        <tbody>${table}</tbody>
      </table></div></div>
      <div style="margin-top:12px">${notice('Красное отклонение — назначенных часов меньше нормы. Это видно, если в неделе есть отменённые уроки; журнал хранит каждую правку.', 'info')}</div>
    </div>`;
}

async function ensureReport() {
  if (S.reportLoading) return;
  S.reportLoading = true;
  try {
    S.report = await api(`/reports/${S.date}`);
    if (S.page === 'reports') render();
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    S.reportLoading = false;
  }
}

/* --------------------------------------------------------------------------
   settings
   -------------------------------------------------------------------------- */

function renderSettings() {
  const school = S.data.school;
  if(!S.updateSettings && !S.loadingUpdates){
    S.loadingUpdates=true;
    api('/updates').then(value=>{S.updateSettings=value;if(S.page==='settings')render();}).catch(()=>{});
  }
  return `
    <div class="page">
      ${pageHead('Настройки', 'Школа и правила', 'Эти данные используются в расписании и отчётах.')}
      <section class="table-card app-about" aria-label="О приложении">
        <div><h2>Расписание</h2><p>Версия <span id="app-version">${esc(S.appVersion || '')}</span></p></div>
        <button type="button" class="btn" data-action="show-releases">${icon('history')}Что нового</button>
      </section>
      ${S.updateSettings?.configured?`<section class="table-card" style="padding:18px 22px;max-width:900px;margin-bottom:20px"><label class="check-row"><input type="checkbox" data-update-setting ${S.updateSettings.enabled?'checked':''}> Обновлять приложение при запуске</label></section>`:''}
      <form id="settings-form" class="table-card" style="padding:20px 22px;max-width:900px">
        <div class="form-grid two">
          <label class="field"><span>Название школы</span><input class="input" name="name" value="${esc(school.name)}"></label>
          <label class="field"><span>Учебный год</span><input class="input" name="year" value="${esc(school.year)}"></label>
          <label class="field"><span>Период</span><input class="input" name="term" value="${esc(school.term)}"></label>
          <label class="field"><span>Смена</span><input class="input" value="Первая смена · пятидневка" disabled></label>
        </div>
        <div class="form-section">
          <h3>Расписание звонков</h3>
          <div class="form-grid two">
            ${school.bells.map((bell, index) => `<label class="field"><span>${index + 1} урок</span><input class="input" name="bell${index}" value="${esc(bell)}"></label>`).join('')}
          </div>
        </div>
        <div class="form-section">
          <h3>Правила</h3>
          <div class="form-grid">
            <p class="muted">У учеников, включая подгруппы, окна запрещены. Подбор сохраняет уроки и сокращает число перестановок; окна учителей допускаются.</p>
            <label class="field" style="max-width:280px"><span>Свободные кабинеты в таблице учителей до урока</span><input class="input" type="number" min="1" max="6" name="freeRoomLastPeriod" value="${school.freeRoomLastPeriod || 6}"></label>
          </div>
        </div>
        <div class="form-section" style="display:flex;align-items:center;gap:10px">
          <button type="submit" class="btn primary">${icon('check')}Сохранить настройки</button>
          <span class="muted">Изменения сохраняются автоматически.</span>
        </div>
      </form>
      ${renderAssistantSettings()}
      <div class="section-head" style="margin-top:26px"><h2>Данные</h2><span class="hint">${esc(S.data.school.year)}</span></div>
      <div class="table-card" style="padding:18px 22px;max-width:900px">
        <div style="display:flex;gap:10px;flex-wrap:wrap">
          <button type="button" class="btn" data-action="backup-full">${icon('download')}Резервная копия</button>
          <button type="button" class="btn" data-action="import-backup">${icon('history')}Загрузить копию</button>
          <button type="button" class="btn ghost" data-action="nav" data-page="history">${icon('history')}Версии расписания</button>
          <button type="button" class="btn danger" data-action="shutdown-app">${icon('closeCircle')}Завершить приложение</button>
        </div>
        <p class="muted" style="margin-top:12px;font-size:12px">Полная копия переносит данные, ограничения, диалоги, историю, настройки и шаблоны. Подключение AI защищается паролем копии.</p>
      </div>
    </div>`;
}

async function saveSettings(form) {
  const data = new FormData(form);
  const bells = S.data.school.bells.map((_, index) => String(data.get(`bell${index}`) || '').trim()).filter(Boolean);
  const school = {
    ...S.data.school,
    name: data.get('name'),
    year: data.get('year'),
    term: data.get('term'),
    bells,
    noClassGaps: true,
    noNewTeacherGaps: false,
    freeRoomLastPeriod: Number(data.get('freeRoomLastPeriod')),
  };
  try {
    const result = await api('/settings', { revision: S.revision, school });
    S.data = result.state;
    S.revision = result.revision;
    render();
    toast('Настройки сохранены.');
  } catch (error) {
    toast(error.message, 'error');
  }
}

document.addEventListener('change',async event=>{
  if(!event.target.matches('[data-update-setting]'))return;
  const control=event.target;control.disabled=true;
  try{S.updateSettings=await api('/updates',{enabled:control.checked});}
  catch(error){control.checked=!control.checked;toast(error.message,'error');}
  finally{control.disabled=false;}
});

async function showReleases(target) {
  target.disabled=true;
  try {
    const info=await api('/about');
    openModal({title:'История обновлений',sub:'Что изменилось в приложении',
      body:`<div class="release-notes">${info.releases.map(release=>`<section class="release-entry"><div class="release-heading"><h3>Версия ${esc(release.version)}</h3>${release.version===info.version?'<span class="pill green">Установлена</span>':''}</div><ul>${release.changes.map(change=>`<li>${esc(change)}</li>`).join('')}</ul></section>`).join('')}</div>`,
      foot:button('Закрыть','close-modal','primary')});
  } finally { target.disabled=false; }
}

/* --------------------------------------------------------------------------
   history
   -------------------------------------------------------------------------- */

function renderHistory() {
  if (!S.history) {
    return `<div class="page">${pageHead('История', 'Версии и копии', 'Загружаем список сохранений…')}<div class="loading"><span class="skeleton tall"></span></div></div>`;
  }
  const rows = S.history.map((row, index) => `<tr>
    <td>${new Date(row.created).toLocaleString('ru-RU')}</td>
    <td>${esc(row.label)}</td>
    <td>${index === 0 ? '<span class="pill green">текущая</span>' : `<button type="button" class="text-btn" data-action="restore-history" data-id="${row.id}">Восстановить</button>`}</td>
  </tr>`).join('');
  return `
    <div class="page">
      ${pageHead('История и копии', 'Версии', 'Каждое сохранение создаёт версию. Можно вернуться к предыдущей.', `<button type="button" class="btn ghost" data-action="backup-full">${icon('download')}Резервная копия</button>`)}
      <div class="table-card"><div class="table-scroll"><table class="data">
        <thead><tr><th>Когда</th><th>Действие</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div></div>
      <div style="margin-top:12px">${notice('Восстановление версии заменяет текущее расписание целиком. Перед важными изменениями скачайте резервную копию.', 'info')}</div>
    </div>`;
}

async function ensureHistory() {
  if (S.historyLoading) return;
  S.historyLoading = true;
  try {
    const result = await api('/history');
    S.history = result.history;
    if (S.page === 'history') render();
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    S.historyLoading = false;
  }
}

async function restoreHistory(id) {
  if (!(await askConfirm({ title: 'Восстановить версию?', text: 'Текущее расписание будет заменено этой версией.', yes: 'Восстановить' }))) return;
  try {
    const result = await api('/history/restore', { revision: S.revision, id });
    S.data = result.state;
    S.revision = result.revision;
    S.history = null;
    await loadDay();
    render();
    toast('Версия восстановлена.');
  } catch (error) {
    toast(error.message, 'error');
  }
}

/* --------------------------------------------------------------------------
   help
   -------------------------------------------------------------------------- */

function renderHelp() {
  return `
    <div class="page">
      ${pageHead('Как пользоваться', 'Коротко о главном', 'Приложение повторяет ваш бумажный порядок работы, но само расставляет уроки и сразу показывает изменения.')}
      <div class="help-grid">
        <div class="help-card">
          <h2>Если учитель заболел</h2>
          <ol>
            <li>Откройте «Расписание на день» и выберите дату.</li>
            <li>Нажмите «Отметить отсутствие»: учитель, даты, уроки.</li>
            <li>Нажмите «Подобрать замены». Время выбирать не нужно; результат появится после проверки ограничений.</li>
            <li>Проверьте список «было → стало» и нажмите «Применить».</li>
            <li>Скачайте Word для учителей и учеников. Изменённые клетки будут красными.</li>
          </ol>
        </div>
        <div class="help-card">
          <h2>Почему нельзя поставить другого учителя</h2>
          <p>В вашей школе урок всегда остаётся у своего преподавателя. Программа никогда не подменяет учителя. Если урок нельзя провести, она сначала пробует <b>переставить</b> занятия местами: например, урок с 7-го на 2-й, если учитель свободен. Если это невозможно — урок отменяется и об этом честно сообщается.</p>
        </div>
        <div class="help-card">
          <h2>Как работает подбор</h2>
          <p>Программа проверяет занятость учителя, каждой подгруппы и кабинета, отсутствие и дневные пределы. У учеников окна запрещены. Варианты с меньшим числом отмен и перестановок предпочтительнее; окна у учителей допускаются. Выберите подходящий вариант в предпросмотре расписания.</p>
        </div>
        <div class="help-card">
          <h2>Перетаскивание</h2>
          <p>Потяните урок на другой урок, чтобы поменять их местами, или на пустую клетку, чтобы перенести. Если при этом появляется окно у учеников или пересечение, программа не разрешит изменение и подскажет причину.</p>
        </div>
        <div class="help-card">
          <h2>Разговоры о важном и группы</h2>
          <p>«Разговоры о важном», в том числе совместные, идут только первым уроком понедельника. Два урока труда и другие спаренные занятия сохраняются парой подряд у каждой подгруппы. Если один преподаватель отсутствует, другая подгруппа может сохранить свою пару. Уроки не переносятся на другой день.</p>
          <p>Редкие исключения для технологии задаются через AI-помощника или в дополнительных настройках раздела «Дополнительные занятия → Подгруппы». Там же указываются состав и численность подгрупп, занятость в началке и индивидуальные занятия.</p>
        </div>
        <div class="help-card">
          <h2>Word</h2>
          <p>Экспорт вставляется в ваши исходные таблицы: размеры, поля, границы и шрифт остаются прежними. Меняются только предметы, классы и кабинеты. Изменённые клетки выделяются красным; заголовок дня сохраняет исходное оформление. Свободные кабинеты в таблице учителей показываются только на 1–6 уроках, как вы просили.</p>
        </div>
        <div class="help-card">
          <h2>Красное — значит изменено</h2>
          <p>Красная клетка и пометка «изм.» означают, что урок переставлен, добавлен или отменён. В журнале хранится, что было и что стало. Кнопка «Вернуть день» возвращает базовое расписание.</p>
        </div>
        <div class="help-card">
          <h2>Если что-то не сходится</h2>
          <p>Нажмите «Проверка» на странице дня. Программа покажет пересечения, отсутствующих учителей и окна. «Учебный план» покажет, каких часов не хватает, а «Достроить недостающие часы» попробует добавить их без новых окон.</p>
        </div>
      </div>
    </div>`;
}

/* --------------------------------------------------------------------------
   page dispatch
   -------------------------------------------------------------------------- */

function render() {
  if (!S.data) return;
  renderNav();
  renderCrumb();
  const pages = {
    assistant: renderAssistant, extras: renderExtras, rules: renderConstraints,
    day: renderDay, week: renderWeek, plan: renderPlan, directory: renderDirectory,
    absences: renderAbsences, journal: renderJournal, reports: renderReports,
    settings: renderSettings, history: renderHistory, help: renderHelp,
  };
  const scroll = $('#main').scrollTop;
  $('#main').innerHTML = (pages[S.page] || renderDay)();
  $('#main').scrollTop = scroll;
  if (S.page === 'reports' && !S.report) ensureReport();
  if (S.page === 'history' && !S.history) ensureHistory();
}

async function setPage(page) {
  closeModal();
  closeSheet();
  if(typeof stopVoiceCapture==='function' && isVoiceBusy())stopVoiceCapture(false);
  if(S.ai && page!=='settings')S.ai.showSpending=false;
  S.preview=null;
  S.page = PAGE_TITLES[page] ? page : 'day';
  if (S.page === 'day') await loadDay();
  if (S.page === 'reports') { S.report = null; }
  if (S.page === 'history') { S.history = null; }
  render();
}

async function refreshAll(message = '') {
  await loadState();
  await loadDay();
  render();
  if (message) toast(message);
}

/* --------------------------------------------------------------------------
   events
   -------------------------------------------------------------------------- */

function goDate(date) {
  if (isWeekend(date)) { toast('В школе пятидневка. Выберите будний день.'); return; }
  S.date = date;
  loadDay().then(render).catch((error) => toast(error.message, 'error'));
}

function setBusyAction(node, text) {
  if (!node) return;
  node.dataset.old = node.innerHTML;
  node.disabled = true;
  node.innerHTML = `${icon('clock')}${text}`;
}

document.addEventListener('click', async (event) => {
  const target = event.target.closest('[data-action]');
  if (!target) return;
  if (Date.now() < (S.suppressClickUntil || 0) && target.closest('.cell')) return;
  const action = target.dataset.action;
  try {
    if (action === 'confirm-yes') { resolveConfirm(true); return; }
    if (action === 'confirm-no') { resolveConfirm(false); return; }
    if (action === 'show-load') { ($('.load-picker') || $('.load-locator'))?.scrollIntoView({block:'start'});return; }
    if (action === 'open-export' || action === 'open-export-folder') { window.chrome?.webview?.postMessage({kind:action,token:target.dataset.token});return; }
    if (action === 'save-project') {
      if(S.preview) {$('[data-action="preview-apply"]')?.click();return;}
      target.disabled=true;
      try { const result=await api('/save',{revision:S.revision});S.revision=result.revision;showSaved(result.savedAt); }
      finally { target.disabled=false; }
      return;
    }
    if (action === 'skip') { $('#main').focus(); return; }
    if (action === 'nav') {
      const page = target.dataset.page;
      history.replaceState(null, '', `#${page}`);
      await setPage(page);
      return;
    }
    if (action === 'close-modal') { closeModal(); return; }
    if (action === 'show-releases') { await showReleases(target); return; }
    if (action === 'close-sheet') { closeSheet(); return; }
    if (action === 'goto-date') { goDate(target.dataset.date); return; }
    if (action === 'prev-week' || action === 'next-week') {
      goDate(addDays(S.date, action === 'prev-week' ? -7 : 7));
      return;
    }
    if (action === 'today') { goDate(S.today); return; }
    if (action === 'view') { S.view = target.dataset.value; S.query = ''; S.changesOnly = false; render(); return; }
    if (action === 'lesson') {
      openLessonSheet(target.dataset);
      return;
    }
    if (action === 'absence') { closeModal(); openAbsenceSheet(); return; }
    if (action === 'absence-from-repair') { closeModal(); openAbsenceSheet(); return; }
    if (action === 'edit-absence') { openAbsenceSheet(target.dataset.id); return; }
    if (action === 'save-absence') { await saveAbsence(target.dataset.repair === '1'); return; }
    if (action === 'delete-absence') { await deleteAbsence(target.dataset.id); return; }
    if (action === 'repair') { openRepair(); return; }
    if (action === 'run-repair') { await runRepair(); return; }
    if (action === 'select-variant') { S.selectedVariant = Number(target.dataset.id); renderRepairPreview(); return; }
    if (action === 'apply-repair') { await applyRepair(target); return; }
    if (action === 'export') { openExport(); return; }
    if (action === 'download') {
      await downloadFile(target.dataset.url, target.dataset.name);
      return;
    }
    if (action === 'download-export') { await downloadExport(target); return; }
    if (action === 'changes') { openChanges(); return; }
    if (action === 'issues') { openIssues(); return; }
    if (action === 'reset-day') { await resetDay(); return; }
    if (action === 'new-entity') { openEntitySheet(target.dataset.kind || S.dirKind); return; }
    if (action === 'edit-entity') { openEntitySheet(target.dataset.kind, target.dataset.id); return; }
    if (action === 'delete-entity') { await deleteEntity(target.dataset.kind, target.dataset.id); return; }
    if (action === 'remove-lesson') { await removeLesson(); return; }
    if (action === 'plan-check') { await checkPlan(); return; }
    if (action === 'build-week') { await buildAnnualWeek(); return; }
    if (action === 'run-build-week') { await runAnnualWeek(); return; }
    if (action === 'apply-build-week') { await applyAnnualWeek(); return; }
    if (action === 'fill-missing') { await previewFillMissing(); return; }
    if (action === 'apply-fill') { await applyFillMissing(target); return; }
    if (action === 'journal-confirm') { await confirmJournal(target.dataset.id); return; }
    if (action === 'restore-history') { await restoreHistory(target.dataset.id); return; }
    if (action === 'import-backup') { $('#import-file').click(); return; }
    if (action === 'shutdown-app') {
      if (!(await askConfirm({ title: 'Завершить приложение?', text: 'Все изменения уже сохранены. Окно можно будет закрыть.', yes: 'Завершить' }))) return;
      try {
        await api('/shutdown', {});
        document.body.innerHTML = '<div style="display:grid;place-items:center;height:100vh;font:16px Segoe UI;color:#3d423b;background:#f4f0e7">Расписание остановлено. Окно можно закрыть.</div>';
      } catch (error) {
        toast(error.message, 'error');
      }
      return;
    }
    if (action === 'dir-kind') { S.dirKind = target.dataset.value; S.dirQuery = ''; render(); return; }
    if (action === 'week-kind') { S.weekKind = target.dataset.value; S.weekId = ''; render(); return; }
  } catch (error) {
    toast(error.message, 'error');
  }
});

document.addEventListener('change', (event) => {
  const target = event.target;
  if (target.id === 'changes-only') { S.changesOnly = target.checked; render(); return; }
  if (target.id === 'journal-all') { S.journalAll = target.checked; render(); return; }
  if (target.id === 'load-entity') { S.loadId=target.value;render();return; }
  if (target.id === 'week-actual') { S.weekActual = target.checked; render(); return; }
  if (target.id === 'week-kind') { S.weekKind = target.value; S.weekId = ''; render(); return; }
  if (target.id === 'week-entity') { S.weekId = target.value; render(); return; }
  if (target.id === 'plan-class') { S.planClass = target.value; render(); return; }
  if (target.id === 'import-file') { importBackup(target.files?.[0]); return; }
  if (target.id === 'date-input') { goDate(target.value); return; }
});

let searchTimer = null;
function debounceSearch(callback) {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(callback, 160);
}

document.addEventListener('input', (event) => {
  const target = event.target;
  if (target.id === 'search') {
    S.query = target.value;
    debounceSearch(() => {
      render();
      const input = $('#search');
      if (input) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
    });
  }
  if (target.id === 'dir-search') {
    S.dirQuery = target.value;
    debounceSearch(() => {
      render();
      const input = $('#dir-search');
      if (input) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
    });
  }
  if (target.id === 'plan-search') {
    S.planQuery = target.value;
    debounceSearch(() => {
      render();
      const input = $('#plan-search');
      if (input) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
    });
  }
});

$('#sheet-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!S.sheetSubmit) return;
  const node = $('#sheet-foot .btn.primary');
  const idleLabel=node?.innerHTML;
  if (node) { node.disabled = true; node.innerHTML = `${icon('clock')}Сохраняем…`; }
  try {
    await S.sheetSubmit($('#sheet-form'));
  } catch (error) {
    sheetError(error.message);
  } finally {
    if (node) { node.disabled = false; node.innerHTML = idleLabel; }
  }
});

document.addEventListener('submit', async (event) => {
  if (event.target.id !== 'settings-form') return;
  event.preventDefault();
  await saveSettings(event.target);
});

async function buildAnnualWeek() {
  openModal({title: 'Составить базовую неделю', sub: 'Подготовка расписания на учебный год',
    body: notice('Будут расставлены все часы учебного плана с закреплёнными учителями. Закреплённые уроки сохранят время. Расчёт может занять несколько секунд; сначала вы увидите результат для проверки.'),
    foot: button('Отмена','close-modal','ghost') + button('Рассчитать неделю','run-build-week','primary','spark')});
}

async function runAnnualWeek() {
  $('#modal-foot').innerHTML = '<span class="muted">Составляем полную неделю…</span>';
  try {
    const result = await api('/week/build', {revision:S.revision});
    S.weekPreview = result;
    const ready = result.status === 'ok';
    openModal({title:ready?'Базовая неделя готова':'Нужно уточнить условия',
      sub:ready?`${result.count} занятий · ${result.changes.length} изменений`:'Текущее расписание сохранено',
      body:notice(result.message,ready?'success':'warn') +
        (result.problems || []).map(p=>notice(p,'warn')).join('') +
        (ready?'<div class="change-list">'+result.changes.map(changeRow).join('')+'</div>':''),
      foot:button('Закрыть','close-modal','ghost')+(ready?button('Применить базовую неделю','apply-build-week','primary','check'):'')});
  } catch(error) { modalError(error.message); $('#modal-foot').innerHTML=button('Закрыть','close-modal','ghost'); }
}

async function applyAnnualWeek() {
  try {
    const result=await api('/week/apply',{revision:S.weekPreview.revision,previewId:S.weekPreview.previewId});
    S.data=result.state;S.revision=result.revision;S.weekPreview=null;
    closeModal();await refreshAll('Базовая неделя сохранена. Предыдущая версия доступна в истории.');
  } catch(error) { modalError(error.message); }
}

async function resetDay() {
  const connected = new Set([S.date]);
  let size;
  do {
    size = connected.size;
    for (const row of S.data.journal) {
      if (row.active && row.movedTo && (connected.has(row.date) || connected.has(row.movedTo))) {
        connected.add(row.date); connected.add(row.movedTo);
      }
    }
  } while (connected.size !== size);
  const text = connected.size > 1
    ? `Переносы связывают несколько дней. Будут отменены изменения за ${[...connected].sort().map(fmtDate).join(', ')}. Это вернёт всю цепочку перестановок; текущая версия останется в истории.`
    : 'Все изменения этого дня будут отменены. Текущая версия останется в истории.';
  if (!(await askConfirm({ title: 'Вернуть день?', text, yes: 'Вернуть расписание', danger: true }))) return;
  try {
    const result = await api('/day/reset', { revision: S.revision, date: S.date });
    S.data = result.state;
    S.revision = result.revision;
    S.day = result.day;
    closeModal();
    render();
    toast('День возвращён к базовому расписанию.');
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function confirmJournal(id) {
  try {
    const result = await api('/journal', { revision: S.revision, id, confirmed: true, payPercent: 100 });
    S.data = result.state;
    S.revision = result.revision;
    render();
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function importBackup(file) {
  if (!file) return;
  if (!(await askConfirm({ title: 'Загрузить резервную копию?', text: 'Текущие данные будут заменены содержимым файла.', yes: 'Загрузить' }))) return;
  try {
    const text = await file.text();
    const payload = JSON.parse(text);
    const state=payload.state||payload;
    if(state._portableBackup?.encryptedKeys) {
      openSheet({title:'Пароль резервной копии',body:'<label class="field"><span>Пароль для переноса подключения AI</span><input class="input" name="password" type="password" minlength="8" maxlength="256" autocomplete="off" required></label>',foot:`${button('Отмена','close-sheet','ghost')}<button class="btn primary" type="submit">Загрузить копию</button>`,submit:form=>restorePortableBackup(state,new FormData(form).get('password'))});
    } else await restorePortableBackup(state);
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    $('#import-file').value = '';
  }
}

async function restorePortableBackup(state,password) {
  const result=await api('/import',{revision:S.revision,state,password});
  S.data=result.state;S.revision=result.revision;S.history=null;S.report=null;S.preview=null;
  assistantReset();S.ai.status=null;S.ai.history=null;S.ai.providerChoice='';
  closeSheet();await loadDay();render();toast('Резервная копия загружена.');
}

// Close dialogs when clicking the dimmed backdrop.
for (const dialog of [$('#modal'), $('#sheet')]) {
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) dialog.close();
  });
}

$('#confirm').addEventListener('close', () => {
  if (S.confirmResolve) {
    const resolve = S.confirmResolve;
    S.confirmResolve = null;
    resolve(false);
  }
});
$('#confirm').addEventListener('click', (event) => {
  if (event.target === $('#confirm')) resolveConfirm(false);
});

function dragRows() { const d=S.dragLesson || S.lastDrag; return d?.scope==='base' ? S.data.baseLessons : lessonsFor(d?.date || S.date); }

function clearDropTargets() {
  $$(':is(.cell,.week-edit).drop-target').forEach((cell) => cell.classList.remove('drop-target'));
  $$(':is(.cell,.week-edit).drop-allowed, :is(.cell,.week-edit).drop-swap').forEach(cell => cell.classList.remove('drop-allowed','drop-swap'));
  $$(':is(.cell,.week-edit).drop-blocked').forEach(cell=>cell.classList.remove('drop-blocked'));
  if($('#drag-feedback'))$('#drag-feedback').textContent='';
}

const targetCache=new Map();
function targetsFor(id,date=S.date,scope='day') {
  const key=`${S.revision}:${date}:${scope}:${id}`;
  if(!targetCache.has(key)) {
    if(targetCache.size>20)targetCache.clear();
    const request=api('/lesson/targets',{revision:S.revision,date,scope,lessonId:id});
    targetCache.set(key,request);
    request.catch(()=>targetCache.delete(key));
  }
  return targetCache.get(key);
}
function dropPermission(cell) {
  if (!S.dragLesson || !S.dragTargets) return null;
  const source=dragRows().find(l=>l.id===S.dragLesson.id);
  if (!source) return null;
  if(cell.dataset.date && cell.dataset.date!==S.dragLesson.date)return {allowed:false,reason:'Перенос доступен только внутри выбранного дня.'};
  if (cell.dataset.lesson) return S.dragTargets.swaps[cell.dataset.lesson] || {allowed:false,reason:'Это тот же урок.'};
  const field={teachers:'teacherIds',classes:'classIds',rooms:'roomIds'}[cell.dataset.rowKind];
  if (field && !source[field].includes(cell.dataset.row)) return {allowed:false,reason:'Переносите урок в строке своего учителя, класса или кабинета. Назначение кабинета можно изменить в редакторе.'};
  return S.dragTargets.moves[cell.dataset.period];
}

document.addEventListener('dragstart', (event) => {
  if(S.preview) {event.preventDefault();return;}
  const cell = event.target.closest(':is(.cell,.week-edit)');
  if (!cell || !cell.dataset.lesson) {
    event.preventDefault();
    return;
  }
  S.dragLesson = { id: cell.dataset.lesson, period: Number(cell.dataset.period), date:cell.dataset.date || S.date, scope:cell.dataset.scope || 'day' };
  S.lastDrag=S.dragLesson;
  S.dragTargets = null;
  S.suppressClickUntil = Date.now() + 900;
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', cell.dataset.lesson);
  cell.classList.add('dragging');

});

document.addEventListener('dragover', (event) => {
  const cell = event.target.closest(':is(.cell,.week-edit)');
  if (!cell || !S.dragLesson) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'move';
  $$(':is(.cell,.week-edit).drop-target').forEach((item) => { if (item !== cell) item.classList.remove('drop-target'); });
  cell.classList.add('drop-target');

  const feedback=$('#drag-feedback');
  if(feedback) feedback.textContent='Отпустите урок в выбранной клетке.';
});

document.addEventListener('dragleave', (event) => {
  const cell = event.target.closest(':is(.cell,.week-edit)');
  if (cell) cell.classList.remove('drop-target');
});

document.addEventListener('dragend', () => {
  clearDropTargets();
  $$(':is(.cell,.week-edit).dragging').forEach((cell) => cell.classList.remove('dragging'));
  S.dragLesson = null;
});

document.addEventListener('drop', async (event) => {
  const cell = event.target.closest(':is(.cell,.week-edit)');
  if (!cell || !S.dragLesson) return;
  event.preventDefault();
  const sourceId = S.dragLesson.id;
  if(cell.dataset.date && cell.dataset.date!==S.dragLesson.date) {clearDropTargets();S.dragLesson=null;await askConfirm({title:'Выберите место в этом же дне',text:'Уроки не переносятся на другие дни недели.',yes:'Понятно'});return;}
  const targetId = cell.dataset.lesson || '';
  const permission = dropPermission(cell);
  const source = dragRows().find(lesson=>lesson.id===sourceId);
  const rowField = {teachers:'teacherIds',classes:'classIds',rooms:'roomIds'}[cell.dataset.rowKind];
  clearDropTargets();
  $$(':is(.cell,.week-edit).dragging').forEach((item) => item.classList.remove('dragging'));
  S.dragLesson = null;
  S.suppressClickUntil = Date.now() + 900;
  if (sourceId === targetId) return;
  if (permission?.allowed===false) { await askConfirm({title:'Сюда нельзя перенести урок',text:permission.reason,yes:'Понятно'}); return; }
  if (!targetId && rowField && !source[rowField].includes(cell.dataset.row)) {
    await askConfirm({title:'Урок остаётся у своего учителя и класса',text:'Выберите свободную клетку в строке этого учителя, класса или кабинета.',yes:'Понятно'}); return;
  }
  try {
    if (targetId) {
      const source = dragRows().find((lesson) => lesson.id === sourceId);
      const target = dragRows().find((lesson) => lesson.id === targetId);
      const ok = await askConfirm({
        title: 'Поменять уроки местами?',
        text: `${describe(source)} ↔ ${describe(target)}. Проверим занятость учителей, классов и кабинетов.`,
        yes: 'Поменять',
      });
      if (!ok) return;
      const result = await api('/lesson/swap', {
        revision: S.revision, date: S.lastDrag.date, scope:S.lastDrag.scope, firstId: sourceId, secondId: targetId,
      });
      S.data = result.state;
      S.revision = result.revision;
      S.day = result.day;
      render();
      toast('Уроки поменялись местами.');
    } else {
      const result = await api('/lesson/move', {
        revision: S.revision, date: S.lastDrag.date, scope:S.lastDrag.scope, lessonId: sourceId, period: Number(cell.dataset.period),
      });
      S.data = result.state;
      S.revision = result.revision;
      S.day = result.day;
      render();
      toast('Урок перенесён.');
    }
  } catch (error) {
    await askConfirm({title:'Перестановка не выполнена',text:error.message,yes:'Понятно'});
  }
});

window.addEventListener('hashchange', () => {
  const page = location.hash.slice(1) || 'day';
  if (page !== S.page) setPage(page);
});

/* --------------------------------------------------------------------------
   start
   -------------------------------------------------------------------------- */

async function boot() {
  try {
    window.ScheduleStartup?.stage('loading-project');
    const requested = new URLSearchParams(location.search).get('date');
    const suffix=requested && /^\d{4}-\d{2}-\d{2}$/.test(requested) && !isWeekend(requested)?'?date='+encodeURIComponent(requested):'';
    const result=await api('/bootstrap'+suffix,undefined,60000);
    S.data=result.state;S.revision=result.revision;S.today=result.today;S.day=result.day;S.date=result.day.date;
    S.features=result.features;S.appVersion=result.server.version;showSaved(result.savedAt);
    S.page = PAGE_TITLES[location.hash.slice(1)] ? location.hash.slice(1) : 'day';
    window.ScheduleStartup?.stage('rendering-timetable');
    render();
    window.ScheduleStartup?.ready();
    if (S.page === 'reports') ensureReport();
    if (S.page === 'history') ensureHistory();
  } catch (error) {
    $('#main').innerHTML = window.ScheduleStartup?'':`<div class="page">${emptyState('Не удалось открыть расписание', 'Закройте программу и повторите запуск. Ваши данные сохранены.', 'alert')}</div>`;
    setSave('error', 'Нет связи');
    window.ScheduleStartup?.failed(error.message);
  }
}

// All deferred feature scripts must be ready before the first render, even
// when the state request finishes before assistant.js has downloaded.
document.addEventListener('DOMContentLoaded', boot, {once: true});







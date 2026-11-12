const $ = selector => document.querySelector(selector);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const stage = $('#stage');
const video = $('#video');
let deck;
let chapter = -1;
let step = 0;
let paused = false;
let black = false;
let elapsed = 0;
let previousTick = performance.now();
let controlTimer;
let lastNav = -1000;
let playbackVersion = 0;

function fit() {
  stage.style.transform = `translate(-50%,-50%) scale(${Math.min(innerWidth / 1920, innerHeight / 1080)})`;
}
addEventListener('resize', fit);
fit();

const hasDialog = () => Boolean(document.querySelector('dialog[open]'));
const current = () => deck?.sections[chapter];
const screens = section => section?.extra ? ['Категорирование', 'ИИ-риск-профиль'] : section?.autoLandingSeconds ? ['Сложная схема', 'Инструкции и QR'] : [];
const lastStep = section => screens(section).length ? 2 : 1;
function canPlay() { return current()?.video && step === 0 && !paused && !black && !hasDialog() && !document.hidden; }
function syncPlayback() {
  const attempt = ++playbackVersion;
  if (canPlay()) video.play().catch(() => {
    if (attempt === playbackVersion && canPlay()) { paused = true; drawControls(); }
  });
  else video.pause();
}

function drawSummary(section) {
  $('#summary').classList.toggle('compact', Boolean(section.extra) || section.graphic === 'risk-model');
  $('#summary').innerHTML = `<p class="eyebrow">${escapeHTML(section.graphic ? 'Цифровой инструмент' : 'Практика Роструда')}</p>
    <h2>${escapeHTML(section.tagline)}</h2>
    <ul>${section.bullets.map(text => `<li>${escapeHTML(text)}</li>`).join('')}</ul>
    ${section.metrics.length ? `<div class="metrics">${section.metrics.map(metric => `<div class="metric"><b>${escapeHTML(metric.value)}</b><span>${escapeHTML(metric.label)}</span></div>`).join('')}</div>` : ''}
    ${section.asOf ? `<p class="source-date">${escapeHTML(section.asOf)}</p>` : ''}
    ${section.autoLandingSeconds ? '<button id="show-instructions" class="secondary-action">Открыть инструкции ↗</button>' : ''}
    ${section.extra ? '<button id="show-risk-model" class="secondary-action">Как работает риск-модель ↗</button>' : ''}`;
  $('#show-instructions')?.addEventListener('click', () => go(chapter, 2));
  $('#show-risk-model')?.addEventListener('click', () => go(chapter, 2));
}

function drawGraphic(section) {
  const graphic = $('#graphic');
  graphic.hidden = !section.graphic;
  if (!section.graphic) { graphic.innerHTML = ''; return; }
  if (section.graphic === 'gasu') {
    graphic.innerHTML = `<p class="graphic-kicker">ГАС «Управление»</p><h2>Результаты работы<br>на одном экране</h2><div class="flow">
      <div class="flow-row"><b>01</b><span>Показатели деятельности</span></div>
      <div class="flow-row"><b>02</b><span>Оценка результатов</span></div>
      <div class="flow-row"><b>03</b><span>Методики премирования</span></div></div>`;
  } else if (section.graphic === 'risk-model') {
    graphic.innerHTML = `<p class="graphic-kicker">Машинное обучение · пилот 2026</p><h2>Аналитическая оценка<br>риска нарушений</h2><div class="flow">
      <div class="flow-row"><b>01</b><span>Восемь внутренних источников АСУ КНД</span></div>
      <div class="flow-row"><b>02</b><span>Логистическая регрессия и скоринг</span></div>
      <div class="flow-row"><b>03</b><span>Оценка риска и влияющие признаки</span></div></div>`;
  } else {
    graphic.innerHTML = `<p class="graphic-kicker">Сервисы для граждан</p><p class="domain">Онлайнинспекция.рф</p><div class="flow">
      <div class="flow-row"><b>01</b><span>Выбрать вопрос</span></div>
      <div class="flow-row"><b>02</b><span>Направить обращение</span></div>
      <div class="flow-row"><b>03</b><span>Получить ответ</span></div></div>
      <a class="online-link" href="https://онлайнинспекция.рф" target="_blank" rel="noopener noreferrer"><img src="assets/qr-online.svg" alt="QR-код сервиса Онлайнинспекция.рф"><span>Открыть сервис ↗</span></a>`;
  }
}

function drawLanding() {
  $('#landing').innerHTML = `<div class="landing-intro"><h2>Нужное действие —<br>в понятной инструкции</h2><p>Короткий маршрут, проверенные шаги и материалы, которые всегда доступны по ссылке.</p></div>
    <div class="instruction-grid">${deck.instructions.map(item => `<a class="instruction-card" href="${escapeHTML(item.url)}" target="_blank" rel="noopener noreferrer"><div><h3>${escapeHTML(item.title)}</h3><p>${escapeHTML(item.description)}</p></div><img src="${escapeHTML(item.qr)}" alt="QR-код: ${escapeHTML(item.title)}"><span class="link-label">Материалы monitoring.gov.ru ↗</span></a>`).join('')}</div>
    <div class="creation-process"><strong>Как создаём</strong><span>Описываем процесс</span><span>Готовим текст и интерфейс с ИИ</span><span>Проверяем шаги со специалистом</span><span>Публикуем и даём QR-ссылку</span></div>`;
}

function drawControls() {
  const section = current();
  const labels = screens(section);
  const screenIndex = step === 2 ? 1 : 0;
  $('#screen-nav').hidden = !labels.length;
  $('#screen-nav').innerHTML = labels.map((label, index) => `<button data-screen="${index === 0 ? (section.video ? 0 : 1) : 2}" ${index === screenIndex ? 'aria-current="step"' : ''}><span>${index + 1} / ${labels.length}</span>${escapeHTML(label)}</button>`).join('');
  $('#screen-nav').querySelectorAll('button').forEach(button => button.addEventListener('click', () => {
    if (Number(button.dataset.screen) === 2 && step === 2) return;
    go(chapter, Number(button.dataset.screen), Number(button.dataset.screen) === 0);
  }));
  $('#previous').disabled = chapter < 0;
  $('#next').disabled = chapter === deck.sections.length;
  $('#position').textContent = chapter < 0 ? 'Начало' : chapter === deck.sections.length ? 'Финал' : `${chapter + 1} / ${deck.sections.length}${labels.length ? ` · экран ${screenIndex + 1}/${labels.length}` : ''}`;
  $('#next').title = section && step !== 2 && labels.length ? `Далее: ${labels[1]} · →` : 'Следующий раздел · →';
  $('#pause').hidden = !section || step === 2 || (!section.video && !section.autoLandingSeconds) || (step === 1 && !section.autoLandingSeconds);
  $('#pause').textContent = paused ? '▶' : 'Ⅱ';
  $('#pause').setAttribute('aria-label', paused ? 'Продолжить' : 'Приостановить');
  $('#pause').title = `${paused ? 'Продолжить' : 'Пауза'} · P`;
  $('#progress').querySelectorAll('button').forEach((button, index) => {
    button.classList.toggle('current', index === chapter);
    button.classList.toggle('done', index < chapter);
    if (index === chapter) button.setAttribute('aria-current', 'step');
    else button.removeAttribute('aria-current');
  });
  $('#page-number').textContent = `${String(chapter + 1).padStart(2, '0')} / ${String(deck.sections.length).padStart(2, '0')}${labels.length ? ` · ${screenIndex + 1}/${labels.length}` : ''}`;
}

function go(index, requestedStep, replay = false) {
  const wasSecondary = step === 2;
  index = Number.isInteger(index) ? Math.max(-1, Math.min(deck.sections.length, index)) : -1;
  const changed = chapter !== index;
  chapter = index;
  const section = current();
  step = section ? Math.min(section.autoLandingSeconds || section.extra ? 2 : 1, Math.max(0, Number(requestedStep) || (section.video ? 0 : 1))) : 0;
  if (section && !section.video) step = 1;
  if (changed || replay) { elapsed = 0; paused = false; }
  else if (wasSecondary && step < 2) elapsed = 0;
  video.pause();
  stage.classList.toggle('cover', chapter < 0);
  stage.classList.toggle('closing', chapter === deck.sections.length);
  $('#cover').hidden = chapter >= 0;
  $('#chapter').hidden = !section;
  $('#closing').hidden = chapter !== deck.sections.length;
  $('#video-error').hidden = true;
  if (section) {
    const screen = step === 2 && section.extra ? section.extra : section;
    const isLanding = step === 2 && Boolean(section.autoLandingSeconds);
    $('#chapter-title').textContent = screen.title;
    $('#chapter-subtitle').textContent = screen.subtitle;
    $('#media-layout').hidden = isLanding;
    $('#landing').hidden = !isLanding;
    $('#still').hidden = !screen.video;
    video.hidden = !screen.video;
    video.classList.toggle('stopped', step !== 0);
    $('#still').src = step === 0 ? section.first : section.poster;
    $('#still').alt = `Кадр раздела «${section.title}»`;
    if (section.video && (changed || replay || video.dataset.section !== section.id)) {
      video.dataset.section = section.id;
      video.poster = section.first;
      video.src = section.video;
      video.load();
    }
    if (section.video && step === 0) video.currentTime = 0;
    drawSummary(screen); drawGraphic(screen);
    $('#media-caption').hidden = section.id !== 'ervk' || step === 2;
    $('#media-caption').textContent = section.id === 'ervk' ? 'Расчёт в АСУ КНД  ·  Подписание  ·  Передача в ЕРВК' : '';
  }
  drawControls();
  const hash = chapter < 0 ? '' : chapter === deck.sections.length ? '#thanks' : `#${section.id}${step === 2 ? '/2' : ''}`;
  history.replaceState(null, '', location.pathname + location.search + hash);
  syncPlayback();
  showControls();
}

function next() {
  if (chapter < 0) return go(0);
  if (chapter >= deck.sections.length) return;
  const section = current();
  if (section.autoLandingSeconds && step < 2) return go(chapter, 2);
  if (section.extra && step < 2) return go(chapter, 2);
  go(chapter + 1);
}
function previous() {
  if (chapter <= -1) return;
  if (chapter === deck.sections.length) return go(chapter - 1, lastStep(deck.sections[chapter - 1]));
  if (step === 2) return go(chapter, 1);
  go(chapter - 1, lastStep(deck.sections[chapter - 1]));
}
function nav(action) {
  const now = performance.now();
  if (now - lastNav < 250) return;
  lastNav = now;
  action();
}

function togglePause() {
  paused = !paused;
  syncPlayback();
  drawControls();
}
function setBlack(value) {
  black = value;
  $('#black').hidden = !value;
  syncPlayback();
}
function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  else document.documentElement.requestFullscreen().catch(() => {});
}
function showControls() {
  document.body.classList.remove('controls-hidden');
  clearTimeout(controlTimer);
  if (document.fullscreenElement) controlTimer = setTimeout(() => document.body.classList.add('controls-hidden'), 3500);
}

function openDialog(dialog) {
  if (hasDialog()) return;
  dialog.showModal();
  syncPlayback();
}
function openNotes() {
  const section = current();
  $('#speaker-content').innerHTML = section ? `<h3>${chapter + 1}. ${escapeHTML(section.title)}</h3><p class="cue">${escapeHTML(section.cue)}</p>${section.notes.map(paragraph => `<p>${escapeHTML(paragraph)}</p>`).join('')}
    ${section.needs.length ? `<div class="pending"><h4>К подготовке финальной версии</h4><ul>${section.needs.map(item => `<li>${escapeHTML(item)}</li>`).join('')}</ul></div>` : ''}
    <p class="source-date">Источники: ${section.sources.map(escapeHTML).join('; ')}</p>` : `<h3>${escapeHTML(deck.title)}</h3><p>${escapeHTML(deck.intro)}</p><p class="cue">После титула сразу начинаются ролики. Стрелки листают экраны, клавиша T открывает разделы, N — текст текущего раздела.</p>`;
  openDialog($('#notes-dialog'));
}

video.addEventListener('ended', () => {
  if (current()?.video && step === 0) go(chapter, 1);
});
video.addEventListener('error', () => {
  if (current()?.video && step === 0 && video.dataset.section === current().id) $('#video-error').hidden = false;
});
$('#retry').addEventListener('click', () => go(chapter, 0, true));
$('#start').addEventListener('click', () => nav(() => go(0)));
$('#restart').addEventListener('click', () => go(-1));
$('#next').addEventListener('click', () => nav(next));
$('#previous').addEventListener('click', () => nav(previous));
$('#pause').addEventListener('click', togglePause);
$('#contents').addEventListener('click', () => openDialog($('#contents-dialog')));
$('#notes').addEventListener('click', openNotes);
$('#fullscreen').addEventListener('click', toggleFullscreen);
$('#black').addEventListener('click', () => setBlack(false));
document.querySelectorAll('dialog').forEach(dialog => {
  dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', syncPlayback);
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const box = dialog.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
  });
});
stage.addEventListener('click', event => {
  if (event.detail > 1 || event.target.closest('button,a') || getSelection()?.toString() || !deck) return;
  nav(next);
});
addEventListener('keydown', event => {
  if (!deck || event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
  const key = event.key;
  if (black) { if (['Escape', ' ', 'Enter', 'ArrowRight', 'ArrowLeft', 'PageDown', 'PageUp', 'b', 'B', '.'].includes(key)) { event.preventDefault(); setBlack(false); } return; }
  if (hasDialog()) return;
  const nextKeys = ['ArrowRight', 'ArrowDown', 'PageDown', ' ', 'Enter'];
  const previousKeys = ['ArrowLeft', 'ArrowUp', 'PageUp', 'Backspace'];
  if (event.target.closest('input,textarea,[contenteditable="true"]')) return;
  if ([' ', 'Enter'].includes(key) && event.target.closest('button,a')) return;
  if (nextKeys.includes(key)) { event.preventDefault(); nav(next); }
  else if (previousKeys.includes(key)) { event.preventDefault(); nav(previous); }
  else if (key === 'Home') { event.preventDefault(); go(-1); }
  else if (key === 'End') { event.preventDefault(); go(deck.sections.length); }
  else if (event.code === 'KeyT') openDialog($('#contents-dialog'));
  else if (event.code === 'KeyN') openNotes();
  else if (event.code === 'KeyR' && current()) go(chapter, 0, true);
  else if (event.code === 'KeyP' && current()) togglePause();
  else if (event.code === 'KeyF' || key === 'F5') { event.preventDefault(); toggleFullscreen(); }
  else if (event.code === 'KeyB' || event.code === 'Period') setBlack(true);
  else if (/^Digit[0-9]$/.test(event.code)) { const index = event.code === 'Digit0' ? 9 : Number(event.code.slice(-1)) - 1; if (index < deck.sections.length) go(index, 0, true); }
});
addEventListener('mousemove', showControls);
addEventListener('touchstart', showControls, {passive:true});
document.addEventListener('fullscreenchange', showControls);
document.addEventListener('visibilitychange', () => { previousTick = performance.now(); syncPlayback(); });

function tick(now) {
  const delta = Math.max(0, now - previousTick);
  previousTick = now;
  const section = current();
  if (section?.autoLandingSeconds && step < 2 && !paused && !black && !hasDialog() && !document.hidden) {
    // Count only active time, including the held final frame after the short clip.
    if (step === 1 || (!video.paused && video.readyState >= 2)) elapsed += delta;
    const button = $('#show-instructions');
    const secondsLeft = Math.max(0, Math.ceil(section.autoLandingSeconds - elapsed / 1000));
    if (button) button.textContent = `Открыть инструкции · через ${secondsLeft} с ↗`;
    if (elapsed >= section.autoLandingSeconds * 1000) go(chapter, 2);
  }
  requestAnimationFrame(tick);
}

try {
  const response = await fetch('content.json?v=20261112-qa2');
  if (!response.ok) throw new Error('content unavailable');
  deck = await response.json();
  drawLanding();
  $('#contents-list').innerHTML = `<li><button data-chapter="-1"><span>↖</span>Титульный экран</button></li>` + deck.sections.map((section, index) => `<li><button data-chapter="${index}"><span>${String(index + 1).padStart(2, '0')}</span>${escapeHTML(section.title)}</button>${screens(section).length ? `<div class="contents-screens">${screens(section).map((label, screenIndex) => `<button data-chapter="${index}" data-step="${screenIndex === 0 ? 0 : 2}"><span>${index + 1}.${screenIndex + 1}</span>${escapeHTML(label)}</button>`).join('')}</div>` : ''}</li>`).join('');
  $('#progress').innerHTML = deck.sections.map((section, index) => `<button data-chapter="${index}" aria-label="${escapeHTML(section.title)}" title="${escapeHTML(section.title)}">${index + 1}</button>`).join('');
  document.querySelectorAll('[data-chapter]').forEach(button => button.addEventListener('click', () => {
    $('#contents-dialog').close();
    go(Number(button.dataset.chapter), Number(button.dataset.step) || 0, true);
  }));
  const [id, initialStep] = location.hash.slice(1).split('/');
  const initialIndex = deck.sections.findIndex(section => section.id === id);
  go(id === 'thanks' ? deck.sections.length : initialIndex, Number(initialStep));
  requestAnimationFrame(tick);
} catch (error) {
  $('#loading-error').hidden = false;
  $('#start').disabled = true;
  console.error('Could not load presentation', error);
}

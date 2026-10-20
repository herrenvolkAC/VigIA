/* Interacción local del informe. Todos los datos ya están incluidos en el HTML. */
(() => {
  'use strict';
  const report = JSON.parse(document.getElementById('report-data').textContent);
  const profiles = new Map(report.perfiles.map(p => [p.id, p]));
  const slides = Array.from(document.querySelectorAll('main > .sheet'));
  const body = document.body;
  const reportButton = document.getElementById('report-mode');
  const presentationButton = document.getElementById('presentation-mode');
  const motionButton = document.getElementById('motion-toggle');
  const fullscreenButton = document.getElementById('fullscreen-toggle');
  const navigation = document.querySelector('.presentation-nav');
  const selector = document.getElementById('slide-select');
  const previous = document.getElementById('previous-slide');
  const next = document.getElementById('next-slide');
  const counter = document.getElementById('slide-count');
  const progress = document.getElementById('deck-progress-value');
  const tooltip = document.getElementById('chart-tooltip');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const formatter = new Intl.NumberFormat('es-AR', {maximumFractionDigits: 0});
  let index = 0;
  let presentation = false;
  let motion = !reducedMotion.matches;
  let explicitMotionPreference = false;
  let printState = null;
  const seenSlides = new WeakSet();
  const runningAnimations = new Set();
  const hideHoverFunctions = [];
  let fitFrame = null;

  function fitSlide(slide, paper = false) {
    const canvas = slide.querySelector(':scope > .slide-canvas');
    if (!canvas) return;
    const previousDisplay = slide.style.getPropertyValue('display');
    const previousPriority = slide.style.getPropertyPriority('display');
    if (paper) slide.style.setProperty('display', 'block', 'important');
    const logicalWidth = slide.classList.contains('integrated-sheet') ? 2000 : 1280;
    canvas.style.width = `${logicalWidth}px`;
    canvas.style.height = 'auto';
    const naturalHeight = Math.max(canvas.scrollHeight, canvas.offsetHeight);
    const width = paper ? 277 * 96 / 25.4 : slide.clientWidth;
    const height = paper ? 190 * 96 / 25.4 : slide.clientHeight;
    if (width > 0 && height > 0 && naturalHeight > 0) {
      const scale = Math.min((width - 2) / logicalWidth, (height - 2) / naturalHeight);
      canvas.style.height = `${naturalHeight}px`;
      canvas.style.transform = `scale(${scale})`;
      canvas.style.left = `${Math.max(0, (width - logicalWidth * scale) / 2)}px`;
      canvas.style.top = `${Math.max(0, (height - naturalHeight * scale) / 2)}px`;
      slide.dataset.fitScale = scale.toFixed(4);
    }
    if (paper) {
      if (previousDisplay) slide.style.setProperty('display', previousDisplay, previousPriority);
      else slide.style.removeProperty('display');
    }
  }
  function fitDeck() {
    if (!presentation || printState !== null) return;
    const top = document.querySelector('.report-toolbar').getBoundingClientRect().height + 12;
    const bottom = navigation.getBoundingClientRect().height + 12;
    const main = document.querySelector('main');
    main.style.paddingTop = `${top}px`;
    main.style.paddingBottom = `${bottom}px`;
    fitSlide(slides[index]);
  }
  function scheduleFit() {
    if (fitFrame !== null) cancelAnimationFrame(fitFrame);
    fitFrame = requestAnimationFrame(() => {fitFrame = null; fitDeck();});
  }

  function number(value) { return formatter.format(value); }
  function hideHover() { tooltip.hidden = true; hideHoverFunctions.forEach(fn => fn()); }
  function finishAnimations() {
    for (const animation of runningAnimations) animation.cancel();
    runningAnimations.clear();
  }
  function animate(element, keyframes, options) {
    if (!motion || !element || !element.animate) return;
    const animation = element.animate(keyframes, options);
    runningAnimations.add(animation);
    animation.addEventListener('finish', () => runningAnimations.delete(animation), {once: true});
    animation.addEventListener('cancel', () => runningAnimations.delete(animation), {once: true});
  }
  function enter(slide, transition = true) {
    if (!motion) return;
    if (transition) animate(slide, [{opacity: .15, transform: 'translateY(12px)'}, {opacity: 1, transform: 'translateY(0)'}], {duration: 300, easing: 'ease-out'});
    const curve = slide.querySelector('.chart-curve');
    const area = slide.querySelector('.chart-area');
    if (curve) {
      const length = curve.getTotalLength();
      animate(area, [{opacity: 0}, {opacity: 1}], {duration: 650, fill: 'backwards'});
      animate(curve, [{strokeDasharray: `${length} ${length}`, strokeDashoffset: length}, {strokeDasharray: `${length} ${length}`, strokeDashoffset: 0}], {duration: 850, easing: 'ease-in-out', fill: 'backwards'});
    }
    animate(slide.querySelector('.active-threshold'), [{opacity: 0}, {opacity: 1}], {delay: 450, duration: 300, fill: 'backwards'});
    slide.querySelectorAll('.chart-reference, .inside-refs .ref, .alternative').forEach((el, i) => animate(el, [{opacity: .05}, {opacity: 1}], {delay: 750 + (i % 3) * 90, duration: 320, fill: 'backwards'}));
    slide.querySelectorAll('.big-stat, .interpretation, .access-number').forEach(el => animate(el, [{backgroundColor: '#dff0f1'}, {backgroundColor: 'transparent'}], {delay: curve ? 1100 : 250, duration: 750, fill: 'backwards'}));
    animate(slide.querySelector('.payment-strip'), [{opacity: .1, transform: 'translateY(5px)'}, {opacity: 1, transform: 'translateY(0)'}], {delay: curve ? 1250 : 300, duration: 300, fill: 'backwards'});
    animate(slide.querySelector('.visual-impact'), [{opacity: .1, transform: 'translateY(5px)'}, {opacity: 1, transform: 'translateY(0)'}], {delay: 1250, duration: 300, fill: 'backwards'});
    slide.querySelectorAll('.story-scene').forEach((el, i) => animate(el, [{opacity: .1, transform: 'translateY(8px)'}, {opacity: 1, transform: 'translateY(0)'}], {delay: i * 220, duration: 450, fill: 'backwards'}));
    slide.querySelectorAll('.compact-profile, .compact-finding').forEach((el, i) => animate(el, [{opacity: .1, transform: 'translateY(7px)'}, {opacity: 1, transform: 'translateY(0)'}], {delay: i * 120, duration: 350, fill: 'backwards'}));
    animate(slide.querySelector('.story-reading'), [{opacity: .1}, {opacity: 1}], {delay: 650, duration: 300, fill: 'backwards'});
  }
  function label(slide, i) {
    const title = slide.querySelector('h2, h1');
    const p = profiles.get(slide.id);
    return p ? `${p.sector} · ${p.operacion === 'PALETS OPERADOS' ? 'Carga + traslado' : p.operacion} ${p.camara ? '· ' + p.camara : ''}` : (title ? title.textContent.replace(/\s+/g, ' ') : `Lámina ${i+1}`);
  }
  slides.forEach((slide, i) => {
    if (!slide.id) slide.id = `lamina-${i+1}`;
    slide.setAttribute('tabindex', '-1');
    const canvas = document.createElement('div');
    canvas.className = 'slide-canvas';
    while (slide.firstChild) canvas.appendChild(slide.firstChild);
    slide.appendChild(canvas);
    const option = document.createElement('option');
    option.value = String(i); option.textContent = label(slide, i); selector.append(option);
  });
  function updateNavigation() {
    previous.disabled = index === 0;
    next.disabled = index === slides.length - 1;
    counter.textContent = `${index + 1} / ${slides.length}`;
    selector.value = String(index);
    progress.style.width = `${(index+1)/slides.length*100}%`;
  }
  function showSlide(value) {
    const target = Math.max(0, Math.min(slides.length-1, value));
    if (target === index && slides[target].classList.contains('is-active')) return;
    finishAnimations(); hideHover();
    slides[index].classList.remove('is-active');
    index = target;
    slides[index].classList.add('is-active');
    slides[index].scrollTop = 0;
    updateNavigation();
    if (presentation) {fitDeck(); enter(slides[index]);}
  }
  function setPresentation(value) {
    if (presentation === value) return;
    finishAnimations(); hideHover();
    if (value) {
      // Continúa desde la lámina que el lector estaba mirando.
      const y = window.innerHeight / 3;
      const visibleIndex = slides.findIndex(el => {const r=el.getBoundingClientRect(); return r.top<=y && r.bottom>y;});
      if (visibleIndex >= 0) index = visibleIndex;
    }
    presentation = value;
    body.classList.toggle('presentation', value);
    document.documentElement.classList.toggle('is-presenting', value);
    navigation.hidden = !value;
    reportButton.setAttribute('aria-pressed', String(!value));
    presentationButton.setAttribute('aria-pressed', String(value));
    slides.forEach((slide, i) => slide.classList.toggle('is-active', i === index));
    updateNavigation();
    if (value) {window.scrollTo(0, 0); slides[index].scrollTop = 0; fitDeck(); enter(slides[index]);}
    else {
      document.querySelector('main').style.removeProperty('padding-top');
      document.querySelector('main').style.removeProperty('padding-bottom');
      requestAnimationFrame(() => slides[index].scrollIntoView({behavior: 'instant', block: 'start'}));
    }
  }
  function updateMotion() {
    body.classList.toggle('motion-off', !motion);
    motionButton.textContent = `Animaciones: ${motion ? 'activadas' : 'desactivadas'}`;
    motionButton.setAttribute('aria-pressed', String(motion));
    if (!motion) finishAnimations();
  }
  reportButton.addEventListener('click', () => setPresentation(false));
  presentationButton.addEventListener('click', () => setPresentation(true));
  motionButton.addEventListener('click', () => {explicitMotionPreference=true; motion=!motion;updateMotion();});
  reducedMotion.addEventListener('change', e => {if(!explicitMotionPreference){motion=!e.matches;updateMotion();}});
  previous.addEventListener('click', () => showSlide(index-1));
  next.addEventListener('click', () => showSlide(index+1));
  selector.addEventListener('change', () => showSlide(Number(selector.value)));
  document.addEventListener('keydown', event => {
    if (document.querySelector('dialog[open]')) return;
    if (!presentation || event.altKey || event.ctrlKey || event.metaKey || /^(INPUT|SELECT|TEXTAREA)$/.test(event.target.tagName) || event.target.isContentEditable) return;
    if (['ArrowRight', 'PageDown'].includes(event.key)) {event.preventDefault();showSlide(index+1);}
    else if (['ArrowLeft', 'PageUp'].includes(event.key)) {event.preventDefault();showSlide(index-1);}
    else if (event.key === 'Home') {event.preventDefault();showSlide(0);}
    else if (event.key === 'End') {event.preventDefault();showSlide(slides.length-1);}
    else if (event.key === 'Escape') {event.preventDefault();setPresentation(false);}
  });
  document.addEventListener('click', event => {
    const anchor = event.target.closest('a[href^="#"]');
    if (!anchor || !presentation) return;
    const slide = document.getElementById(anchor.getAttribute('href').slice(1));
    const target = slides.indexOf(slide);
    if (target >= 0) {event.preventDefault(); showSlide(target);}
  });
  fullscreenButton.hidden = !document.documentElement.requestFullscreen;
  fullscreenButton.addEventListener('click', async () => {
    try {
      if(document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch (_) {fullscreenButton.textContent='Usá F11 para ampliar';}
  });
  document.addEventListener('fullscreenchange', () => {fullscreenButton.textContent=document.fullscreenElement?'Salir de pantalla completa':'Pantalla completa';scheduleFit();});
  window.addEventListener('resize', scheduleFit);
  window.addEventListener('load', scheduleFit);
  if (window.visualViewport) window.visualViewport.addEventListener('resize', scheduleFit);
  document.addEventListener('toggle', event => {if(event.target.tagName==='DETAILS') scheduleFit();}, true);
  function beforePrint() {
    if (printState !== null) return;
    printState = presentation;
    finishAnimations(); hideHover();
    // Compone todas las láminas en el mismo lienzo antes de escalar a A4.
    body.classList.add('presentation', 'print-layout');
    slides.forEach(slide => fitSlide(slide, true));
  }
  function afterPrint() {
    if (printState === null) return;
    body.classList.remove('print-layout');
    body.classList.toggle('presentation', printState);
    document.documentElement.classList.toggle('is-presenting', printState);
    printState = null;
    if (presentation) fitDeck();
  }
  document.getElementById('print-report').addEventListener('click', () => {beforePrint();window.print();});
  window.addEventListener('beforeprint', beforePrint);
  window.addEventListener('afterprint', afterPrint);
  function svgElement(tag, attrs) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [name, value] of Object.entries(attrs)) el.setAttribute(name,String(value));
    return el;
  }
  document.querySelectorAll('.threshold-chart').forEach(svg => {
    const p = profiles.get(svg.dataset.profile);
    if (!p || !p.valores.length) return;
    svg.dataset.interactive = 'true';
    const hover = svgElement('g', {class:'chart-hover', visibility:'hidden'});
    const guide = svgElement('line',{class:'hover-guide',y1:76,y2:438});
    const dot = svgElement('circle',{class:'hover-dot',r:6});
    hover.append(guide,dot);svg.append(hover);
    const hide = () => {hover.setAttribute('visibility','hidden');};
    hideHoverFunctions.push(hide);
    svg.addEventListener('pointerleave', () => {hide();tooltip.hidden=true;});
    svg.addEventListener('pointermove', event => {
      const matrix = svg.getScreenCTM();
      if (!matrix) return;
      const point = svg.createSVGPoint();point.x=event.clientX;point.y=event.clientY;
      const loc=point.matrixTransform(matrix.inverse());
      if(loc.x<88 || loc.x>1075 || loc.y<76 || loc.y>438){hide();tooltip.hidden=true;return;}
      const pct=(loc.x-88)/(1075-88)*100;
      const rank=Math.max(1,Math.ceil(pct/100*p.dias));
      tooltip.replaceChildren();
      if(rank>p.valores.length){
        hide();
        const text=document.createElement('strong');text.textContent='Sin base computable';tooltip.append(text);
        const sub=document.createElement('small');sub.textContent='Ese objetivo de días excede la base disponible.';tooltip.append(sub);
      }else{
        const bound=p.valores[rank-1];const suggested=Math.ceil(bound)-1;
        const achieved=p.diario.filter(day=>day.base>0 && day.produccion>suggested*day.base).length;
        const actualPct=achieved/p.dias*100;
        const title=document.createElement('small');title.textContent=`Objetivo: ${rank} de ${p.dias} días`;
        const amount=document.createElement('strong');amount.textContent=suggested>0?`${number(suggested)} ${p.unidad}`:'Sin umbral positivo';
        const desc=document.createElement('span');desc.textContent=suggested>0?`Con ese umbral: ${achieved} días (${actualPct.toLocaleString('es-AR',{maximumFractionDigits:1})}%)`:'La producción no permite alcanzar ese objetivo.';
        const foot=document.createElement('small');foot.textContent='Referencia entera para superar la meta.';
        tooltip.append(title,amount,desc,foot);
        const x=88+(1075-88)*rank/p.dias;const y=438-(438-76)*bound/Number(svg.dataset.ymax);
        guide.setAttribute('x1',x);guide.setAttribute('x2',x);dot.setAttribute('cx',x);dot.setAttribute('cy',y);hover.setAttribute('visibility','visible');
      }
      tooltip.hidden=false;
      const rect=tooltip.getBoundingClientRect();
      tooltip.style.left=`${Math.max(8,Math.min(event.clientX+18,window.innerWidth-rect.width-10))}px`;
      tooltip.style.top=`${Math.max(8,Math.min(event.clientY+16,window.innerHeight-rect.height-10))}px`;
    });
  });
  if ('IntersectionObserver' in window) {
    const observer=new IntersectionObserver(entries=>{
      for(const entry of entries){
        if(entry.isIntersecting && !presentation && !seenSlides.has(entry.target)){
          seenSlides.add(entry.target);enter(entry.target,false);
        }
      }
    },{threshold:.15});
    slides.forEach(slide=>observer.observe(slide));
  }
  updateMotion();updateNavigation();
})();

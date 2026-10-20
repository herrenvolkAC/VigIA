const { chromium } = require('C:/Users/207189/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path = require('path');
(async () => {
  const browser = await chromium.launch({headless:true, channel:'msedge'});
  const page = await browser.newPage({viewport:{width:1440,height:900}, deviceScaleFactor:1});
  const errors=[];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto('file:///' + path.resolve('outputs/informe_gerencial_umbrales_75_balanceado_20261019.html').replaceAll('\\','/'));
  await page.click('#presentation-mode');
  const slides = await page.locator('section.sheet').count();
  const layout=[];
  for(let i=0;i<slides;i++){
    await page.selectOption('#slide-select', String(i));
    await page.waitForTimeout(40);
    const info=await page.locator('section.sheet').nth(i).evaluate(el=>({id:el.id,scrollW:el.scrollWidth,clientW:el.clientWidth,scrollH:el.scrollHeight,clientH:el.clientHeight}));
    layout.push(info);
    if([0,2,16,17].includes(i)) await page.screenshot({path:`outputs/qa_slide_${i+1}.png`,fullPage:false});
  }
  const missing = await page.locator('[data-open-profile]').evaluateAll(btns => btns.map(b=>b.dataset.openProfile).filter(id=>!document.getElementById('detalle-'+id)));
  await page.selectOption('#slide-select','2');
  await page.locator('[data-open-profile^="escala-"]').first().click();
  const dialogOpen=await page.locator('dialog[open]').count();
  console.log(JSON.stringify({slides,errors,missing:[...new Set(missing)],overflow:layout.filter(x=>x.scrollW>x.clientW+1||x.scrollH>x.clientH+1),dialogOpen,layout},null,2));
  await browser.close();
})();

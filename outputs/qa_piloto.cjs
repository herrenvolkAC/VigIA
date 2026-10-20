const {chromium}=require('C:/Users/207189/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1440,height:900}});let errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('file:///C:/Ingenieria/VigIA/outputs/informe_gerencial_umbrales_piloto_20261019.html');await page.locator('#presentation-mode').click();await page.locator('#slide-select').selectOption({label:await page.locator('#slide-select option').filter({hasText:'Secos · Armado'}).textContent()});await page.waitForTimeout(500);await page.screenshot({path:'C:/Ingenieria/VigIA/outputs/piloto_impacto.png'});await page.locator('#secos-armado .integrated-case').first().click();console.log(JSON.stringify({slides:await page.locator('section.sheet').count(),dialog:await page.locator('dialog[open]').count(),errors}));await browser.close()})();




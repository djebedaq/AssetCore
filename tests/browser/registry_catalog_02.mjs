// Disposable Edge/Chromium acceptance. No storage state, HAR or traces are saved.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser=await chromium.launch({headless:true,ignoreDefaultArgs:['--hide-scrollbars'],args:['--disable-features=OverlayScrollbar,FluentOverlayScrollbar'],...(process.env.QA_BROWSER_CHANNEL ? {channel:process.env.QA_BROWSER_CHANNEL}: {})});
const context=await browser.newContext({viewport:{width:1440,height:900}});
const page=await context.newPage();
const base=process.env.PUBLIC_BASE_URL, out=process.env.QA_OUTPUT;
const errors=[], screenshots=[], checks=[];
const registryRequests=[];
page.on('request',request=>{const url=new URL(request.url());if(url.pathname==='/api/official-documents/registry/items')registryRequests.push(url.search);});
page.on('pageerror',error=>errors.push(error.message));
page.setDefaultTimeout(30000);
const shot=async (name,fullPage=true)=>{await page.screenshot({path:`${out}/${name}.png`,fullPage}); screenshots.push(`${name}.png`);};
const nav=async name=>page.locator('.sidebar-navigation').getByRole('button',{name,exact:true}).click();
const choose=async (name, option)=>{await page.getByRole('combobox',{name,exact:true}).click();await page.getByRole('option',{name:option,exact:typeof option==='string'}).click();};
const json=async path=>{const response=await page.request.get(`${base}/api${path}`);assert.equal(response.status(),200,path);return response.json();};
const wait=ms=>page.waitForTimeout(ms);
try {
 await page.goto(base);
 await page.locator('input[type=email]').fill(process.env.QA_EMAIL);
 await page.locator('input[type=password]').fill(process.env.QA_PASSWORD);
 await page.getByRole('button',{name:'Вход',exact:true}).click();
 await page.locator('.sidebar-navigation').waitFor();
 await nav('Машини');
 await page.getByRole('button',{name:'Всички',exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:'Всички',exact:true}).getAttribute('aria-pressed'),'true');
 await page.locator('.machine-registry-table tbody tr').first().waitFor();
 await shot('01-machines-all');
 const machines=await json('/machines');
 const mappings={G39300296:'8',G39300297:'9',G39300298:'10',G39300299:'11'};
 for(const [serial,number] of Object.entries(mappings)) assert.equal(machines.find(machine=>machine.serial_number===serial)?.inventory_number,number);
 await page.getByRole('textbox',{name:'Търсене',exact:true}).fill('G393002');
 await wait(500);assert.equal(await page.locator('.machine-registry-table tbody tr').count(),4);
 await shot('02-falch-identities');checks.push('All default; exact four physical serial mappings; server search');
 await page.goto(`${base}/machines?category=HPWJ`);
 await page.locator('.machine-registry-table tbody tr').first().waitFor();
 assert.equal(await page.locator('.machine-category.active').innerText(), 'Водоструйни машини с високо налягане\n19');
 await nav('Машини');
 assert.equal(await page.getByRole('button',{name:'Всички',exact:true}).getAttribute('aria-pressed'),'true');
 checks.push('Category deep link and menu reset to All');
 await page.setViewportSize({width:1440,height:620});
 const scrollbar=await page.locator('.sidebar-navigation').evaluate(element=>({
   width:element.offsetWidth-element.clientWidth,
   overflowing:element.scrollHeight>element.clientHeight,
   track:getComputedStyle(element,'::-webkit-scrollbar-track').backgroundColor,
   thumb:getComputedStyle(element,'::-webkit-scrollbar-thumb').backgroundColor,
 }));
 assert.equal(scrollbar.overflowing,true);assert.equal(scrollbar.width,7);assert.equal(scrollbar.track,'rgb(10, 29, 48)');
 await page.locator('.sidebar-navigation').hover();await page.mouse.wheel(0,220);await wait(200);
 await shot('07-sidebar-scrollbar',false);checks.push('Seven-pixel navy scrollbar with real wheel scrolling');
 await page.emulateMedia({forcedColors:'active'});
 assert.equal(await page.locator('.sidebar-navigation').evaluate(element=>getComputedStyle(element).scrollbarColor),'auto');
 await page.emulateMedia({forcedColors:'none'});await page.setViewportSize({width:1440,height:900});

 await nav('Каталожен конструктор');
 await page.getByRole('button',{name:'Свържи съществуваща референция',exact:true}).click();
 await page.getByRole('heading',{name:'Свържи съществуваща референция',exact:true}).waitFor();
 await shot('03-reference-source-selection');
 for(const number of ['4','5']) {
   await choose('Целева машина',new RegExp(`^№${number} ·`));
   await page.getByRole('button',{name:'Добави машина',exact:true}).click();
 }
 await choose('Публикуван източник / ревизия',/falch_500_pump · PARTS_CATALOG_V2/);
 await choose('Разглобена схема',/PDF страница 1/);
 await choose('Списък с резервни части',/PDF страница 2/);
 const selectedPart=page.locator('.reference-parts tbody tr').first();
 await selectedPart.getByRole('checkbox').check();
 await page.locator('.reference-previews img').first().waitFor();
 await shot('04-scheme-and-parts-list');
 await page.locator('.reference-reason textarea').fill('SYNTHETIC QA ONLY — selected physical variant verification acceptance');
 assert.equal(await page.getByRole('button',{name:'Запази',exact:true}).isEnabled(),false);
 await page.getByRole('checkbox',{name:/Проверих схемата/}).check();
 await shot('05-explicit-compatibility-confirmation');
 await page.getByRole('button',{name:'Запази',exact:true}).click();
 await page.getByText('Референцията е свързана с одитна следа.',{exact:true}).waitFor();
 checks.push('Existing original PDF; exact scheme/list; one variant; two machines; explicit confirmation');
 await nav('Каталог резервни части');
 await choose('Категория',/Водоструйни машини с високо налягане/);
 await choose('Избери машина',/^№4 ·/);
 await page.locator('.shared-references article').waitFor();
 await page.locator('.catalog-v2-layout table tbody tr').first().waitFor();
 await shot('06-machine-shared-reference');
 const combi=machines.find(machine=>machine.inventory_number==='4');
 const catalog=await json(`/catalog/v2/machines/${combi.id}`);
 assert.equal(catalog.references.length,1);assert.equal(catalog.references[0].part_ids.length,1);
 assert.equal(catalog.assemblies[0].is_supplemental,true);
 const detail=await json(`/catalog/v2/assemblies/falch_500_pump?machine_id=${combi.id}`);
 assert.equal(detail.parts.length,1);assert.equal(detail.diagrams.length,1);
 checks.push('CombiJet retains its identity; one approved variant shown with source, revision and operator');

 await nav('Официални документи и подписи');
 for(const [category,title,index] of [['transfers','Приемане / предаване','08'],['repairs','Ремонти','09'],['parts','Заявени части','10']]) {
   await page.getByRole('button',{name:new RegExp(`^Отвори ${title.replaceAll('/','\\/')}`)}).click();
   await page.getByRole('textbox',{name:'Търсене в избраната категория'}).waitFor();
   const query=category==='transfers'?'TR-REG':category==='repairs'?'REP-':'PR-';
   const response=page.waitForResponse(response=>response.url().includes(`/registry/items?category=${category}`)&&response.url().includes(`q=${query}`));
   await page.getByRole('textbox',{name:'Търсене в избраната категория'}).fill(query);await response;
   const signatureLabel=category==='transfers'?'Подписан':category==='repairs'?'Не се изисква':'Неподписан';
   await choose('Състояние на подписите',signatureLabel);
   const statusCode=category==='transfers'?'INCOMPLETE':category==='repairs'?'COMPLETED':'APPROVED';
   const statusLabel=category==='transfers'?'Незавършен':category==='repairs'?'Завършена':'Одобрена';
   await Promise.all([
     page.waitForResponse(response=>response.url().includes(`/registry/items?category=${category}`)&&response.url().includes(`status=${statusCode}`)),
     choose('Статус',statusLabel),
   ]);
   await page.getByRole('textbox',{name:'Търсене в избраната категория'}).fill('');
   await page.getByLabel('От дата',{exact:true}).fill('2026-08-01');
   await page.getByLabel('До дата',{exact:true}).fill('2026-09-30');
   await wait(600);await shot(`${index}-official-${category}-filters`);
   await page.getByRole('button',{name:'Всички категории',exact:true}).click();
 }
 checks.push('All three independent compact registries; debounce, workflow status, signature evidence and date filters');

 const qrRequests=[];page.on('request',request=>{if(/\/machines\/\d+\/qr$/.test(request.url()))qrRequests.push(request.url());});
 await nav('QR кодове');
 await page.getByRole('button',{name:/QA категория за QR печат.*27/}).waitFor();
 await wait(300);assert.equal(qrRequests.length,0);assert.equal(await page.locator('.qr-card').count(),0);
 await shot('11-qr-initial-categories');
 await page.getByRole('button',{name:/QA категория за QR печат.*27/}).click();
 await page.locator('.qr-screen-grid .qr-card img').last().waitFor();
 assert.equal(await page.locator('.qr-screen-grid .qr-card').count(),24);
 await shot('12-qr-selected-category');
 await page.evaluate(()=>{window.print=()=>{window.__qaPrintCalled=true;};});
 await page.getByRole('button',{name:'Печат на QR етикети (27)',exact:true}).click();
 await page.waitForFunction(()=>window.__qaPrintCalled===true);
 assert.equal(await page.locator('.qr-print-grid .qr-card').count(),27);
 await page.emulateMedia({media:'print'});await shot('13-qr-print-selected-category');
 assert.equal(await page.locator('.qr-screen-grid').isVisible(),false);
 await page.pdf({path:`${out}/qr-selected-category.pdf`,format:'A4',printBackground:true});
 await page.emulateMedia({media:'screen'});await page.evaluate(()=>window.dispatchEvent(new Event('afterprint')));
 checks.push('No initial QR images; 24-label display page; all 27 selected labels in Chromium print output');
 await page.setViewportSize({width:390,height:844});await shot('14-mobile-qr');
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
 await page.locator('.mobile-toggle').click();
 await nav('Машини');await page.locator('.machine-registry-table').waitFor();await shot('15-mobile-machines');
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
 await page.setViewportSize({width:1440,height:900});
 for(const [locale,label] of [['en','English'],['ru','Русский']]) {
   await page.locator('.language-switch').getByRole('combobox').click();await page.getByRole('option',{name:label,exact:true}).click();
   await wait(500);await shot(`16-machines-${locale}`);
   assert.equal(await page.locator('body').innerText().then(text=>/ref\.|registry\.signatures/.test(text)),false);
 }
 await page.getByRole('combobox').first().focus();await page.keyboard.press('Tab');
 assert.equal(await page.evaluate(()=>document.activeElement===document.body),false);
 checks.push('390-pixel responsive views; BG/EN/RU; keyboard focus');
 assert.deepEqual(errors,[]);
 await writeFile(`${out}/qa-results.json`,JSON.stringify({passed:true,browser:await browser.version(),checks,screenshots,scrollbar,errors},null,2));
 console.log(`Browser acceptance passed: ${checks.length} groups; ${screenshots.length} screenshots.`);
} catch(error) {
 await page.screenshot({path:`${out}/failed-step.png`,fullPage:true});
 const safe=String(error.stack||error).replaceAll(process.env.QA_PASSWORD,'[redacted]');console.error(safe);console.error(JSON.stringify(registryRequests.slice(-12)));
 await writeFile(`${out}/qa-results.json`,JSON.stringify({passed:false,checks,screenshots,error:safe},null,2));process.exitCode=1;
} finally {await browser.close();}

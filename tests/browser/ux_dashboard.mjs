// Real browser acceptance. Use only the disposable fixture runner in this folder.
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';

export async function uxDashboard({page, browser, baseUrl, screenshotDir, credentials, observerCredentials}) {
 const out=screenshotDir;
 page.setDefaultTimeout(30000);
 const redact=value=>[credentials.password,observerCredentials.password].reduce((text,secret)=>text.replaceAll(secret,'[redacted]'),String(value));
let signatureSequence=0; const signatureSeed=Math.floor(Math.random()*40)+20;
const errors=[]; page.on('pageerror',e=>errors.push(redact(e.message)));
const nav=async name=>page.locator('.sidebar').getByRole('button',{name,exact:true}).click();
try {
 await page.goto(baseUrl);
 await page.locator('input[type=email]').fill(credentials.email);
 await page.locator('input[type=password]').fill(credentials.password);
 await page.getByRole('button',{name:'Вход',exact:true}).click();
 await page.getByRole('heading',{name:'Машини по категории',exact:true}).waitFor();
 for(const locale of ['bg','en','ru']) {
  await page.setViewportSize({width:1440,height:1000});
  if(locale!=='bg') {await page.locator('.language-switch').getByRole('combobox').click();await page.getByRole('option',{name:locale==='en'?'English':'Русский',exact:true}).click();}
  for(const width of [1920,1440,1280,900,390]) {
   await page.setViewportSize({width,height:1000});
   await page.screenshot({path:`${out}/dashboard-${locale}-${width}.png`,fullPage:true});
   const over=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1);
   assert.equal(over,false,`dashboard overflow ${locale}/${width}`);
  }
 }
 await page.setViewportSize({width:1440,height:1000});
 await page.locator('.language-switch').getByRole('combobox').click();await page.getByRole('option',{name:'Български',exact:true}).click();
 await nav('Приемане / предаване');
 const currentActive=await (await page.request.get(`${baseUrl}/api/workspace/batches?context=active`)).json();
 if(!currentActive.total) await page.getByRole('button',{name:'Индивидуална история',exact:true}).click();
 await page.getByRole('button',{name:'Детайли',exact:true}).first().click();
 await page.locator('.batch-details').waitFor();
 await page.screenshot({path:`${out}/transfer-inline-details.png`,fullPage:true});
 assert.equal(await page.locator('.batch-details').getByRole('button',{name:'Детайли',exact:true}).count(),0);
 // All operational changes below use the real forms and signature workflow.
 const firstBatch=await (await page.request.get(`${baseUrl}/api/workspace/batches?context=active`)).json();
 if(firstBatch.total) assert.equal(firstBatch.items[0].issued_machines,2);
 async function receive(machineNumber, remaining) {
  await page.getByRole('button',{name:'Приеми',exact:true}).click();
  const modal=page.getByRole('dialog',{name:'Приеми',exact:true});
  await modal.getByRole('checkbox',{name:`Връщане на машина №${machineNumber}`,exact:true}).check();
  await modal.getByLabel('Състояние при връщане *',{exact:true}).fill('Synthetic UX QA verified return condition');
  await modal.getByLabel('Резултат / необходима последваща работа *',{exact:true}).fill('Synthetic UX QA return result');
  await modal.getByRole('button',{name:'Преглед и потвърждение',exact:true}).click();
  await modal.getByRole('button',{name:'Потвърди връщането',exact:true}).click();
  for(let signer=0;signer<2;signer++) {
   const canvas=modal.locator('canvas.signature-canvas'); await canvas.waitFor();
   await modal.locator('.signature-summary').waitFor();
   await canvas.scrollIntoViewIfNeeded(); const r=await canvas.boundingBox();
   const y=50+signatureSeed+(++signatureSequence)*8;
   await page.mouse.move(r.x+40,r.y+y);await page.mouse.down();
   for(let i=0;i<12;i++) await page.mouse.move(r.x+40+i*15,r.y+y+Math.sin(i+signatureSequence)*18,{steps:2});
   await page.mouse.up();
   await modal.locator('.signature-consent input').check();
   await modal.getByRole('button',{name:'Преглед на подписа',exact:true}).click();
   await modal.getByRole('button',{name:'Потвърди подписа',exact:true}).click();
   if(signer===0) await modal.locator('.signature-review').waitFor({state:'hidden'});
  }
  await modal.getByText('Връщането е записано успешно.',{exact:true}).waitFor();
  await modal.getByRole('button',{name:'Готово',exact:true}).click();
  const active=await (await page.request.get(`${baseUrl}/api/workspace/batches?context=active`)).json();
  assert.equal(active.total,remaining?1:0);
  if(remaining) assert.equal(active.items[0].still_issued_machines,remaining);
  await page.screenshot({path:`${out}/transfer-remaining-${remaining}.png`,fullPage:true});
 }
 if(firstBatch.total) {await receive('QA-UX-1',1);await receive('QA-UX-2',0);} else assert.equal((await (await page.request.get(`${baseUrl}/api/workspace/batches?context=completed`)).json()).total,1);
 await nav('Машини'); await nav('Приемане / предаване');
 await page.getByRole('button',{name:'Индивидуална история',exact:true}).click();
 await page.getByRole('button',{name:'Детайли',exact:true}).first().click();
 await page.locator('.batch-details').waitFor();
 const complete=(await (await page.request.get(`${baseUrl}/api/workspace/batches?context=completed`)).json()).items[0];
 const completeDetails=await (await page.request.get(`${baseUrl}/api/transfer-batches/${complete.batch_id}`)).json();
 assert.equal(completeDetails.return_operations.filter(item=>item.signing_status==='COMPLETED').length,2);
 assert.equal(await page.locator('.batch-details > section > .batch-transfer-item').count(),completeDetails.return_operations.length);
 await page.screenshot({path:`${out}/completed-partial-return-history.png`,fullPage:true});
 // Download original issue/return documents from the inline view.
 const doc=page.locator('.batch-details').getByRole('button',{name:'DOCX',exact:true}).first();
 if(await doc.count()) {const download=page.waitForEvent('download');await doc.click();assert.equal(await (await download).failure(),null);}
 const pdf=page.locator('.batch-details').getByRole('button',{name:'PDF',exact:true}).first();
 const pdfDownload=page.waitForEvent('download');await pdf.click();assert.equal(await (await pdfDownload).failure(),null);
 const zipDownload=page.waitForEvent('download');await page.locator('.batch-details .batch-detail-actions button').first().click();assert.equal(await (await zipDownload).failure(),null);
 await page.locator('.batch-details').getByRole('button',{name:'Преглед',exact:true}).first().click();
 await page.locator('object.generated-document-preview').waitFor();
 await page.screenshot({path:`${out}/preserved-pdf-preview.png`,fullPage:true});
 await page.getByRole('dialog').getByRole('button',{name:'Затвори',exact:true}).click();
 await nav('Ремонти');
 const already=await (await page.request.get(`${baseUrl}/api/workspace/repairs?q=Synthetic+UX+QA+timeline`)).json();
 if(!already.total) {
  await page.getByRole('button',{name:'Нов ремонт',exact:true}).click();
  const create=page.getByRole('dialog',{name:'Нов вътрешен ремонт',exact:true});
  await create.getByRole('combobox',{name:'Машина',exact:true}).click();
  await page.getByRole('combobox',{name:'Търсене: Машина',exact:true}).fill('QA-UX-1');
  await page.getByRole('option',{name:/QA UX asset 1/}).click();
  await create.getByLabel('Установен проблем',{exact:true}).fill('Synthetic UX QA timeline repair');
  await create.getByLabel('Състояние преди ремонта',{exact:true}).fill('Synthetic UX QA condition');
  await create.getByRole('button',{name:'Създай ремонт',exact:true}).click();
  await create.waitFor({state:'hidden'});
 }

 await page.getByRole('combobox',{name:'Категория',exact:true}).click();await page.getByRole('option',{name:'QA категория A',exact:true}).click();
 await page.getByText('Synthetic UX QA repair category 2',{exact:false}).waitFor();
 await page.getByText('Synthetic UX QA repair category 3',{exact:false}).waitFor({state:'hidden'});
 await page.getByRole('textbox',{name:'Търсене',exact:true}).fill('Synthetic UX QA');
 await page.getByLabel('От дата',{exact:true}).fill(new Date().toISOString().slice(0,10));
 await page.getByRole('combobox',{name:'Статус',exact:true}).click();await page.getByRole('option',{name:'Приета',exact:true}).click();
 await page.screenshot({path:`${out}/repairs-category-filters.png`,fullPage:true});
 // Complete an existing QA repair through all original stages and open its evidence.
 await page.locator('.repair-card').filter({hasText:'Synthetic UX QA repair category 2'}).click();
 const repairModal=page.getByRole('dialog',{name:/REP-/});
 const repairReference=await repairModal.getAttribute('aria-label');
 await repairModal.getByRole('button',{name:'Запази и продължи към Диагностика',exact:true}).click();
 await repairModal.getByLabel('Диагностика',{exact:true}).fill('Synthetic UX QA verified diagnosis');
 await repairModal.getByLabel('Необходима работа',{exact:true}).fill('Synthetic UX QA verified work');
 await repairModal.getByLabel('Реално време за диагностика (минути)',{exact:true}).fill('35');
 await repairModal.getByRole('button',{name:'Запази и продължи към ремонт',exact:true}).click();
 await repairModal.getByLabel('Извършена работа',{exact:true}).fill('Synthetic UX QA completed work');
 await repairModal.getByLabel('Реално време за ремонт (минути)',{exact:true}).fill('70');
 await repairModal.getByRole('button',{name:'Запази и продължи към Завършване',exact:true}).click();
 await repairModal.getByLabel('Успешен тест',{exact:true}).selectOption('yes');
 await repairModal.getByLabel('Метод на тестване',{exact:true}).fill('Synthetic UX QA functional test');
 await repairModal.getByLabel('Реално време за тестване (минути)',{exact:true}).fill('25');
 await repairModal.getByLabel('Реален резултат от теста',{exact:true}).fill('Synthetic UX QA verified result');
 await repairModal.getByLabel('Състояние след ремонта',{exact:true}).fill('Synthetic UX QA ready condition');
 await repairModal.getByLabel('Краен резултат',{exact:true}).fill('Synthetic UX QA successful completion');
 await repairModal.getByLabel('Три имена',{exact:true}).fill('QA UX Operator');
 await repairModal.getByLabel('Длъжност',{exact:true}).fill('QA operator');
 await repairModal.getByLabel('Минути',{exact:true}).fill('30');
 await repairModal.getByRole('button',{name:'Добави участник',exact:true}).click();
 await repairModal.locator('.request-line-list').getByText('QA UX Operator',{exact:true}).waitFor();
 page.once('dialog',dialog=>dialog.accept());
 await repairModal.getByRole('button',{name:'Завърши ремонта и създай протокол',exact:true}).click();
 await repairModal.locator('.document-list').getByRole('button',{name:'DOCX',exact:true}).waitFor();
 await repairModal.getByRole('button',{name:'Затвори',exact:true}).click();
 await page.getByRole('combobox',{name:'Статус',exact:true}).click();
 await page.getByRole('option',{name:'Завършена',exact:true}).click();
 const finished=page.locator('.repair-card').filter({hasText:'Synthetic UX QA repair category 2'});
 await finished.click();
 assert.equal(await repairModal.getAttribute('aria-label'),repairReference);
 for(const format of ['DOCX','PDF']) {
  const download=page.waitForEvent('download');
  await repairModal.locator('.document-list').getByRole('button',{name:format,exact:true}).click();
  assert.equal(await (await download).failure(),null);
 }
 await page.screenshot({path:`${out}/completed-repair-original-protocols.png`,fullPage:true});
 await repairModal.getByRole('button',{name:'Затвори',exact:true}).click();
 await nav('Каталог резервни части');
 const category=page.getByRole('combobox',{name:'Категория',exact:true});
 await category.click();await page.getByRole('option',{name:'QA',exact:true}).click();
 const machine=page.getByRole('combobox',{name:'Избери машина',exact:true});
 await machine.click();await page.getByRole('option',{name:/QA UX asset 5/}).click();
 await page.getByText('QA тестова част',{exact:true}).first().waitFor();
 await page.locator('.catalog-v2-workspace').waitFor();
 const runtimeImage=page.locator('.catalog-v2-diagram-canvas img');await runtimeImage.waitFor();await runtimeImage.evaluate(img=>img.decode());
 await page.locator('.catalog-v2-hotspot').first().click();
 await page.getByRole('dialog').waitFor();
 await page.screenshot({path:`${out}/catalog-original-hotspot-dialog.png`,fullPage:true});
 await page.getByRole('dialog').getByRole('button',{name:'Затвори',exact:true}).click();
 await page.screenshot({path:`${out}/published-catalog-hotspot.png`,fullPage:true});
 await category.click();await page.getByRole('option',{name:/^QA категория B/}).click();
 assert.equal(await machine.innerText(),'Избери машина от регистъра…');
 await machine.click();
 await page.getByRole('option',{name:/QA UX asset 4/}).waitFor();
 assert.equal(await page.getByRole('option',{name:/QA UX asset 5/}).count(),0);
 assert.equal(await page.getByRole('option',{name:/QA UX asset 4/}).count(),1);
 await page.keyboard.press('Escape');
 await nav('Машини');
 await page.locator('.machine-category-pills').getByRole('button',{name:'Всички',exact:true}).click();
 await page.getByRole('textbox',{name:'Търсене',exact:true}).fill('QA-UX-1');
 const row=page.locator('tbody tr').filter({hasText:'QA UX asset 1'});
 await row.getByRole('button',{name:'Паспорт',exact:true}).click();
 await page.getByRole('tab',{name:'История',exact:true}).click();
 const events=page.locator('.passport-timeline-list > li');await events.first().waitFor();
 const keys=await events.evaluateAll(items=>items.map(item=>item.getAttribute('data-event-key')));
 assert.equal(new Set(keys).size,keys.length);
 const timestamps=await events.locator('time').evaluateAll(items=>items.map(item=>Date.parse(item.dateTime)));
 assert.ok(timestamps.every((value,index)=>index===0||value<=timestamps[index-1]));
 await events.first().scrollIntoViewIfNeeded();
 await page.screenshot({path:`${out}/machine-timeline.png`,fullPage:true});
 const originalRepair=await (await page.request.get(`${baseUrl}/api/workspace/repairs?q=Synthetic+UX+QA+timeline`)).json();
 await events.filter({hasText:originalRepair.items[0].repair_reference}).getByRole('button',{name:'Отвори оригиналния запис',exact:true}).first().click();
 await page.getByRole('dialog',{name:/REP-/}).waitFor();
 await page.screenshot({path:`${out}/timeline-original-repair.png`,fullPage:true});
 await page.getByRole('dialog').getByRole('button',{name:'Затвори',exact:true}).click();
 await nav('Машини');await page.locator('.machine-category-pills').getByRole('button',{name:'Всички',exact:true}).click();await page.getByRole('textbox',{name:'Търсене',exact:true}).fill('QA-UX-6');
 await page.locator('tbody tr').filter({hasText:'QA UX asset 6'}).getByRole('button',{name:'Паспорт',exact:true}).click();
 await page.getByRole('tab',{name:'История',exact:true}).click();
 await page.getByText('Няма регистрирани събития за тази машина.',{exact:true}).waitFor();
 await page.screenshot({path:`${out}/machine-empty-timeline.png`,fullPage:true});
 await page.getByRole('dialog').getByRole('button',{name:'Затвори',exact:true}).click();
 await nav('Табло');
 const activity=page.locator('.ac-activity button');await activity.first().waitFor();
 await activity.first().click();
 assert.equal(await page.locator('.ac-dashboard').count(),0);
 if(await page.getByRole('dialog').count()) await page.getByRole('dialog').getByRole('button',{name:'Затвори',exact:true}).click();
 await page.emulateMedia({reducedMotion:'reduce'});await nav('Табло');
 await page.getByRole('heading',{name:'Машини по категории',exact:true}).waitFor();
 assert.equal(await page.locator('.stat-card').first().evaluate(item=>getComputedStyle(item).animationName),'none');
 await page.screenshot({path:`${out}/dashboard-reduced-motion.png`,fullPage:true});
 // Real empty search results and keyboard interaction, including a long list in a modal.
 await nav('Ремонти');
 await page.getByRole('textbox',{name:'Търсене',exact:true}).fill('QA_ABSENT_RECORD_20261008');
 await page.locator('.ac-pagination').getByText('Резултати: 0',{exact:true}).waitFor();
 await page.screenshot({path:`${out}/repairs-empty-search.png`,fullPage:true});
 await page.getByRole('button',{name:'Изчисти',exact:true}).click();
 await page.getByRole('button',{name:'Нов ремонт',exact:true}).click();
 const newRepair=page.getByRole('dialog',{name:'Нов вътрешен ремонт',exact:true});
 const target=newRepair.getByRole('combobox',{name:'Машина',exact:true});
 await target.focus();await target.press('ArrowDown');
 const list=page.locator('.ac-select-menu [role=listbox]');
 await list.getByRole('option').nth(10).waitFor();
 assert.ok(await list.evaluate(el=>el.scrollHeight>el.clientHeight));
 await page.getByRole('combobox',{name:'Търсене: Машина',exact:true}).press('End');
 await page.screenshot({path:`${out}/keyboard-long-list.png`,fullPage:true});
 await page.keyboard.press('Escape');
 assert.equal(await target.evaluate(el=>el===document.activeElement),true);
 await newRepair.getByRole('button',{name:'Отказ',exact:true}).click();
 const modules={bg:[['Машини','machines'],['Приемане / предаване','transfers'],['Ремонти','repairs'],['Заявени части','requests'],['Каталог резервни части','catalog']],en:[['Assets','machines'],['Issue / return','transfers'],['Repairs','repairs'],['Requested parts','requests'],['Spare-parts catalog','catalog']]};
 for(const locale of ['bg','en']) {
  await page.setViewportSize({width:1440,height:1000});
  if(locale==='en'){await page.locator('.language-switch').getByRole('combobox').click();await page.getByRole('option',{name:'English',exact:true}).click();}
  for(const [label,slug] of modules[locale]) {
   await nav(label);
   await page.locator('.ac-filter-toolbar, .catalog-v2-machine').first().waitFor();
   for(const width of [1920,1440,1280,900,390]) {
    await page.setViewportSize({width,height:1000});
    await page.screenshot({path:`${out}/${slug}-${locale}-${width}.png`,fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1),false,`${slug} overflow ${locale}/${width}`);
   }
   await page.setViewportSize({width:1440,height:1000});
  }
 }
 await page.locator('.language-switch').getByRole('combobox').click();await page.getByRole('option',{name:'Български',exact:true}).click();
 const observerContext=await browser.newContext({viewport:{width:1280,height:900}});
 const observer=await observerContext.newPage();
 await observer.goto(baseUrl);
 await observer.locator('input[type=email]').fill(observerCredentials.email);
 await observer.locator('input[type=password]').fill(observerCredentials.password);
 await observer.getByRole('button',{name:'Вход',exact:true}).click();
 await observer.locator('.machine-category-pills').getByRole('button',{name:'Всички',exact:true}).click();
 await observer.getByRole('textbox',{name:'Търсене',exact:true}).fill('QA-UX-1');
 await observer.locator('tbody tr').filter({hasText:'QA UX asset 1'}).getByRole('button',{name:'Паспорт',exact:true}).click();
 await observer.getByText('Ограничен изглед',{exact:true}).waitFor();
 assert.equal(await observer.getByRole('tab',{name:'История',exact:true}).count(),0);
 assert.equal((await observer.request.get(`${baseUrl}/api/workspace/repairs`)).status(),403);
 await observer.screenshot({path:`${out}/observer-authorized-limited-passport.png`,fullPage:true});
 await observerContext.close();
 assert.deepEqual(errors,[]);
 console.log('Real browser operational workflows, signatures, filters, dependent catalog and timeline passed.');
 await writeFile(`${out}/qa-results.json`,JSON.stringify({errors,phase:'complete workflows',viewports:[1920,1440,1280,900,390],languages:['bg','en','ru']},null,2));
 console.log('QA screenshot artifacts were captured.');
} catch(error) {
 await page.screenshot({path:`${out}/failure.png`,fullPage:true});
 throw new Error(redact(error.stack || error));
}
}

export async function emptyDashboard({page, baseUrl, screenshotDir, credentials}) {
 await page.goto(baseUrl);
 await page.locator('input[type=email]').fill(credentials.email);
 await page.locator('input[type=password]').fill(credentials.password);
 let release;
 const pending=new Promise(resolve=>{release=resolve});
 await page.route(`${baseUrl}/api/dashboard`,async route=>{await pending;await route.continue()});
 await page.getByRole('button',{name:'Вход',exact:true}).click();
 await page.locator('.loading').waitFor();
 await page.screenshot({path:`${screenshotDir}/dashboard-real-loading.png`,fullPage:true});
 release();
 await page.getByText('Все още няма оперативна активност.',{exact:true}).waitFor();
 await page.unroute(`${baseUrl}/api/dashboard`);
 const dashboard=await (await page.request.get(`${baseUrl}/api/dashboard`)).json();
 assert.equal(dashboard.total_machines,19);
 assert.equal(dashboard.categories.reduce((total,item)=>total+item.asset_count,0)+dashboard.uncategorized_assets,19);
 assert.equal(dashboard.recent_activity.length,0);
 await page.screenshot({path:`${screenshotDir}/dashboard-real-empty.png`,fullPage:true});
 console.log('Real loading, empty activity and verified 19-machine inventory passed.');
}

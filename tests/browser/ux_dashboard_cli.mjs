// Credentials stay in process memory; no storage state, HAR or trace is written.
import {createRequire} from 'node:module';
import {emptyDashboard, uxDashboard} from './ux_dashboard.mjs';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser=await chromium.launch({headless:true,...(process.env.QA_BROWSER_CHANNEL ? {channel:process.env.QA_BROWSER_CHANNEL} : {})});
const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
const page=await context.newPage();
const credentials={email:process.env.QA_EMAIL,password:process.env.QA_PASSWORD};
const observerCredentials={email:'ux-observer@assetcore.invalid',password:process.env.QA_OBSERVER_PASSWORD};
const redact=value=>[credentials.password,observerCredentials.password].filter(Boolean).reduce((text,secret)=>text.replaceAll(secret,'[redacted]'),String(value));
try {
 const run=process.env.QA_PHASE==='empty' ? emptyDashboard : uxDashboard;
 await run({page,browser,baseUrl:process.env.PUBLIC_BASE_URL,screenshotDir:process.env.QA_OUTPUT,credentials,observerCredentials});
} catch(error) {console.error(redact(error.stack || error));process.exitCode=1;}
finally {await browser.close();}

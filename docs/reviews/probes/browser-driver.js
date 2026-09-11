const { chromium } = require('playwright-core');
const SHOTS = process.env.SHOTS || '/tmp/claude-1000/-home-aliasgher-qonvo/e506e586-9025-4847-b76d-3e95c83c7f8e/scratchpad/shots';
const PORT = process.env.CDP || '9222';
(async () => {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:' + PORT);
  const ctx = browser.contexts()[0];
  let page = ctx.pages().find(p => !p.url().startsWith('devtools')) || await ctx.newPage();
  const out = [];
  for (const arg of process.argv.slice(2)) {
    const [cmd, ...rest] = arg.split('::');
    const a = rest.join('::');
    try {
      if (cmd === 'goto') { await page.goto(a, { waitUntil: 'domcontentloaded', timeout: 45000 }); await page.waitForTimeout(1500); }
      else if (cmd === 'wait') await page.waitForTimeout(Number(a));
      else if (cmd === 'size') { const [w,h]=a.split('x').map(Number); await page.setViewportSize({width:w,height:h}); }
      else if (cmd === 'click') { await page.click(a, { timeout: 15000 }); await page.waitForTimeout(1200); }
      else if (cmd === 'fill') { const [sel,...v]=a.split('=>'); await page.fill(sel, v.join('=>')); }
      else if (cmd === 'upload') { const [sel,...f]=a.split('=>'); await page.setInputFiles(sel, f.join('=>')); await page.waitForTimeout(2500); out.push('uploaded'); }
      else if (cmd === 'press') await page.keyboard.press(a);
      else if (cmd === 'shot') { const [name, full] = a.split('|'); await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: full === 'full' }); out.push(`shot ${SHOTS}/${name}.png`); }
      else if (cmd === 'text') out.push((await page.locator(a || 'body').innerText()).slice(0, 14000));
      else if (cmd === 'url') out.push(page.url());
      else if (cmd === 'eval') out.push(String(await page.evaluate(a)).slice(0, 14000));
      else out.push('unknown ' + cmd);
    } catch (e) { out.push(`ERR ${cmd}: ${e.message.split('\n')[0]}`); }
  }
  console.log(out.join('\n---\n'));
  await browser.close();
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });

// Varre PÁGINAS REAIS do GitHub com o mesmo PageScanner do app (Chromium via Playwright) e grava os JSON usados
// por LiveGithubTest. Uso: NODE_PATH=<node_modules> LR_LIVE_DIR=<dir> node tools/live-scan.js [url-do-repositório]
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');
const outDir = process.env.LR_LIVE_DIR || path.join(__dirname, '..', 'live');
fs.mkdirSync(outDir, { recursive: true });
const src = fs.readFileSync(path.join(__dirname, '..', 'app/src/main/java/app/linkresolver/core/PageScanner.kt'), 'utf8');
const script = src.match(/const val SCRIPT = """([\s\S]*?)"""/)[1];
const repo = process.argv[2] || 'https://github.com/retrobrews/snes-games';
const ROM = /\.(smc|sfc|nes|gba|gbc|gb|n64|z64|v64)$/i;
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36', locale: 'en-US' });
  const p = await ctx.newPage();
  const report = [];
  const log = m => { console.log(m); report.push(m); };
  await p.goto(repo, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await p.waitForSelector('a[href*="/blob/"]', { timeout: 40000 }).catch(() => log('AVISO: nenhum link /blob/ apareceu em 40 s'));
  await sleep(1500);
  const raw = await p.evaluate(script);
  fs.writeFileSync(path.join(outDir, 'dir.json'), JSON.stringify(raw));
  const d = JSON.parse(raw);
  const roms = d.cands.filter(c => ROM.test((c.url || '').split('?')[0]));
  log(`DIR ${p.url()}  total=${d.total}  mantidos=${d.cands.length}  ROMs=${roms.length}`);
  log('primeiros candidatos: ' + d.cands.slice(0, 8).map(c => `${(c.url || '').replace('https://github.com', '')}`).join(' | '));
  for (const n of ['astrohawk.smc', 'blt.sfc', 'bucket.smc']) log(`  ${n}: ${d.cands.some(c => (c.url || '').endsWith('/' + n)) ? 'ENCONTRADO' : 'ausente'}`);
  const first = roms.find(c => /\/blob\//.test(c.url));
  if (!first) { log('FALHA: nenhuma página /blob/ de ROM'); fs.writeFileSync(path.join(outDir, 'report.txt'), report.join('\n')); await b.close(); process.exit(0); }
  fs.writeFileSync(path.join(outDir, 'blob-url.txt'), first.url);
  const q = await ctx.newPage();
  await q.goto(first.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await sleep(2500);
  const r1 = JSON.parse(await q.evaluate(script));
  await sleep(2500);
  const raw2 = await q.evaluate(script);
  fs.writeFileSync(path.join(outDir, 'blob.json'), JSON.stringify(raw2));
  const r2 = JSON.parse(raw2);
  const rawLinks = r2.cands.filter(c => /\/raw\/|raw\.githubusercontent\.com/.test(c.url || ''));
  log(`BLOB ${q.url()}  candidatos=${r2.total}  links Raw: ${rawLinks.map(c => `"${c.text}" ${c.url}`).join(' | ') || 'NENHUM (o app derivará de /blob/)'}`);
  log(`  (1ª varredura: ${r1.cands.filter(c => /\/raw\//.test(c.url || '')).length} raw; 2ª: ${rawLinks.length})`);
  fs.writeFileSync(path.join(outDir, 'report.txt'), report.join('\n'));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });

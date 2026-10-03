const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const path = require('path'); const SHOTS = process.env.SHOTS || path.join(__dirname, 'shots'); const S = path.join(__dirname, '../backend/sample_uploads/'); const FX = (process.env.FIXTURES || '/tmp/sentinel-fixtures') + '/';
require('fs').mkdirSync(SHOTS, { recursive: true });
const URL = 'http://127.0.0.1:5173';
const log = (...a) => console.log('✓', ...a);
let n = 0;
const shot = async (p, name, full = true) => p.screenshot({ path: `${SHOTS}/${String(++n).padStart(2, '0')}_${name}.png`, fullPage: full });

async function login(p, email, pw) {
  await p.goto(URL + '/');
  await p.getByLabel('Email or user ID').fill(email);
  await p.getByLabel('Password').fill(pw);
  await p.getByRole('button', { name: 'Sign in', exact: true }).first().click();
  await p.waitForSelector('text=UPI SENTINEL >> nth=0'); await p.waitForURL(/\/(my|bank|cyber)/);
}
async function logout(p) { await p.getByRole('button', { name: 'Sign out' }).first().click(); await p.waitForSelector('text=Digital payment dispute investigation'); }

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const p = await ctx.newPage();
  p.setDefaultTimeout(60000);
  const step = process.argv[2] || 'all';

  if (step === 'all') {
    // ---------------- VICTIM
    await p.goto(URL); await shot(p, 'login');
    await login(p, 'victim@demo.upisentinel.in', 'Victim@2026'); log('1 victim signed in');
    await shot(p, 'victim_dashboard');
    await p.getByRole('button', { name: 'Report a fraud' }).first().click();
    await p.getByLabel('Tell us what happened in your own words').fill('I received a call from someone claiming to be from my bank. Later ₹25,000 was transferred from my account. I did not make this payment.');
    await p.getByRole('button', { name: /Continue — upload your proof/ }).click();
    await p.waitForURL(/\/my\/cases\/[0-9a-f-]{36}/); await p.waitForSelector('h2:text-is("Upload your proof")'); log('2 case created from a simple statement');
    const caseUrl = p.url().split('?')[0];
    await p.locator('input[type=file][accept^="image/*"]').setInputFiles(S + 'upi_screenshot_847291.png'); log('3 screenshot uploaded');
    await p.getByRole('button', { name: 'Paste message' }).click();
    await p.getByLabel('Paste the message exactly as you received it').fill('Your account has been debited Rs.25,000 through UPI.\nReference number 847291.');
    await p.getByRole('button', { name: 'Add message' }).click(); log('4 SMS pasted');
    await p.locator('input[type=file][accept^="audio/*"]').setInputFiles(S + 'scam_call.wav'); log('5 audio uploaded');
    await p.waitForSelector('text=Related information connected', { timeout: 120000 });
    await p.waitForSelector('text=Confirmed by 2 sources', { timeout: 60000 });
    await p.waitForSelector('text=What happened');
    await shot(p, 'victim_case_processed');
    const body = await p.locator('main').innerText();
    if (!body.includes('₹25,000')) throw new Error('amount not extracted');
    if (!body.includes('847291')) throw new Error('reference not extracted');
    if (!/We could not transcribe|We do not have device or login information/.test(body)) throw new Error('missing info not shown');
    log('7-10 extracted ₹25,000 + Ref 847291 (no manual entry), linked (2 sources), timeline + missing info shown');
    await p.getByRole('button', { name: 'Generate my report' }).click();
    await p.waitForSelector('text=Download report (version 1)'); log('report v1 generated');
    await p.getByRole('button', { name: 'Submit case' }).click();
    await p.getByRole('button', { name: /Yes, submit to/ }).click();
    await p.waitForSelector('text=Your case has been submitted for review.');
    await p.waitForSelector('text=Where your case is now');
    const ref = (await p.locator('text=/CASE #UPI-\\d{4}-\\d{4}/').first().innerText()).replace('CASE #', '').trim();
    await shot(p, 'victim_submitted'); log('11 submitted as', ref);
    await logout(p);

    // ---------------- BANK
    await login(p, 'bank@demo.upisentinel.in', 'Bank@2026'); log('12 bank signed in');
    await shot(p, 'bank_dashboard');
    await p.getByRole('link', { name: 'Cases', exact: true }).click();
    await p.getByText(ref).first().click();
    await p.waitForSelector(`text=CASE #${ref}`); log('13 same case opened by bank');
    await p.waitForSelector('text=Under bank review');
    await shot(p, 'bank_workspace_overview');
    await p.getByRole('tab', { name: /Evidence/ }).click();
    for (const f of ['upi_screenshot_847291.png', 'Pasted_message.txt', 'scam_call.wav']) await p.waitForSelector(`text=${f}`);
    await p.getByText('upi_screenshot_847291.png').first().click();
    await p.waitForSelector('img[alt="Evidence E1"]');
    await shot(p, 'bank_source_panel', false); log('14 bank sees the exact uploaded files (original image rendered)');
    await p.keyboard.press('Escape');
    await p.getByRole('tab', { name: 'Timeline' }).click(); await p.waitForSelector('text=Disputed transaction'); await shot(p, 'bank_timeline'); log('15 timeline');
    await p.getByRole('tab', { name: /Findings/ }).click(); await p.waitForSelector('text=Why it matters'); await shot(p, 'bank_findings');
    await p.getByRole('tab', { name: 'Investigation report' }).click();
    await p.getByRole('button', { name: 'Generate report' }).click(); await p.waitForSelector('text=Version 1'); log('16 investigation report v1');
    await p.getByRole('tab', { name: /Case actions/ }).click();
    await p.getByRole('button', { name: 'Request more evidence' }).click();
    await p.getByLabel('Bank statement').check();
    await p.getByLabel('Message to the customer (plain language)').fill('Please upload the bank statement showing the disputed transaction.');
    await p.getByRole('button', { name: 'Send request' }).click();
    await p.waitForSelector('text=Additional evidence requested'); log('17 evidence requested');
    await logout(p);

    // ---------------- VICTIM responds
    await login(p, 'victim@demo.upisentinel.in', 'Victim@2026');
    await p.waitForSelector('text=Upload the evidence your bank asked for'); log('18-19 victim sees the request');
    await p.goto(caseUrl);
    await p.waitForSelector('text=Action required');
    await shot(p, 'victim_action_required');
    await p.locator('input[type=file][accept=".pdf,.docx,.txt,.eml"]').setInputFiles(FX + 'bank_statement.pdf'); log('20 statement uploaded');
    await p.waitForSelector('text=Under bank review', { timeout: 60000 });
    await p.waitForSelector('text=Which payment are you reporting?', { state: 'detached' }).catch(() => {});
    await logout(p);

    // ---------------- BANK again
    await login(p, 'bank@demo.upisentinel.in', 'Bank@2026');
    await p.goto(URL + '/bank/cases'); await p.getByText(ref).first().click();
    await p.getByRole('tab', { name: /Evidence/ }).click(); await p.waitForSelector('text=bank_statement.pdf'); log('21-22 new evidence visible to bank');
    const ov = await p.locator('main').innerText();
    if (!/Bank statement/.test(ov)) throw new Error('statement not classified');
    await p.getByRole('tab', { name: 'Overview' }).click();
    await p.waitForSelector('text=Confirmed by 3 sources', { timeout: 60000 }); log('23 investigation updated (amount now confirmed by 3 sources)');
    await p.getByRole('tab', { name: 'Investigation report' }).click();
    await p.waitForSelector('text=Generate new version');
    await p.getByRole('tab', { name: /Case actions/ }).click();
    await p.getByLabel('Account action').selectOption({ label: 'Account restricted' });
    await p.getByRole('button', { name: 'Record bank action' }).click();
    await p.waitForSelector('text=Account restricted');
    await p.getByRole('button', { name: 'Escalate to cyber crime' }).click();
    await p.getByLabel('Reason (required)').fill('Customer reports bank impersonation; amount confirmed by bank statement and SMS. Escalating for investigation.');
    await p.getByRole('button', { name: 'Confirm' }).click();
    await p.waitForSelector('text=Escalated to cyber crime'); log('24 escalated with account restricted');
    await shot(p, 'bank_actions');
    await logout(p);

    // ---------------- CYBER
    await login(p, 'cyber@demo.upisentinel.in', 'Cyber@2026');
    await shot(p, 'cyber_dashboard');
    await p.getByRole('link', { name: 'Escalated' }).click();
    await p.getByText(ref).first().click();
    await p.waitForSelector(`text=CASE #${ref}`); log('25-26 same case received by cyber crime');
    await p.getByRole('tab', { name: /Connections/ }).click(); await p.waitForSelector('text=Possible related cases'); log('27 related-case analysis shown');
    await shot(p, 'cyber_connections');
    await p.getByRole('tab', { name: /Case actions/ }).click();
    await p.getByRole('button', { name: 'Accept case' }).click(); await p.getByRole('button', { name: 'Confirm' }).click();
    await p.waitForSelector('text=Cyber crime review');
    await p.getByPlaceholder(/Beneficiary appears in multiple related complaints/).fill('Customer statement and bank records consistent. Further investigation required.');
    await p.getByRole('button', { name: 'Add note' }).click();
    await p.getByRole('button', { name: 'Mark under investigation' }).click(); await p.getByRole('button', { name: 'Confirm' }).click();
    await p.waitForSelector('text=Under investigation');
    await p.getByRole('button', { name: 'Mark pending' }).click();
    await p.getByLabel('Reason (required)').fill('Awaiting telecom records for the caller number.');
    await p.getByRole('button', { name: 'Confirm' }).click();
    await p.waitForSelector('span:text-is("Pending")'); log('28 cyber crime updated the case (accepted → under investigation → pending)');
    await p.getByRole('tab', { name: 'Investigation report' }).click();
    await p.waitForSelector('text=Cyber crime reporting export');
    await shot(p, 'cyber_report_export');
    await p.goto(URL + '/cyber/network?synthetic=1'); await p.waitForSelector('text=Clusters'); await shot(p, 'cyber_network_synthetic');
    await logout(p);

    // ---------------- VICTIM sees the update
    await login(p, 'victim@demo.upisentinel.in', 'Victim@2026');
    await p.goto(caseUrl);
    await p.waitForSelector('span:text-is("Pending")');
    await p.waitForSelector('text=Your case has been escalated to cyber crime.');
    await shot(p, 'victim_final'); log('29 victim sees the cyber crime status');
    require('fs').writeFileSync(path.join(SHOTS, 'state.json'), JSON.stringify({ ref, caseUrl }));
  } else if (step === 'after-restart') {
    const { ref, caseUrl } = JSON.parse(require('fs').readFileSync(path.join(SHOTS, 'state.json')));
    await login(p, 'victim@demo.upisentinel.in', 'Victim@2026');
    await p.waitForSelector(`text=${ref}`);
    await p.goto(caseUrl);
    await p.waitForSelector('span:text-is("Pending")');
    for (const f of ['upi_screenshot_847291.png', 'Pasted_message.txt', 'scam_call.wav', 'bank_statement.pdf']) await p.waitForSelector(`text=${f}`);
    log('30-32 after restart: case', ref, 'still exists with status Pending and all 4 evidence files');
    await logout(p);
    await login(p, 'bank@demo.upisentinel.in', 'Bank@2026');
    await p.goto(URL + '/bank/cases'); await p.getByText(ref).first().click();
    await p.getByRole('tab', { name: 'Audit trail' }).click(); await p.waitForSelector('text=Case status changed');
    await shot(p, 'bank_audit_after_restart'); log('audit trail intact after restart');
    // mobile victim
    const m = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true });
    const mp = await m.newPage();
    await login(mp, 'victim@demo.upisentinel.in', 'Victim@2026');
    await shot(mp, 'mobile_victim_dashboard');
    await mp.goto(caseUrl); await mp.waitForSelector('text=What happened'); await shot(mp, 'mobile_victim_case');
    log('mobile victim views rendered');
  }
  await browser.close();
})().catch(e => { console.error('✗ FAILED:', e.message); process.exit(1); });

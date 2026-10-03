const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const path = require('path'); const D = path.join(__dirname, '../backend/demo_evidence/'), SH = process.env.SHOTS || path.join(__dirname, 'shots'), URL = 'http://127.0.0.1:5173';
async function login(p, e, pw) { await p.goto(URL); await p.getByLabel('Email or user ID').fill(e); await p.getByLabel('Password').fill(pw);
  await p.getByRole('button', { name: 'Sign in', exact: true }).first().click(); await p.waitForURL(/\/(my|bank|cyber)/) }
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1360, height: 900 } }); p.setDefaultTimeout(90000)
  await login(p, 'victim@demo.upisentinel.in', 'Victim@2026')
  await p.getByRole('button', { name: 'Report a fraud' }).first().click()
  await p.getByLabel('Tell us what happened in your own words').fill('I received a call from someone claiming to be from my bank KYC team. Later ₹25,000 was transferred from my account. I did not intend this payment.')
  await p.getByText('Mark as a synthetic demo case').click()
  await p.getByRole('button', { name: /Continue — upload your proof/ }).click(); await p.waitForURL(/\/my\/cases\/[0-9a-f-]{36}/)
  await p.locator('input[type=file][accept^="image/*"]').setInputFiles([D + 'upi_payment_screenshot.png', D + 'bank_sms_screenshot.png', D + 'chat_screenshot.png'])
  await p.locator('input[type=file][accept^="audio/*"]').setInputFiles(D + 'scam_call.wav')
  await p.waitForSelector('text=Confirmed by 2 sources'); await p.waitForTimeout(3000)
  await p.screenshot({ path: SH + '/20_demo_victim_case.png', fullPage: true })
  await p.getByRole('button', { name: 'Submit case' }).click(); await p.getByRole('button', { name: /Yes, submit to/ }).click()
  await p.waitForSelector('text=Your case has been submitted for review.')
  const ref = (await p.locator('text=/CASE #DEMO-\\d{4}-\\d{4}/').first().innerText()).replace('CASE #', '').trim()
  await p.getByRole('button', { name: 'Sign out' }).click()
  await login(p, 'bank@demo.upisentinel.in', 'Bank@2026'); await p.goto(URL + '/bank/cases'); await p.getByText(ref).first().click()
  await p.waitForSelector('text=Related case alert'); const t = await p.locator('[role=alert]').first().innerText(); console.log('ALERT:', t.replace(/\n/g, ' '))
  await p.waitForSelector('text=Possible fraud pattern')
  await p.screenshot({ path: SH + '/21_demo_bank_overview.png', fullPage: true })
  await p.getByRole('tab', { name: /Connections/ }).click(); await p.waitForSelector('text=Related transaction clusters'); await p.waitForTimeout(1500)
  await p.screenshot({ path: SH + '/22_demo_bank_connections.png', fullPage: true })
  await p.getByRole('tab', { name: /Findings/ }).click(); await p.waitForSelector('text=Why it matters')
  await p.screenshot({ path: SH + '/23_demo_bank_findings.png', fullPage: true })
  console.log('demo case', ref); await b.close()
})().catch(e => { console.error('FAILED', e.message); process.exit(1) })

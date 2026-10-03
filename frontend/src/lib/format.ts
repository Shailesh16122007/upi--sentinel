import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export const cn = (...c: ClassValue[]) => twMerge(clsx(c))

export const inr = (n: number | null | undefined, digits = 0) =>
  n == null ? '—' : `₹${n.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`

const IST: Intl.DateTimeFormatOptions = { timeZone: 'Asia/Kolkata' }

export const dateTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString('en-IN', { ...IST, day: '2-digit', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' }) : '—'

export const clock = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString('en-IN', { ...IST, hour: 'numeric', minute: '2-digit', second: '2-digit' }) : '—'

export const shortDate = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString('en-IN', { ...IST, day: '2-digit', month: 'short', year: 'numeric' }) : '—'

export const humanize = (s: string | null | undefined) =>
  !s ? '—' : s.replace(/_/g, ' ').toLowerCase().replace(/^\w/, c => c.toUpperCase())

export const bytes = (n: number | null | undefined) =>
  n == null ? '—' : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`

export const mmss = (s: number | null | undefined) =>
  s == null ? '--:--' : `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`

export const SUBTYPE: Record<string, string> = {
  UPI_SCREENSHOT: 'UPI screenshot', BANK_SMS: 'Bank SMS', BANK_SMS_SCREENSHOT: 'Bank SMS screenshot', CHAT: 'Chat',
  CHAT_SCREENSHOT: 'Chat screenshot', CALL_RECORDING: 'Call recording', CALL_LOG: 'Call log', BANK_STATEMENT: 'Bank statement',
  PAYMENT_RECEIPT: 'Payment receipt', COMPLAINT: 'Complaint', TXN_HISTORY: 'Transaction history', ACCOUNT_LOG: 'Account activity log',
  SYSTEM_RECORD: 'Platform risk record', MESSAGE: 'Message', IMAGE_OTHER: 'Image', DOCUMENT_OTHER: 'Document', OTHER: 'Other',
  SCREEN_RECORDING: 'Screen recording',
}
export const kindLabel = (e: { kind: string; subtype: string | null }) =>
  (e.subtype && SUBTYPE[e.subtype]) || humanize(e.kind)

export const METHOD: Record<string, string> = {
  OCR: 'OCR', TEXT: 'Text', PDF_TEXT: 'PDF text layer', PDF_OCR: 'PDF · OCR', 'PDF_TEXT+OCR': 'PDF text + OCR', DOCX: 'Word document',
  STRUCTURED_CSV: 'CSV records', STRUCTURED_JSON: 'JSON records', PROVIDED_TRANSCRIPT: 'Transcript provided by user', SYSTEM: 'Platform record',
  STT: 'Speech-to-text', USER_INPUT: 'Entered by user', EMAIL: 'E-mail', VIDEO_OCR: 'Video frames (OCR)',
}
export const methodLabel = (m: string | null) =>
  !m ? '—' : m.startsWith('faster-whisper') ? 'Speech-to-text (Whisper)' : METHOD[m] ?? humanize(m)

export const timeOnly = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString('en-IN', { ...IST, hour: 'numeric', minute: '2-digit' }).toUpperCase() : '—'

const dayKey = (d: Date) => d.toLocaleDateString('en-CA', IST)

/** "Today, 2:34 PM" · "Yesterday, 9:10 AM" · "03 Oct 2026, 4:20 PM" */
export const when = (iso: string | null | undefined) => {
  if (!iso) return '—'
  const d = new Date(iso)
  const now = new Date()
  const y = new Date(now.getTime() - 86_400_000)
  if (dayKey(d) === dayKey(now)) return `Today, ${timeOnly(iso)}`
  if (dayKey(d) === dayKey(y)) return `Yesterday, ${timeOnly(iso)}`
  return dateTime(iso)
}

export const greeting = () => {
  const h = Number(new Date().toLocaleString('en-IN', { ...IST, hour: 'numeric', hour12: false }))
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

export type Tone = 'neutral' | 'accent' | 'ok' | 'warn' | 'bad' | 'outline'
export const STATUS_TONE: Record<string, Tone> = {
  DRAFT: 'outline', SUBMITTED: 'accent', BANK_REVIEW: 'accent', EVIDENCE_REQUESTED: 'warn', ESCALATED: 'accent',
  CYBER_REVIEW: 'accent', INFO_REQUESTED: 'warn', UNDER_INVESTIGATION: 'accent', PENDING: 'warn', RESOLVED: 'ok', CLOSED: 'neutral',
}

export const lakh = (n: number | null | undefined) => {
  if (n == null) return '—'
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(n % 1e7 ? 2 : 0)} Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(n % 1e5 ? 2 : 0).replace(/\.?0+$/, '')}L`
  return inr(n)
}

export const fieldLabel: Record<string, string> = {
  amount: 'Amount', time: 'Date & time', reference: 'Reference / UTR', beneficiary_vpa: 'Recipient UPI ID',
  beneficiary_name: 'Recipient name', status: 'Status', channel: 'Channel', account: 'Account', bank: 'Bank',
}

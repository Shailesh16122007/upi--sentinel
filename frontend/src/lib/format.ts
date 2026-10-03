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
}
export const kindLabel = (e: { kind: string; subtype: string | null }) =>
  (e.subtype && SUBTYPE[e.subtype]) || humanize(e.kind)

export const METHOD: Record<string, string> = {
  OCR: 'OCR', TEXT: 'Text', PDF_TEXT: 'PDF text layer', PDF_OCR: 'PDF · OCR', 'PDF_TEXT+OCR': 'PDF text + OCR', DOCX: 'Word document',
  STRUCTURED_CSV: 'CSV records', STRUCTURED_JSON: 'JSON records', PROVIDED_TRANSCRIPT: 'Transcript provided by user', SYSTEM: 'Platform record',
  STT: 'Speech-to-text', USER_INPUT: 'Entered by user',
}
export const methodLabel = (m: string | null) =>
  !m ? '—' : m.startsWith('faster-whisper') ? 'Speech-to-text (Whisper)' : METHOD[m] ?? humanize(m)

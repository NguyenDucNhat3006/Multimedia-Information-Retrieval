/** Gọi API cùng origin, giữ lỗi có ích và không tự thử lại thao tác nộp bài. */
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(path, { ...options, headers });
  const contentType = response.headers.get('content-type') ?? '';
  const body: unknown = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof body === 'object' && body !== null && 'detail' in body ? body.detail : undefined;
    const message = typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : `API trả lỗi ${response.status}. Kiểm tra backend và cấu hình.`;
    throw new Error(message);
  }
  if (!contentType.includes('application/json')) throw new Error('API không trả JSON. Kiểm tra backend hoặc proxy /api.');
  return body as T;
}

export const post = <T>(path: string, body: unknown, signal?: AbortSignal) =>
  api<T>(path, { method: 'POST', body: JSON.stringify(body), signal });

/** Chỉ đổi đơn vị tại player; API và nhãn luôn giữ integer milliseconds. */
export function formatTime(milliseconds: number): string {
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return '—';
  const total = Math.round(milliseconds);
  const hours = Math.floor(total / 3600000);
  const minutes = Math.floor((total % 3600000) / 60000);
  const seconds = Math.floor((total % 60000) / 1000);
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(total % 1000).padStart(3, '0')}`;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Có lỗi khi kết nối. Hãy thử lại.';
}

/** Giữ nguyên chuỗi QA, bao gồm số 0 đầu; chỉ chấp nhận chữ số ASCII. */
export function validQa(answer: string): boolean { return /^[0-9]+$/.test(answer); }

export function field(record: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) if (record[key] !== undefined && record[key] !== null) return String(record[key]);
  return '—';
}

export function extractCandidates(value: unknown): import('./types').SearchResult[] {
  if (Array.isArray(value)) return value;
  if (typeof value === 'object' && value !== null) {
    const record = value as Record<string, unknown>;
    if (Array.isArray(record.candidates)) return record.candidates;
    if (Array.isArray(record.results)) return record.results;
  }
  return [];
}

/** Chỉ lưu ID phiên feedback không nhạy cảm; không có token DRES trong browser storage. */
export function getFeedbackSession(): string {
  try {
    const stored = sessionStorage.getItem('cs336-feedback-session');
    if (stored) return stored;
    const session = `web-${crypto.randomUUID()}`;
    sessionStorage.setItem('cs336-feedback-session', session);
    return session;
  } catch { return `web-${crypto.randomUUID()}`; }
}

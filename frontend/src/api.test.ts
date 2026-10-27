import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, formatTime, validQa } from './api';
afterEach(() => vi.unstubAllGlobals());

describe('time and QA contract', () => {
  it('preserves millisecond boundaries and hours', () => {
    expect(formatTime(12340)).toBe('00:00:12.340');
    expect(formatTime(3599999)).toBe('00:59:59.999');
    expect(formatTime(3600000)).toBe('01:00:00.000');
    expect(formatTime(-1)).toBe('—');
    expect(formatTime(NaN)).toBe('—');
  });
  it('accepts 007 exactly, rejects prefixes and non-ASCII digits', () => {
    expect(validQa('007')).toBe(true);
    expect(validQa('QA-007')).toBe(false);
    expect(validQa('００７')).toBe(false);
    expect(validQa('007 ')).toBe(false);
    expect(validQa('')).toBe(false);
  });
});
describe('API boundary', () => {
  it('passes the abort signal to fetch', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"results":[]}', { headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    const controller = new AbortController();
    await api('/api/search', { signal: controller.signal });
    expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal);
  });
  it('exposes useful backend validation errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"detail":"Missing encoder manifest"}', { status: 503, headers: { 'content-type': 'application/json' } })));
    await expect(api('/api/search')).rejects.toThrow('Missing encoder manifest');
  });
  it('rejects an HTML page returned by a broken API proxy', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html></html>', { headers: { 'content-type': 'text/html' } })));
    await expect(api('/api/search')).rejects.toThrow('API không trả JSON');
  });
});

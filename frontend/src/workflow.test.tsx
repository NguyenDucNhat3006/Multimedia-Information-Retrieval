import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { Inspector } from './Inspector';
import { SubmissionPanel } from './SubmissionPanel';
import type { SearchResult } from './types';

const fixtureResult: SearchResult = { keyframe_id: 'fixture-k1', video_uid: 'fixture-v1', media_item_name: 'FIXTURE_VIDEO', timestamp_ms: 12340, thumbnail_url: '/fixture.jpg', video_url: '/fixture.mp4', score: .42, contributions: { visual: { rank: 1 } } };
const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } });
afterEach(() => vi.unstubAllGlobals());

describe('DRES deliberate submission', () => {
  it('requires current preview and preserves QA leading zeroes in both requests', async () => {
    const fetchMock = vi.fn(async (url: string) => json(url.endsWith('/preview') ? { payload: { answerSets: [{ answers: [{ text: '007-FIXTURE_VIDEO-12340' }] }] }, mode: 'mock', profile: 'aic2024_v2' } : { attempt_id: 'fixture-attempt', status: 'correct', payload: {} }));
    vi.stubGlobal('fetch', fetchMock);
    render(<SubmissionPanel selected={fixtureResult} evaluations={{ evaluations: [{ id: 'mock-evaluation', name: 'Fixture mock', status: 'ACTIVE', mock: true }], mode: 'mock', profile: 'aic2024_v2' }} onSubmitted={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Loại đáp án'), { target: { value: 'QA' } });
    fireEvent.change(screen.getByLabelText('Chế độ'), { target: { value: 'mock' } });
    fireEvent.change(screen.getByLabelText('Evaluation'), { target: { value: 'mock-evaluation' } });
    fireEvent.change(screen.getByLabelText('Task / round key'), { target: { value: 'fixture-task' } });
    fireEvent.change(screen.getByLabelText('Đáp án QA (chuỗi số)'), { target: { value: '007' } });
    expect(screen.getByRole('button', { name: 'Nộp vào mock' })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Xem trước JSON' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Nộp vào mock' })).toBeEnabled());
    expect(screen.getByText(/007-FIXTURE_VIDEO-12340/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Nộp vào mock' }));
    await screen.findByText('Đúng theo ground truth mock');
    for (const call of fetchMock.mock.calls as unknown as [string, RequestInit][]) {
      expect(JSON.parse(String(call[1].body)).answer).toBe('007');
      expect(JSON.parse(String(call[1].body)).timestamp_ms).toBe(12340);
    }
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
  it('invalidates preview after the task changes', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ payload: {}, mode: 'dry_run', profile: 'aic2024_v2' })));
    render(<SubmissionPanel selected={fixtureResult} evaluations={{ evaluations: [{ id: 'fixture-eval', name: 'Fixture', status: 'ACTIVE' }], mode: 'dry_run', profile: 'aic2024_v2' }} onSubmitted={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Evaluation'), { target: { value: 'fixture-eval' } });
    fireEvent.change(screen.getByLabelText('Task / round key'), { target: { value: 'task-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Xem trước JSON' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Ghi nhận dry run' })).toBeEnabled());
    fireEvent.change(screen.getByLabelText('Task / round key'), { target: { value: 'task-2' } });
    expect(screen.getByRole('button', { name: 'Ghi nhận dry run' })).toBeDisabled();
  });
});

describe('player time contract', () => {
  it('seeks ms / 1000 after metadata and cleans listeners when frame changes', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ results: [] })));
    const props = { evaluations: null, saved: false, imageAvailable: false, onClose: vi.fn(), onSelect: vi.fn(), onSave: vi.fn(), onFeedback: vi.fn(), onExample: vi.fn(), onSubmitted: vi.fn() };
    const { rerender } = render(<Inspector selected={fixtureResult} {...props} />);
    const video = screen.getByLabelText('Video FIXTURE_VIDEO') as HTMLVideoElement;
    fireEvent.loadedMetadata(video);
    expect(video.currentTime).toBe(12.34);
    const remove = vi.spyOn(video, 'removeEventListener');
    rerender(<Inspector selected={{ ...fixtureResult, keyframe_id: 'fixture-k2', timestamp_ms: 23456 }} {...props} />);
    fireEvent.loadedMetadata(video);
    expect(video.currentTime).toBe(23.456);
    expect(remove).toHaveBeenCalledWith('loadedmetadata', expect.any(Function));
    await waitFor(() => expect(screen.queryByText('Đang tải filmstrip…')).not.toBeInTheDocument());
  });
});

describe('request races', () => {
  it('aborts old search and ignores its late response', async () => {
    const pending: { resolve: (response: Response) => void; signal: AbortSignal }[] = [];
    vi.stubGlobal('fetch', vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/search') return new Promise<Response>(resolve => pending.push({ resolve, signal: options!.signal! }));
      if (url === '/api/health') return Promise.resolve(json({ status: 'ok' }));
      if (url === '/api/capabilities') return Promise.resolve(json({ modes: { visual_text: false, image: false, ocr: true, asr: false, hybrid: false, temporal: false }, reasons: {}, contest_mode: false, fixture: true }));
      if (url === '/api/data') return Promise.resolve(json({ videos: [], counts: { videos: 0, keyframes: 0, ocr: 1, asr: 0 }, jobs: [], fixture: true }));
      if (url === '/api/dres/evaluations') return Promise.resolve(json({ evaluations: [], mode: 'dry_run', profile: 'fixture' }));
      if (url === '/api/evaluation') return Promise.resolve(json({ reports: [], ground_truth_available: false }));
      if (url === '/api/history') return Promise.resolve(json({ queries: [], submissions: [] }));
      return Promise.resolve(json({ candidates: [] }));
    }));
    render(<App />);
    await waitFor(() => expect(screen.getByText('Backend kết nối')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('tab', { name: 'OCR' }));
    const input = screen.getByLabelText('Nội dung truy vấn');
    fireEvent.change(input, { target: { value: 'first fixture query' } });
    fireEvent.submit(input.closest('form')!);
    await waitFor(() => expect(pending).toHaveLength(1));
    fireEvent.change(input, { target: { value: 'second fixture query' } });
    fireEvent.submit(input.closest('form')!);
    await waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[0].signal.aborted).toBe(true);
    await act(async () => pending[1].resolve(json({ results: [{ ...fixtureResult, media_item_name: 'FIXTURE_SECOND' }], elapsed_ms: 1, index_version: 'fixture-index' })));
    await screen.findByRole('button', { name: 'FIXTURE_SECOND' });
    await act(async () => pending[0].resolve(json({ results: [{ ...fixtureResult, media_item_name: 'FIXTURE_FIRST' }], elapsed_ms: 1, index_version: 'fixture-index' })));
    expect(screen.queryByRole('button', { name: 'FIXTURE_FIRST' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'FIXTURE_SECOND' })).toBeInTheDocument();
  });
});

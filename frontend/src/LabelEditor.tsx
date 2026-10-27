import { useState } from 'react';
import { errorMessage, post } from './api';
import { Icon } from './icons';
import type { Video } from './types';

interface EventLabel { event_id: string; video_uid: string; start_ms: number; end_ms: number; grade: number }
interface QueryLabel { query_id: string; query: string; visual_query?: string; query_b?: string; mode: string; exhaustive_judgments: boolean; events: EventLabel[] }
interface LabelSet { provenance: string; split: string; queries: QueryLabel[] }

/** Công cụ gán nhãn thủ công: chỉ lưu ground truth do người dùng kiểm tra trên video gốc. */
export function LabelEditor({ videos, onSaved }: { videos: Video[]; onSaved: () => void }) {
  const [queryId, setQueryId] = useState('');
  const [query, setQuery] = useState('');
  const [visualQuery, setVisualQuery] = useState('');
  const [queryB, setQueryB] = useState('');
  const [mode, setMode] = useState('visual_text');
  const [eventId, setEventId] = useState('');
  const [videoUid, setVideoUid] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [grade, setGrade] = useState(1);
  const [exhaustive, setExhaustive] = useState(false);
  const [events, setEvents] = useState<EventLabel[]>([]);
  const [labels, setLabels] = useState<LabelSet>({ provenance: 'human_reviewed', split: 'test', queries: [] });
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const validEvent = eventId.trim() && videoUid && start !== '' && end !== '' && Number.isInteger(Number(start)) && Number.isInteger(Number(end)) && Number(start) >= 0 && Number(end) >= Number(start);
  function addEvent() {
    if (!validEvent) return;
    if (events.some(item => item.event_id === eventId.trim())) { setError('Event ID đã có trong truy vấn này.'); return; }
    setEvents(current => [...current, { event_id: eventId.trim(), video_uid: videoUid, start_ms: Number(start), end_ms: Number(end), grade }]);
    setEventId(''); setStart(''); setEnd(''); setError('');
  }
  function addQuery() {
    if (!queryId.trim() || !query.trim() || !events.length || (mode === 'temporal' && !queryB.trim())) return;
    if (labels.queries.some(item => item.query_id === queryId.trim())) { setError('Query ID đã có trong bộ nhãn này.'); return; }
    setLabels(current => ({ ...current, queries: [...current.queries, { query_id: queryId.trim(), query: query.trim(), ...(visualQuery.trim() && (mode === 'visual_text' || mode === 'hybrid') ? { visual_query: visualQuery.trim() } : {}), ...(mode === 'temporal' ? { query_b: queryB.trim() } : {}), mode, exhaustive_judgments: exhaustive, events }] }));
    setEvents([]); setQuery(''); setQueryId(''); setVisualQuery(''); setQueryB(''); setExhaustive(false); setError(''); setStatus('Đã thêm truy vấn vào bộ nhãn đang soạn.');
  }
  async function importFile(file?: File) {
    if (!file) return;
    try {
      if (file.size > 10 * 1024 * 1024) throw new Error('Bộ nhãn phải dưới 10 MB.');
      const value: unknown = JSON.parse(await file.text());
      if (typeof value !== 'object' || value === null || !('queries' in value) || !Array.isArray(value.queries)) throw new Error('File cần là JSON có mảng queries theo schema backend.');
      const imported = value as LabelSet;
      if (imported.queries.some(item => typeof item.query_id !== 'string' || typeof item.query !== 'string' || !Array.isArray(item.events))) throw new Error('Mỗi query cần query_id, query và mảng events.');
      setLabels(imported); setError(''); setStatus(`Đã mở ${file.name}; ${imported.queries.length} truy vấn. Backend sẽ kiểm tra schema khi lưu.`);
    } catch (reason) { setError(errorMessage(reason)); }
  }
  async function save() {
    if (!labels.queries.length || busy) return;
    setBusy(true); setError(''); setStatus('');
    try { await post('/api/evaluation/labels', labels); setStatus('Đã kiểm tra và lưu bộ nhãn trên backend. Chạy đánh giá offline để tạo báo cáo.'); onSaved(); }
    catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(labels, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'cs336-human-labels.json'; anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section className="panel padded label-editor"><div className="section-title"><h2>Soạn bộ nhãn</h2><label className="button secondary import-labels"><Icon name="upload" size={16} />Mở JSON<input type="file" accept="application/json,.json" onChange={event => void importFile(event.target.files?.[0])} /></label></div><p className="muted small">Kiểm tra video gốc rồi thêm từng event vào truy vấn. Lưu bộ nhãn sau khi thêm truy vấn; phản hồi relevance trong trang tìm kiếm không tự trở thành ground truth.</p>
    <div className="form-row"><label>Query ID<input value={queryId} onChange={event => setQueryId(event.target.value)} placeholder="q1" /></label><label>Kênh đánh giá<select value={mode} onChange={event => setMode(event.target.value)}><option value="visual_text">Visual text</option><option value="ocr">OCR</option><option value="asr">ASR</option><option value="hybrid">Hybrid</option><option value="temporal">Temporal A → B</option></select></label></div><label>Nội dung truy vấn{mode === 'temporal' ? ' / sự kiện A' : ''}<input value={query} onChange={event => setQuery(event.target.value)} placeholder="Mô tả đã viết trước khi tìm" /></label>{(mode === 'visual_text' || mode === 'hybrid') && <label>Mô tả visual tiếng Anh để đánh giá (tùy chọn)<input value={visualQuery} onChange={event => setVisualQuery(event.target.value)} /></label>}{mode === 'temporal' && <label>Sự kiện B để đánh giá<input value={queryB} onChange={event => setQueryB(event.target.value)} /></label>}<div className="form-row"><label>Event ID<input value={eventId} onChange={event => setEventId(event.target.value)} placeholder="e1" /></label><label>Video đúng<select value={videoUid} onChange={event => setVideoUid(event.target.value)}><option value="">Chọn video…</option>{videos.map(video => <option key={video.video_uid} value={video.video_uid}>{video.media_item_name} · {video.source_batch}</option>)}</select></label></div><div className="form-row"><label>Bắt đầu (ms)<input type="number" min="0" step="1" value={start} onChange={event => setStart(event.target.value)} /></label><label>Kết thúc (ms)<input type="number" min="0" step="1" value={end} onChange={event => setEnd(event.target.value)} /></label><label>Mức liên quan<select value={grade} onChange={event => setGrade(Number(event.target.value))}><option value={0}>0 · không liên quan</option><option value={1}>1 · liên quan</option><option value={2}>2 · rất liên quan</option><option value={3}>3 · liên quan cao</option><option value={4}>4 · liên quan tối đa</option></select></label></div>
    <button className="button secondary" disabled={!validEvent} onClick={addEvent}><Icon name="plus" size={16} />Thêm event ({events.length})</button>{events.length > 0 && <div className="label-events">{events.map(item => <div key={item.event_id}><code>{item.event_id}</code><span>{item.start_ms}–{item.end_ms} ms · grade {item.grade}</span><button className="icon-button" aria-label={`Xóa event ${item.event_id}`} onClick={() => setEvents(current => current.filter(value => value.event_id !== item.event_id))}><Icon name="close" size={15} /></button></div>)}</div>}
    <div className="label-exhaustive"><label className="checkbox-label"><input type="checkbox" checked={exhaustive} onChange={event => setExhaustive(event.target.checked)} /> Đã gán nhãn đầy đủ các event liên quan cho truy vấn này</label><small className="muted">Chỉ xác nhận khi đã rà soát đủ. mAP không được báo khi judgment chưa đầy đủ.</small></div><button className="button secondary" disabled={!queryId.trim() || !query.trim() || !events.length || (mode === 'temporal' && !queryB.trim())} onClick={addQuery}>Thêm truy vấn vào bộ nhãn</button>
    {labels.queries.length > 0 && <div className="label-events">{labels.queries.map(item => <div key={item.query_id}><code>{item.query_id}</code><span>{item.query} · {item.events.length} event</span><button className="button text-button" onClick={() => { setQueryId(item.query_id); setQuery(item.query); setMode(item.mode); setVisualQuery(item.visual_query ?? ''); setQueryB(item.query_b ?? ''); setEvents(item.events); setExhaustive(item.exhaustive_judgments); setLabels(current => ({ ...current, queries: current.queries.filter(value => value.query_id !== item.query_id) })); }}>Sửa</button><button className="icon-button" aria-label={`Xóa query ${item.query_id}`} onClick={() => setLabels(current => ({ ...current, queries: current.queries.filter(value => value.query_id !== item.query_id) }))}><Icon name="close" size={15} /></button></div>)}</div>}
    <div className="label-set-footer"><div><strong>{labels.queries.length} truy vấn trong bộ nhãn</strong><small>{labels.provenance} · split {labels.split}</small></div><button className="button secondary" disabled={!labels.queries.length} onClick={download}><Icon name="code" size={15} />Xuất JSON</button><button className="button primary" disabled={!labels.queries.length || busy} onClick={() => void save()}>{busy ? 'Đang lưu…' : 'Kiểm tra & lưu nhãn'}</button></div>{error && <p role="alert" className="inline-error">{error}</p>}{status && <p role="status" className="success small">{status}</p>}
    <details className="evidence"><summary>Xem bộ nhãn đang soạn</summary><pre>{JSON.stringify(labels, null, 2)}</pre></details>
  </section>;
}

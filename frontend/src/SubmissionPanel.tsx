import { useMemo, useRef, useState } from 'react';
import { errorMessage, field, formatTime, post, validQa } from './api';
import { Icon } from './icons';
import type { EvaluationList, PreviewResponse, SearchResult, SubmissionRequest, SubmissionResponse, Video } from './types';

const verdicts: Record<string, string> = {
  dry_run: 'Dry run · chỉ kiểm tra payload',
  accepted_pending: 'Đã nhận · đang chờ kết luận', pending: 'Đang chờ kết luận', rejected: 'Bị từ chối', unknown: 'Chưa biết kết quả · đối chiếu lịch sử trước khi gửi lại',
};

/** Preview và submit tách biệt; payload chỉ được nộp sau khi người dùng xem đúng bản hiện tại. */
export function SubmissionPanel({ selected, evaluations, onSubmitted }: {
  selected: SearchResult; evaluations: EvaluationList | null; onSubmitted: () => void;
}) {
  const [evaluationId, setEvaluationId] = useState('');
  const [taskKey, setTaskKey] = useState('');
  const [taskType, setTaskType] = useState<'KIS' | 'QA'>('KIS');
  const [answer, setAnswer] = useState('');
  const [mode, setMode] = useState<'dry_run' | 'mock' | 'live'>('dry_run');
  const [preview, setPreview] = useState<{ key: string; value: PreviewResponse } | null>(null);
  const [submission, setSubmission] = useState<SubmissionResponse | null>(null);
  const [submissionKey, setSubmissionKey] = useState('');
  const [busy, setBusy] = useState<'preview' | 'submit' | null>(null);
  const [error, setError] = useState('');
  const inFlight = useRef(false);
  const request = useMemo<SubmissionRequest>(() => ({
    keyframe_id: selected.keyframe_id, timestamp_ms: selected.timestamp_ms,
    task_type: taskType, ...(taskType === 'QA' ? { answer } : {}), evaluation_id: evaluationId, task_key: taskKey.trim(), mode,
  }), [selected, taskType, answer, evaluationId, taskKey, mode]);
  const requestKey = JSON.stringify(request);
  const allowedEvaluations = evaluations?.evaluations.filter(item => mode === 'mock' ? item.mock === true : mode === 'live' ? item.mock !== true && field(item, 'status', 'state') === 'ACTIVE' : true) ?? [];
  const valid = Boolean(allowedEvaluations.some(item => field(item, 'id', 'evaluation_id', 'evaluationId') === evaluationId) && taskKey.trim() && (taskType === 'KIS' || validQa(answer)));
  const previewCurrent = preview?.key === requestKey;

  async function action(kind: 'preview' | 'submit') {
    if (inFlight.current || !valid || (kind === 'submit' && !previewCurrent)) return;
    inFlight.current = true;
    setBusy(kind); setError(''); setSubmission(null);
    try {
      if (kind === 'preview') setPreview({ key: requestKey, value: await post<PreviewResponse>('/api/dres/preview', request) });
      else { setSubmission(await post<SubmissionResponse>('/api/dres/submit', request)); setSubmissionKey(requestKey); onSubmitted(); }
    } catch (reason) { setError(errorMessage(reason)); }
    finally { inFlight.current = false; setBusy(null); }
  }

  return <section className="submission-panel" aria-labelledby="submission-title">
    <div className="section-title"><h3 id="submission-title"><Icon name="send" size={17} /> Chuẩn bị đáp án</h3><span className={`badge ${mode === 'live' ? 'coral' : ''}`}>{mode === 'dry_run' ? 'DRY RUN' : mode.toUpperCase()}</span></div>
    <p className="muted small">{evaluations?.profile ?? 'Chưa tải profile'} · Không tự nộp khi chọn keyframe.</p>
    <div className="form-row">
      <label>Loại đáp án<select aria-label="Loại đáp án" value={taskType} onChange={e => setTaskType(e.target.value as 'KIS' | 'QA')}><option>KIS</option><option>QA</option></select></label>
      <label>Chế độ<select aria-label="Chế độ" value={mode} onChange={e => { setMode(e.target.value as typeof mode); setEvaluationId(''); }}><option value="dry_run">Dry run</option><option value="mock">Luyện tập mock</option><option value="live" disabled={evaluations?.mode !== 'live'}>Live (server phải bật)</option></select></label>
    </div>
    <label>Evaluation<select aria-label="Evaluation" value={evaluationId} onChange={e => setEvaluationId(e.target.value)}><option value="">Chọn phiên đánh giá…</option>{allowedEvaluations.map((item, i) => { const id = field(item, 'id', 'evaluation_id', 'evaluationId'); return <option key={`${id}-${i}`} value={id}>{field(item, 'name', 'title', 'id')} · {field(item, 'status', 'state')}</option>; })}</select></label>
    <label>Task / round key<input value={taskKey} onChange={e => setTaskKey(e.target.value)} placeholder="Ví dụ: round-01" autoComplete="off" /></label>
    {taskType === 'QA' && <label>Đáp án QA (chuỗi số)<input aria-label="Đáp án QA (chuỗi số)" value={answer} onChange={e => setAnswer(e.target.value)} inputMode="numeric" placeholder="Ví dụ: 007" autoComplete="off" aria-invalid={answer !== '' && !validQa(answer)} /><span className="input-hint">Chỉ chữ số 0–9; giữ nguyên số 0 đầu.</span></label>}
    <div className="answer-anchor"><span>{selected.media_item_name}</span><code>{formatTime(selected.timestamp_ms)}</code><small>{selected.timestamp_ms} ms · {taskType === 'KIS' ? 'KIS gửi start = end' : 'Thời điểm trên video gốc'}</small></div>
    {error && <div role="alert" className="inline-error">{error}</div>}
    <button className="button secondary full" disabled={!valid || busy !== null} onClick={() => void action('preview')}><Icon name="code" size={17} />{busy === 'preview' ? 'Đang kiểm tra…' : 'Xem trước JSON'}</button>
    {previewCurrent && <div className="payload-preview"><pre>{JSON.stringify(preview.value.payload, null, 2)}</pre>{preview.value.warnings?.map((warning, i) => <p className="small warning" key={i}>{warning}</p>)}</div>}
    <button className="button primary full" disabled={!valid || !previewCurrent || busy !== null} onClick={() => void action('submit')}><Icon name="send" size={17} />{busy === 'submit' ? 'Đang gửi…' : mode === 'dry_run' ? 'Ghi nhận dry run' : mode === 'mock' ? 'Nộp vào mock' : 'Nộp đáp án live'}</button>
    {!previewCurrent && <p className="small muted">Chọn evaluation, nhập task key và xem trước JSON để bật nút nộp.</p>}
    {submission && submissionKey === requestKey && <div className="submission-status" role="status"><strong>{submission.status === 'correct' ? mode === 'mock' ? 'Đúng theo ground truth mock' : 'DRES xác nhận đúng' : submission.status === 'incorrect' ? mode === 'mock' ? 'Chưa đúng theo ground truth mock' : 'DRES xác nhận chưa đúng' : verdicts[submission.status] ?? submission.status}</strong><small>Mã lần nộp: {submission.attempt_id}</small>{submission.response !== undefined && <pre>{JSON.stringify(submission.response, null, 2)}</pre>}</div>}
  </section>;
}

/** Ground truth luyện tập được khai báo độc lập, không suy ra từ thứ hạng truy vấn. */
export function MockTaskForm({ videos, onCreated }: { videos: Video[]; onCreated: () => void }) {
  const [taskKey, setTaskKey] = useState('');
  const [videoUid, setVideoUid] = useState('');
  const [type, setType] = useState<'textual_kis' | 'video_kis' | 'qa'>('textual_kis');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [answer, setAnswer] = useState('');
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const valid = taskKey.trim() && videoUid && start !== '' && end !== '' && Number.isInteger(Number(start)) && Number.isInteger(Number(end)) && Number(start) >= 0 && Number(end) >= Number(start) && (type !== 'qa' || validQa(answer));
  async function create() {
    if (!valid || busy) return;
    setBusy(true); setError(''); setStatus('');
    try {
      await post('/api/dres/mock/start', { task_key: taskKey.trim(), task_type: type, video_uid: videoUid, start_ms: Number(start), end_ms: Number(end), ...(type === 'qa' ? { answer } : {}) });
      setStatus(`Đã bắt đầu task ${taskKey.trim()}. Ground truth do bạn khai báo.`); onCreated();
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  }
  return <details className="mock-task panel"><summary><Icon name="plus" /> Tạo task luyện tập có ground truth</summary><div className="mock-task-body">
    <p className="muted">Xem video gốc và tự khai báo đoạn đúng. Dữ liệu này dùng để chấm mock, độc lập với đánh giá retrieval offline.</p>
    <div className="form-row"><label>Task key<input value={taskKey} onChange={e => setTaskKey(e.target.value)} placeholder="practice-01" /></label><label>Loại task<select aria-label="Loại task" value={type} onChange={e => setType(e.target.value as typeof type)}><option value="textual_kis">Textual KIS</option><option value="video_kis">Video KIS</option><option value="qa">QA</option></select></label></div>
    <label>Video ground truth<select aria-label="Video ground truth" value={videoUid} onChange={e => setVideoUid(e.target.value)}><option value="">Chọn video đã kiểm tra…</option>{videos.map(video => <option key={video.video_uid} value={video.video_uid}>{video.media_item_name} ({video.source_batch})</option>)}</select></label>
    <div className="form-row"><label>Bắt đầu (ms)<input type="number" min="0" step="1" value={start} onChange={e => setStart(e.target.value)} /></label><label>Kết thúc (ms)<input type="number" min="0" step="1" value={end} onChange={e => setEnd(e.target.value)} /></label></div>
    {type === 'qa' && <label>Đáp án QA<input inputMode="numeric" value={answer} onChange={e => setAnswer(e.target.value)} placeholder="007" /></label>}
    {error && <div className="inline-error" role="alert">{error}</div>}{status && <p className="success" role="status">{status}</p>}
    <button className="button secondary" disabled={!valid || busy} onClick={() => void create()}>{busy ? 'Đang tạo…' : 'Bắt đầu task mock'}</button>
  </div></details>;
}

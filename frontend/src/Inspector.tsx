import { useEffect, useRef, useState } from 'react';
import { api, errorMessage, formatTime } from './api';
import { Icon } from './icons';
import { SubmissionPanel } from './SubmissionPanel';
import type { EvaluationList, SearchResult } from './types';

/** Seek bằng ms / 1000 sau loadedmetadata; hủy listener và request cũ khi đổi kết quả. */
export function Inspector({ selected, evaluations, saved, feedback, imageAvailable, onClose, onSelect, onSave, onFeedback, onExample, onSubmitted }: {
  selected: SearchResult; evaluations: EvaluationList | null; saved: boolean; feedback?: boolean; imageAvailable: boolean;
  onClose: () => void; onSelect: (result: SearchResult) => void; onSave: (result: SearchResult) => void;
  onFeedback: (result: SearchResult, relevant: boolean) => void; onExample: (result: SearchResult) => void; onSubmitted: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [neighbors, setNeighbors] = useState<SearchResult[]>([]);
  const [neighborError, setNeighborError] = useState('');
  const [videoError, setVideoError] = useState('');
  const [neighborLoading, setNeighborLoading] = useState(false);
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    setVideoError('');
    const seek = () => {
      try { video.currentTime = selected.timestamp_ms / 1000; }
      catch { setVideoError('Trình duyệt chưa thể seek video. Kiểm tra codec và byte ranges của nguồn.'); }
    };
    video.addEventListener('loadedmetadata', seek);
    if (video.readyState >= 1) seek();
    return () => video.removeEventListener('loadedmetadata', seek);
  }, [selected.video_url, selected.timestamp_ms, selected.keyframe_id]);
  useEffect(() => {
    const controller = new AbortController();
    setNeighbors([]); setNeighborError(''); setNeighborLoading(true);
    api<{ results: SearchResult[] }>(`/api/videos/${encodeURIComponent(selected.video_uid)}/neighbors?timestamp_ms=${selected.timestamp_ms}`, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setNeighbors(value.results); })
      .catch(reason => { if (!controller.signal.aborted) setNeighborError(errorMessage(reason)); })
      .finally(() => { if (!controller.signal.aborted) setNeighborLoading(false); });
    return () => controller.abort();
  }, [selected.video_uid, selected.timestamp_ms]);
  const sorted = neighbors.filter(item => item.video_uid === selected.video_uid).sort((a, b) => a.timestamp_ms - b.timestamp_ms);
  const previous = sorted.filter(item => item.timestamp_ms < selected.timestamp_ms).at(-1);
  const next = sorted.find(item => item.timestamp_ms > selected.timestamp_ms);

  return <aside className="inspector panel" aria-label="Chi tiết keyframe">
    <div className="inspector-heading"><div><span className="eyebrow">KHUNG HÌNH ĐÃ CHỌN</span><h2>{selected.media_item_name}</h2></div><button className="icon-button" aria-label="Đóng chi tiết" onClick={onClose}><Icon name="close" /></button></div>
    <video ref={videoRef} key={selected.video_url} src={selected.video_url} controls preload="metadata" poster={selected.thumbnail_url} onError={() => setVideoError('Không phát được video. Trình duyệt cần codec hỗ trợ; hãy kiểm tra nguồn media.')} aria-label={`Video ${selected.media_item_name}`} />
    {videoError && <p className="inline-error" role="alert">{videoError}</p>}
    <div className="seek-bar"><code>{formatTime(selected.timestamp_ms)}</code><span>{selected.timestamp_ms} ms</span></div>
    <div className="neighbor-toolbar"><button className="button text-button" disabled={!previous} onClick={() => previous && onSelect(previous)}><Icon name="chevron" className="rotate" size={15} /> Trước</button><span className="muted small">Keyframe lân cận</span><button className="button text-button" disabled={!next} onClick={() => next && onSelect(next)}>Sau <Icon name="chevron" size={15} /></button></div>
    {neighborLoading ? <p className="small muted" role="status">Đang tải filmstrip…</p> : <div className="filmstrip">{sorted.map(item => <button key={item.keyframe_id} className={item.keyframe_id === selected.keyframe_id ? 'active' : ''} onClick={() => onSelect(item)} aria-label={`Xem ${formatTime(item.timestamp_ms)}`}><img src={item.thumbnail_url} alt="" loading="lazy" /><small>{formatTime(item.timestamp_ms).slice(3)}</small></button>)}</div>}
    {neighborError && <p className="small inline-error">{neighborError}</p>}
    {selected.pair && <div className="pair-info"><Icon name="temporal" size={17} /><span>A → B: <strong>{formatTime(selected.pair.timestamp_ms)}</strong><small>Khoảng cách {selected.pair.gap_ms} ms</small></span><button className="button text-button" onClick={() => onSelect({ ...selected, keyframe_id: selected.pair!.keyframe_id, timestamp_ms: selected.pair!.timestamp_ms, thumbnail_url: `/api/media/thumbnail/${encodeURIComponent(selected.pair!.keyframe_id)}`, pair: undefined })}>Xem B</button></div>}
    <div className="feedback-actions"><button className={`button secondary ${feedback === true ? 'selected-positive' : ''}`} onClick={() => onFeedback(selected, true)} aria-pressed={feedback === true}><Icon name="check" size={17} /> Liên quan</button><button className={`button secondary ${feedback === false ? 'selected-negative' : ''}`} onClick={() => onFeedback(selected, false)} aria-pressed={feedback === false}><Icon name="close" size={17} /> Không liên quan</button></div>
    <button className={`button secondary full ${saved ? 'saved' : ''}`} onClick={() => onSave(selected)}><Icon name={saved ? 'check' : 'bookmark'} size={17} />{saved ? 'Đã lưu · bấm để bỏ lưu' : 'Lưu vào ứng viên'}</button>
    <button className="button text-button full" disabled={!imageAvailable} title={!imageAvailable ? 'Tìm bằng ảnh chưa có sẵn hoặc bị chặn bởi luật Video KIS.' : undefined} onClick={() => onExample(selected)}><Icon name="image" size={17} /> Dùng khung hình này để tìm tiếp</button>
    <details className="evidence"><summary>Điểm xếp hạng & nguồn đóng góp</summary><p className="small muted">{Object.keys(selected.contributions).length ? `Điểm ${Number(selected.score).toFixed(5)} là điểm xếp hạng, không phải xác suất đúng.` : 'Khung hình từ metadata. Không có điểm truy vấn cho lần chọn này.'}</p><pre>{JSON.stringify(selected.contributions, null, 2)}</pre>{selected.text && <blockquote>{selected.text}</blockquote>}<small className="muted">Keyframe ID: {selected.keyframe_id}</small></details>
    <SubmissionPanel selected={selected} evaluations={evaluations} onSubmitted={onSubmitted} />
  </aside>;
}

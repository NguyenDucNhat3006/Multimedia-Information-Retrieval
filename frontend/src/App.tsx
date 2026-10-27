import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorMessage, extractCandidates, formatTime, getFeedbackSession, post } from './api';
import { Icon } from './icons';
import { Inspector } from './Inspector';
import { DataPage, EvaluationPage, HistoryPage } from './Pages';
import type { Capabilities, DataResponse, EvaluationList, EvaluationResponse, HistoryResponse, JsonRecord, Mode, Page, SearchResponse, SearchResult } from './types';

const modes: { id: Mode; label: string; icon: string; hint: string }[] = [
  { id: 'visual_text', label: 'Thị giác', icon: 'text', hint: 'Mô tả hình ảnh, đối tượng và hành động. Với CLIP tiếng Anh, bạn có thể nhập mô tả visual riêng.' },
  { id: 'ocr', label: 'OCR', icon: 'image', hint: 'Tìm chữ xuất hiện trong khung hình. Có thể dùng cụm từ hoặc AND / OR / NOT theo grammar backend.' },
  { id: 'asr', label: 'ASR', icon: 'audio', hint: 'Tìm từ hoặc cụm từ được nói trong video có transcript ASR.' },
  { id: 'hybrid', label: 'Kết hợp', icon: 'layers', hint: 'Hợp nhất thứ hạng thị giác, OCR và ASR. Chỉnh trọng số trong bộ lọc nâng cao.' },
  { id: 'temporal', label: 'A → B', icon: 'temporal', hint: 'Tìm hai sự kiện trong cùng video. B phải xảy ra sau A, trong khoảng thời gian bạn khai báo.' },
  { id: 'image', label: 'Ảnh mẫu', icon: 'image', hint: 'Chỉ áp dụng Top-k cho truy vấn ảnh. Không tải ảnh clip đề trong chế độ thi Video KIS.' },
];
const navigation: { id: Page; label: string; icon: string }[] = [
  { id: 'search', label: 'Truy vấn video', icon: 'search' }, { id: 'data', label: 'Dữ liệu & index', icon: 'database' },
  { id: 'evaluation', label: 'Đánh giá', icon: 'chart' }, { id: 'history', label: 'Lịch sử', icon: 'history' },
];

/** Không gian nghiên cứu video: trạng thái capability và kết quả đều đến từ backend thật. */
export default function App() {
  const [page, setPage] = useState<Page>('search');
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [data, setData] = useState<DataResponse | null>(null);
  const [evaluations, setEvaluations] = useState<EvaluationList | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationResponse | null>(null);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [candidates, setCandidates] = useState<SearchResult[]>([]);
  const [connected, setConnected] = useState(false);
  const [bootLoading, setBootLoading] = useState(true);
  const [bootErrors, setBootErrors] = useState<string[]>([]);
  const [mode, setMode] = useState<Mode>('visual_text');
  const [query, setQuery] = useState('');
  const [visualQuery, setVisualQuery] = useState('');
  const [queryB, setQueryB] = useState('');
  const [topK, setTopK] = useState(24);
  const [batch, setBatch] = useState('');
  const [videoUid, setVideoUid] = useState('');
  const [startMs, setStartMs] = useState('');
  const [endMs, setEndMs] = useState('');
  const [minGap, setMinGap] = useState(1);
  const [maxGap, setMaxGap] = useState(30000);
  const [groupByVideo, setGroupByVideo] = useState(false);
  const [useFeedback, setUseFeedback] = useState(false);
  const [expansion, setExpansion] = useState('');
  const [weights, setWeights] = useState({ visual: 1, ocr: 1, asr: 1 });
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [resultQuery, setResultQuery] = useState('');
  const [searchLoading, setSearchLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [actionError, setActionError] = useState('');
  const [toast, setToast] = useState('');
  const [selected, setSelected] = useState<SearchResult | null>(null);
  const [view, setView] = useState<'results' | 'candidates'>('results');
  const [feedback, setFeedback] = useState<Record<string, boolean>>({});
  const [mobileNav, setMobileNav] = useState(false);
  const [resultLimit, setResultLimit] = useState(24);
  const [feedbackSession] = useState(getFeedbackSession);
  const searchController = useRef<AbortController | null>(null);
  const mutationLocks = useRef(new Set<string>());
  const searchInput = useRef<HTMLTextAreaElement>(null);
  const bootGeneration = useRef(0);
  const feedbackRevision = useRef(0);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const generation = ++bootGeneration.current;
    const feedbackVersion = feedbackRevision.current;
    setBootLoading(true);
    const options = { signal };
    const responses = await Promise.allSettled([
      api<{ status: string }>('/api/health', options), api<Capabilities>('/api/capabilities', options), api<DataResponse>('/api/data', options),
      api<EvaluationList>('/api/dres/evaluations', options), api<EvaluationResponse>('/api/evaluation', options), api<HistoryResponse>('/api/history', options), api<unknown>('/api/candidates', options),
      api<{ feedback: { keyframe_id: string; relevant: boolean }[] }>(`/api/feedback/${encodeURIComponent(feedbackSession)}`, options),
    ]);
    if (signal?.aborted || generation !== bootGeneration.current) return;
    const [health, caps, library, dres, reports, past, saved, labels] = responses;
    setConnected(health.status === 'fulfilled');
    if (caps.status === 'fulfilled') setCapabilities(caps.value);
    if (library.status === 'fulfilled') setData(library.value);
    if (dres.status === 'fulfilled') setEvaluations(dres.value);
    if (reports.status === 'fulfilled') setEvaluation(reports.value);
    if (past.status === 'fulfilled') setHistory(past.value);
    if (saved.status === 'fulfilled') setCandidates(extractCandidates(saved.value));
    if (labels.status === 'fulfilled' && Array.isArray(labels.value.feedback) && feedbackRevision.current === feedbackVersion) setFeedback(Object.fromEntries(labels.value.feedback.map(item => [item.keyframe_id, item.relevant])));
    setBootErrors(responses.flatMap((item, i) => item.status === 'rejected' ? [`${['Health', 'Capabilities', 'Dữ liệu', 'DRES', 'Đánh giá', 'Lịch sử', 'Ứng viên', 'Feedback'][i]}: ${errorMessage(item.reason)}`] : []));
    setBootLoading(false);
  }, [feedbackSession]);

  useEffect(() => { const controller = new AbortController(); void refresh(controller.signal); return () => controller.abort(); }, [refresh]);
  useEffect(() => () => searchController.current?.abort(), []);
  useEffect(() => {
    if (!imageFile) { setImagePreview(''); return; }
    const url = URL.createObjectURL(imageFile); setImagePreview(url);
    return () => URL.revokeObjectURL(url);
  }, [imageFile]);
  useEffect(() => { if (!toast) return; const timer = window.setTimeout(() => setToast(''), 4000); return () => window.clearTimeout(timer); }, [toast]);
  useEffect(() => {
    function shortcut(event: KeyboardEvent) { if ((event.ctrlKey || event.metaKey) && event.key === 'k') { event.preventDefault(); setPage('search'); window.requestAnimationFrame(() => searchInput.current?.focus()); } if (event.key === 'Escape') setSelected(null); }
    window.addEventListener('keydown', shortcut); return () => window.removeEventListener('keydown', shortcut);
  }, []);

  const imageAvailable = Boolean(capabilities?.modes.image && !(capabilities.contest_mode && /video.?kis/i.test(capabilities.task_type)));
  const available = mode === 'image' ? imageAvailable : Boolean(capabilities?.modes[mode]);
  const activeMode = modes.find(item => item.id === mode)!;
  const batches = [...new Set(data?.videos.map(item => item.source_batch).filter(Boolean) ?? [])];
  const filteredVideos = data?.videos.filter(item => !batch || item.source_batch === batch) ?? [];
  const validationError = mode === 'image' ? '' : startMs !== '' && (!Number.isInteger(Number(startMs)) || Number(startMs) < 0) ? 'Mốc bắt đầu phải là integer milliseconds không âm.'
    : endMs !== '' && (!Number.isInteger(Number(endMs)) || Number(endMs) < 0 || (startMs !== '' && Number(endMs) < Number(startMs))) ? 'Mốc kết thúc phải là milliseconds không âm và không trước bắt đầu.'
    : mode === 'temporal' && (minGap <= 0 || maxGap < minGap || !Number.isInteger(minGap) || !Number.isInteger(maxGap)) ? 'Khoảng cách A → B phải là số nguyên dương, max ≥ min.' : '';
  const canSearch = available && !validationError && (mode === 'image' ? Boolean(imageFile) : query.trim() !== '' && (mode !== 'temporal' || queryB.trim() !== ''));

  async function search(example?: SearchResult) {
    if ((!example && !canSearch) || (example && !imageAvailable)) return;
    searchController.current?.abort();
    const controller = new AbortController(); searchController.current = controller;
    setSearchLoading(true); setSearchError(''); setActionError(''); setView('results'); setResultLimit(24);
    try {
      let result: SearchResponse;
      if (example) result = await post<SearchResponse>('/api/search/example', { keyframe_id: example.keyframe_id, top_k: topK }, controller.signal);
      else if (mode === 'image') {
        const form = new FormData(); form.append('file', imageFile!);
        result = await api<SearchResponse>(`/api/search/image?top_k=${topK}`, { method: 'POST', body: form, signal: controller.signal });
      } else result = await post<SearchResponse>('/api/search', {
        mode, query: query.trim(), ...(visualQuery.trim() && (mode === 'visual_text' || mode === 'hybrid') ? { visual_query: visualQuery.trim() } : {}),
        ...(mode === 'temporal' ? { query_b: queryB.trim() } : {}), top_k: topK,
        video_uids: videoUid ? [videoUid] : batch ? filteredVideos.map(item => item.video_uid) : [],
        ...(startMs !== '' ? { start_ms: Number(startMs) } : {}), ...(endMs !== '' ? { end_ms: Number(endMs) } : {}),
        min_gap_ms: minGap, max_gap_ms: maxGap, group_by_video: groupByVideo, feedback_session: feedbackSession, use_feedback: useFeedback,
        expansion: expansion.split(',').map(item => item.trim()).filter(Boolean), weights,
      }, controller.signal);
      if (controller.signal.aborted) return;
      setResults(result.results); setResponse(result); setSearched(true); setSelected(null);
      setResultQuery(example ? `Ảnh mẫu: ${example.media_item_name} · ${formatTime(example.timestamp_ms)}` : mode === 'image' ? imageFile!.name : query.trim());
      void refresh();
    } catch (reason) { if (!controller.signal.aborted) { setSearchError(errorMessage(reason)); setSearched(true); } }
    finally { if (!controller.signal.aborted) setSearchLoading(false); }
  }

  async function saveCandidate(result: SearchResult) {
    const lock = `save-${result.keyframe_id}`;
    if (mutationLocks.current.has(lock)) return;
    mutationLocks.current.add(lock); setActionError('');
    try {
      const saved = candidates.some(item => item.keyframe_id === result.keyframe_id);
      if (saved) { await api(`/api/candidates/${encodeURIComponent(result.keyframe_id)}`, { method: 'DELETE' }); setCandidates(current => current.filter(item => item.keyframe_id !== result.keyframe_id)); }
      else { await post('/api/candidates', { keyframe_id: result.keyframe_id }); const value = await api('/api/candidates'); setCandidates(extractCandidates(value)); }
      setToast(saved ? 'Đã bỏ lưu ứng viên.' : 'Đã lưu ứng viên trên backend.');
    } catch (reason) { setActionError(errorMessage(reason)); }
    finally { mutationLocks.current.delete(lock); }
  }

  async function markFeedback(result: SearchResult, relevant: boolean) {
    const lock = `feedback-${result.keyframe_id}`;
    if (mutationLocks.current.has(lock)) return;
    mutationLocks.current.add(lock); feedbackRevision.current += 1;
    setActionError('');
    try { await post('/api/feedback', { session_id: feedbackSession, keyframe_id: result.keyframe_id, relevant }); setFeedback(current => ({ ...current, [result.keyframe_id]: relevant })); setToast(relevant ? 'Đã ghi nhận keyframe liên quan.' : 'Đã ghi nhận keyframe không liên quan.'); }
    catch (reason) { setActionError(errorMessage(reason)); }
    finally { mutationLocks.current.delete(lock); }
  }

  async function resetFeedback() {
    feedbackRevision.current += 1;
    try { await api(`/api/feedback/${encodeURIComponent(feedbackSession)}`, { method: 'DELETE' }); setFeedback({}); setToast('Đã xóa feedback của phiên này.'); }
    catch (reason) { setActionError(errorMessage(reason)); }
  }

  function reuse(item: JsonRecord) {
    let source: JsonRecord = item;
    if (typeof item.request === 'object' && item.request !== null) source = item.request as JsonRecord;
    if (typeof source.query === 'string') setQuery(source.query);
    if (typeof source.visual_query === 'string') setVisualQuery(source.visual_query);
    if (typeof source.query_b === 'string') setQueryB(source.query_b);
    if (modes.some(value => value.id === source.mode)) setMode(source.mode as Mode);
    setPage('search'); setToast('Đã nạp câu truy vấn. Kiểm tra bộ lọc rồi bấm Tìm kiếm.');
  }

  const displayedResults = view === 'candidates' ? candidates : results;
  return <div className="workspace">
    <a href="#main-content" className="skip-link">Đến nội dung chính</a>
    <aside className={`sidebar ${mobileNav ? 'mobile-open' : ''}`}>
      <a className="brand" href="#" onClick={event => { event.preventDefault(); setPage('search'); }} aria-label="Frame, trang truy vấn"><span className="brand-mark"><i /><i /><i /><i /></span><span>frame<span className="brand-period">.</span></span></a>
      <div className="workspace-label">VIDEO RETRIEVAL WORKSPACE</div>
      <nav aria-label="Điều hướng chính">{navigation.map(item => <button key={item.id} className={page === item.id ? 'active' : ''} onClick={() => { setPage(item.id); setMobileNav(false); }} aria-current={page === item.id ? 'page' : undefined}><Icon name={item.icon} /><span>{item.label}</span>{item.id === 'search' && <kbd aria-hidden="true">Ctrl K</kbd>}</button>)}</nav>
      <div className="sidebar-note"><span className="sidebar-note-icon"><Icon name="layers" size={22} /></span><strong>Từ mô tả đến khoảnh khắc.</strong><p>Thị giác, văn bản và thời gian trong một không gian truy vấn.</p><span className="sidebar-note-line" /></div>
      <div className="sidebar-bottom"><div className="course-badge">CS336 <span>UIT</span></div><div className="profile"><span className="avatar">NN</span><div><strong>Nguyễn Đức Nhật</strong><small>Đồ án truy hồi thông tin</small></div></div></div>
    </aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumb"><button className="icon-button mobile-menu" aria-label="Mở điều hướng" onClick={() => setMobileNav(!mobileNav)}><Icon name="menu" /></button><span>Không gian làm việc</span><Icon name="chevron" size={13} /><strong>{navigation.find(item => item.id === page)?.label}</strong></div><div className="topbar-status"><span className={`status-dot ${connected ? 'ready' : ''}`} /><span>{bootLoading ? 'Đang đồng bộ' : connected ? 'Backend kết nối' : 'Backend chưa kết nối'}</span><span className="topbar-divider" /><span className="badge">{capabilities?.contest_mode ? 'CONTEST' : 'LOCAL RESEARCH'}</span></div></header>
      <main id="main-content">
        {bootErrors.length > 0 && <div className="connection-banner" role="alert"><Icon name="info" size={18} /><div><strong>Một phần dữ liệu chưa tải được.</strong><details><summary>Xem lỗi kết nối</summary>{bootErrors.map((error, i) => <p key={i}>{error}</p>)}</details></div><button className="button text-button" onClick={() => void refresh()}>Kết nối lại <Icon name="refresh" size={15} /></button></div>}
        {capabilities?.fixture && <div className="fixture-banner"><Icon name="info" size={16} /> Đang dùng fixture để kiểm thử tích hợp. Kết quả này không đại diện chất lượng retrieval trên dataset thật.</div>}
        {page === 'search' ? <div className="search-page"><div className="page-intro"><div><span className="eyebrow">TRUY VẤN SỰ KIỆN TRONG VIDEO</span><h1>Tìm đúng <span>khoảnh khắc.</span></h1><p className="muted">Mô tả điều bạn đang tìm. Kiểm tra khung hình và thời điểm trong video gốc.</p></div><div className="library-indicator"><Icon name="database" size={19} /><div><strong>{data ? `${data.counts.videos.toLocaleString('vi-VN')} video` : 'Kho dữ liệu'}</strong><small>{data ? `${data.counts.keyframes.toLocaleString('vi-VN')} keyframe đã đăng ký` : 'Đang chờ backend'}</small></div></div></div>
          <section className="search-panel panel" aria-label="Tìm kiếm video"><div className="mode-tabs" role="tablist" aria-label="Kênh truy vấn">{modes.map(item => { const enabled = item.id === 'image' ? imageAvailable : capabilities?.modes[item.id]; return <button role="tab" aria-selected={mode === item.id} key={item.id} className={`${mode === item.id ? 'active' : ''} ${!enabled ? 'unavailable' : ''}`} onClick={() => setMode(item.id)} title={enabled ? item.hint : capabilities?.reasons[item.id] ?? 'Chưa sẵn sàng'}><Icon name={item.icon} size={17} />{item.label}{!enabled && <span className="mode-status" aria-label="chưa sẵn sàng" />}</button>; })}</div>
            <form onSubmit={event => { event.preventDefault(); void search(); }}><div className="query-area">{mode === 'image' ? <div className="image-upload"><input id="query-image" type="file" accept="image/png,image/jpeg,image/webp" disabled={!imageAvailable} onChange={event => { const file = event.target.files?.[0] ?? null; if (file && (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 10 * 1024 * 1024)) { setSearchError('Chọn ảnh PNG, JPEG hoặc WebP tối đa 10 MiB.'); event.target.value = ''; return; } setSearchError(''); setImageFile(file); }} />{imagePreview ? <img src={imagePreview} alt="Ảnh truy vấn do bạn chọn" /> : <Icon name="upload" size={30} />}<label htmlFor="query-image">{imageFile ? imageFile.name : 'Chọn ảnh mẫu từ máy'}<small>PNG, JPEG, WebP · tối đa 10 MiB</small></label></div> : <><label className="query-label" htmlFor="main-query">{mode === 'temporal' ? 'Sự kiện A' : 'Nội dung truy vấn'}</label><div className="query-input-wrap"><Icon name="search" size={23} /><textarea ref={searchInput} id="main-query" value={query} onChange={event => setQuery(event.target.value)} placeholder={mode === 'ocr' ? 'Nhập chữ xuất hiện trong hình, ví dụ: “thành phố”' : mode === 'asr' ? 'Nhập từ hoặc cụm từ được nói trong video…' : 'Một người đi xe đạp qua cây cầu vào buổi sáng…'} rows={2} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void search(); } }} /><button className="button primary search-button" disabled={!canSearch} type="submit">{searchLoading ? <span className="spinner" /> : <Icon name="arrow" size={20} />}<span>{searchLoading ? 'Tìm lại' : 'Tìm kiếm'}</span></button></div></>}
              {mode === 'image' && <button type="submit" className="button primary" disabled={!canSearch}><Icon name="search" />Tìm bằng ảnh</button>}
              {(mode === 'visual_text' || mode === 'hybrid') && <div className="visual-query"><label htmlFor="visual-query"><span className="language-badge">EN</span>Mô tả visual tiếng Anh <span className="muted">· tùy chọn, nhập riêng</span></label><input id="visual-query" value={visualQuery} onChange={event => setVisualQuery(event.target.value)} placeholder="A person riding a bicycle across a bridge in the morning" /></div>}
              {mode === 'temporal' && <div className="temporal-inputs"><label>Sự kiện B<textarea value={queryB} onChange={event => setQueryB(event.target.value)} placeholder="Điều gì xảy ra tiếp theo?" rows={2} /></label><div className="form-row"><label>Khoảng cách tối thiểu (ms)<input type="number" min="1" step="1" value={minGap} onChange={event => setMinGap(Number(event.target.value))} /></label><label>Khoảng cách tối đa (ms)<input type="number" min="1" step="1" value={maxGap} onChange={event => setMaxGap(Number(event.target.value))} /></label></div></div>}
              <div className="query-hint"><Icon name="info" size={14} /><span>{available ? activeMode.hint : capabilities?.reasons[mode] ?? (capabilities ? 'Kênh này chưa sẵn sàng. Kiểm tra dữ liệu và index.' : 'Đang kiểm tra capabilities từ backend.')}</span></div>
            </div><div className="filter-toolbar"><label className="compact-select"><Icon name="filter" size={16} /><select value={batch} onChange={event => { setBatch(event.target.value); setVideoUid(''); }} aria-label="Lọc batch"><option value="">Tất cả batch</option>{batches.map(item => <option key={item} value={item}>{item}</option>)}</select></label><label className="compact-select"><Icon name="play" size={15} /><select value={videoUid} onChange={event => setVideoUid(event.target.value)} aria-label="Lọc video"><option value="">Tất cả video</option>{filteredVideos.map(item => <option key={item.video_uid} value={item.video_uid}>{item.media_item_name}</option>)}</select></label><label className="compact-select">Top<select value={topK} onChange={event => setTopK(Number(event.target.value))} aria-label="Top k">{[12, 24, 48, 100, 200].map(value => <option key={value}>{value}</option>)}</select></label><label className="checkbox-label"><input type="checkbox" checked={groupByVideo} onChange={event => setGroupByVideo(event.target.checked)} /> Nhóm theo video</label></div>
            <details className="advanced-filters"><summary><Icon name="filter" size={15} /> Bộ lọc & điều chỉnh nâng cao <Icon name="chevron" size={14} /></summary><div className="advanced-body"><div className="form-row"><label>Từ thời điểm (ms)<input type="number" min="0" step="1" value={startMs} onChange={event => setStartMs(event.target.value)} placeholder="Không giới hạn" /></label><label>Đến thời điểm (ms)<input type="number" min="0" step="1" value={endMs} onChange={event => setEndMs(event.target.value)} placeholder="Không giới hạn" /></label></div><label>Từ mở rộng <span className="muted">(phân cách bằng dấu phẩy)</span><input value={expansion} onChange={event => setExpansion(event.target.value)} placeholder="Các từ bạn muốn bổ sung, không tự dịch" /></label>{mode === 'hybrid' && <div className="form-row weights-row">{Object.entries(weights).map(([name, weight]) => <label key={name}>Trọng số {name}<input type="number" min="0" max="10" step="0.1" value={weight} onChange={event => setWeights(current => ({ ...current, [name]: Number(event.target.value) }))} /></label>)}</div>}<div className="feedback-settings"><label className="checkbox-label"><input type="checkbox" checked={useFeedback} onChange={event => setUseFeedback(event.target.checked)} /> Dùng relevance feedback ({Object.keys(feedback).length} nhãn)</label><button className="button text-button" type="button" disabled={!Object.keys(feedback).length} onClick={() => void resetFeedback()}>Xóa feedback</button></div>{mode === 'image' && <p className="small warning">API ảnh chỉ áp dụng top-k. Bộ lọc thời gian, video và feedback ở trên dành cho truy vấn văn bản.</p>}</div></details>
          </form>{validationError && <div role="alert" className="inline-error">{validationError}</div>}</section>
          {searchError && <div className="error-banner" role="alert"><Icon name="info" /><div><strong>Chưa thực hiện được truy vấn</strong><p>{searchError}</p>{results.length > 0 && <p className="small">Lưới bên dưới vẫn là kết quả của truy vấn trước: {resultQuery}.</p>}</div></div>}{actionError && <div className="error-banner" role="alert"><Icon name="info" /><span>{actionError}</span><button className="icon-button" aria-label="Ẩn lỗi" onClick={() => setActionError('')}><Icon name="close" /></button></div>}
          <div className="results-toolbar"><div className="view-tabs"><button className={view === 'results' ? 'active' : ''} onClick={() => setView('results')}><Icon name="grid" size={17} />Kết quả{searched && <span>{results.length}</span>}</button><button className={view === 'candidates' ? 'active' : ''} onClick={() => setView('candidates')}><Icon name="bookmark" size={17} />Ứng viên<span>{candidates.length}</span></button></div><div className="results-meta">{searchLoading ? <span role="status"><span className="spinner dark" /> Đang truy vấn…</span> : response && view === 'results' ? <><Icon name="clock" size={14} />{response.elapsed_ms.toFixed(0)} ms<span className="meta-divider">·</span><span title={response.index_version ?? ''}>Index {response.index_version ?? 'text'}</span></> : <span>Thumbnail & mốc thời gian gốc</span>}</div></div>
          {response?.warnings?.map((warning, i) => <p className="warning small" key={i}>{warning}</p>)}
          <div className={`results-workspace ${selected ? 'has-selection' : ''}`}><section className="results-region" aria-label="Kết quả truy vấn" aria-busy={searchLoading}>
            {searchLoading ? <div className="result-grid skeleton-grid">{Array.from({ length: 6 }, (_, i) => <div className="result-skeleton panel" key={i}><div /><span /><span /></div>)}</div> : displayedResults.length ? <><div className="result-grid">{displayedResults.slice(0, resultLimit).map((result, i) => <ResultCard key={`${result.keyframe_id}-${i}`} result={result} rank={view === 'results' ? i + 1 : undefined} selected={selected?.keyframe_id === result.keyframe_id} saved={candidates.some(item => item.keyframe_id === result.keyframe_id)} feedback={feedback[result.keyframe_id]} onSelect={() => setSelected(result)} onSave={() => void saveCandidate(result)} />)}</div>{displayedResults.length > resultLimit && <button className="button secondary load-more" onClick={() => setResultLimit(value => value + 24)}>Xem thêm {Math.min(24, displayedResults.length - resultLimit)} keyframe</button>}</> : <div className="empty-state results-empty"><div className="empty-frame"><span /><Icon name={view === 'candidates' ? 'bookmark' : 'search'} size={32} /><span /></div><span className="eyebrow">{view === 'candidates' ? 'DANH SÁCH ỨNG VIÊN' : searched ? 'KẾT QUẢ TRUY VẤN' : 'SẴN SÀNG KHÁM PHÁ'}</span><h2>{view === 'candidates' ? 'Giữ lại những khoảnh khắc đáng chú ý.' : searched ? 'Chưa tìm thấy khung hình phù hợp.' : 'Một mô tả. Một khoảnh khắc.'}</h2><p>{view === 'candidates' ? 'Bấm biểu tượng lưu trên kết quả để tạo danh sách ứng viên. Danh sách được lưu trên backend và giữ sau khi tải lại trang.' : searched ? 'Thử điều chỉnh mô tả, chọn kênh có dữ liệu hoặc mở rộng bộ lọc thời gian và video.' : 'Nhập câu truy vấn phía trên để tìm khung hình. Chọn kết quả để xem video đúng thời điểm, đánh dấu liên quan và chuẩn bị đáp án.'}</p>{!searched && view === 'results' && <div className="empty-workflow"><span><b>01</b> Mô tả sự kiện</span><Icon name="arrow" size={16} /><span><b>02</b> Kiểm tra video</span><Icon name="arrow" size={16} /><span><b>03</b> Lưu & đánh giá</span></div>}</div>}
          </section>{selected && <Inspector selected={selected} evaluations={evaluations} saved={candidates.some(item => item.keyframe_id === selected.keyframe_id)} feedback={feedback[selected.keyframe_id]} imageAvailable={imageAvailable} onClose={() => setSelected(null)} onSelect={setSelected} onSave={result => void saveCandidate(result)} onFeedback={(result, relevant) => void markFeedback(result, relevant)} onExample={result => void search(result)} onSubmitted={() => void refresh()} />}</div>
        </div> : page === 'data' ? <DataPage data={data} capabilities={capabilities} onRefresh={() => void refresh()} /> : page === 'evaluation' ? <EvaluationPage evaluation={evaluation} videos={data?.videos ?? []} onSaved={() => void refresh()} /> : <HistoryPage history={history} onReuse={reuse} onInspect={result => { setPage('search'); setSelected(result); }} />}
      </main><footer className="workspace-footer"><span>FRAME / CS336</span><span>Milliseconds chính xác. Thứ hạng có giải thích.</span><button className="button text-button" onClick={() => void refresh()}><Icon name="refresh" size={13} />Đồng bộ dữ liệu</button></footer>
    </div>{toast && <div className="toast" role="status"><Icon name="check" size={18} />{toast}</div>}
  </div>;
}

/** Card dùng thumbnail backend thật; không tự gán nhãn hoặc tạo ảnh thay thế giả. */
function ResultCard({ result, rank, selected, saved, feedback, onSelect, onSave }: { result: SearchResult; rank?: number; selected: boolean; saved: boolean; feedback?: boolean; onSelect: () => void; onSave: () => void }) {
  const [imageError, setImageError] = useState(false);
  return <article className={`result-card panel ${selected ? 'selected' : ''}`}><button className="result-image-button" onClick={onSelect} aria-label={`Xem ${result.media_item_name} tại ${formatTime(result.timestamp_ms)}`}>{imageError ? <div className="thumbnail-error"><Icon name="image" /><span>Không tải được thumbnail</span></div> : <img src={result.thumbnail_url} alt={`${result.media_item_name}, ${formatTime(result.timestamp_ms)}`} loading="lazy" onError={() => setImageError(true)} />}{rank && <span className="rank-badge">#{String(rank).padStart(2, '0')}</span>}<code className="time-badge">{formatTime(result.timestamp_ms)}</code><span className="image-play"><Icon name="play" size={22} /></span></button><div className="result-card-body"><div className="result-card-title"><button onClick={onSelect}>{result.media_item_name}</button><button className={`icon-button ${saved ? 'saved' : ''}`} onClick={onSave} aria-label={saved ? `Bỏ lưu ${result.media_item_name}` : `Lưu ${result.media_item_name}`} aria-pressed={saved}><Icon name={saved ? 'check' : 'bookmark'} size={18} /></button></div><div className="result-card-meta"><span title={rank ? 'Điểm xếp hạng, không phải xác suất' : undefined}>{rank ? `Score ${Number(result.score).toFixed(4)}` : 'Ứng viên đã lưu'}</span><span className="channel-tags">{Object.keys(result.contributions ?? {}).map(channel => <small key={channel}>{channel}</small>)}</span></div>{result.pair && <p className="pair-caption"><Icon name="temporal" size={13} /> B: {formatTime(result.pair.timestamp_ms)} · +{result.pair.gap_ms} ms</p>}{feedback !== undefined && <p className={`feedback-caption ${feedback ? 'success' : 'warning'}`}><Icon name={feedback ? 'check' : 'close'} size={13} /> {feedback ? 'Đã đánh dấu liên quan' : 'Đã đánh dấu không liên quan'}</p>}</div></article>;
}

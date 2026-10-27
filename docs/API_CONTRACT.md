# Contract v1 · CS336

Thời gian API là integer milliseconds. Không có absolute filesystem path/secret trong response.

- `GET /api/health`: `{status, version}`
- `GET /api/capabilities`: `{modes: {visual_text,image,ocr,asr,hybrid,temporal}, reasons: {}, contest_mode, task_type, index_version, encoder_id, fixture}`
- `POST /api/search`: JSON `{mode,query,visual_query?,query_b?,top_k:24,video_uids:[],start_ms?,end_ms?,min_gap_ms:1,max_gap_ms:30000,group_by_video:false,feedback_session:"default",use_feedback:false,expansion:[],weights:{visual:1,ocr:1,asr:1}}`; response `{results:[],elapsed_ms,index_version,query_id,warnings:[]}`.
- `POST /api/search/image`: multipart `file` OR `POST /api/search/example` JSON `{keyframe_id,top_k}`. Video KIS contest blocks both.
- Result: `{keyframe_id,video_uid,media_item_name,timestamp_ms,thumbnail_url,video_url,score,contributions:{},text?,pair?:{keyframe_id,timestamp_ms,gap_ms}}`; score is ranking score, never probability.
- `GET /api/videos/{uid}/neighbors?timestamp_ms=...`: `{results:[]}`.
- `GET /api/media/video/{uid}`, `GET /api/media/thumbnail/{keyframe_id}`: safe file bytes with range support for video.
- `GET /api/data`: `{videos:[],counts:{videos,keyframes,ocr,asr},jobs:[],index_version,fixture,doctor?}`.
- `POST /api/feedback`: `{session_id,keyframe_id,relevant:bool}`; `GET /api/feedback/{session_id}`: `{feedback:[{keyframe_id,relevant:bool}]}`; `DELETE /api/feedback/{session_id}`. UI giữ ID session không nhạy cảm trong sessionStorage để khôi phục sau reload.
- `GET/POST /api/candidates`; POST `{keyframe_id,note?}`; DELETE `/api/candidates/{keyframe_id}`.
- `GET /api/history`: `{queries:[],submissions:[]}`.
- `GET /api/dres/evaluations`: `{evaluations:[],mode,profile}`.
- `POST /api/dres/preview`, `POST /api/dres/submit`: `{keyframe_id,timestamp_ms?,task_type:"KIS"|"QA",answer?,evaluation_id,task_key,mode:"dry_run"|"mock"|"live"}`. Server resolves media name, validates duration and ambiguity. Preview returns `{payload,mode,profile,warnings:[]}`. Submit returns `{attempt_id,status,payload,response?}`.
- `POST /api/dres/mock/start`: `{task_key,task_type:"textual_kis"|"video_kis"|"qa",video_uid,start_ms,end_ms,answer?}`. Ground truth declared by user, never inferred from ranking.
- `GET /api/evaluation`: `{reports:[],label_schema,ground_truth_available}`.

Failures use FastAPI `{detail: string}` and appropriate 400/403/404/409/422/503. Core starts without weights; no automatic model or dataset download.

## Internal adapters

`Database.connection()` is a closing transaction context with SQLite Row, foreign keys and busy timeout. `rows(sql, params=()) -> list[dict]`, `one(...) -> dict|None`, `execute(...) -> int`. Tables: videos, keyframes, text_segments, jobs, query_history, feedback, candidates. DRES owns creation of submissions/mock_tasks tables.

`Settings.from_env()`: `data_root`, `db_path`, `index_root`, `model_name`, `pretrained`, `device`, `contest_mode`, `task_type`; data root defaults workspace/data.

`RetrievalService(db,settings)`: `capabilities()`, `search(request:dict)->dict`, `search_image(image_bytes,top_k)->dict`, `search_example(keyframe_id,top_k)->dict`. Root adds history/query_id; results use above contract.

`DresService(db,settings)`: `evaluations()`, `preview(request:dict)`, `submit(request:dict)`, `start_mock(request:dict)`, `history()`. ValueError => 400, PermissionError =>403, duplicate =>409.

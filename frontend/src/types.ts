export type Mode = 'visual_text' | 'image' | 'ocr' | 'asr' | 'hybrid' | 'temporal';
export type Page = 'search' | 'data' | 'evaluation' | 'history';
export type JsonRecord = Record<string, unknown>;
export interface Capabilities {
  modes: Record<Mode, boolean>;
  reasons: Partial<Record<Mode, string>>;
  contest_mode: boolean;
  task_type: string;
  index_version: string | null;
  encoder_id: string | null;
  fixture: boolean;
}
export interface SearchResult {
  keyframe_id: string;
  video_uid: string;
  media_item_name: string;
  timestamp_ms: number;
  thumbnail_url: string;
  video_url: string;
  score: number;
  contributions: Record<string, unknown>;
  text?: string;
  pair?: { keyframe_id: string; timestamp_ms: number; gap_ms: number };
  note?: string;
}
export interface SearchResponse {
  results: SearchResult[];
  elapsed_ms: number;
  index_version: string | null;
  query_id?: string;
  warnings?: string[];
}
export interface Video {
  video_uid: string;
  media_item_name: string;
  source_batch?: string;
  duration_ms: number;
  keyframe_count?: number;
  width?: number;
  height?: number;
  codec?: string;
  fps_num?: number;
  fps_den?: number;
}
export interface DataResponse {
  videos: Video[];
  counts: { videos: number; keyframes: number; ocr: number; asr: number };
  jobs: JsonRecord[];
  index_version: string | null;
  fixture: boolean;
  doctor?: unknown;
}
export interface EvaluationList {
  evaluations: JsonRecord[];
  mode: 'dry_run' | 'mock' | 'live';
  profile: string;
}
export interface EvaluationResponse {
  reports: JsonRecord[];
  label_schema?: unknown;
  ground_truth_available: boolean;
}
export interface HistoryResponse { queries: JsonRecord[]; submissions: JsonRecord[] }
export interface SubmissionRequest {
  keyframe_id: string;
  timestamp_ms: number;
  task_type: 'KIS' | 'QA';
  answer?: string;
  evaluation_id: string;
  task_key: string;
  mode: 'dry_run' | 'mock' | 'live';
}
export interface PreviewResponse { payload: unknown; mode: string; profile: string; warnings?: string[] }
export interface SubmissionResponse { attempt_id: string; status: string; payload: unknown; response?: unknown }

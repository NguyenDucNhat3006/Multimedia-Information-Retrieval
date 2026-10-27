"""Schema chung cho pipeline/API: thời gian nguyên ms và ID ổn định, không dùng ordinal làm frame gốc."""

from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator


class Video(BaseModel):
    """Metadata video gốc; fps chỉ mô tả, VFR luôn cần PTS để xác định timestamp."""
    video_uid: str
    media_item_name: str = Field(min_length=1)
    source_batch: str
    relative_path: str
    duration_ms: int = Field(gt=0, strict=True)
    fps_num: int | None = Field(default=None, gt=0)
    fps_den: int | None = Field(default=None, gt=0)
    time_base: str | None = None
    start_time: float | None = None
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    vfr: bool | None = None
    fingerprint: str


class Keyframe(BaseModel):
    """Ảnh đại diện; original_frame_index bắt đầu từ 0 nếu decoder xác định được."""
    keyframe_id: str
    video_uid: str
    original_frame_index: int | None = Field(default=None, ge=0)
    timestamp_ms: int = Field(ge=0, strict=True)
    thumbnail_path: str
    timestamp_source: str
    encoder_id: str | None = None


class TextSegment(BaseModel):
    """OCR/ASR giữ khoảng thời gian gốc ms, văn bản gốc và Unicode chuẩn hóa."""
    segment_id: str
    video_uid: str
    start_ms: int = Field(ge=0, strict=True)
    end_ms: int = Field(ge=0, strict=True)
    source: Literal["ocr", "asr"]
    text: str
    normalized_text: str = ""
    metadata_json: str = "{}"

    @model_validator(mode="after")
    def check_interval(self):
        """Từ chối interval ngược trước khi thay đổi text index."""
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms phải lớn hơn hoặc bằng start_ms")
        return self


class SearchRequest(BaseModel):
    """Contract tìm kiếm độc lập các kênh; score là điểm xếp hạng, không là xác suất."""
    model_config = ConfigDict(extra="forbid")
    mode: Literal["visual_text", "ocr", "asr", "hybrid", "temporal"] = "visual_text"
    query: str = Field(min_length=1, max_length=4000)
    visual_query: str | None = Field(default=None, max_length=4000)
    query_b: str | None = Field(default=None, max_length=4000)
    top_k: int = Field(default=24, ge=1, le=200)
    video_uids: list[str] = Field(default_factory=list, max_length=2000)
    start_ms: int | None = Field(default=None, ge=0, strict=True)
    end_ms: int | None = Field(default=None, ge=0, strict=True)
    min_gap_ms: int = Field(default=1, ge=0, strict=True)
    max_gap_ms: int = Field(default=30000, gt=0, le=86400000, strict=True)
    group_by_video: bool = False
    feedback_session: str = Field(default="default", min_length=1, max_length=100)
    use_feedback: bool = False
    expansion: list[str] = Field(default_factory=list, max_length=30)
    weights: dict[str, float] = Field(default_factory=lambda: {"visual": 1, "ocr": 1, "asr": 1})

    @model_validator(mode="after")
    def check_ranges(self):
        """Giới hạn phạm vi trước khi encode để không lãng phí inference."""
        import math
        if self.end_ms is not None and self.start_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("Khoảng thời gian tìm kiếm bị đảo ngược")
        if self.min_gap_ms > self.max_gap_ms:
            raise ValueError("min_gap_ms phải <= max_gap_ms")
        if self.mode == "temporal" and not (self.query_b or "").strip():
            raise ValueError("Temporal cần mô tả sự kiện B")
        if any(k not in {"visual", "ocr", "asr"} or not math.isfinite(v) or v < 0 for k, v in self.weights.items()):
            raise ValueError("Trọng số visual/ocr/asr phải hữu hạn và không âm")
        if self.weights and not any(self.weights.values()):
            raise ValueError("Cần ít nhất một trọng số dương")
        return self


class FeedbackRequest(BaseModel):
    """Feedback lưu theo session; reset không thay embedding đã lập chỉ mục."""
    session_id: str = Field(min_length=1, max_length=100)
    keyframe_id: str
    relevant: bool


class CandidateRequest(BaseModel):
    """Ứng viên lưu bền vững để kiểm tra và nộp thủ công."""
    keyframe_id: str
    note: str = Field(default="", max_length=1000)


class SubmissionRequest(BaseModel):
    """Không nhận media name tùy ý: backend resolve tên và kiểm tra duration/ambiguity."""
    keyframe_id: str
    timestamp_ms: int | None = Field(default=None, ge=0, strict=True)
    task_type: Literal["KIS", "QA"] = "KIS"
    answer: str | None = None
    evaluation_id: str = Field(min_length=1, max_length=200)
    task_key: str = Field(min_length=1, max_length=200)
    mode: Literal["dry_run", "mock", "live"] = "dry_run"


class ExampleRequest(BaseModel):
    """Query-by-example dùng embedding cùng không gian của một keyframe đã có."""
    keyframe_id: str
    top_k: int = Field(default=24, ge=1, le=200)


class MockTaskRequest(BaseModel):
    """Nhãn local do người dùng khai báo; không lấy một result làm ground truth tự động."""
    task_key: str = Field(min_length=1, max_length=200)
    task_type: Literal["textual_kis", "video_kis", "qa"] = "textual_kis"
    video_uid: str
    start_ms: int = Field(ge=0, strict=True)
    end_ms: int = Field(ge=0, strict=True)
    answer: str | None = None


class EmbeddingManifest(BaseModel):
    """Bằng chứng embedding space; cùng dimension chưa đủ để import hoặc dùng query encoder."""
    schema_version: Literal[1]
    pipeline_version: str
    encoder_id: str
    model_name: str
    pretrained: str
    checkpoint_sha256: str = Field(min_length=64, max_length=64)
    preprocessing_hash: str = Field(min_length=64, max_length=64)
    dimension: int = Field(gt=0)
    normalization: Literal["l2"]
    dtype: Literal["float32"]
    dataset_fingerprint: str
    keyframe_fingerprint: str
    row_count: int = Field(gt=0)
    shards: list[dict] = Field(min_length=1)
    fixture: bool = False


class Job(BaseModel):
    """Trạng thái pipeline bền vững; progress/total là số item, không phải tỷ lệ giả."""
    job_id: str
    kind: str
    status: Literal["running", "completed", "failed"]
    progress: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    config_json: str = "{}"
    error: str | None = None


class QueryHistory(BaseModel):
    """Input đủ tái hiện query; không giữ bytes ảnh hoặc thông tin đăng nhập."""
    query_id: str
    request_json: str
    result_count: int = Field(ge=0)
    elapsed_ms: float = Field(ge=0)
    index_version: str | None = None


class SubmissionAttempt(BaseModel):
    """Ledger có namespace, task và canonical payload; unknown không được tự retry."""
    attempt_id: str
    namespace: str
    evaluation_id: str
    task_key: str
    payload_hash: str
    payload_json: str
    status: Literal["dry_run", "sending", "accepted_pending", "correct", "incorrect", "rejected", "unknown"]
    response_json: str | None = None

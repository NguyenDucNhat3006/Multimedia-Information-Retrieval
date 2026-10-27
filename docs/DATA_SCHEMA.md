# Schema chung và thời gian

Các model typed trong `app/schemas.py`, cấu hình trong `app/config.py`, SQLite adapter trong `app/db.py`. Metadata local dùng SQLite WAL, foreign keys, busy timeout và migration version 1. Mỗi connection đóng sau transaction; validate hoàn tất trước khi import text batch.

## Video

| Field | Ý nghĩa |
|---|---|
| `video_uid` | Internal ID, riêng với media name; pipeline băm source path + source batch |
| `media_item_name` | Tên file bỏ extension, đúng tên dùng khi gửi DRES |
| `source_batch` | Batch nguồn hoặc `fixture` rõ ràng |
| `relative_path` | Relative path dưới `Settings.data_root`; không trả vào frontend |
| `duration_ms` | Integer >0, full video duration, không duration của smoke subset |
| `fps_num`, `fps_den` | Frame rate hữu tỷ nếu metadata có; không tự mặc định |
| `time_base` | Chuỗi hữu tỷ của stream, ví dụ `1/90000` |
| `start_time` | Stream start theo giây nếu có; extraction trừ origin PTS |
| `codec`, `width`, `height` | Metadata decoder đã quan sát |
| `vfr` | True/false theo PTS deltas đã decode, None nếu chưa đủ bằng chứng |
| `fingerprint` | `sampled-sha256:` size/mtime/đầu/cuối; không phải full checksum |

Không unique `media_item_name` vì hai batch có thể trùng tên. Inventory phát hiện xung đột, DRES validator chặn tên mơ hồ. Không tự thêm batch vào media name gửi BTC. Di chuyển input sang path khác có thể tạo UID khác; không coi UID nội bộ là official dataset ID.

## Keyframe

| Field | Ý nghĩa |
|---|---|
| `keyframe_id` | Stable hash của video UID, timestamp và sampling config |
| `video_uid` | Foreign key đến video |
| `original_frame_index` | Frame gốc decode từ 0 nếu biết, không keyframe ordinal |
| `timestamp_ms` | Integer >=0 và <= duration trên video gốc |
| `thumbnail_path` | Relative thumbnail dưới data root |
| `timestamp_source` | `decoder_pts` với pipeline thực; fixture/test có provenance riêng |
| `encoder_id` | None trước embed; identity space sau embed |

Unique `(video_uid,timestamp_ms)` ngăn resume tạo hai frame cùng điểm. Full frame được lưu theo convention `frames/<video_uid>/<keyframe_id>.jpg`; thumbnail UI riêng. Backend URL là `/api/media/thumbnail/<keyframe_id>` và `/api/media/video/<video_uid>`, không có absolute path.

## TextSegment

`segment_id,video_uid,start_ms,end_ms,source,text,normalized_text,metadata_json`. Source chỉ `ocr|asr`; `0<=start_ms<=end_ms<=duration_ms`. Text gốc giữ để hiển thị; DB normalized text NFC+casefold, tokenizer query giữ dấu tiếng Việt. Metadata JSON có OCR boxes/confidence hoặc ASR engine/model/language/logprob. Fixture segments ghi provenance synthetic. FTS5 được cập nhật bằng SQLite insert/update/delete triggers trong cùng transaction.

JSON import tối thiểu:

```json
[
  {"video_uid":"<UID>","source":"asr","start_ms":12000,"end_ms":14300,"text":"Xin chào Việt Nam"}
]
```

`media_item_name` được chấp nhận thay UID khi resolve đúng một video. Segment ID nếu bỏ qua được băm content để import lại không nhân bản. Nếu cung cấp segment ID cũ, upsert cập nhật row đó. Khóa ID phải được quản lý theo provenance của nguồn, không dùng ordinal keyframe làm milliseconds.

## Embedding manifest và index

Embedding vectors là float32 `[rows,dimension]`, L2-normalized. Encoder ID gồm model name, checkpoint SHA256, transform preprocessing hash và dimension thực đo. Checkpoint revision được pin bằng file SHA256, không chỉ tag pretrained có thể thay đổi upstream.

`data/embeddings/manifest.json` ghi encoder identity, model/pretrained, fixture flag, pipeline/schema version, row count, dataset/keyframe fingerprints, chunk paths và checksum vector/mapping. Mapping chunk có ordered IDs, image fingerprints và encoder ID. Build kiểm tra mapping checksum, full row-ID coverage và keyframe encoder IDs.

Index bất biến dưới `index/versions/<version>/manifest.json`:

```json
{
  "schema_version":1,
  "pipeline_version":"pts-shards-v1",
  "version":"<uuid>",
  "encoder_id":"openclip:<sha256>",
  "checkpoint_sha256":"<sha256>",
  "preprocessing_hash":"<sha256>",
  "dimension":512,
  "normalization":"l2",
  "dtype":"float32",
  "dataset_fingerprint":"<sha256>",
  "keyframe_fingerprint":"<sha256>",
  "row_count":72,
  "fixture":false,
  "shards":[
    {"vectors":"vectors-000000.npy","mapping":"mapping-000000.json","rows":72,
     "vectors_sha256":"<sha256>","mapping_sha256":"<sha256>"}
  ]
}
```

Dimension 512 và row count 72 là ví dụ schema; manifest runtime ghi giá trị đo được. Mapping JSON là array IDs theo đúng row order. Vector/cột/normalization/mapping/encoder/checksum đều phải khớp; cùng dimension không đủ chứng minh space. Import vector ngoài chưa có workflow được xác minh, không tự hợp nhất `.npy` không rõ encoder.

`CURRENT` chứa một version basename, được thay bằng `os.replace` sau validation. Loader từ chối path traversal trong CURRENT/shard names, version lệch manifest, dtype/shape sai, norm khác 1, NaN, duplicate IDs hoặc checksum sai. Phiên bản cũ giữ nguyên để process đang query sử dụng snapshot nhất quán.

## Job, history và feedback

`jobs`: job ID, kind, status, progress/total, config JSON, error, created/updated time. Extraction/embed/index/import/OCR/ASR tạo ledger `running` → `completed|failed`. Process kill có thể để `running`; checkpoint chứ không nhãn job quyết định phần đã commit.

`query_history`: query ID, request JSON, result count, elapsed milliseconds, index version và created time. `feedback`: primary key `(session_id,keyframe_id)`, relevant bool, created time. `candidates`: keyframe primary key, note, created time. Index không bị feedback sửa; query dùng bản sao vector và normalize sau Rocchio.

DRES tạo bảng ledger riêng trong `app/dres.py`; xem `docs/DRES_INTEGRATION.md`. Payload secret không thuộc query/media schema. API lỗi schema trả 422; interval invalid bị từ chối trước inference. Duplicate media name được phép lưu metadata nhưng chặn submission chưa có mapping được xác nhận.

## Quy ước timestamp và kiểm tra

Mọi time field API/database là integer milliseconds. Frontend chỉ đổi `timestamp_ms/1000` khi gán `video.currentTime`; không đổi payload DRES thành seconds. `start_time` trong metadata là ngoại lệ rõ ràng theo giây, chỉ dùng để giải thích stream origin.

PTS: `round((pts-origin_pts)*time_base*1000)`. CFR fallback chỉ khi CFR xác nhận và FPS hữu tỷ có đủ: `round(frame_index*1000*fps_den/fps_num)`. Frame 300@25fps → 12000 ms; frame 300@30000/1001fps → 10010 ms. VFR không dùng fallback mean FPS. Sampling count/ordinal không dùng để suy thời gian nộp thi.

Tests `tests/test_pipeline.py` và `tests/test_retrieval.py` kiểm tra chính các invariant trên. Kiểm tra trên fixture giúp chứng minh mapping/công thức, còn seek/timestamp trên video thật cần integration report tương ứng. Không gọi fixture là ground truth được BTC xác nhận.

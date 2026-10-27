# Review backend và hợp đồng API

Review read-only ngày 14/10/2026 trên `app/main.py`, `app/db.py`, `app/schemas.py`, `app/evaluation.py`, `app/media.py` và các đoạn adapter mà route gọi. Không chỉnh source của các module này. Reproduction dùng SQLite/temp dưới `.audit`, TestClient local và vector fixture; không gọi DRES/network/model thật. Các phát hiện được gửi cho chủ sở hữu module để sửa và thêm regression test. Báo cáo ghi trạng thái **tại lúc reproduction**, không tự khẳng định bản sửa sau đó đã pass.

## Phát hiện mức trung bình

| Vị trí tại lúc review | Điều kiện / bằng chứng quan sát | Cách sửa và regression cần có |
|---|---|---|
| `app/main.py:150`, jobs response; `app/pipeline.py:200` lưu raw exception | DB job failed error `Cannot open E:/private/input/video.mp4` được `/api/data` trả nguyên. Lỗi decoder/file thật có thể chứa đường dẫn máy; trái hợp đồng không absolute path trong API | Whitelist job fields cho frontend; error an toàn theo error code/message, sanitize config nếu chứa path; internal ledger vẫn giữ audit cần thiết. Test error có drive path và POSIX path không xuất hiện JSON API |
| `app/evaluation.py:38–45,80` QueryLabels không validate hợp đồng retrieval | POST labels với mode temporal nhưng không query_b trả200/saved, `ground_truth_available=true`; CLI evaluation sau đó tạo SearchRequest và thất bại. Mode không hợp lệ/query dài cũng có thể được publish trước phát hiện | Validate mode, query length và temporal B bằng SearchRequest hoặc shared schema ngay lúc save; test malformed modes/temporal B/blank query không thay nhãn đang có |
| `app/evaluation.py:89–91` dùng staging chung `labels.tmp` | Test hai thread với thứ tự A viết→B viết→A replace→B replace cho A=`saved`, B=`FileNotFoundError`; JSON final chứa query B dù A được báo thành công | Staging filename riêng per request và atomic replace; test hai request đều thành công và final là một payload JSON hoàn chỉnh; không cross-talk staging hoặc unlink file của request khác |
| `app/db.py:98–100` update video duration không kiểm tra metadata con | Video duration10000 + keyframe timestamp9000; upsert duration1000 vẫn thành công. Join trả `{timestamp_ms:9000,duration_ms:1000}`; text_segments có thể tương tự. Guard mới chỉ lúc upsert child | Reject shrink nếu dependent interval/timestamp vượt duration hoặc transactionally invalidate/rewrite child cùng video khi re-extract; test keyframe+text vượt duration và rollback giữ metadata cũ |
| `app/retrieval.py:95–98,104` giữ index khi encoder adapter lỗi | Publish index fixture với encoder_id khác fixture adapter; NumpyShardIndex mở xong, encoder_for_manifest raise; `_index` còn nhưng `_encoder=None`. GET capabilities500 do `_encoder.available` | Set cả index/encoder về None khi load pair không hoàn tất; test malformed fixture identity trả capability false có reason, không crash; gửi owner pipeline/retrieval |
| `app/retrieval.py:98,110,144` raw `_error` đưa vào API | `CURRENT=missingversion`, không manifest: GET capabilities200 nhưng reason chứa absolute `.../.audit/.../index/versions/.../manifest.json`; search cũng có thể expose cùng string qua RuntimeError wrapper | Public unavailable reason generic/mã lỗi, internal audit giữ detail riêng. Test thiếu manifest/shard/malformed record không path leak và vẫn core chạy; gửi owner pipeline/retrieval |
| `app/main.py` static mount sau khi chỉ check `dist.is_dir()` | Chạy targeted API/evaluation/DRES suite trong lúc frontend build: một case create_app thất bại RuntimeError vì `frontend/dist` tồn tại nhưng `dist/assets` chưa có. Quan sát56 pass/1 fail ở `test_invalid_duration_and_labels` | Guard `index.html` và assets directory riêng để core startup không phụ thuộc build chưa đầy đủ. Retest sau frontend build ổn định và có test partial dist |

Các repro ở đây là điều kiện thực có thể xảy ra khi dữ liệu thay đổi hoặc pipeline thất bại; không yêu cầu một deployment public để xảy ra. Không phát hiện critical issue trong phạm vi review.

## Kết quả kiểm tra hợp đồng hiện tại

- Schema mới đã dùng `strict=True` cho duration/timestamp/start/end/gap milliseconds, nên JSON bool/float/string không bị âm thầm đổi thành mốc ms. `tests/test_api.py` đã có hồi quy submission timestamp. Neighbor query parameter là chuỗi HTTP theo bản chất, parsing số nguyên từ querystring là hợp lệ.
- `safe_path` resolve symlink/path và kiểm tra `is_relative_to(root.resolve())`, chặn absolute/`..`; route media chỉ tra path bằng ID nội bộ. Test range normal/suffix/416 và traversal có sẵn. Không quan sát path vào JSON media. Chưa làm OS symlink/junction test riêng trong review.
- SQLite Row context có FK/busy timeout/commit/rollback/final close; parameterized SQL cho input động. Dynamic upsert table/cột chỉ từ model dump nội bộ. Transaction text batch bảo đảm một row invalid không ghi nửa batch; video duration update là ngoại lệ invariant nêu trên.
- `invoke` ánh xạ DuplicateSubmission(ValueError,status_code409)→409 và DresHttpError(RuntimeError,status_code503)→503; PermissionError→403. DRES timeout GET đã được adapter đổi thành DresHttpError503; POST sau reserve giữ unknown. TestClient wrapper duplicate409/timeout503 là regression bổ sung có ích.
- Timestamp audit `query_history/jobs` dùng datetime SQLite strings là chấp nhận được; thời điểm video trong API vẫn ms. Submission ledger trả epoch ms. Không coi chuỗi datetime audit là mốc media.
- API `GET /api/evaluation` chỉ liệt kê report có trên đĩa, không tạo metric giả; tuy nhiên existence của labels chưa chứng minh query hợp lệ nếu validator cho publish như phát hiện trên.

## Metric event-level

Đọc `metrics_at_k`: duplicate frame của một event chỉ hit/gain một lần; vị trí rank vẫn tính cả slot duplicate; Precision denominator K ngay khi ít hơn K kết quả; Recall denominator số event grade>0; MRR hit relevant đầu; nDCG gain `2^grade−1` và ideal thứ hạng grade; AP@K chia tổng relevant, chỉ công bố khi exhaustive. Các lựa chọn này nhất quán với protocol đã mô tả và test event dedup. QueryLabels ngăn event IDs trùng và interval cùng video chồng lấn; boundary shared bị coi overlap vì interval đóng, cần giữ quy ước rõ.

Mức thấp: `metrics_at_k([],[],0)` hiện ZeroDivisionError; caller `evaluate_file` đã chặn K không dương nên chưa route public trigger. Nếu coi hàm public là API thư viện, thêm validation K kiểu int>0 và nhãn duplicate/overlap ngay tại helper hoặc ghi rõ yêu cầu dùng QueryLabels. `grade` chưa strict nên bool/whole-float có thể thành integer relevance; cân nhắc strict để tránh nhãn nhiều mức bị ép kiểu.

Temporal benchmark hiện dùng anchor timestamp A, không có schema ground truth riêng cho pair A/B. Protocol cần nói rõ đánh giá event anchor; không dùng metric này để khẳng định cả thứ tự và semantics của B đã được người gán nhãn kiểm chứng. Nếu đánh giá cả sequence, cần nhãn A/B riêng và matcher kiểm tra cả pair theo cùng video/gap.

Giới hạn review: không vận hành DRES live hoặc model GPU, không đánh giá retrieval quality và không tự gán nhãn video. Bộ DRES riêng hiện45 tests pass; số test toàn dự án và retest sau sửa do root ghi trong báo cáo kiểm thử cuối.

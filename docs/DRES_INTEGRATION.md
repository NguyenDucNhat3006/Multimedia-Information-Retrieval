# DRES v2 và mô phỏng AIC2024

`app/dres.py` thực hiện login khi cần, đọc evaluation và POST một đáp án v2. Mặc định **dry run**, không network khi khởi tạo/preview/dry run. Profile `configs/aic2024_v2.json` phản ánh tài liệu gốc AIC2024; chưa có bằng chứng luật/server năm hiện tại giống 2024.

## Bằng chứng và schema đã khóa

Tài liệu người dùng `references/THONG TIN HE THONG THI VONG CHUNG KET AIC2024.docx` được đọc trực tiếp OOXML gồm đoạn văn và bảng; ảnh phương trình `word/media/image2.png` được trích và nhìn trực tiếp (`docs/reference_audit/image2-white.png`). Toàn bộ DOCX không render được bởi máy hiện tại thiếu LibreOffice; `render_docx.py` báo `soffice.exe was not found on PATH`. Không sửa tài liệu gốc, không tuyên bố đã nhìn toàn bộ layout DOCX.

Snapshot [DRES Client OpenAPI chính thức](https://raw.githubusercontent.com/dres-dev/DRES/master/doc/oas-client.json) lưu tại `references/dres-client-openapi.json`, đọc ngày 14/10/2026. Version quan sát: `2.0.5-SNAPSHOT`; SHA256:

```text
921c8743116a2d58d12505eb48cf6d6f71ff614738627266eaa0c7778375e90e
```

Test kiểm tra hash và enum verdict để upstream thay đổi không âm thầm đổi adapter. Schema do BTC/giảng viên cung cấp có ưu tiên hơn upstream snapshot. [DRES Client Examples](https://github.com/dres-dev/Client-Examples) là nguồn protocol bổ trợ. Không đăng nhập/gửi thử tới `eventretrieval.one` hoặc địa chỉ mạng lịch sử trong baseline/tài liệu.

## Payload và định danh

Backend nhận `keyframe_id`, resolve video gốc và media name không phần đuôi, kiểm tra `timestamp_ms` nguyên từ 0 đến duration. Không suy thời gian từ keyframe ordinal hoặc FPS mặc định. Nếu nhiều video có cùng `media_item_name`, preview/submit bị chặn, cần mapping có nguồn xác minh. KIS point giữ `start=end`, ví dụ:

```json
{"answerSets":[{"answers":[{"mediaItemName":"K01_V001","start":12340,"end":12340}]}]}
```

QA yêu cầu `answer` là **chuỗi ASCII `[0-9]+`**, không ép integer, không trim để che input sai, không thêm `QA-`. `007` vẫn được giữ:

```json
{"answerSets":[{"answers":[{"text":"007-K01_V001-12340"}]}]}
```

`evaluation_id` và `task_key` đều bắt buộc. Live chỉ chấp nhận evaluation có id đúng user chọn và `status="ACTIVE"`; nhiều evaluation ACTIVE không tự chọn cái đầu. Pinned client `currentTask` chỉ mô tả template (`name/taskGroup/taskType/duration`), không có task ID riêng, nên profile yêu cầu người dùng nhập task key riêng mỗi truy vấn/round. **Không dùng evaluation ID thay task key**. Task key chỉ phục vụ chống trùng local, không giả mạo thành server `taskId`; server suy task hiện tại theo protocol. Trước đổi round phải xác nhận task key mới tương ứng task đang chạy trên DRES.

## Bật live trên backend

Chỉ thực hiện sau khi có server hiện tại và tài khoản hợp lệ, đối chiếu schema/luật với BTC/giảng viên. Ví dụ ENV PowerShell trước khởi chạy backend:

```powershell
$env:DRES_BASE_URL = 'https://server-do-btc-cung-cap.example'
$env:DRES_DRY_RUN = 'false'
$env:DRES_SESSION_ID = '<token-chỉ-trên-backend>'
# Hoặc thay DRES_SESSION_ID bằng cặp ENV DRES_USERNAME/DRES_PASSWORD.
```

Không đặt token vào frontend/localStorage hay commit `.env`. Backend không có default server. HTTPS mặc định; chỉ server HTTP được chủ động cấu hình thêm `DRES_ALLOW_INSECURE=true` mới được gọi. Adapter tắt redirect, proxy từ ENV và automatic retry; session/password không ghi ledger. Session nhận từ login chỉ trong bộ nhớ backend. Error response lưu/trả API được redact theo tên field và giá trị credential; HTML/non-JSON không echo. Backend không log URL/query/cookie. Với logging của hệ thống triển khai, cấu hình proxy/DRES access log không ghi query token; adapter không kiểm soát log server bên ngoài.

Endpoints protocol: `POST /api/v2/login` JSON username/password; `GET /api/v2/client/evaluation/list?session=...`; `POST /api/v2/submit/{evaluationId}?session=...` JSON payload. Frontend gọi các route `POST /api/dres/preview`, `POST /api/dres/submit`, `GET /api/dres/evaluations`; không gọi trực tiếp server DRES.

## Ledger và trạng thái

SQLite `submissions` có unique `(namespace,evaluation_id,task_key,payload_hash)`. Payload canonical dùng JSON sorted keys và SHA256. Reservation commit **trước POST**, giữ atomically qua đa tab/process và restart. Task mới được phép gửi cùng payload. Live namespace gồm server fingerprint; dry run namespace riêng từng attempt, mock độc lập. Dry run vẫn ghi lịch sử nhưng không khóa live. Không có automatic xóa/ghi đè unknown hoặc retry submit.

| Trạng thái | Ý nghĩa |
|---|---|
| `dry_run` | Payload được validate, không network, không verdict chính thức |
| `sending` | Reserved trước network; sau crash vẫn giữ để đối chiếu, không cho gửi trùng |
| `accepted_pending` | Accepted nhưng chưa có verdict; `202` luôn pending; `status=true` đơn độc không chứng minh đúng |
| `correct` / `incorrect` | HTTP 200, `status=true` đúng kiểu boolean và field `submission` đúng enum `CORRECT` / `WRONG` của snapshot |
| `rejected` | HTTP 400/401/403/404/412/429 hoặc status=false; không suy rejected thành đáp án sai |
| `unknown` | Timeout, kết nối lỗi sau reserve, 5xx, redirect, non-JSON hoặc response HTTP không rõ; server có thể đã nhận |

`INDETERMINATE` và `UNDECIDABLE` ánh xạ pending. Thiếu `status` hoặc status sai kiểu trở thành unknown; không coi chuỗi `"true"` là boolean. Lịch sử trả response đã redact, HTTP status và `retry_allowed=false`; audit `created_at/updated_at` là integer epoch ms. Khi sending/unknown, đối chiếu lịch sử chính thức trên DRES/BTC; không thử lại mù vì có thể tăng sai/penalty. Lỗi login/evaluation trước reserve không tạo attempt vì chưa POST đáp án. Duplicate trả 409.

## Mock có ground truth và clock

`POST /api/dres/mock/start` tạo task có `video_uid/start_ms/end_ms` do user gán nhãn, task loại `textual_kis`, `video_kis`, `qa`; QA cần chuỗi answer đúng. Response có `started_at_ms` và `time_limit_ms`. Evaluation mock có id `local-mock`, được ghi nhãn mô phỏng và vẫn được liệt kê khi backend bật live; adapter không cho gửi evaluation mock tới server thật. Task key không tái dùng để reset đồng hồ/penalty; muốn round mới dùng key mới. Mock không lấy result score/top-1 làm ground truth.

KIS đúng khi cùng video và timestamp nằm trong cửa sổ nhãn đóng `[start_ms,end_ms]`; QA còn phải khớp chuỗi answer chính xác. Clock injectable trả epoch giây. Đếm sai và đáp án đúng đầu tiên trong transaction `BEGIN IMMEDIATE` để hai tab không đua. Sai task type hoặc quá hạn/đã đúng bị rejected, không tăng sai sau đóng task.

Ảnh công thức DOCX cho:

```text
score = max(0, 50 + 50 × (1 − elapsed_s/time_limit_s) − 10 × wrong_submissions)
```

Chỉ áp dụng khi đúng đầu tiên trong hạn; chưa đúng/ngoài hạn điểm 0. `time_limit_s=240` cho Video KIS; 300 cho Textual KIS/QA. `elapsed_s` là thời gian thực từ bắt đầu task tới đúng đầu tiên, không timestamp video. Clamp ở ngoài toàn biểu thức: t=0 và 6 sai vẫn 40 điểm; không clamp riêng phần 50 điểm chính xác. Điểm mock theo tài liệu 2024, **không phải điểm/verdict server chính thức**.

## Kiểm chứng và giới hạn

`python -m pytest tests/test_dres.py -q` kiểm tra 45 trường hợp hồi quy bằng SQLite file thật và transport tiêm, gồm atomic concurrent submission, restart, timeout no-retry, exact KIS ms, QA `007`, ASCII-only, duplicate media, login/evaluation explicit, HTTP lỗi, response redaction, status-type guard, API audit time ms, pending và clock/formula. Đây là kiểm thử protocol local; live server hiện tại chưa được thử và không có account/ground truth cuộc thi thực.

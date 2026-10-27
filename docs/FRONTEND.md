# Website React

Frontend dùng React 19, TypeScript và Vite, giao diện tiếng Việt với sidebar, vùng tìm kiếm/kết quả và inspector xem video. Các production components nhận dữ liệu từ backend, không có danh sách result giả. Phiên bản dependency được pin trong `frontend/package.json`; `package-lock.json` lưu dependency graph để setup có thể tái hiện.

Khi FastAPI phục vụ `frontend/dist`, API và website dùng cùng origin. Khi chạy Vite dev, proxy chuyển `/api` tới `127.0.0.1:8000`. Frontend chỉ biết ID và URL media; đường dẫn filesystem, OpenCLIP checkpoint và secret DRES do backend quản lý.

## Search và state

`frontend/src/App.tsx` sở hữu query, mode, visual query riêng, filters, loading state, results, candidates và feedback session. Mode gồm visual text, OCR, ASR, hybrid, temporal và image. Boot gọi health/capabilities/data/evaluation/history/candidates; một kênh tùy chọn unavailable không làm mất các kênh còn lại.

Search tạo JSON theo `SearchRequest` hoặc upload multipart khi mode image. Filters video/time/top-k/gap/weights được gửi tới backend và validate lại ở server. `AbortController` hủy request cũ để response chậm không ghi đè query mới. Result cards render trực tiếp result API, mở inspector và lưu ứng viên. Contributions hiển thị điểm xếp hạng cùng nguồn đóng góp; score không được gọi là xác suất đúng.

`frontend/src/api.ts` tập trung fetch, HTTP error/detail parsing, candidate extraction và formatting thời gian. `frontend/src/types.ts` định nghĩa TypeScript contract. UI giữ query gốc cho OCR/ASR và cho nhập `visual_query` tiếng Anh khi dùng CLIP; nó không tạo bản dịch giả.

## Player, filmstrip và feedback

`frontend/src/Inspector.tsx` nhận selected result, sở hữu video ref và neighbors. Effect chờ `loadedmetadata`, sau đó gán `video.currentTime = timestamp_ms / 1000`. Đây là điểm đổi milliseconds sang seconds duy nhất cho seek; text hiển thị và API vẫn dùng milliseconds. Listener và neighbors request được cleanup khi thay selection/unmount.

Filmstrip chỉ lấy frame lân cận cùng video. Nút trước/sau đổi selected result theo timeline. Temporal pair có nút xem B ở timestamp tương ứng. Codec hoặc byte-range lỗi có thông báo riêng, giúp phân biệt lỗi phát media với lỗi search.

Relevant/irrelevant gửi feedback theo session. Session mới được tạo khi mở trang mới; reset xóa feedback của phiên đang dùng. Candidates lưu trong SQLite qua API nên reload còn dữ liệu, độc lập với session feedback. Nút example chỉ bật khi capability image cho phép; server vẫn kiểm tra contest guard.

## Preview và submit DRES

`frontend/src/SubmissionPanel.tsx` có Preview và Submit riêng. Preview gắn với request key; đổi selected keyframe, answer, task key, evaluation hoặc mode làm preview cũ không còn hợp lệ để submit. QA input giữ kiểu text, kiểm tra ASCII digits và bảo toàn `007`.

Evaluation dropdown phân biệt mock/live; live chỉ bật khi backend khai báo khả dụng. Buttons bị disable trong mutation để giảm double click, còn SQLite ledger ở server là lớp chống trùng cuối cùng. UI hiển thị accepted/pending, correct, incorrect, rejected và unknown theo response, không coi HTTP thành công là đáp án đúng.

`MockTaskForm` nằm trong cùng file, nhận video/interval/answer do người dùng kiểm tra và khai báo. Nó không lấy rank 1 làm ground truth. Secret DRES giữ ở backend environment; components không lưu token trong localStorage hoặc query URL.

## Data, evaluation và history

`frontend/src/Pages.tsx::DataPage` hiển thị counts, jobs, channel readiness và index version từ API. `EvaluationPage` hiển thị reports offline đã chạy, provenance, metrics và N/A khi judgments chưa đủ. `HistoryPage` hiển thị query/submission ledger; có thể dùng lại query.

`frontend/src/LabelEditor.tsx` hỗ trợ nhập/sửa JSON labels, import/export và save qua API. Người gán nhãn phải xem video gốc, khai báo event interval/grade, provenance và split. Tool không tự suy relevance từ ranking. Chưa có labels/report thì website hướng dẫn chuẩn bị nhãn, không tạo số benchmark.

## Khả dụng và accessibility

UI có boot/loading/skeleton/empty/error/partial states và thao tác thử kết nối lại. Mode thiếu capability bị disable kèm giải thích. Layout responsive, controls có labels/ARIA, focus bằng keyboard; `Ctrl+K` focus Search và `Escape` đóng inspector. Object URL ảnh upload được revoke khi đổi file hoặc unmount.

Video KIS contest chặn image ở UI và backend, gồm upload lẫn example. Đây là profile theo tài liệu AIC2024; luật thi hiện tại phải được xác nhận riêng. Các trạng thái dependency/model/data chưa có được hiển thị rõ qua capability thay vì giả rằng mọi adapter đã chạy.

## Chạy và kiểm tra

```powershell
Set-Location 'D:\mutimedia-information-retrival\frontend'
npm.cmd ci
npm.cmd run typecheck
npm.cmd run lint
npm.cmd test
npm.cmd run build
# Backend chạy tại port 8000 trước khi mở Vite dev:
npm.cmd run dev
```

Component tests kiểm tra cancellation, seek/listener cleanup, preview invalidation, QA validation và các state. Browser QA chạy website với media thật ở port 8000 và fixture riêng khi cần; report/screenshots dưới `docs/reports` ghi kết quả từng lần chạy. Xem `docs/VALIDATION.md` để biết checks nào đã pass và giới hạn thực tế, thay vì suy từ việc build thành công rằng toàn bộ luồng media/DRES đã hoạt động.

Tests giao diện và fixture chứng minh hành vi/contract trên input kiểm chứng được. Chúng không là benchmark semantic của OpenCLIP hoặc relevance toàn kho video.

# Frame / CS336 frontend

Giao diện React + TypeScript + Vite tiếng Việt, chạy local cùng FastAPI. API cùng origin theo `docs/API_CONTRACT.md`; không có dataset, ảnh kết quả, metric hoặc token DRES được nhúng trong bundle.

```powershell
cd frontend
npm ci
npm run dev
```

Vite dev dùng `http://127.0.0.1:5173` và proxy `/api` đến `http://127.0.0.1:8000`. Bản production tạo bằng `npm run build`; FastAPI phục vụ `frontend/dist` cùng API. Phiên bản dependency cố định trong `package.json` và `package-lock.json`.

```powershell
npm run typecheck
npm run lint
npm run test
npm run build
```

Chín test tự động kiểm tra thời gian milliseconds, ASCII QA / `007`, lỗi API, AbortSignal, hủy và bỏ qua query cũ, preview bắt buộc trước submit, preview hết hiệu lực sau đổi task, seek sau metadata và cleanup listener.

Các thành phần chính:

- `src/App.tsx`: điều phối capabilities, các kênh truy vấn, bộ lọc, feedback, ứng viên và kết nối.
- `src/Inspector.tsx`: player gốc, seek `timestamp_ms / 1000`, filmstrip, chứng cứ và thao tác liên quan.
- `src/SubmissionPanel.tsx`: chọn evaluation theo namespace, task key, QA chuỗi số, preview và submit riêng, khai báo ground truth mock.
- `src/Pages.tsx`, `src/LabelEditor.tsx`: dữ liệu/jobs, lịch sử, report thực và soạn/import/export/lưu nhãn do người dùng kiểm tra.
- `src/api.ts`: API JSON, lỗi hữu ích, định dạng thời gian và ID phiên feedback không nhạy cảm trong sessionStorage. Token DRES chỉ ở backend.

Nút ảnh và query-by-example dựa trên capability, đồng thời bị chặn trong Video KIS contest. Kênh chưa có dữ liệu hiện nguyên nhân backend trả về. Điểm xếp hạng không được biểu diễn như xác suất. Ứng viên lưu và khung hình metadata không tự có điểm truy vấn. Giao diện có focus, skip link, Ctrl+K, Escape, lỗi/loading/empty, lazy thumbnails và responsive.

UI lưu nhãn qua `POST /api/evaluation/labels`. Nhãn được kiểm tra schema/duration phía server; đánh giá chạy bằng CLI riêng:

```powershell
python -m app.cli evaluate cs336-human-labels.json --top-k 10 --output data/evaluation/report.json
```

Không công bố mAP khi judgments chưa đầy đủ. Ground truth mock nhập thủ công, tách khỏi nhãn offline và feedback.

QA trình duyệt dùng Chrome hoặc Edge đã có sẵn, không tự tải browser:

```powershell
# Terminal root 1: python -m app.cli serve --port 8000 (dữ liệu local thật)
# Terminal root 2: python -m app.cli --data-root data-fixture-test serve --port 8001
node qa/browser.mjs
```

Fixture phải được tạo bằng lệnh CLI fixture trong data root riêng trước đó. `CS336_BASE_URL`, `CS336_FIXTURE_URL` và `CS336_BROWSER_PATH` có thể cấu hình. `CS336_SKIP_REAL=true` chỉ chạy luồng fixture. Script chạy tìm kiếm/seek/playback, feedback, ứng viên qua reload, preview+dry run QA, navigation, mobile overflow và mock có ground truth tổng hợp đã khai báo. Script không gửi live DRES, không tạo nhãn relevance trên dữ liệu thật. Ảnh và report tại `docs/reports/ui-*`; audit dependency tại `qa/dependency-audit.json`.

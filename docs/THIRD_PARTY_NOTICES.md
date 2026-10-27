# Nguồn và ghi công

Ứng dụng app/ và frontend/src được viết mới cho workspace này. Baseline [Hungquan5/retrievalBaseline](https://github.com/Hungquan5/retrievalBaseline) được dùng làm đối chiếu ý tưởng và audit tại SHA trong BASELINE_AUDIT. Không sao chép nguồn baseline vào ứng dụng; repo audit nằm .audit/ bị ignore. Chưa thấy LICENSE/COPYING tại SHA đã đọc, không tự gán giấy phép hoặc công khai lại toàn repo.

Model/code được cài qua dependency: [OpenCLIP](https://github.com/mlfoundations/open_clip); decoder [PyAV](https://github.com/PyAV-Org/PyAV); tùy chọn [FAISS và cosine](https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances), [pytesseract](https://github.com/madmaze/pytesseract), [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Giấy phép code và model weights phải đọc từ từng nguồn/phân phối khi tái sử dụng/publish; chưa gán một giấy phép chung cho chúng trong workspace.

[DRES](https://github.com/dres-dev/DRES) và [Client Examples](https://github.com/dres-dev/Client-Examples) cung cấp protocol đối chiếu; snapshot schema được giữ cùng hash. Luật AIC2024 và đề cương CS336 là tài liệu người dùng cung cấp, không khẳng định là quy định thi hiện tại. Hai input local do người dùng cung cấp; file gốc được giữ nguyên và không tải lên hosting công khai.

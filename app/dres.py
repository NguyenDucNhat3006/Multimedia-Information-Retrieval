"""Adapter DRES v2: payload có thời gian ms, ledger SQLite và chấm luyện tập local.

Không có network call lúc import/khởi tạo. Profile AIC2024 là luật lịch sử;
chỉ ENV backend mới bật live và chọn server. Không suy ground truth từ thứ hạng.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import socket
import sqlite3
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
MOCK_EVALUATION_ID = "local-mock"
LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions(
attempt_id TEXT PRIMARY KEY,namespace TEXT NOT NULL,mode TEXT NOT NULL,
evaluation_id TEXT NOT NULL,task_key TEXT NOT NULL,payload_hash TEXT NOT NULL,
payload_json TEXT NOT NULL,status TEXT NOT NULL,response_json TEXT,
created_at REAL NOT NULL,updated_at REAL NOT NULL,
UNIQUE(namespace,evaluation_id,task_key,payload_hash));
CREATE INDEX IF NOT EXISTS submission_recent ON submissions(created_at DESC);
CREATE TABLE IF NOT EXISTS mock_tasks(
task_key TEXT PRIMARY KEY,task_type TEXT NOT NULL,video_uid TEXT NOT NULL,
start_ms INTEGER NOT NULL,end_ms INTEGER NOT NULL,answer TEXT,
started_at REAL NOT NULL,time_limit_s INTEGER NOT NULL,
wrong_submissions INTEGER NOT NULL DEFAULT 0,first_correct_at REAL,
score REAL NOT NULL DEFAULT 0);
"""


class DuplicateSubmission(ValueError):
    """Cùng server/evaluation/task/payload đã được reserve; API trả HTTP 409."""

    status_code = 409


class DresHttpError(RuntimeError):
    """Lỗi adapter đã loại bỏ URL/token và nội dung response không tin cậy."""

    status_code = 503


@dataclass(frozen=True)
class DresResponse:
    """HTTP status và JSON/text của transport; không giữ URL hoặc header bí mật."""

    status_code: int
    body: object


class _NoRedirect(HTTPRedirectHandler):
    """Không chuyển credentials/session sang host khác khi server redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Giữ redirect như HTTP error để không vô tình thực hiện POST lần hai."""
        return None


def practice_score(elapsed_s: float, limit_s: float, wrong_submissions: int,
                   correct: bool = True) -> float:
    """Tính công thức từ ảnh DOCX: clamp ngoài tổng; thời gian là giây task.

    Args: elapsed_s từ start task đến đúng đầu tiên; limit_s > 0; số sai >= 0.
    Returns: 0 nếu không đúng/ngoài hạn; ngược lại điểm từ 0 đến 100.
    Raises: ValueError nếu input không hữu hạn hoặc số sai không nguyên hợp lệ.
    """
    if (not math.isfinite(elapsed_s) or not math.isfinite(limit_s) or limit_s <= 0
            or type(wrong_submissions) is not int or wrong_submissions < 0):
        raise ValueError("Tham số điểm luyện tập không hợp lệ")
    if not correct or not 0 <= elapsed_s <= limit_s:
        return 0.0
    return max(0.0, 50.0 + 50.0 * (1.0 - elapsed_s / limit_s) - 10 * wrong_submissions)


class DresService:
    """Dịch vụ DRES nhận Database/Settings; clock và transport tiêm cho kiểm thử.

    Clock trả epoch giây để task mock vẫn có nghĩa sau restart. Transport nhận
    (method, url, params, body, timeout) và trả DresResponse; mặc định urllib
    không log request, không proxy ENV, không redirect hoặc tự retry POST.
    """

    def __init__(self, db, settings, *, clock: Callable[[], float] | None = None,
                 transport: Callable | None = None, environ: dict | None = None):
        """Tạo migration ledger bền vững; không tải schema/model hoặc gọi DRES."""
        self.db, self.settings = db, settings
        self.clock = clock or time.time
        self.environ = dict(os.environ if environ is None else environ)
        self.profile = json.loads((ROOT / "configs/aic2024_v2.json").read_text(encoding="utf-8"))
        self.dry_run = self.environ.get("DRES_DRY_RUN", "true").lower() != "false"
        self.base_url = self.environ.get("DRES_BASE_URL", "").rstrip("/")
        self._session = self.environ.get("DRES_SESSION_ID", "")
        self._transport = transport or self._urllib_transport
        with self.db.connection() as conn:
            conn.executescript(LEDGER_SCHEMA)

    @staticmethod
    def _urllib_transport(method, url, params, body, timeout) -> DresResponse:
        """Một request duy nhất; không log URL chứa session kể cả khi HTTP lỗi."""
        full_url = url + ("?" + urlencode(params) if params else "")
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = Request(full_url, data=data, method=method,
                      headers={"Accept": "application/json", "Content-Type": "application/json"})
        # Tắt proxy ENV tránh token query trong proxy access log không kiểm soát.
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(req, timeout=timeout) as response:
                status = response.status
                raw = response.read(1024 * 1024 + 1)
        except HTTPError as error:
            status = error.code
            raw = error.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return DresResponse(status, None)
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            decoded = None  # Không echo HTML/error body có thể chứa secret.
        return DresResponse(status, decoded)

    def _require_live(self):
        """Live chỉ bật qua ENV; URL không nhận từ frontend và không có userinfo."""
        if self.dry_run:
            raise PermissionError("Live bị tắt: cấu hình backend DRES_DRY_RUN=false để bật")
        parsed = urlsplit(self.base_url)
        if (not parsed.hostname or parsed.username or parsed.password or parsed.query
                or parsed.fragment or parsed.scheme not in {"http", "https"}):
            raise ValueError("DRES_BASE_URL backend không hợp lệ")
        if parsed.scheme != "https" and self.environ.get("DRES_ALLOW_INSECURE", "false").lower() != "true":
            raise PermissionError("Server HTTP cần DRES_ALLOW_INSECURE=true trong backend")

    def _request(self, method, path, *, authenticated=True, body=None) -> DresResponse:
        """Gọi transport có timeout; giữ lỗi network tổng quát, không URL/secret."""
        self._require_live()
        params = {"session": self._get_session()} if authenticated else {}
        try:
            result = self._transport(method, self.base_url + path, params, body, 15)
            if not isinstance(result, DresResponse):
                raise DresHttpError("Transport DRES trả response không hợp lệ")
            return result
        except (TimeoutError, socket.timeout):
            raise DresHttpError("DRES timeout; không tự gửi lại") from None
        except (URLError, OSError):
            raise DresHttpError("Không thể kết nối DRES; không tự gửi lại") from None
        except DresHttpError:
            raise
        except Exception:
            raise DresHttpError("DRES request thất bại; response/credentials đã được ẩn") from None

    def _get_session(self) -> str:
        """Dùng token ENV hoặc login khi cần; session chỉ ở bộ nhớ backend."""
        if self._session:
            return self._session
        username = self.environ.get("DRES_USERNAME", "")
        password = self.environ.get("DRES_PASSWORD", "")
        if not username or not password:
            raise PermissionError("Backend thiếu DRES_SESSION_ID hoặc DRES_USERNAME/DRES_PASSWORD")
        response = self._request("POST", self.profile["login_path"], authenticated=False,
                                 body={"username": username, "password": password})
        if response.status_code != 200 or not isinstance(response.body, dict):
            raise DresHttpError(f"DRES login thất bại (HTTP {response.status_code})")
        session = response.body.get("sessionId")
        if not isinstance(session, str) or not session:
            raise DresHttpError("DRES login thiếu sessionId theo schema đã khóa")
        self._session = session
        return session

    def _redact(self, value):
        """Loại trường credential và chuỗi secret trước ghi ledger/trả API."""
        if isinstance(value, dict):
            return {str(k): ("[REDACTED]" if re.search(r"session|token|password|cookie|authorization|secret", str(k), re.I)
                             else self._redact(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [self._redact(v) for v in value[:100]]
        if isinstance(value, str):
            value = value[:4096]
            for secret in [self._session, self.environ.get("DRES_PASSWORD", ""), self.environ.get("DRES_SESSION_ID", "")]:
                if secret:
                    value = value.replace(secret, "[REDACTED]")
            value = re.sub(r"(?i)(session|token|password|cookie|authorization)=([^\s&]+)", r"\1=[REDACTED]", value)
            return value
        if isinstance(value, float) and not math.isfinite(value):
            return "[REDACTED]"
        return value if value is None or isinstance(value, (bool, int, float)) else "[REDACTED]"

    def evaluations(self) -> dict:
        """Trả danh sách evaluation; khi mặc định dry run hoàn toàn không network.

        Local-mock được ghi nhãn mô phỏng. Live trả id/name/status theo schema;
        người dùng phải chọn rõ một evaluation ACTIVE, không tự chọn phần tử đầu.
        """
        local_evaluation = {"id": MOCK_EVALUATION_ID, "name": "Luyện tập local (mô phỏng AIC2024)",
                            "status": "ACTIVE", "mock": True}
        if self.dry_run:
            return {"evaluations": [local_evaluation],
                    "mode": "dry_run", "profile": self.profile["name"]}
        response = self._request("GET", self.profile["evaluations_path"])
        if response.status_code != 200 or not isinstance(response.body, list):
            raise DresHttpError(f"Không đọc được evaluations DRES (HTTP {response.status_code})")
        evaluations = [{k: self._redact(row.get(k)) for k in ("id", "name", "status", "type")}
                       for row in response.body if isinstance(row, dict)]
        return {"evaluations": evaluations + [local_evaluation], "mode": "live", "profile": self.profile["name"]}

    @staticmethod
    def _identifier(request, field):
        """Định danh phải được cung cấp rõ; không dùng evaluation thay task key."""
        value = request.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError(f"Thiếu hoặc không hợp lệ: {field}")
        return value.strip()

    def _prepare(self, request: dict) -> tuple[dict, dict]:
        """Resolve media từ keyframe, kiểm tra ms/duration/QA và name xung đột."""
        mode = request.get("mode", "dry_run")
        if mode not in {"dry_run", "mock", "live"}:
            raise ValueError("mode phải là dry_run, mock hoặc live")
        evaluation_id = self._identifier(request, "evaluation_id")
        task_key = self._identifier(request, "task_key")
        task_type = request.get("task_type", "KIS")
        if task_type not in {"KIS", "QA"}:
            raise ValueError("task_type phải là KIS hoặc QA")
        keyframe_id = self._identifier(request, "keyframe_id")
        item = self.db.one("SELECT k.*,v.media_item_name,v.duration_ms,v.source_batch FROM keyframes k "
                           "JOIN videos v ON v.video_uid=k.video_uid WHERE k.keyframe_id=?", (keyframe_id,))
        if item is None:
            raise ValueError("Keyframe không tồn tại")
        ms = request.get("timestamp_ms", item["timestamp_ms"])
        if ms is None:
            ms = item["timestamp_ms"]
        if type(ms) is not int or not 0 <= ms <= item["duration_ms"]:
            raise ValueError("timestamp_ms phải là số nguyên trong duration video gốc")
        name = item["media_item_name"]
        if not isinstance(name, str) or not name or any(c in name for c in "\\/\r\n"):
            raise ValueError("media_item_name không hợp lệ")
        duplicate = self.db.one("SELECT COUNT(*) AS n FROM videos WHERE media_item_name=?", (name,))
        if duplicate["n"] != 1:
            raise ValueError("Trùng media_item_name giữa video; cần mapping đã kiểm chứng trước khi nộp")
        answer = request.get("answer")
        if task_type == "QA":
            if not isinstance(answer, str) or re.fullmatch(self.profile["qa_answer_pattern"], answer) is None:
                raise ValueError("QA yêu cầu chuỗi ASCII 0–9; giữ nguyên các số 0 đầu")
            payload_answer = {"text": self.profile["qa_format"].format(answer=answer, media_item_name=name, timestamp_ms=ms)}
        else:
            payload_answer = {"mediaItemName": name, "start": ms, "end": ms}
        if mode == "live":
            self._require_live()
            source = str(item["timestamp_source"]).casefold()
            if not source or any(tag in source for tag in ("unknown", "unverified", "fallback", "fixture")) or "fixture" in str(item["source_batch"]).casefold():
                raise ValueError("Live cần timestamp/data thật đã kiểm chứng; không nộp fixture hoặc FPS fallback")
        context = {"mode": mode, "evaluation_id": evaluation_id, "task_key": task_key,
                   "task_type": task_type, "answer": answer, "timestamp_ms": ms, "video_uid": item["video_uid"]}
        return {"answerSets": [{"answers": [payload_answer]}]}, context

    def preview(self, request: dict) -> dict:
        """Preview payload point KIS hoặc QA; không network và không reserve ledger."""
        payload, context = self._prepare(request)
        return {"payload": payload, "mode": context["mode"], "profile": self.profile["name"],
                "warnings": ["Profile luật lịch sử AIC2024; cần đối chiếu BTC/giảng viên trước live.",
                             "task_key phải định danh riêng từng truy vấn/round; schema client không cung cấp taskId."]}

    def _reserve(self, payload, context) -> str:
        """Unique SQLite giữ quyền gửi trước POST; hai tab/process chỉ một thắng."""
        attempt = uuid4().hex
        mode = context["mode"]
        server_key = sha256((self.base_url + "|" + self.environ.get("DRES_USERNAME", "")).encode()).hexdigest()[:20]
        namespace = f"live:{server_key}" if mode == "live" else "mock"
        if mode == "dry_run":
            namespace = "dry_run:" + attempt
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        try:
            with self.db.connection() as conn:
                conn.execute("INSERT INTO submissions(attempt_id,namespace,mode,evaluation_id,task_key,payload_hash,"
                             "payload_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                             (attempt, namespace, mode, context["evaluation_id"], context["task_key"],
                              sha256(canonical.encode()).hexdigest(), canonical, "sending", self.clock(), self.clock()))
        except sqlite3.IntegrityError:
            raise DuplicateSubmission("Payload đã gửi/đang gửi trong task này; xem lịch sử, không tự retry") from None
        return attempt

    def _finish(self, attempt_id, status, response, *, conn=None):
        """Ghi status/response đã redact; có thể nằm cùng transaction chấm mock."""
        cleaned = self._redact(response)
        sql = "UPDATE submissions SET status=?,response_json=?,updated_at=? WHERE attempt_id=?"
        params = (status, json.dumps(cleaned, ensure_ascii=False, sort_keys=True), self.clock(), attempt_id)
        if conn is None:
            self.db.execute(sql, params)
        else:
            conn.execute(sql, params)
        return cleaned

    def _parse_verdict(self, response: DresResponse) -> str:
        """Chỉ field submission enum đã khóa chứng minh verdict; 202 luôn pending."""
        if response.status_code >= 500 or 300 <= response.status_code < 400:
            return "unknown"
        if response.status_code in {400, 401, 403, 404, 412, 429}:
            return "rejected"
        if response.status_code not in {200, 202}:
            return "unknown"
        if not isinstance(response.body, dict):
            return "unknown"
        if type(response.body.get("status")) is not bool:
            return "unknown"
        if response.body["status"] is False:
            return "rejected"
        if response.status_code == 202:
            return "accepted_pending"
        verdict = response.body.get(self.profile["verdict_field"])
        return self.profile["verdicts"].get(verdict, "accepted_pending") if isinstance(verdict, str) else "accepted_pending"

    def submit(self, request: dict) -> dict:
        """Nộp một lần với ledger; dry run không network/khóa live, timeout unknown.

        Returns: attempt_id/status/payload và response đã redact. HTTP thành công
        không tự coi đúng. Raises: ValueError, PermissionError, DuplicateSubmission,
        DresHttpError trước POST; lỗi sau reserve được lưu unknown để đối chiếu.
        """
        payload, context = self._prepare(request)
        if context["mode"] == "live":
            active = self.evaluations()["evaluations"]
            selected = next((row for row in active if row.get("id") == context["evaluation_id"]), None)
            if selected is None or selected.get("status") != "ACTIVE" or selected.get("mock"):
                raise ValueError("Phải chọn rõ evaluation ACTIVE; không tự chọn evaluation khác")
        if context["mode"] == "mock":
            if context["evaluation_id"] != MOCK_EVALUATION_ID:
                raise ValueError("Mock phải chọn evaluation local-mock")
            if not self.db.one("SELECT task_key FROM mock_tasks WHERE task_key=?", (context["task_key"],)):
                raise ValueError("Task mock chưa có ground truth; tạo task trước")
        attempt = self._reserve(payload, context)
        if context["mode"] == "dry_run":
            status, response = "dry_run", {"network_called": False, "official_verdict": False}
            response = self._finish(attempt, status, response)
        elif context["mode"] == "mock":
            status, response = self._score_mock(attempt, context)
        else:
            try:
                result = self._request("POST", self.profile["submit_path"].format(
                    evaluation_id=quote(context["evaluation_id"], safe="")), body=payload)
                status = self._parse_verdict(result)
                response = {"http_status": result.status_code, "body": result.body,
                            "retry_allowed": False}
            except Exception:
                # Không expose exception của transport: URL thường chứa session.
                status, response = "unknown", {"description": "Không xác định server đã nhận hay chưa; đối chiếu lịch sử DRES.",
                                              "retry_allowed": False}
            response = self._finish(attempt, status, response)
        return {"attempt_id": attempt, "status": status, "payload": payload, "response": response}

    def start_mock(self, request: dict) -> dict:
        """Tạo ground truth local do người dùng khai báo; task mới cần key mới.

        Args: video_uid, start_ms/end_ms nguyên trong video, task_type, QA answer.
        Returns: giới hạn/start task và nhãn mô phỏng; không sửa task đã bắt đầu.
        """
        key = self._identifier(request, "task_key")
        video_uid = self._identifier(request, "video_uid")
        kind = request.get("task_type")
        if kind not in self.profile["task_limits_seconds"]:
            raise ValueError("Mock task_type phải là textual_kis, video_kis hoặc qa")
        video = self.db.one("SELECT duration_ms FROM videos WHERE video_uid=?", (video_uid,))
        start, end = request.get("start_ms"), request.get("end_ms")
        if (video is None or type(start) is not int or type(end) is not int
                or not 0 <= start <= end <= video["duration_ms"]):
            raise ValueError("Ground truth phải là khoảng ms hợp lệ trong video có thật trong metadata")
        answer = request.get("answer")
        if kind == "qa" and (not isinstance(answer, str) or re.fullmatch(r"[0-9]+", answer) is None):
            raise ValueError("Ground truth QA yêu cầu chuỗi ASCII 0–9")
        now, limit = self.clock(), self.profile["task_limits_seconds"][kind]
        try:
            self.db.execute("INSERT INTO mock_tasks(task_key,task_type,video_uid,start_ms,end_ms,answer,started_at,time_limit_s) "
                            "VALUES(?,?,?,?,?,?,?,?)", (key, kind, video_uid, start, end, answer, now, limit))
        except sqlite3.IntegrityError:
            raise DuplicateSubmission("Task mock đã bắt đầu; dùng task_key mới cho round mới") from None
        return {"task_key": key, "evaluation_id": MOCK_EVALUATION_ID, "task_type": kind,
                "started_at_ms": round(now * 1000), "time_limit_ms": limit * 1000,
                "mock": True, "ground_truth_declared": True}

    def _score_mock(self, attempt, context):
        """Chấm/cập nhật sai/đúng đầu tiên trong BEGIN IMMEDIATE để hai tab không đua."""
        with self.db.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = dict(conn.execute("SELECT * FROM mock_tasks WHERE task_key=?", (context["task_key"],)).fetchone())
            now = self.clock()
            elapsed = now - task["started_at"]
            closed = task["first_correct_at"] is not None or not 0 <= elapsed <= task["time_limit_s"]
            expected_type = "QA" if task["task_type"] == "qa" else "KIS"
            if context["task_type"] != expected_type or closed:
                status = "rejected"
            elif (context["video_uid"] == task["video_uid"] and task["start_ms"] <= context["timestamp_ms"] <= task["end_ms"]
                  and (expected_type != "QA" or context["answer"] == task["answer"])):
                status = "correct"
                task["score"] = practice_score(elapsed, task["time_limit_s"], task["wrong_submissions"])
                conn.execute("UPDATE mock_tasks SET first_correct_at=?,score=? WHERE task_key=?", (now, task["score"], task["task_key"]))
            else:
                status = "incorrect"
                task["wrong_submissions"] += 1
                conn.execute("UPDATE mock_tasks SET wrong_submissions=? WHERE task_key=?", (task["wrong_submissions"], task["task_key"]))
            response = {"mock": True, "official_verdict": False, "score": task["score"],
                        "wrong_submissions": task["wrong_submissions"], "elapsed_s": elapsed,
                        "time_limit_s": task["time_limit_s"]}
            self._finish(attempt, status, response, conn=conn)
        return status, response

    def history(self) -> list[dict]:
        """Trả 200 attempt gần nhất, không secret/path; sending cũ cần đối chiếu.

        Không tự đổi hoặc xóa reserve: request đang chạy ở process khác vẫn có
        thể hoàn tất. UI xem sending/unknown để đối chiếu server trước hành động.
        """
        records = self.db.rows("SELECT attempt_id,mode,evaluation_id,task_key,payload_json,status,response_json,"
                               "created_at,updated_at FROM submissions ORDER BY created_at DESC LIMIT 200")
        for row in records:
            # Audit clock lưu giây epoch bên trong; API trả milliseconds nhất quán.
            row["created_at"] = round(row["created_at"] * 1000)
            row["updated_at"] = round(row["updated_at"] * 1000)
            row["payload"] = json.loads(row.pop("payload_json"))
            raw = row.pop("response_json")
            row["response"] = self._redact(json.loads(raw)) if raw else None
        return records

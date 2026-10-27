"""Hồi quy DRES: không đổi sai ms/QA, gửi trùng đa tab, timeout và công thức thật."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from app.dres import (DresService, DresResponse, DuplicateSubmission, DresHttpError,
                      MOCK_EVALUATION_ID, practice_score)


class TestDatabase:
    """SQLite file thật kiểm tra transaction/đa process; không cần model inference."""

    __test__ = False

    def __init__(self, path):
        self.path = path
        with self.connection() as conn:
            conn.executescript("""
            CREATE TABLE videos(video_uid TEXT PRIMARY KEY,media_item_name TEXT,source_batch TEXT,duration_ms INTEGER);
            CREATE TABLE keyframes(keyframe_id TEXT PRIMARY KEY,video_uid TEXT,timestamp_ms INTEGER,timestamp_source TEXT);
            INSERT INTO videos VALUES('v1','K01_V001','batch1',20000);
            INSERT INTO videos VALUES('v2','K02_V001','batch2',20000);
            INSERT INTO keyframes VALUES('k1','v1',12340,'decoder_pts');
            INSERT INTO keyframes VALUES('k2','v2',9876,'decoder_pts');
            """)

    @contextmanager
    def connection(self):
        """Mỗi call connection riêng, commit/rollback chuẩn và timeout SQLite."""
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def rows(self, sql, params=()):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        rows = self.rows(sql, params)
        return rows[0] if rows else None

    def execute(self, sql, params=()):
        with self.connection() as conn:
            return conn.execute(sql, params).lastrowid


@pytest.fixture
def db(tmp_path):
    """Metadata tối thiểu, timestamp có ms lẻ để bắt phép làm tròn không hợp lệ."""
    return TestDatabase(tmp_path / "ledger.sqlite3")


def request(**overrides):
    """Mặc định một round explicit, không lấy evaluation làm task ID."""
    return {"keyframe_id": "k1", "evaluation_id": "eval-1", "task_key": "round-1",
            "task_type": "KIS", "mode": "dry_run", **overrides}


def service(db, **kwargs):
    """Không ENV thật hoặc network ngoài; live tests chỉ dùng transport tiêm."""
    kwargs.setdefault("environ", {})
    return DresService(db, SimpleNamespace(), **kwargs)


def live_service(db, response=None, *, clock=None, fail=False):
    """Server cục bộ giả protocol giữ call log để đếm POST duy nhất."""
    calls = []

    def transport(method, url, params, body, timeout):
        calls.append((method, url, params, body))
        if url.endswith("/list"):
            return DresResponse(200, [{"id": "eval-1", "name": "Visible evaluation", "status": "ACTIVE"}])
        if fail:
            raise TimeoutError("request secret-token session=secret-token")
        return response or DresResponse(200, {"status": True, "submission": "CORRECT"})

    result = service(db, environ={"DRES_DRY_RUN": "false", "DRES_BASE_URL": "https://dres.test",
                                 "DRES_SESSION_ID": "secret-token"}, transport=transport, clock=clock)
    return result, calls


def test_payload_milliseconds_and_qa_leading_zeros(db):
    """Ngăn fallback 25FPS, round 2 chữ số và tiền tố QA sai của demo baseline."""
    dres = service(db)
    kis = dres.preview(request())["payload"]["answerSets"][0]["answers"][0]
    assert kis == {"mediaItemName": "K01_V001", "start": 12340, "end": 12340}
    qa = dres.preview(request(task_type="QA", answer="007", timestamp_ms=12341))["payload"]
    assert qa == {"answerSets": [{"answers": [{"text": "007-K01_V001-12341"}]}]}


@pytest.mark.parametrize("answer", ["", "１２", "١٢", "QA-007", "7.0", " 007 ", 7])
def test_qa_rejects_non_ascii_digits(db, answer):
    """Upstream text rộng hơn luật AIC2024; Unicode digits cũng phải bị chặn."""
    with pytest.raises(ValueError, match="ASCII"):
        service(db).preview(request(task_type="QA", answer=answer))


@pytest.mark.parametrize("timestamp", [-1, 20001, 12340.0, float("nan"), True, "12340"])
def test_strict_integer_milliseconds(db, timestamp):
    with pytest.raises(ValueError, match="timestamp_ms"):
        service(db).preview(request(timestamp_ms=timestamp))


def test_duplicate_media_names_block_submission(db):
    """UID khác batch không được thay media name BTC để lách xung đột."""
    db.execute("INSERT INTO videos VALUES('v3','K01_V001','batch2',20000)")
    with pytest.raises(ValueError, match="Trùng"):
        service(db).submit(request())
    assert not service(db).history()


def test_default_no_network_and_dry_run_does_not_lock_live(db):
    """Dry run có thể lặp nhiều lần rồi live nộp đúng một lần cùng payload."""
    def forbidden(*args):
        pytest.fail("Dry run đã gọi network")

    dres = service(db, transport=forbidden)
    assert dres.evaluations()["mode"] == "dry_run"
    assert dres.submit(request())["status"] == "dry_run"
    assert dres.submit(request())["status"] == "dry_run"
    with pytest.raises(PermissionError):
        dres.submit(request(mode="live"))
    live, calls = live_service(db)
    assert live.submit(request(mode="live"))["status"] == "correct"
    assert len([c for c in calls if c[0] == "POST"]) == 1


def test_atomic_duplicate_reservation_and_restart(db):
    """Hai service/tab chạy thật đồng thời; unique SQLite giữ một quyền POST."""
    first, first_calls = live_service(db)
    second, second_calls = live_service(db)

    def attempt(dres):
        try:
            return dres.submit(request(mode="live"))["status"]
        except DuplicateSubmission:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [first, second]))
    assert sorted(results) == ["correct", "duplicate"]
    assert len([c for c in first_calls + second_calls if c[0] == "POST"]) == 1
    restarted, _ = live_service(db)
    with pytest.raises(DuplicateSubmission):
        restarted.submit(request(mode="live"))
    assert restarted.submit(request(mode="live", task_key="round-2"))["status"] == "correct"


def test_timeout_unknown_preserves_reservation_and_redacts(db):
    """Server có thể nhận trước timeout; nhấn retry không được nộp/phạt lần hai."""
    dres, calls = live_service(db, fail=True)
    result = dres.submit(request(mode="live"))
    assert result["status"] == "unknown"
    assert "secret-token" not in json.dumps(result)
    with pytest.raises(DuplicateSubmission):
        dres.submit(request(mode="live"))
    assert len([c for c in calls if c[0] == "POST"]) == 1
    assert dres.history()[0]["status"] == "unknown"


@pytest.mark.parametrize("http,body,status", [
    (200, {"status": True}, "accepted_pending"),
    (200, {"submission": "CORRECT"}, "unknown"),
    (200, {"status": "true", "submission": "CORRECT"}, "unknown"),
    (202, {"status": True, "submission": "CORRECT"}, "accepted_pending"),
    (200, {"status": True, "submission": "WRONG"}, "incorrect"),
    (200, {"status": True, "submission": "UNDECIDABLE"}, "accepted_pending"),
    (200, {"status": True, "submission": "INDETERMINATE"}, "accepted_pending"),
    (200, {"status": False}, "rejected"),
    (200, None, "unknown"),
    (500, {"status": False}, "unknown"),
    (302, None, "unknown"),
    (400, {"description": "bad"}, "rejected"),
    (401, None, "rejected"),
    (404, None, "rejected"),
    (412, None, "rejected"),
    (429, None, "rejected"),
])
def test_pinned_verdict_and_http_errors(db, http, body, status):
    """HTTP success/status=true không được báo đúng khi chưa có verdict."""
    dres, _ = live_service(db, DresResponse(http, body))
    assert dres.submit(request(mode="live"))["status"] == status


def test_redaction_of_nested_echoed_credentials(db):
    dres, _ = live_service(db, DresResponse(200, {"status": True, "submission": "CORRECT",
                                               "sessionId": "secret-token", "nested": {"cookie": "foo"},
                                               "description": "url?session=secret-token&token=unknown-value"}))
    result = dres.submit(request(mode="live"))
    assert "secret-token" not in json.dumps(result)
    assert "unknown-value" not in json.dumps(result)
    assert "foo" not in json.dumps(dres.history())


def test_explicit_active_evaluation_selection_and_login(db):
    """Nhiều ACTIVE vẫn phải dùng ID user chọn; credential không tới response."""
    calls = []

    def transport(method, url, params, body, timeout):
        calls.append((method, url, params, body))
        if url.endswith("/login"):
            return DresResponse(200, {"sessionId": "login-secret"})
        if url.endswith("/list"):
            return DresResponse(200, [{"id": "eval-a", "name": "A", "status": "ACTIVE"},
                                     {"id": "eval-1", "name": "B", "status": "ACTIVE"},
                                     {"id": "stopped", "name": "C", "status": "TERMINATED"}])
        return DresResponse(200, {"status": True, "submission": "CORRECT"})

    dres = service(db, transport=transport, environ={"DRES_DRY_RUN": "false", "DRES_BASE_URL": "https://dres.test",
                                                  "DRES_USERNAME": "tester", "DRES_PASSWORD": "pass-secret"})
    with pytest.raises(ValueError, match="ACTIVE"):
        dres.submit(request(mode="live", evaluation_id="stopped"))
    result = dres.submit(request(mode="live"))
    assert calls[-1][1].endswith("/submit/eval-1")
    assert len([c for c in calls if c[1].endswith("/login")]) == 1
    assert "login-secret" not in json.dumps(result)
    assert "pass-secret" not in json.dumps(dres.history())


def test_transport_error_does_not_echo_url_on_evaluations(db):
    def transport(*args):
        raise RuntimeError("https://test?session=top-secret")

    dres = service(db, transport=transport, environ={"DRES_DRY_RUN": "false", "DRES_BASE_URL": "https://dres.test",
                                                  "DRES_SESSION_ID": "top-secret"})
    with pytest.raises(DresHttpError) as error:
        dres.evaluations()
    assert "top-secret" not in str(error.value)


def test_evaluations_timeout_is_redacted_service_error(db):
    """GET timeout trước reserve cần API 503 có nghĩa, không traceback bí mật."""
    def transport(*args):
        raise TimeoutError("session=top-secret")

    dres = service(db, transport=transport, environ={"DRES_DRY_RUN": "false", "DRES_BASE_URL": "https://dres.test",
                                                  "DRES_SESSION_ID": "top-secret"})
    with pytest.raises(DresHttpError) as error:
        dres.evaluations()
    assert error.value.status_code == 503
    assert "top-secret" not in str(error.value)
    assert dres.history() == []


def test_api_audit_clock_is_integer_milliseconds(db):
    dres = service(db, clock=lambda: 1000.123)
    task = dres.start_mock({"task_key": "time-unit", "task_type": "video_kis", "video_uid": "v1",
                            "start_ms": 100, "end_ms": 200})
    assert task["started_at_ms"] == 1000123
    assert task["time_limit_ms"] == 240000
    dres.submit(request())
    assert dres.history()[0]["created_at"] == 1000123


def test_mock_clock_wrong_count_and_first_correct_score(db):
    """t là thời gian task, không timestamp video; wrong count trước đúng đầu tiên."""
    now = [1000.0]
    dres = service(db, clock=lambda: now[0])
    dres.start_mock({"task_key": "practice", "task_type": "textual_kis", "video_uid": "v1",
                     "start_ms": 12300, "end_ms": 12400})
    mock_req = request(mode="mock", evaluation_id=MOCK_EVALUATION_ID, task_key="practice")
    now[0] = 1010
    assert dres.submit({**mock_req, "keyframe_id": "k2"})["status"] == "incorrect"
    now[0] = 1150
    right = dres.submit(mock_req)
    assert right["status"] == "correct"
    assert right["response"]["score"] == 65.0
    assert right["response"]["wrong_submissions"] == 1
    now[0] = 1180
    assert dres.submit({**mock_req, "timestamp_ms": 12341})["status"] == "rejected"
    assert dres.history()[0]["response"]["score"] == 65.0


def test_mock_qa_ground_truth_and_expiration(db):
    now = [500.0]
    dres = service(db, clock=lambda: now[0])
    task = {"task_key": "qa-round", "task_type": "qa", "video_uid": "v1",
            "start_ms": 12300, "end_ms": 12400, "answer": "007"}
    dres.start_mock(task)
    with pytest.raises(DuplicateSubmission):
        dres.start_mock(task)
    req = request(mode="mock", evaluation_id=MOCK_EVALUATION_ID, task_key="qa-round", task_type="QA")
    assert dres.submit({**req, "answer": "7"})["status"] == "incorrect"
    now[0] = 801
    expired = dres.submit({**req, "answer": "007"})
    assert expired["status"] == "rejected"
    assert expired["response"]["score"] == 0


def test_mock_and_live_namespaces_independent(db):
    dres = service(db)
    dres.start_mock({"task_key": "round-1", "task_type": "video_kis", "video_uid": "v1",
                     "start_ms": 12300, "end_ms": 12400})
    assert dres.submit(request(mode="mock", evaluation_id=MOCK_EVALUATION_ID))["status"] == "correct"
    live, _ = live_service(db)
    assert live.submit(request(mode="live"))["status"] == "correct"


def test_live_evaluation_list_keeps_mock_available_without_live_post(db):
    """Backend bật live vẫn luyện mock được; không POST local-mock lên server thật."""
    live, calls = live_service(db)
    assert any(row.get("mock") and row["id"] == MOCK_EVALUATION_ID for row in live.evaluations()["evaluations"])
    with pytest.raises(ValueError, match="ACTIVE"):
        live.submit(request(mode="live", evaluation_id=MOCK_EVALUATION_ID))
    assert not [c for c in calls if c[0] == "POST"]


def test_practice_score_outer_clamp_and_deadline():
    """6 sai vẫn được 40 điểm nếu t=0: không clamp riêng 50 điểm chính xác."""
    assert practice_score(0, 300, 6) == 40
    assert practice_score(240, 240, 0) == 50
    assert practice_score(241, 240, 0) == 0
    assert practice_score(0, 300, 11) == 0
    assert practice_score(0, 300, 0, correct=False) == 0


def test_schema_snapshot_hash_and_enum_are_pinned():
    """Upstream thay schema phải khiến audit/test buộc đối chiếu profile trước live."""
    root = Path(__file__).resolve().parents[1]
    profile = json.loads((root / "configs/aic2024_v2.json").read_text(encoding="utf-8"))
    schema_bytes = (root / profile["openapi_file"]).read_bytes()
    assert hashlib.sha256(schema_bytes).hexdigest() == profile["openapi_sha256"]
    schema = json.loads(schema_bytes)
    assert schema["components"]["schemas"]["ApiVerdictStatus"]["enum"] == list(profile["verdicts"])
    assert schema["components"]["schemas"]["ApiClientAnswer"]["properties"]["start"]["type"] == "integer"

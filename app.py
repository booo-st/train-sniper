#!/usr/bin/env python3
"""Local web UI for KTX/SRT Sniper.

This intentionally uses only the Python standard library plus korail2 so the
tool can run on a Mac without pulling in a web framework.
"""

from __future__ import annotations

import json
import os
import random
import secrets
import signal
import stat
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from korail2 import AdultPassenger, ChildPassenger, Korail, ReserveOption, SeniorPassenger, ToddlerPassenger, TrainType
from SRT import SRT
from SRT.passenger import Adult as SRTAdult, Child as SRTChild, Senior as SRTSenior
from SRT.seat_type import SeatType as SRTSeatType


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
SETTINGS_FILE = APP_DIR / "settings.local.json"
CONFIG_FILE = APP_DIR / "config.json"

AUTH_SESSIONS: set[str] = set()


def get_auth_password() -> str:
    env = os.getenv("KTX_SNIPER_PASSWORD", "")
    if env:
        return env
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
        return data.get("ui_password", "")
    return ""


def check_auth(handler: BaseHTTPRequestHandler) -> bool:
    if not get_auth_password():
        return True
    cookie_header = handler.headers.get("Cookie", "")
    for part in cookie_header.split(";"):
        name, _, value = part.strip().partition("=")
        if name.strip() == "ktx_session" and value.strip() in AUTH_SESSIONS:
            return True
    return False

TRAIN_TYPES = {
    "ktx": TrainType.KTX,
    "all": TrainType.ALL,
    "saemaeul": TrainType.SAEMAEUL,
    "itx-saemaeul": TrainType.ITX_SAEMAEUL,
    "mugunghwa": TrainType.MUGUNGHWA,
    "nuriro": TrainType.NURIRO,
    "itx-cheongchun": TrainType.ITX_CHEONGCHUN,
    "airport": TrainType.AIRPORT,
}

SEAT_OPTIONS = {
    "general-first": ReserveOption.GENERAL_FIRST,
    "general-only": ReserveOption.GENERAL_ONLY,
    "special-first": ReserveOption.SPECIAL_FIRST,
    "special-only": ReserveOption.SPECIAL_ONLY,
}

SRT_SEAT_OPTIONS = {
    "general-first": SRTSeatType.GENERAL_FIRST,
    "general-only": SRTSeatType.GENERAL_ONLY,
    "special-first": SRTSeatType.SPECIAL_FIRST,
    "special-only": SRTSeatType.SPECIAL_ONLY,
}


def load_config_profiles(service: str) -> list[dict[str, Any]]:
    key = f"{service}_profiles"
    if not CONFIG_FILE.exists():
        return []
    with CONFIG_FILE.open(encoding="utf-8") as f:
        data = json.load(f)
    return [{"name": p["name"], "id": p.get("id", ""), "has_password": bool(p.get("password"))} for p in data.get(key, [])]


def get_profile_name_by_id(service: str, user_id: str) -> str:
    key = f"{service}_profiles"
    if not CONFIG_FILE.exists():
        return user_id
    with CONFIG_FILE.open(encoding="utf-8") as f:
        data = json.load(f)
    for p in data.get(key, []):
        if p.get("id") == user_id:
            return p.get("name", user_id)
    return user_id


def get_config_profile(service: str, name: str) -> dict[str, str] | None:
    key = f"{service}_profiles"
    if not CONFIG_FILE.exists():
        return None
    with CONFIG_FILE.open(encoding="utf-8") as f:
        data = json.load(f)
    for p in data.get(key, []):
        if p.get("name") == name:
            return p
    return None


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_train_no(value: str) -> str:
    value = str(value).strip()
    return value.zfill(3) if value.isdigit() and len(value) < 3 else value


def json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler: BaseHTTPRequestHandler, body: bytes, content_type: str) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "accounts": {
                    "ktx": {"id": "", "password": ""},
                    "srt": {"id": "", "password": ""},
                },
                "telegram": {"token": "", "chat_id": ""},
                "sleep": {"prevent": False},
            }
        with self.path.open(encoding="utf-8") as f:
            data = json.load(f)
        if "accounts" not in data:
            data["accounts"] = {
                "ktx": data.get("account", {"id": "", "password": ""}),
                "srt": {"id": "", "password": ""},
            }
        data["accounts"].setdefault("ktx", {"id": "", "password": ""})
        data["accounts"].setdefault("srt", {"id": "", "password": ""})
        return data

    def save(self) -> None:
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
            tmp.replace(self.path)

    def public(self) -> dict[str, Any]:
        accounts = self.data.get("accounts", {})
        telegram = self.data.get("telegram", {})
        return {
            "accounts": {
                service: {
                    "id": account.get("id", ""),
                    "has_password": bool(account.get("password")),
                }
                for service, account in accounts.items()
            },
            "telegram": {
                "has_token": bool(telegram.get("token")),
                "chat_id": telegram.get("chat_id", ""),
            },
            "sleep": self.data.get("sleep", {"prevent": False}),
        }


class CaffeinateManager:
    def __init__(self) -> None:
        self.proc: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()

    def start(self) -> None:
        with self.lock:
            if self.proc and self.proc.poll() is None:
                return
            self.proc = subprocess.Popen(["caffeinate", "-dimsu"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)

    def stop(self) -> None:
        with self.lock:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            self.proc = None

    def enabled(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)


@dataclass
class Job:
    id: str
    service: str
    name: str
    dep: str
    arr: str
    date: str
    time: str
    train_numbers: set[str]
    train_type: str
    seat_option: str
    interval_min: int
    interval_max: int
    adults: int = 1
    children: int = 0
    seniors: int = 0
    toddlers: int = 0
    include_waiting: bool = False
    account_label: str = ""
    active: bool = False
    started: bool = False
    done: bool = False
    last_check: str | None = None
    next_check_in: int | None = None
    last_status: str = "대기 중"
    result: str | None = None
    logs: list[str] = field(default_factory=list)
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    def log(self, message: str) -> None:
        line = f"[{now()}] {message}"
        self.logs.append(line)
        self.logs[:] = self.logs[-80:]
        self.last_status = message
        print(f"[{self.name}] {message}", flush=True)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "service": self.service,
            "name": self.name,
            "dep": self.dep,
            "arr": self.arr,
            "date": self.date,
            "time": self.time,
            "train_numbers": sorted(self.train_numbers),
            "train_type": self.train_type,
            "seat_option": self.seat_option,
            "interval_min": self.interval_min,
            "interval_max": self.interval_max,
            "active": self.active,
            "started": self.started,
            "done": self.done,
            "last_check": self.last_check,
            "next_check_in": self.next_check_in,
            "last_status": self.last_status,
            "result": self.result,
            "logs": self.logs[-20:],
        }


class AppState:
    def __init__(self) -> None:
        self.settings = SettingsStore(SETTINGS_FILE)
        self.caffeinate = CaffeinateManager()
        self.lock = threading.Lock()
        self.jobs: dict[str, Job] = self._load_jobs()

    def _load_jobs(self) -> dict[str, Job]:
        saved = self.settings.data.get("jobs", [])
        jobs: dict[str, Job] = {}
        for d in saved:
            try:
                job = Job(
                    id=d["id"],
                    service=d.get("service", "ktx"),
                    name=d["name"],
                    dep=d["dep"],
                    arr=d["arr"],
                    date=d["date"],
                    time=d["time"],
                    train_numbers=set(d.get("train_numbers", [])),
                    train_type=d.get("train_type", "ktx"),
                    seat_option=d.get("seat_option", "special-first"),
                    interval_min=d.get("interval_min", 25),
                    interval_max=d.get("interval_max", 40),
                    adults=d.get("adults", 1),
                    children=d.get("children", 0),
                    seniors=d.get("seniors", 0),
                    toddlers=d.get("toddlers", 0),
                    include_waiting=d.get("include_waiting", False),
                    started=d.get("started", False),
                    done=d.get("done", False),
                    result=d.get("result"),
                    last_status="서버 재시작으로 중지됨" if d.get("started") and not d.get("done") else d.get("last_status", "대기 중"),
                )
                jobs[job.id] = job
            except Exception:
                pass
        return jobs

    def save_jobs(self) -> None:
        self.settings.data["jobs"] = [
            {
                "id": j.id, "service": j.service, "name": j.name,
                "dep": j.dep, "arr": j.arr, "date": j.date, "time": j.time,
                "train_numbers": sorted(j.train_numbers),
                "train_type": j.train_type, "seat_option": j.seat_option,
                "interval_min": j.interval_min, "interval_max": j.interval_max,
                "adults": j.adults, "children": j.children,
                "seniors": j.seniors, "toddlers": j.toddlers,
                "include_waiting": j.include_waiting,
                "started": j.started, "active": j.active, "done": j.done, "result": j.result,
                "last_status": j.last_status,
            }
            for j in self.jobs.values()
        ]
        self.settings.save()

    def credentials(self, service: str) -> tuple[str, str]:
        account = self.settings.data.get("accounts", {}).get(service, {})
        if service == "ktx":
            user_id = os.getenv("KSKILL_KTX_ID") or account.get("id", "")
            password = os.getenv("KSKILL_KTX_PASSWORD") or account.get("password", "")
            label = "코레일"
        elif service == "srt":
            user_id = os.getenv("KSKILL_SRT_ID") or account.get("id", "")
            password = os.getenv("KSKILL_SRT_PASSWORD") or account.get("password", "")
            label = "SRT"
        else:
            raise RuntimeError("지원하지 않는 서비스입니다.")
        if not user_id or not password:
            raise RuntimeError(f"{label} 계정을 먼저 등록하세요.")
        return user_id, password

    def korail(self) -> Korail:
        korail_id, password = self.credentials("ktx")
        return Korail(korail_id, password)

    def srt(self) -> SRT:
        srt_id, password = self.credentials("srt")
        return SRT(srt_id, password)

    def notify(self, message: str) -> None:
        telegram = self.settings.data.get("telegram", {})
        token = os.getenv("KTX_SNIPER_TELEGRAM_TOKEN") or telegram.get("token", "")
        chat_id = os.getenv("KTX_SNIPER_TELEGRAM_CHAT_ID") or telegram.get("chat_id", "")
        if not token or not chat_id:
            return
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        urllib.request.urlopen(url, data=data, timeout=10).read()


state = AppState()


def ktx_passengers(job: Job) -> list[Any]:
    ps = []
    if job.adults:
        ps.append(AdultPassenger(job.adults))
    if job.children:
        ps.append(ChildPassenger(job.children))
    if job.seniors:
        ps.append(SeniorPassenger(job.seniors))
    if job.toddlers:
        ps.append(ToddlerPassenger(job.toddlers))
    return ps or [AdultPassenger(1)]


def srt_passengers(job: Job) -> list[Any]:
    ps = []
    if job.adults:
        ps.append(SRTAdult(job.adults))
    if job.children:
        ps.append(SRTChild(job.children))
    if job.seniors:
        ps.append(SRTSenior(job.seniors))
    return ps or [SRTAdult(1)]


def ktx_train_to_dict(train: Any) -> dict[str, Any]:
    price = getattr(train, "price", None)
    return {
        "service": "ktx",
        "train_no": train.train_no,
        "train_type": train.train_type_name,
        "dep_name": train.dep_name,
        "arr_name": train.arr_name,
        "dep_date": train.dep_date,
        "arr_date": train.arr_date,
        "dep_time": train.dep_time,
        "arr_time": train.arr_time,
        "has_general_seat": train.has_general_seat(),
        "has_special_seat": train.has_special_seat(),
        "has_waiting_list": train.has_waiting_list(),
        "price": price,
        "summary": ktx_train_summary(train),
    }


def srt_train_to_dict(train: Any) -> dict[str, Any]:
    return {
        "service": "srt",
        "train_no": train.train_number,
        "train_type": train.train_name,
        "dep_name": train.dep_station_name,
        "arr_name": train.arr_station_name,
        "dep_date": train.dep_date,
        "arr_date": train.arr_date,
        "dep_time": train.dep_time,
        "arr_time": train.arr_time,
        "has_general_seat": train.general_seat_available(),
        "has_special_seat": train.special_seat_available(),
        "has_waiting_list": train.reserve_standby_available(),
        "price": None,
        "summary": srt_train_summary(train),
    }


def ktx_train_summary(train: Any) -> str:
    dep = f"{train.dep_time[:2]}:{train.dep_time[2:4]}"
    arr = f"{train.arr_time[:2]}:{train.arr_time[2:4]}"
    seats = []
    if train.has_general_seat():
        seats.append("일반실")
    if train.has_special_seat():
        seats.append("특실")
    if train.has_waiting_list():
        seats.append("예약대기")
    return f"{train.train_type_name} {train.train_no} {dep}->{arr} {'/'.join(seats) if seats else '매진'}"


def srt_train_summary(train: Any) -> str:
    dep = f"{train.dep_time[:2]}:{train.dep_time[2:4]}"
    arr = f"{train.arr_time[:2]}:{train.arr_time[2:4]}"
    seats = []
    if train.general_seat_available():
        seats.append("일반실")
    if train.special_seat_available():
        seats.append("특실")
    if train.reserve_standby_available():
        seats.append("예약대기")
    return f"{train.train_name} {train.train_number} {dep}->{arr} {'/'.join(seats) if seats else '매진'}"


def ktx_reservation_summary(reservation: Any) -> str:
    buy_time = f"{reservation.buy_limit_time[:2]}:{reservation.buy_limit_time[2:4]}"
    return (
        f"예약번호 {reservation.rsv_id}\n"
        f"{reservation.train_type_name} {reservation.train_no} "
        f"{reservation.dep_name} {reservation.dep_time[:2]}:{reservation.dep_time[2:4]}"
        f" -> {reservation.arr_name} {reservation.arr_time[:2]}:{reservation.arr_time[2:4]}\n"
        f"{reservation.price:,}원 / 구입기한 {reservation.buy_limit_date} {buy_time}"
    )


def srt_reservation_summary(reservation: Any) -> str:
    buy_time = f"{reservation.payment_time[:2]}:{reservation.payment_time[2:4]}"
    return (
        f"예약번호 {reservation.reservation_number}\n"
        f"{reservation.train_name} {reservation.train_number} "
        f"{reservation.dep_station_name} {reservation.dep_time[:2]}:{reservation.dep_time[2:4]}"
        f" -> {reservation.arr_station_name} {reservation.arr_time[:2]}:{reservation.arr_time[2:4]}\n"
        f"{int(reservation.total_cost):,}원 / 구입기한 {reservation.payment_date} {buy_time}"
    )


def sniper_worker(job: Job) -> None:
    try:
        job_date = datetime.strptime(job.date, "%Y%m%d").date()
    except ValueError:
        job_date = None
    if job_date and job_date < datetime.today().date():
        job.log(f"이미 지난 날짜입니다 ({job_date}). 자동 중지.")
        job.active = False
        state.save_jobs()
        return

    try:
        user_id, password = state.credentials(job.service)
        job.account_label = get_profile_name_by_id(job.service, user_id)
        if job.service == "ktx":
            client = Korail(user_id, password)
        else:
            client = SRT(user_id, password)
    except Exception as exc:
        job.log(f"로그인 실패: {exc}")
        job.active = False
        return

    ttype = TRAIN_TYPES.get(job.train_type, TrainType.KTX)
    ktx_option = SEAT_OPTIONS.get(job.seat_option, ReserveOption.SPECIAL_FIRST)
    srt_option = SRT_SEAT_OPTIONS.get(job.seat_option, SRTSeatType.SPECIAL_FIRST)
    job.log("스나이핑 시작")

    while not job.stop_event.is_set():
        try:
            if job.service == "ktx":
                trains = client.search_train(
                    job.dep,
                    job.arr,
                    job.date,
                    job.time,
                    train_type=ttype,
                    passengers=ktx_passengers(job),
                    include_no_seats=True,
                    include_waiting_list=job.include_waiting,
                )
                matched = [t for t in trains if t.train_no in job.train_numbers]
            else:
                trains = client.search_train(job.dep, job.arr, job.date, job.time, available_only=False)
                matched = [t for t in trains if t.train_number in job.train_numbers]
        except Exception as exc:
            job.last_check = now()
            job.log(f"조회 실패: {exc}")
            wait_with_countdown(job, max(30, job.interval_max))
            continue

        job.last_check = now()
        if not matched:
            job.log("선택한 열차를 찾지 못함")
        for train in matched:
            summary = ktx_train_summary(train) if job.service == "ktx" else srt_train_summary(train)
            has_seat = train.has_seat() if job.service == "ktx" else train.seat_available()
            has_waiting = train.has_waiting_list() if job.service == "ktx" else train.reserve_standby_available()
            job.log(summary)
            if has_seat or (job.include_waiting and has_waiting):
                job.log("좌석 발견, 예약 시도")
                try:
                    if job.service == "ktx":
                        reservation = client.reserve(train, ktx_passengers(job), option=ktx_option, try_waiting=job.include_waiting)
                        result = ktx_reservation_summary(reservation)
                    elif job.include_waiting and not has_seat and has_waiting:
                        reservation = client.reserve_standby(train, srt_passengers(job), special_seat=srt_option)
                        result = srt_reservation_summary(reservation)
                    else:
                        reservation = client.reserve(train, srt_passengers(job), special_seat=srt_option)
                        result = srt_reservation_summary(reservation)
                except Exception as exc:
                    job.log(f"예약 실패: {exc}")
                    account_info = f" · {job.account_label}" if job.account_label else ""
                    try_notify(f"[{job.name}{account_info}] 예약 실패\n{summary}\n{exc}")
                    continue
                job.result = result
                job.done = True
                job.active = False
                job.log("예약 완료")
                state.save_jobs()
                pay_label = "코레일" if job.service == "ktx" else "SRT"
                account_info = f" · {job.account_label}" if job.account_label else ""
                try_notify(f"[{job.name}{account_info}] 예약 완료\n{job.result}\n\n{pay_label}에서 구입기한 전 결제하세요.")
                return

        wait_with_countdown(job, random.randint(job.interval_min, job.interval_max))

    job.active = False
    job.log("중지됨")
    state.save_jobs()


def wait_with_countdown(job: Job, seconds: int) -> None:
    for remaining in range(seconds, 0, -1):
        if job.stop_event.is_set():
            return
        job.next_check_in = remaining
        time.sleep(1)
    job.next_check_in = None


def telegram_send_test(telegram: dict[str, Any]) -> None:
    token = os.getenv("KTX_SNIPER_TELEGRAM_TOKEN") or telegram.get("token", "")
    chat_id = os.getenv("KTX_SNIPER_TELEGRAM_CHAT_ID") or telegram.get("chat_id", "")
    if not token:
        raise RuntimeError("Bot Token이 설정되지 않았습니다.")
    if not chat_id:
        raise RuntimeError("Chat ID가 설정되지 않았습니다.")
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": "KTX 스나이퍼 텔레그램 연결 테스트"}).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = urllib.request.urlopen(url, data=data, timeout=10).read()
        result = json.loads(resp)
        if not result.get("ok"):
            raise RuntimeError(result.get("description", "Telegram API 오류"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("description", body)
        except Exception:
            detail = body
        raise RuntimeError(f"Telegram API 오류: {detail}") from exc


def try_notify(message: str) -> None:
    try:
        state.notify(message)
    except Exception as exc:
        print(f"Telegram notify failed: {exc}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/login":
            return self.serve_static("login.html")
        if not check_auth(self):
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/login")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if parsed.path == "/":
            return self.serve_static("index.html")
        if parsed.path == "/api/state":
            return json_response(self, api_state())
        if parsed.path == "/api/profiles":
            qs = urllib.parse.parse_qs(parsed.query)
            service = (qs.get("service") or ["ktx"])[0]
            return json_response(self, {"ok": True, "profiles": load_config_profiles(service)})
        if parsed.path.startswith("/static/"):
            return self.serve_static(parsed.path.removeprefix("/static/"))
        return json_response(self, {"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/login":
                return self.handle_login(payload)
            if not check_auth(self):
                json_response(self, {"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            result = self.route_post(path, payload)
            json_response(self, result)
        except Exception as exc:
            json_response(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_login(self, payload: dict[str, Any]) -> None:
        pw = get_auth_password()
        if not pw or payload.get("password") != pw:
            json_response(self, {"ok": False, "error": "비밀번호가 틀렸습니다."}, HTTPStatus.UNAUTHORIZED)
            return
        token = secrets.token_hex(32)
        AUTH_SESSIONS.add(token)
        body = json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", f"ktx_session={token}; Path=/; HttpOnly; SameSite=Lax")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def serve_static(self, name: str) -> None:
        path = (STATIC_DIR / name).resolve()
        if not str(path).startswith(str(STATIC_DIR.resolve())) or not path.exists():
            return json_response(self, {"error": "not found"}, HTTPStatus.NOT_FOUND)
        content_type = "text/html; charset=utf-8"
        if path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        text_response(self, path.read_bytes(), content_type)

    def route_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if path == "/api/profiles/apply":
            service = payload.get("service", "ktx")
            name = payload.get("name", "")
            profile = get_config_profile(service, name)
            if not profile:
                raise RuntimeError(f"프로필 '{name}'을 찾을 수 없습니다.")
            account = state.settings.data.setdefault("accounts", {}).setdefault(service, {"id": "", "password": ""})
            account["id"] = profile.get("id", "")
            account["password"] = profile.get("password", "")
            state.settings.save()
            return {"ok": True, "settings": state.settings.public()}

        if path == "/api/account":
            service = payload.get("service", "ktx")
            if service not in ("ktx", "srt"):
                raise RuntimeError("지원하지 않는 서비스입니다.")
            account = state.settings.data.setdefault("accounts", {}).setdefault(service, {"id": "", "password": ""})
            account["id"] = payload.get("id", "").strip()
            if payload.get("password"):
                account["password"] = payload["password"]
            state.settings.save()
            return {"ok": True, "settings": state.settings.public()}

        if path == "/api/account/test":
            service = payload.get("service", "ktx")
            if payload.get("id") and payload.get("password"):
                if service == "ktx":
                    Korail(payload["id"], payload["password"])
                elif service == "srt":
                    SRT(payload["id"], payload["password"])
                else:
                    raise RuntimeError("지원하지 않는 서비스입니다.")
            else:
                state.korail() if service == "ktx" else state.srt()
            return {"ok": True}

        if path == "/api/telegram":
            telegram = state.settings.data.setdefault("telegram", {})
            if "token" in payload:
                telegram["token"] = payload.get("token", "").strip()
            telegram["chat_id"] = payload.get("chat_id", "").strip()
            state.settings.save()
            return {"ok": True, "settings": state.settings.public()}

        if path == "/api/telegram/test":
            if payload:
                old = state.settings.data.setdefault("telegram", {}).copy()
                state.settings.data["telegram"].update(payload)
                try:
                    telegram_send_test(state.settings.data.get("telegram", {}))
                finally:
                    state.settings.data["telegram"] = old
            else:
                telegram_send_test(state.settings.data.get("telegram", {}))
            return {"ok": True}

        if path == "/api/sleep":
            enabled = bool(payload.get("prevent"))
            state.settings.data.setdefault("sleep", {})["prevent"] = enabled
            state.settings.save()
            if enabled:
                state.caffeinate.start()
            else:
                state.caffeinate.stop()
            return {"ok": True, "sleep_prevented": state.caffeinate.enabled()}

        if path == "/api/search":
            return {"ok": True, "trains": search_trains(payload)}

        if path == "/api/jobs":
            job = create_job(payload)
            with state.lock:
                state.jobs[job.id] = job
            state.save_jobs()
            return {"ok": True, "job": job.public()}

        if path.startswith("/api/jobs/"):
            parts = path.split("/")
            job_id = parts[3]
            action = parts[4] if len(parts) > 4 else ""
            job = state.jobs.get(job_id)
            if not job:
                raise RuntimeError("작업을 찾을 수 없습니다.")
            if action == "start":
                start_job(job)
                return {"ok": True, "job": job.public()}
            if action == "stop":
                stop_job(job)
                return {"ok": True, "job": job.public()}
            if action == "delete":
                stop_job(job)
                with state.lock:
                    state.jobs.pop(job_id, None)
                state.save_jobs()
                return {"ok": True}

        raise RuntimeError("지원하지 않는 API입니다.")


def api_state() -> dict[str, Any]:
    return {
        "ok": True,
        "settings": state.settings.public(),
        "sleep_prevented": state.caffeinate.enabled(),
        "jobs": [job.public() for job in state.jobs.values()],
    }


def search_trains(payload: dict[str, Any]) -> list[dict[str, Any]]:
    service = payload.get("service", "ktx")
    train_type = payload.get("train_type", "ktx")
    date = payload["date"].replace("-", "")
    time_value = payload["time"].replace(":", "")[:4].ljust(6, "0")
    if service == "ktx":
        korail = state.korail()
        trains = korail.search_train(
            payload["dep"],
            payload["arr"],
            date,
            time_value,
            train_type=TRAIN_TYPES[train_type],
            passengers=[AdultPassenger(int(payload.get("adults", 1)))],
            include_no_seats=True,
            include_waiting_list=bool(payload.get("include_waiting", False)),
        )
        return [ktx_train_to_dict(t) for t in trains]
    if service == "srt":
        srt = state.srt()
        trains = srt.search_train(payload["dep"], payload["arr"], date, time_value, available_only=False)
        return [srt_train_to_dict(t) for t in trains]
    raise RuntimeError("지원하지 않는 서비스입니다.")


def create_job(payload: dict[str, Any]) -> Job:
    train_numbers = {normalize_train_no(n) for n in payload.get("train_numbers", [])}
    if not train_numbers:
        raise RuntimeError("감시할 열차를 하나 이상 선택하세요.")
    interval_min = int(payload.get("interval_min", 25))
    interval_max = int(payload.get("interval_max", 40))
    if interval_min < 1 or interval_max < interval_min:
        raise RuntimeError("조회 간격을 확인하세요. 최소값은 1초 이상이어야 합니다.")
    raw_date = payload.get("date", "").replace("-", "")
    try:
        job_date = datetime.strptime(raw_date, "%Y%m%d").date()
    except ValueError:
        raise RuntimeError("날짜 형식이 올바르지 않습니다.")
    if job_date < datetime.today().date():
        raise RuntimeError(f"이미 지난 날짜입니다 ({job_date}). 날짜를 다시 확인하세요.")
    return Job(
        id=secrets.token_hex(4),
        service=payload.get("service", "ktx"),
        name=payload.get("name") or f"{payload['dep']}→{payload['arr']} {payload['date']}",
        dep=payload["dep"],
        arr=payload["arr"],
        date=payload["date"].replace("-", ""),
        time=payload["time"].replace(":", "")[:4].ljust(6, "0"),
        train_numbers=train_numbers,
        train_type=payload.get("train_type", "ktx"),
        seat_option=payload.get("seat_option", "special-first"),
        interval_min=interval_min,
        interval_max=interval_max,
        adults=int(payload.get("adults", 1)),
        children=int(payload.get("children", 0)),
        seniors=int(payload.get("seniors", 0)),
        toddlers=int(payload.get("toddlers", 0)),
        include_waiting=bool(payload.get("include_waiting", False)),
    )


def start_job(job: Job) -> None:
    if job.active:
        return
    job.stop_event.clear()
    job.active = True
    job.started = True
    job.done = False
    job.result = None
    job.thread = threading.Thread(target=sniper_worker, args=(job,), daemon=True)
    job.thread.start()
    state.save_jobs()


def stop_job(job: Job) -> None:
    job.stop_event.set()
    job.active = False
    job.next_check_in = None


def shutdown(signum: int, frame: Any) -> None:
    for job in list(state.jobs.values()):
        stop_job(job)
    state.caffeinate.stop()
    raise SystemExit(0)


def main() -> None:
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    if state.settings.data.get("sleep", {}).get("prevent"):
        state.caffeinate.start()
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("KTX Sniper UI: http://127.0.0.1:8765", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

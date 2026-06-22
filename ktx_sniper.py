#!/usr/bin/env python3
"""KTX cancel-ticket sniper.

Polls Korail for configured trains and reserves the first available seat.
Payment is intentionally not automated; complete purchase in Korail before the
buy limit shown in the success message.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from korail2 import AdultPassenger, ChildPassenger, Korail, ReserveOption, SeniorPassenger, ToddlerPassenger, TrainType


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

running = True
lock = threading.Lock()


@dataclass
class Job:
    name: str
    dep: str
    arr: str
    date: str
    time: str
    train_numbers: set[str]
    train_type: str = "ktx"
    seat_option: str = "general-first"
    try_waiting: bool = False
    interval_min: int = 25
    interval_max: int = 40
    adults: int = 1
    children: int = 0
    seniors: int = 0
    toddlers: int = 0
    active: bool = True
    last_check: str | None = None
    last_status: str = "not started"


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    print(f"[{now()}] {message}", flush=True)


def notify(message: str, config: dict[str, Any]) -> None:
    print(message, flush=True)
    telegram = config.get("telegram", {})
    token = os.getenv("KTX_SNIPER_TELEGRAM_TOKEN") or telegram.get("token")
    chat_id = os.getenv("KTX_SNIPER_TELEGRAM_CHAT_ID") or telegram.get("chat_id")
    if not token or not chat_id:
        return

    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        urllib.request.urlopen(url, data=payload, timeout=10).read()
    except Exception as exc:
        log(f"Telegram notify failed: {exc}")


def passengers(job: Job) -> list[Any]:
    result: list[Any] = []
    if job.adults:
        result.append(AdultPassenger(job.adults))
    if job.children:
        result.append(ChildPassenger(job.children))
    if job.seniors:
        result.append(SeniorPassenger(job.seniors))
    if job.toddlers:
        result.append(ToddlerPassenger(job.toddlers))
    return result or [AdultPassenger(1)]


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        config = json.load(f)
    if not config.get("jobs"):
        raise ValueError("config must contain at least one job")
    return config


def load_jobs(config: dict[str, Any]) -> list[Job]:
    defaults = config.get("defaults", {})
    jobs: list[Job] = []
    for raw in config["jobs"]:
        merged = {**defaults, **raw}
        jobs.append(
            Job(
                name=merged.get("name") or f"{merged['dep']}->{merged['arr']} {merged['date']}",
                dep=merged["dep"],
                arr=merged["arr"],
                date=merged["date"],
                time=merged["time"],
                train_numbers={str(n).zfill(3) if str(n).isdigit() and len(str(n)) < 3 else str(n) for n in merged["train_numbers"]},
                train_type=merged.get("train_type", "ktx"),
                seat_option=merged.get("seat_option", "general-first"),
                try_waiting=bool(merged.get("try_waiting", False)),
                interval_min=int(merged.get("interval_min", 25)),
                interval_max=int(merged.get("interval_max", 40)),
                adults=int(merged.get("adults", 1)),
                children=int(merged.get("children", 0)),
                seniors=int(merged.get("seniors", 0)),
                toddlers=int(merged.get("toddlers", 0)),
            )
        )
    return jobs


def login(config: dict[str, Any]) -> Korail:
    korail_id = os.getenv("KSKILL_KTX_ID") or config.get("korail_id")
    korail_pw = os.getenv("KSKILL_KTX_PASSWORD") or config.get("korail_password")
    if not korail_id or not korail_pw:
        raise RuntimeError("Set KSKILL_KTX_ID and KSKILL_KTX_PASSWORD, or put korail_id/korail_password in config.json")
    return Korail(korail_id, korail_pw)


def train_summary(train: Any) -> str:
    dep = f"{train.dep_time[:2]}:{train.dep_time[2:4]}"
    arr = f"{train.arr_time[:2]}:{train.arr_time[2:4]}"
    seats = []
    if train.has_general_seat():
        seats.append("일반실")
    if train.has_special_seat():
        seats.append("특실")
    if train.has_waiting_list():
        seats.append("예약대기")
    seat_text = ",".join(seats) if seats else "매진"
    return f"{train.train_type_name} {train.train_no} {dep}->{arr} {seat_text}"


def reservation_summary(reservation: Any) -> str:
    buy_time = f"{reservation.buy_limit_time[:2]}:{reservation.buy_limit_time[2:4]}"
    return (
        "예약 완료\n"
        f"예약번호: {reservation.rsv_id}\n"
        f"열차: {reservation.train_type_name} {reservation.train_no}\n"
        f"구간: {reservation.dep_name} {reservation.dep_time[:2]}:{reservation.dep_time[2:4]}"
        f" -> {reservation.arr_name} {reservation.arr_time[:2]}:{reservation.arr_time[2:4]}\n"
        f"좌석수: {reservation.seat_no_count}\n"
        f"요금: {reservation.price:,}원\n"
        f"구입기한: {reservation.buy_limit_date} {buy_time}"
    )


def run_job(job: Job, korail: Korail, config: dict[str, Any]) -> None:
    log(f"[{job.name}] start: {job.dep}->{job.arr} {job.date} {job.time}, trains={sorted(job.train_numbers)}")
    ttype = TRAIN_TYPES.get(job.train_type)
    option = SEAT_OPTIONS.get(job.seat_option)
    if not ttype:
        raise ValueError(f"Unknown train_type: {job.train_type}")
    if not option:
        raise ValueError(f"Unknown seat_option: {job.seat_option}")

    while running and job.active:
        try:
            trains = korail.search_train(
                job.dep,
                job.arr,
                job.date,
                job.time,
                train_type=ttype,
                passengers=passengers(job),
                include_no_seats=True,
                include_waiting_list=job.try_waiting,
            )
        except Exception as exc:
            with lock:
                job.last_status = f"search error: {exc}"
            log(f"[{job.name}] search error: {exc}")
            time.sleep(max(30, job.interval_max))
            continue

        matched = [t for t in trains if t.train_no in job.train_numbers]
        with lock:
            job.last_check = now()
            job.last_status = "; ".join(train_summary(t) for t in matched) or "target trains not found"

        for train in matched:
            log(f"[{job.name}] {train_summary(train)}")
            if train.has_seat() or (job.try_waiting and train.has_waiting_list()):
                notify(f"[{job.name}] 좌석 발견: {train_summary(train)}\n예약 시도 중...", config)
                try:
                    reservation = korail.reserve(train, passengers(job), option=option, try_waiting=job.try_waiting)
                except Exception as exc:
                    notify(f"[{job.name}] 예약 실패: {exc}", config)
                    log(f"[{job.name}] reserve failed: {exc}")
                    continue

                job.active = False
                message = f"[{job.name}] {reservation_summary(reservation)}"
                notify(message, config)
                return

        interval = random.randint(job.interval_min, job.interval_max)
        log(f"[{job.name}] next check in {interval}s")
        for _ in range(interval):
            if not running or not job.active:
                return
            time.sleep(1)


def print_status(jobs: list[Job]) -> None:
    for job in jobs:
        status = "running" if job.active else "stopped"
        print(f"{job.name}: {status}")
        print(f"  last_check: {job.last_check or '-'}")
        print(f"  trains: {', '.join(sorted(job.train_numbers))}")
        print(f"  last_status: {job.last_status}")


def handle_signal(signum: int, frame: Any) -> None:
    global running
    running = False
    log(f"received signal {signum}, stopping")


def main() -> int:
    parser = argparse.ArgumentParser(description="KTX cancel-ticket sniper")
    parser.add_argument("--config", default="config.json", help="Path to config JSON")
    parser.add_argument("--once", action="store_true", help="Run one status search without reserving")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    jobs = load_jobs(config)
    korail = login(config)

    if args.once:
        for job in jobs:
            trains = korail.search_train(
                job.dep,
                job.arr,
                job.date,
                job.time,
                train_type=TRAIN_TYPES[job.train_type],
                passengers=passengers(job),
                include_no_seats=True,
                include_waiting_list=job.try_waiting,
            )
            for train in trains:
                if train.train_no in job.train_numbers:
                    print(f"[{job.name}] {train_summary(train)}")
        return 0

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    threads = []
    notify("KTX 스나이퍼 시작", config)
    for job in jobs:
        thread = threading.Thread(target=run_job, args=(job, korail, config), daemon=False)
        thread.start()
        threads.append(thread)

    try:
        while running and any(thread.is_alive() for thread in threads):
            time.sleep(3)
    finally:
        print_status(jobs)
    return 0


if __name__ == "__main__":
    sys.exit(main())

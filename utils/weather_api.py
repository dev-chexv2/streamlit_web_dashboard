# -*- coding: utf-8 -*-
"""
weather_api.py — 기상청 단기예보 API 호출·파싱

[담당 챕터] 9장 API 활용
[핵심 포인트]
  1) 기상청은 위경도가 아니라 격자좌표(nx, ny)를 씁니다. 주요 도시는 GRID에 미리 등록.
  2) 예보는 하루 8번(02,05,08,11,14,17,20,23시) 발표됩니다.
     아직 발표 안 된 시각을 요청하면 빈 응답이 오므로,
     "현재 시각 기준 가장 최근에 발표된 시각"을 역산해야 합니다. (latest_base_datetime)
  3) API 키가 없거나 호출이 실패하면 data/fallback.json으로 자동 전환됩니다.
     → 발표 영상 촬영 중 와이파이가 죽어도 앱은 돌아갑니다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests

# 도시별 기상청 격자좌표 (nx, ny)
GRID = {
    "울산": (102, 84),
    "부산": (98, 76),
    "서울": (60, 127),
    "대구": (89, 90),
    "대전": (67, 100),
    "광주": (58, 74),
}

BASE_HOURS = [2, 5, 8, 11, 14, 17, 20, 23]  # 발표 시각
URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
FALLBACK_PATH = Path(__file__).resolve().parent.parent / "data" / "fallback.json"


def latest_base_datetime(now: datetime | None = None) -> tuple[str, str]:
    """
    현재 시각 기준, 조회 가능한 가장 최근 발표 (base_date, base_time) 계산.
    발표 직후에는 데이터 반영이 늦을 수 있어 40분 여유를 둔다.
    """
    now = now or datetime.now()
    t = now - timedelta(minutes=40)
    for h in reversed(BASE_HOURS):
        if t.hour >= h:
            return t.strftime("%Y%m%d"), f"{h:02d}00"
    # 새벽 02:40 이전 → 전날 23시 발표분 사용
    y = t - timedelta(days=1)
    return y.strftime("%Y%m%d"), "2300"


def _parse_items(items: list[dict]) -> list[dict]:
    """
    API 응답의 item 리스트 → 시간별 레코드 리스트로 변환.
    사용하는 카테고리: TMP(기온) REH(습도) POP(강수확률)
    반환: [{"dt": datetime, "temp": float, "humidity": float, "pop": int}, ...]
    """
    bucket: dict[str, dict] = {}
    for it in items:
        key = it["fcstDate"] + it["fcstTime"]
        rec = bucket.setdefault(key, {})
        cat, val = it["category"], it["fcstValue"]
        if cat == "TMP":
            rec["temp"] = float(val)
        elif cat == "REH":
            rec["humidity"] = float(val)
        elif cat == "POP":
            rec["pop"] = int(val)

    records = []
    for key, rec in sorted(bucket.items()):
        if "temp" not in rec:
            continue
        records.append({
            "dt": datetime.strptime(key, "%Y%m%d%H%M"),
            "temp": rec["temp"],
            "humidity": rec.get("humidity", 60.0),
            "pop": rec.get("pop", 0),
        })
    return records


def fetch_forecast(service_key: str, city: str = "울산", timeout: int = 10) -> list[dict]:
    """기상청 단기예보 실시간 호출. 실패 시 예외를 그대로 올린다."""
    nx, ny = GRID.get(city, GRID["울산"])
    base_date, base_time = latest_base_datetime()
    params = {
        "serviceKey": service_key,
        "pageNo": 1,
        "numOfRows": 1000,
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx,
        "ny": ny,
    }
    r = requests.get(URL, params=params, timeout=timeout)
    r.raise_for_status()
    body = r.json()["response"]["body"]
    records = _parse_items(body["items"]["item"])
    if not records:
        raise ValueError("예보 응답이 비어 있음 (base_time 확인 필요)")
    return records


def load_fallback() -> list[dict]:
    """
    내장 샘플 예보 로드.
    저장된 hour_offset을 '오늘 00시' 기준으로 다시 깔아주기 때문에
    언제 실행해도 날짜가 오늘처럼 보인다. (데모용 트릭)
    """
    with open(FALLBACK_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    base = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return [
        {
            "dt": base + timedelta(hours=r["hour_offset"]),
            "temp": r["temp"],
            "humidity": r["humidity"],
            "pop": r.get("pop", 0),
        }
        for r in raw["records"]
    ]


def save_fallback_from_records(records: list[dict]) -> None:
    """실시간 응답을 fallback으로 저장 → 다음 데모 때 최신 데이터가 비상용이 된다."""
    base = records[0]["dt"].replace(hour=0, minute=0, second=0, microsecond=0)
    data = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "records": [
            {
                "hour_offset": int((r["dt"] - base).total_seconds() // 3600),
                "temp": r["temp"],
                "humidity": r["humidity"],
                "pop": r.get("pop", 0),
            }
            for r in records
        ],
    }
    FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FALLBACK_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def get_forecast(service_key: str | None, city: str = "울산") -> tuple[list[dict], str]:
    """
    앱에서 부르는 단일 진입점.
    반환: (records, source)  source ∈ {"live", "fallback"}
    """
    if service_key:
        try:
            records = fetch_forecast(service_key, city)
            try:
                save_fallback_from_records(records)
            except OSError:
                pass  # 저장 실패는 치명적이지 않음
            return records, "live"
        except Exception:
            pass  # 아래 fallback으로
    return load_fallback(), "fallback"


# ──────────────────────────────────────────────
# 예보 분석 함수 (모듈 2·3에서 사용)
# ──────────────────────────────────────────────

def tropical_night(records: list[dict], now: datetime | None = None) -> dict:
    """
    오늘 밤 열대야 판정.
    정의: 밤(18:01~다음날 09:00) 최저기온 25°C 이상.
    반환: {"is_tropical", "min_temp", "min_time", "cool_time"(25°C 하회 첫 시각 or None)}
    """
    now = now or datetime.now()
    start = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if now.hour >= 9 and now.hour < 18:
        pass  # 오늘 저녁 밤을 본다
    elif now.hour < 9:
        start -= timedelta(days=1)  # 새벽이면 어젯밤부터
    end = start + timedelta(hours=15)  # 다음날 09:00

    night = [r for r in records if start <= r["dt"] <= end]
    if not night:
        return {"is_tropical": None, "min_temp": None, "min_time": None, "cool_time": None}

    coldest = min(night, key=lambda r: r["temp"])
    cool = next(
        (r["dt"] for r in night if r["dt"] >= start.replace(hour=21) and r["temp"] < 25.0),
        None,
    )
    return {
        "is_tropical": coldest["temp"] >= 25.0,
        "min_temp": coldest["temp"],
        "min_time": coldest["dt"],
        "cool_time": cool,
    }


def hours_ahead(records: list[dict], hours: int = 24, now: datetime | None = None) -> list[dict]:
    """지금부터 N시간의 예보만 추출 (외출 타이밍 차트용)."""
    now = now or datetime.now()
    end = now + timedelta(hours=hours)
    return [r for r in records if now - timedelta(hours=1) <= r["dt"] <= end]

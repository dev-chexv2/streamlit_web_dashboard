# -*- coding: utf-8 -*-
"""
air_env.py — 자외선지수(기상청 생활기상지수) + 대기질(에어코리아) 조회

[담당 챕터] 9장 API 활용 (두 번째·세 번째 API — "API 여러 개 조합" 어필 포인트)
[필요한 활용신청] 같은 공공데이터포털 키로 아래 두 서비스에 각각 활용신청 필요:
  1) "기상청_생활기상지수 조회서비스(3.0)"   → 자외선지수
  2) "한국환경공단_에어코리아_대기오염정보"  → 미세먼지·오존
  * 신청 안 했거나 동기화 전이면 자동으로 샘플값으로 동작 (앱은 안 죽음)
"""
from __future__ import annotations

from datetime import datetime, timedelta

import requests

# 행정구역코드 (areaNo) — 광역시 단위
AREA_NO = {
    "울산": "3100000000",
    "부산": "2600000000",
    "서울": "1100000000",
    "대구": "2700000000",
    "대전": "3000000000",
    "광주": "2900000000",
}

UV_URL = "https://apis.data.go.kr/1360000/LivingWthrIdxServiceV4/getUVIdxV4"
AIR_URL = "http://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getCtprvnRltmMesureDnsty"

# 데모 비상용 샘플 (7월 한낮 시나리오)
SAMPLE_UV = {"now": 7, "max_today": 9, "source": "sample"}
SAMPLE_AIR = {"pm10": 42.0, "pm25": 21.0, "o3": 0.085, "station_count": 0, "source": "sample"}


# ──────────────────────────────────────────────
# 등급 판정 (기상청·환경부 공식 기준)
# ──────────────────────────────────────────────

def uv_grade(v: float | None) -> str:
    """자외선지수 등급: 낮음 <3 / 보통 3~5 / 높음 6~7 / 매우높음 8~10 / 위험 11+"""
    if v is None:
        return "정보없음"
    if v >= 11:
        return "위험"
    if v >= 8:
        return "매우높음"
    if v >= 6:
        return "높음"
    if v >= 3:
        return "보통"
    return "낮음"


def pm10_grade(v: float | None) -> str:
    if v is None:
        return "정보없음"
    if v > 150:
        return "매우나쁨"
    if v > 80:
        return "나쁨"
    if v > 30:
        return "보통"
    return "좋음"


def pm25_grade(v: float | None) -> str:
    if v is None:
        return "정보없음"
    if v > 75:
        return "매우나쁨"
    if v > 35:
        return "나쁨"
    if v > 15:
        return "보통"
    return "좋음"


def o3_grade(v: float | None) -> str:
    if v is None:
        return "정보없음"
    if v > 0.150:
        return "매우나쁨"
    if v > 0.090:
        return "나쁨"
    if v > 0.030:
        return "보통"
    return "좋음"


# ──────────────────────────────────────────────
# 자외선지수 (생활기상지수 API)
# ──────────────────────────────────────────────

def _uv_candidate_times(now: datetime) -> list[str]:
    """발표시각이 정확히 문서화돼 있지 않아, 최근 후보 시각을 순서대로 시도한다."""
    cands = []
    floor3 = now.replace(minute=0, second=0, microsecond=0)
    floor3 -= timedelta(hours=floor3.hour % 3)
    for h in range(0, 13, 3):  # 최근 12시간 내 3시간 간격 후보
        cands.append((floor3 - timedelta(hours=h)).strftime("%Y%m%d%H"))
    return cands


def _parse_uv_item(item: dict, base: datetime, now: datetime) -> dict:
    """h0, h3, h6 ... 필드에서 '지금' 값과 '오늘 낮 최대' 값을 계산."""
    values = {}
    for k, v in item.items():
        if k.startswith("h") and k[1:].isdigit() and str(v).strip():
            try:
                values[int(k[1:])] = float(v)
            except ValueError:
                continue
    if not values:
        raise ValueError("h* 필드 없음")

    # 지금 값: 발표시각 기준 경과시간을 3시간 단위로 반올림
    off = (now - base).total_seconds() / 3600
    off3 = min(max(round(off / 3) * 3, 0), max(values))
    uv_now = values.get(off3)

    # 오늘 낮(6~20시) 최대
    todays = [
        v for h, v in values.items()
        if (base + timedelta(hours=h)).date() == now.date()
        and 6 <= (base + timedelta(hours=h)).hour <= 20
    ]
    return {
        "now": round(uv_now) if uv_now is not None else None,
        "max_today": round(max(todays)) if todays else None,
        "source": "live",
    }


def get_uv(service_key: str | None, city: str = "울산", now: datetime | None = None) -> dict:
    """자외선지수 조회. 실패 시 샘플값 반환 (source로 구분)."""
    now = now or datetime.now()
    if not service_key:
        return dict(SAMPLE_UV)
    for t in _uv_candidate_times(now):
        try:
            r = requests.get(UV_URL, params={
                "serviceKey": service_key,
                "pageNo": 1,
                "numOfRows": 10,
                "dataType": "JSON",
                "areaNo": AREA_NO.get(city, AREA_NO["울산"]),
                "time": t,
            }, timeout=8)
            r.raise_for_status()
            items = r.json()["response"]["body"]["items"]["item"]
            if not items:
                continue
            base = datetime.strptime(t, "%Y%m%d%H")
            return _parse_uv_item(items[0], base, now)
        except Exception:
            continue
    return dict(SAMPLE_UV)


# ──────────────────────────────────────────────
# 대기질 (에어코리아 시도별 실시간 평균)
# ──────────────────────────────────────────────

def _avg(items: list[dict], field: str) -> float | None:
    """측정소들 값 평균. '-' 같은 결측값은 제외."""
    nums = []
    for it in items:
        try:
            nums.append(float(it.get(field, "")))
        except (TypeError, ValueError):
            continue
    return round(sum(nums) / len(nums), 3) if nums else None


def get_air(service_key: str | None, city: str = "울산") -> dict:
    """시도 내 측정소 평균 PM10/PM2.5/O3. 실패 시 샘플값."""
    if not service_key:
        return dict(SAMPLE_AIR)
    try:
        r = requests.get(AIR_URL, params={
            "serviceKey": service_key,
            "returnType": "json",
            "numOfRows": 100,
            "pageNo": 1,
            "sidoName": city,
            "ver": "1.3",
        }, timeout=8)
        r.raise_for_status()
        items = r.json()["response"]["body"]["items"]
        if not items:
            return dict(SAMPLE_AIR)
        pm10 = _avg(items, "pm10Value")
        pm25 = _avg(items, "pm25Value")
        o3 = _avg(items, "o3Value")
        if pm10 is None and pm25 is None and o3 is None:
            return dict(SAMPLE_AIR)
        return {"pm10": pm10, "pm25": pm25, "o3": o3, "station_count": len(items), "source": "live"}
    except Exception:
        return dict(SAMPLE_AIR)


def overall_outing_verdict(heat_grade: str, uv_g: str, air_pm25_g: str, air_o3_g: str) -> tuple[str, str]:
    """
    체감온도·자외선·대기질을 종합한 오늘의 외출 판정.
    가장 나쁜 요소 하나가 전체 판정을 결정한다 (최악값 지배 방식).
    반환: (판정 이모지+문구, 근거 요소)
    """
    severity = {
        "쾌적": 0, "좋음": 0, "낮음": 0,
        "관심": 1, "보통": 1,
        "주의": 2, "높음": 2, "나쁨": 3,
        "경고": 3, "매우높음": 3,
        "위험": 4, "매우나쁨": 4,
        "정보없음": 0,
    }
    factors = {
        "더위": heat_grade,
        "자외선": uv_g,
        "초미세먼지": air_pm25_g,
        "오존": air_o3_g,
    }
    worst_name, worst_grade = max(factors.items(), key=lambda kv: severity.get(kv[1], 0))
    level = severity.get(worst_grade, 0)
    verdicts = [
        "🟢 외출하기 좋아요",
        "🟡 외출 무난, 물만 챙기세요",
        "🟠 한낮 외출은 줄이세요",
        "🔴 꼭 필요한 외출만",
        "⛔ 외출 자제, 실내 대피 권고",
    ]
    return verdicts[level], f"{worst_name} {worst_grade}"

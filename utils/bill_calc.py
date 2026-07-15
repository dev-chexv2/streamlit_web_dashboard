# -*- coding: utf-8 -*-
"""
bill_calc.py — 전기요금(누진제) 계산 + 여름 체감온도 엔진

[담당 챕터] 8장 데이터 분석 (계산 로직)
[주의] 요금 단가는 한전 주택용(저압) 기준 상수입니다.
       한전 고시가 바뀌면 아래 상수만 수정하면 됩니다. (기준: 2025년 요금표)
"""
from __future__ import annotations

import calendar
import math
from datetime import date

# ──────────────────────────────────────────────
# 요금 상수 (한전 주택용 저압)
#   각 구간: (구간 상한 kWh, 전력량요금 원/kWh, 기본요금 원)
#   하계(7~8월)는 누진 구간이 완화됨: 300 / 450 kWh
#   그 외 계절: 200 / 400 kWh
# ──────────────────────────────────────────────
SUMMER_BRACKETS = [
    (300, 120.0, 910),
    (450, 214.6, 1600),
    (float("inf"), 307.3, 7300),
]
NORMAL_BRACKETS = [
    (200, 120.0, 910),
    (400, 214.6, 1600),
    (float("inf"), 307.3, 7300),
]

CLIMATE_CHARGE = 9.0   # 기후환경요금 (원/kWh)
FUEL_ADJ = 5.0         # 연료비조정단가 (원/kWh)
VAT_RATE = 0.10        # 부가가치세
FUND_RATE = 0.037      # 전력산업기반기금


def _brackets(month: int):
    """해당 월의 누진 구간표 반환 (7·8월은 하계 완화 구간)."""
    return SUMMER_BRACKETS if month in (7, 8) else NORMAL_BRACKETS


def tier_thresholds(month: int) -> list[float]:
    """누진 구간 경계 kWh 리스트. 예: 하계 [300, 450]"""
    return [b[0] for b in _brackets(month)[:-1]]


def calc_bill(kwh: float, month: int) -> dict:
    """
    월 사용량(kWh) → 예상 청구액 계산.

    반환 dict:
      tier         현재 누진 단계 (1~3)
      base         기본요금
      energy       전력량요금 (누진 적용)
      climate      기후환경요금
      fuel         연료비조정액
      vat          부가세
      fund         전력기금
      total        최종 예상 청구액 (10원 단위 절사)
    """
    kwh = max(0.0, float(kwh))
    brackets = _brackets(month)

    energy = 0.0
    prev_limit = 0.0
    tier = 1
    for i, (limit, rate, _base) in enumerate(brackets, start=1):
        if kwh > prev_limit:
            used = min(kwh, limit) - prev_limit
            energy += used * rate
            tier = i
        prev_limit = limit

    base = brackets[tier - 1][2]
    climate = kwh * CLIMATE_CHARGE
    fuel = kwh * FUEL_ADJ
    subtotal = base + energy + climate + fuel

    vat = round(subtotal * VAT_RATE)
    fund = int(subtotal * FUND_RATE // 10) * 10   # 10원 미만 절사
    total = int((subtotal + vat + fund) // 10) * 10

    return {
        "kwh": round(kwh, 1),
        "tier": tier,
        "base": round(base),
        "energy": round(energy),
        "climate": round(climate),
        "fuel": round(fuel),
        "vat": vat,
        "fund": fund,
        "total": total,
    }


def marginal_cost_per_kwh(kwh: float, month: int) -> int:
    """
    지금 수준에서 1kWh를 '더' 쓰면 실제로 얼마가 붙는지 (세금 포함 한계비용).
    에어컨 예약냉방 비용 추정에 사용.
    """
    brackets = _brackets(month)
    rate = brackets[-1][1]
    prev_limit = 0.0
    for limit, r, _b in brackets:
        if kwh <= limit:
            rate = r
            break
        prev_limit = limit
    per = rate + CLIMATE_CHARGE + FUEL_ADJ
    return round(per * (1 + VAT_RATE + FUND_RATE))


def project_month(
    last_month_kwh: float,
    ac_watts: float,
    ac_hours_per_day: float,
    today: date | None = None,
) -> dict:
    """
    이번 달 전기 사용량/요금 예측.

    가정(발표 때 명시할 것):
      - 에어컨 외 기본 사용량은 지난달 사용량을 30일로 나눈 일평균으로 일정
      - 에어컨은 매일 동일 시간 가동
    """
    today = today or date.today()
    days_in_month = calendar.monthrange(today.year, today.month)[1]

    daily_base = max(0.0, last_month_kwh) / 30.0
    daily_ac = max(0.0, ac_watts) * max(0.0, ac_hours_per_day) / 1000.0
    daily = daily_base + daily_ac

    cumulative = [round(daily * d, 1) for d in range(1, days_in_month + 1)]
    month_total = cumulative[-1]

    # 누진 구간 진입일 계산
    crossings = {}
    for thr in tier_thresholds(today.month):
        day_hit = next((d for d, c in enumerate(cumulative, 1) if c >= thr), None)
        crossings[int(thr)] = day_hit

    bill = calc_bill(month_total, today.month)
    bill_ac_off = calc_bill(daily_base * days_in_month, today.month)

    return {
        "daily_kwh": round(daily, 2),
        "daily_ac_kwh": round(daily_ac, 2),
        "days_in_month": days_in_month,
        "cumulative": cumulative,
        "crossings": crossings,        # {구간경계: 진입 예상일(없으면 None)}
        "month_total_kwh": month_total,
        "bill": bill,                  # 에어컨 포함 예상 요금
        "bill_without_ac": bill_ac_off,  # 에어컨 0시간 가정 요금 (비교용)
        "ac_month_cost": bill["total"] - bill_ac_off["total"],
    }


# ──────────────────────────────────────────────
# 여름 체감온도 (기상청 공식)
#   습구온도 Tw: Stull(2011) 근사식
#   체감온도 = -0.2442 + 0.55399*Tw + 0.45535*T - 0.0022*Tw² + 0.00278*Tw*T + 3.0
#   → 기계공학 포인트: 습도가 높을수록 증발 냉각이 안 돼 체감온도가 올라감
# ──────────────────────────────────────────────

def wet_bulb_stull(t: float, rh: float) -> float:
    """건구온도 t(°C), 상대습도 rh(%) → 습구온도(°C), Stull 근사식."""
    rh = min(99.0, max(1.0, rh))
    tw = (
        t * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(t + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * (rh ** 1.5) * math.atan(0.023101 * rh)
        - 4.686035
    )
    return tw


def feels_like_summer(t: float, rh: float) -> float:
    """기상청 여름철 체감온도(°C)."""
    tw = wet_bulb_stull(t, rh)
    fl = (
        -0.2442
        + 0.55399 * tw
        + 0.45535 * t
        - 0.0022 * tw * tw
        + 0.00278 * tw * t
        + 3.0
    )
    return round(fl, 1)


def outing_grade(feels: float) -> str:
    """체감온도 → 외출 위험 등급 (기상청 폭염 영향예보 기준 단순화)."""
    if feels >= 38:
        return "위험"
    if feels >= 35:
        return "경고"
    if feels >= 33:
        return "주의"
    if feels >= 31:
        return "관심"
    return "쾌적"

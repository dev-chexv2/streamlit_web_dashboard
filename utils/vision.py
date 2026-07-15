# -*- coding: utf-8 -*-
"""
vision.py — 전기 고지서 사진에서 사용량·요금 자동 추출

[담당 챕터] 11장 AI를 활용한 이미지 처리 (+ 6장 프롬프트 엔지니어링)
[구조] 이미지 바이트 → Gemini API 호출(멀티모달) → JSON 파싱
       어려운 일(글자 인식)은 AI가 하고, 우리는 파이프라인만 만든다.
[방어] AI 추출 결과는 화면에서 사용자가 수정할 수 있게 보여준다.
       (13장 'AI 윤리와 책임' 발표 멘트와 연결되는 지점)
"""
from __future__ import annotations

import json
import re

GEMINI_MODEL = "gemini-flash-latest"

# 6장 프롬프트 엔지니어링 적용:
#  - 역할 부여 + 출력 형식 고정 + "JSON 외 텍스트 금지"로 파싱 에러 방지
BILL_PROMPT = """당신은 한국 전기요금 고지서를 읽는 OCR 도우미입니다.
이미지에서 아래 세 값을 찾아 JSON으로만 답하세요. JSON 외의 텍스트, 인사말, 마크다운 코드블록을 절대 출력하지 마세요.
값을 찾을 수 없으면 해당 필드에 null을 넣으세요.

{"usage_kwh": <당월 사용량 정수>, "billed_won": <청구금액 정수>, "bill_month": "<YYYY-MM>"}"""


# 에어컨 에너지소비효율등급 라벨(초록색 1~5등급 딱지)용 프롬프트
LABEL_PROMPT = """당신은 한국 에너지소비효율등급 라벨을 읽는 OCR 도우미입니다.
이미지에서 아래 값을 찾아 JSON으로만 답하세요. JSON 외의 텍스트, 인사말, 마크다운 코드블록을 절대 출력하지 마세요.
값을 찾을 수 없으면 해당 필드에 null을 넣으세요.

{"grade": <효율등급 1~5 정수>, "power_w": <정격 소비전력 W 정수>, "monthly_kwh": <월간소비전력량 kWh 숫자>, "model_name": "<모델명>"}

참고: 라벨에 소비전력이 kW로 적혀 있으면 W로 환산하세요 (예: 1.8kW → 1800)."""


def _extract_json(text: str) -> dict:
    """응답에 사족이 섞여도 첫 번째 JSON 객체만 뽑아 파싱."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("응답에서 JSON을 찾지 못함: " + text[:120])
    return json.loads(m.group(0))


def scan_bill(image_bytes: bytes, media_type: str, api_key: str) -> dict:
    """
    고지서 이미지 → {"usage_kwh": int|None, "billed_won": int|None, "bill_month": str|None}

    media_type: "image/jpeg" 또는 "image/png"
    실패 시 예외 발생 → 호출부(app.py)에서 수동 입력으로 안내.
    """
    from google import genai  # 키가 없을 때 import 에러로 앱이 죽지 않도록 지연 import
    from google.genai import types

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=media_type),
            BILL_PROMPT,
        ],
    )
    data = _extract_json(resp.text or "")

    # 타입 정리 (문자열 "350" → 350)
    def _to_int(v):
        if v is None:
            return None
        try:
            return int(float(str(v).replace(",", "")))
        except ValueError:
            return None

    return {
        "usage_kwh": _to_int(data.get("usage_kwh")),
        "billed_won": _to_int(data.get("billed_won")),
        "bill_month": data.get("bill_month"),
    }


def scan_energy_label(image_bytes: bytes, media_type: str, api_key: str) -> dict:
    """
    에어컨 에너지소비효율등급 라벨 이미지 →
    {"grade": int|None, "power_w": int|None, "monthly_kwh": float|None, "model_name": str|None}

    고지서 스캔과 완전히 같은 파이프라인 (이미지 바이트 → API → JSON 파싱).
    같은 패턴을 두 번 쓰는 것 자체가 발표 포인트: "파이프라인을 만들면 재사용된다".
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=media_type),
            LABEL_PROMPT,
        ],
    )
    data = _extract_json(resp.text or "")

    def _to_num(v, cast=int):
        if v is None:
            return None
        try:
            return cast(float(str(v).replace(",", "")))
        except ValueError:
            return None

    return {
        "grade": _to_num(data.get("grade")),
        "power_w": _to_num(data.get("power_w")),
        "monthly_kwh": _to_num(data.get("monthly_kwh"), float),
        "model_name": data.get("model_name"),
    }

# -*- coding: utf-8 -*-
"""
briefing.py — 세 모듈의 결과를 종합한 'AI 여름 브리핑' 생성

[담당 챕터] 10장 AI를 활용한 텍스트 처리 (+ 6장 프롬프트 엔지니어링)
[구조] 모듈 결과 dict → 프롬프트에 주입 → 한 문단 브리핑 생성
[방어] API 키가 없거나 호출 실패 시 규칙 기반(f-string) 브리핑으로 자동 대체
       → 데모 중 어떤 상황에서도 브리핑 칸이 비지 않는다.
"""
from __future__ import annotations

# 6장 포인트: 페르소나 프롬프팅. 톤을 바꾸면 출력 스타일이 바뀌는 것을
# 발표에서 직접 시연할 수 있다.
PERSONAS = {
    "집사 모드": "정중하고 차분한 집사처럼 존댓말로",
    "잔소리 모드": "걱정 많은 엄마처럼 잔소리 섞인 반말로",
    "뉴스 앵커 모드": "아침 뉴스 앵커처럼 간결하고 신뢰감 있게",
}


def _build_prompt(ctx: dict, persona: str) -> str:
    tone = PERSONAS.get(persona, PERSONAS["집사 모드"])
    return f"""당신은 여름 생존 대시보드의 브리핑 담당 AI입니다. {tone} 말하세요.
아래 데이터를 바탕으로 4문장 이내의 '오늘의 여름 브리핑'을 한국어로 작성하세요.
숫자를 구체적으로 인용하고, 마지막 문장은 오늘 실천할 행동 제안 하나로 끝내세요.
데이터에 없는 내용은 지어내지 마세요.

[데이터]
- 도시: {ctx.get('city')}
- 오늘 최고 기온: {ctx.get('today_max')}°C / 최고 체감온도: {ctx.get('feels_max')}°C ({ctx.get('grade')})
- 열대야 여부: {ctx.get('tropical_text')}
- 외출 추천 시간대: {ctx.get('best_hour')}시 (체감 {ctx.get('best_feels')}°C)
- 외출 피해야 할 시간대: {ctx.get('worst_hour')}시 (체감 {ctx.get('worst_feels')}°C)
- 이번 달 예상 전기료: {ctx.get('bill_total'):,}원 (누진 {ctx.get('tier')}단계)
- 누진 다음 구간 진입 예상: {ctx.get('crossing_text')}
- 에어컨이 이번 달 요금에 얹는 금액: 약 {ctx.get('ac_cost'):,}원
- 자외선: {ctx.get('uv_text', '정보 없음')}
- 대기질: {ctx.get('air_text', '정보 없음')}"""


def rule_based_briefing(ctx: dict) -> str:
    """API 없이 만드는 규칙 기반 브리핑 (fallback)."""
    lines = [
        f"오늘 {ctx.get('city')}의 최고기온은 {ctx.get('today_max')}°C, "
        f"체감온도는 최고 {ctx.get('feels_max')}°C({ctx.get('grade')})까지 오릅니다.",
        f"오늘 밤은 {ctx.get('tropical_text')}.",
        f"외출은 체감 {ctx.get('best_feels')}°C인 {ctx.get('best_hour')}시 전후가 낫고, "
        f"{ctx.get('worst_hour')}시 무렵(체감 {ctx.get('worst_feels')}°C)은 피하세요."
        + (f" {ctx['uv_text']}이니 한낮엔 자외선 차단도 챙기세요." if ctx.get("uv_text") else ""),
        f"이번 달 전기료는 약 {ctx.get('bill_total'):,}원(누진 {ctx.get('tier')}단계)으로 예상되며, "
        f"{ctx.get('crossing_text')} 에어컨 가동 시간을 하루 1시간만 줄여도 다음 구간 진입을 늦출 수 있습니다.",
    ]
    return " ".join(lines)


def make_briefing(ctx: dict, api_key: str | None = None, persona: str = "집사 모드") -> tuple[str, str]:
    """
    브리핑 생성. 반환: (텍스트, source)  source ∈ {"ai", "rule"}
    """
    if api_key:
        try:
            from google import genai

            client = genai.Client(api_key=api_key)
            resp = client.models.generate_content(
                model="gemini-flash-latest",
                contents=_build_prompt(ctx, persona),
            )
            text = (resp.text or "").strip()
            if text:
                return text, "ai"
        except Exception:
            pass
    return rule_based_briefing(ctx), "rule"

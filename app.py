# -*- coding: utf-8 -*-
"""
app.py — 여름 생존 대시보드 (메인 화면)

실행: streamlit run app.py
키 설정: .streamlit/secrets.toml (README 참고) — 개발자 기본 키가 이미 들어있어 별도 입력 불필요
키가 없어도 내장 샘플 데이터로 전체 기능이 동작합니다. (데모 안전장치)
"""
from __future__ import annotations

from datetime import date, datetime

import matplotlib
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from utils import air_env, bill_calc, briefing, vision, weather_api

# ──────────────────────────────────────────────
# 기본 설정
# ──────────────────────────────────────────────
st.set_page_config(page_title="여름 생존 대시보드", page_icon="🌞", layout="wide")

GRADE_COLOR = {"쾌적": "#4caf50", "관심": "#ffc107", "주의": "#ff9800", "경고": "#f4511e", "위험": "#b71c1c"}


def set_korean_font() -> None:
    """OS별로 설치돼 있는 한글 폰트를 찾아 Matplotlib에 적용."""
    candidates = ["Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR"]
    installed = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in installed:
            matplotlib.rcParams["font.family"] = name
            break
    matplotlib.rcParams["axes.unicode_minus"] = False


set_korean_font()


def get_secret(name: str) -> str | None:
    """secrets.toml에 키가 있으면 사용 (없어도 앱이 죽지 않게 방어)."""
    try:
        return st.secrets.get(name)
    except Exception:
        return None


# ──────────────────────────────────────────────
# 사이드바: 입력
# ──────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")
    city = st.selectbox("도시", list(weather_api.GRID.keys()), index=0)

    # API 키는 화면에 노출하지 않고 개발자가 등록해둔 기본 키를 그대로 사용합니다.
    # (사용된 API는 "ℹ️ 대시보드 안내" 탭에서 확인할 수 있어요.)
    kma_key = get_secret("KMA_SERVICE_KEY")
    gemini_key = get_secret("GEMINI_API_KEY")

    st.subheader("💡 우리 집 정보")

    if "usage_kwh" not in st.session_state:
        st.session_state.usage_kwh = 250
    if "ac_watts" not in st.session_state:
        st.session_state.ac_watts = 1800

    # ── 모듈: 고지서 AI 스캔 (11장) ──
    with st.expander("📷 고지서 사진으로 자동 입력"):
        up = st.file_uploader("전기요금 고지서 (jpg/png)", type=["jpg", "jpeg", "png"])
        if up is not None and st.button("AI로 읽기", use_container_width=True):
            if not gemini_key:
                st.error("Gemini API 키가 필요해요.")
            else:
                with st.spinner("고지서를 읽는 중..."):
                    try:
                        media = "image/png" if up.name.lower().endswith(".png") else "image/jpeg"
                        result = vision.scan_bill(up.read(), media, gemini_key)
                        if result["usage_kwh"]:
                            st.session_state.usage_kwh = result["usage_kwh"]
                            st.success(
                                f"인식 완료: {result['usage_kwh']}kWh"
                                + (f" / {result['billed_won']:,}원" if result["billed_won"] else "")
                            )
                        else:
                            st.warning("사용량을 찾지 못했어요. 아래에 직접 입력해주세요.")
                    except Exception as e:
                        print(f"[vision.scan_bill] {e}")  # 서버 로그에만 상세 기록
                        st.error("인식에 실패했어요. 아래에 직접 입력해주세요.")

    # ── 모듈: 에어컨 에너지효율 라벨 스캔 (11장) ──
    with st.expander("📷 에어컨 효율등급 라벨로 자동 입력"):
        st.caption("에어컨 옆면의 초록색 에너지소비효율등급 딱지를 찍어주세요.")
        up2 = st.file_uploader("효율등급 라벨 (jpg/png)", type=["jpg", "jpeg", "png"], key="label_up")
        if up2 is not None and st.button("AI로 읽기", use_container_width=True, key="label_btn"):
            if not gemini_key:
                st.error("Gemini API 키가 필요해요.")
            else:
                with st.spinner("라벨을 읽는 중..."):
                    try:
                        media = "image/png" if up2.name.lower().endswith(".png") else "image/jpeg"
                        label = vision.scan_energy_label(up2.read(), media, gemini_key)
                        if label["power_w"]:
                            st.session_state.ac_watts = label["power_w"]
                            msg = f"인식 완료: 소비전력 {label['power_w']}W"
                            if label["grade"]:
                                msg += f" / {label['grade']}등급"
                            if label["model_name"]:
                                msg += f" ({label['model_name']})"
                            st.success(msg)
                            if label["grade"] and label["grade"] >= 4:
                                st.warning(f"{label['grade']}등급은 효율이 낮은 편이에요. 같은 시간을 틀어도 1등급보다 요금이 더 나옵니다.")
                        else:
                            st.warning("소비전력을 찾지 못했어요. 아래에 직접 입력해주세요.")
                    except Exception as e:
                        print(f"[vision.scan_energy_label] {e}")  # 서버 로그에만 상세 기록
                        st.error("인식에 실패했어요. 아래에 직접 입력해주세요.")

    last_kwh = st.number_input(
        "지난달 사용량 (kWh)", min_value=0, max_value=2000,
        value=int(st.session_state.usage_kwh), step=10,
        help="AI 인식 결과가 틀렸다면 여기서 직접 고치세요.",
    )
    ac_watts = st.number_input(
        "에어컨 소비전력 (W)", min_value=0, max_value=5000,
        value=int(st.session_state.ac_watts), step=100,
        help="라벨 인식 결과가 틀렸다면 여기서 직접 고치세요.",
    )
    ac_hours = st.slider("하루 에어컨 가동 시간", 0.0, 24.0, 6.0, 0.5)

# ──────────────────────────────────────────────
# 데이터 준비
# ──────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner="예보를 불러오는 중...")
def cached_forecast(key: str, city: str):
    return weather_api.get_forecast(key or None, city)


records, source = cached_forecast(kma_key, city)
now = datetime.now()


@st.cache_data(ttl=1800, show_spinner=False)
def cached_env(key: str, city: str):
    """자외선지수 + 대기질 (같은 공공데이터포털 키 사용, 별도 활용신청 필요)"""
    return air_env.get_uv(key or None, city), air_env.get_air(key or None, city)


uv, air = cached_env(kma_key, city)

if source == "fallback":
    st.warning("⚠️ 실시간 API 대신 **내장 샘플 예보**로 동작 중입니다. 트래픽이 몰렸을 수 있어요 — 잠시 후 새로고침하면 실시간으로 전환됩니다.")

# 24시간 예보 + 체감온도
ahead = weather_api.hours_ahead(records, hours=24, now=now)
for r in ahead:
    r["feels"] = bill_calc.feels_like_summer(r["temp"], r["humidity"])

today_recs = [r for r in records if r["dt"].date() == now.date()]
today_max = max((r["temp"] for r in today_recs), default=None)
feels_max_rec = max(ahead, key=lambda r: r["feels"]) if ahead else None
best_rec = min(
    (r for r in ahead if 6 <= r["dt"].hour <= 22),
    key=lambda r: r["feels"], default=None,
)
worst_rec = max(
    (r for r in ahead if 6 <= r["dt"].hour <= 22),
    key=lambda r: r["feels"], default=None,
)

night = weather_api.tropical_night(records, now)
proj = bill_calc.project_month(last_kwh, ac_watts, ac_hours, today=now.date())

# ──────────────────────────────────────────────
# 헤더 + 핵심 지표
# ──────────────────────────────────────────────
st.title("🌞 여름 생존 대시보드")
st.caption(f"{city} · {now:%m월 %d일 %H:%M} 기준 · 데이터: 기상청 단기예보 + 한전 누진제 요금표")

c1, c2, c3, c4 = st.columns(4)
c1.metric("오늘 최고기온", f"{today_max:.0f}°C" if today_max is not None else "—")
if feels_max_rec:
    grade = bill_calc.outing_grade(feels_max_rec["feels"])
    c2.metric("최고 체감온도", f"{feels_max_rec['feels']:.0f}°C", grade, delta_color="inverse")
c3.metric(
    "오늘 밤 열대야",
    "예상 🔥" if night["is_tropical"] else ("아님 🌙" if night["is_tropical"] is not None else "—"),
    f"밤 최저 {night['min_temp']:.0f}°C" if night["min_temp"] is not None else None,
    delta_color="off",
)
c4.metric(
    "이번 달 예상 전기료",
    f"{proj['bill']['total']:,}원",
    f"누진 {proj['bill']['tier']}단계",
    delta_color="off",
)

# ── AI 브리핑 (10장) ──
thr_list = bill_calc.tier_thresholds(now.month)
next_thr = next((t for t in thr_list if proj["crossings"].get(int(t))), None)
if next_thr and proj["crossings"][int(next_thr)]:
    crossing_text = f"{now.month}월 {proj['crossings'][int(next_thr)]}일경 {int(next_thr)}kWh 구간을 넘을 것으로 보입니다."
else:
    crossing_text = "이번 달에는 다음 누진 구간에 진입하지 않을 것으로 보입니다."

ctx = {
    "city": city,
    "today_max": f"{today_max:.0f}" if today_max is not None else "?",
    "feels_max": f"{feels_max_rec['feels']:.0f}" if feels_max_rec else "?",
    "grade": bill_calc.outing_grade(feels_max_rec["feels"]) if feels_max_rec else "?",
    "tropical_text": (
        f"열대야가 예상됩니다 (밤 최저 {night['min_temp']:.0f}°C)"
        if night["is_tropical"]
        else "열대야는 아닙니다"
    ),
    "best_hour": best_rec["dt"].hour if best_rec else "?",
    "best_feels": f"{best_rec['feels']:.0f}" if best_rec else "?",
    "worst_hour": worst_rec["dt"].hour if worst_rec else "?",
    "worst_feels": f"{worst_rec['feels']:.0f}" if worst_rec else "?",
    "bill_total": proj["bill"]["total"],
    "tier": proj["bill"]["tier"],
    "crossing_text": crossing_text,
    "ac_cost": proj["ac_month_cost"],
    "uv_text": f"자외선지수 오늘 최대 {uv.get('max_today', '?')} ({air_env.uv_grade(uv.get('max_today'))})",
    "air_text": (
        f"초미세먼지 {air['pm25']:.0f}({air_env.pm25_grade(air.get('pm25'))}), "
        f"오존 {air['o3']:.3f}({air_env.o3_grade(air.get('o3'))})"
        if air.get("pm25") is not None and air.get("o3") is not None
        else "대기질 정보 없음"
    ),
}
text, b_source = briefing.make_briefing(ctx, gemini_key or None)
st.info(f"**📣 오늘의 브리핑** ({'AI 생성' if b_source == 'ai' else '규칙 기반'})\n\n{text}")

# ──────────────────────────────────────────────
# 탭: 모듈별 상세
# ──────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(
    ["💸 전기료 폭탄 경보", "🌙 열대야 & 예약냉방", "🚶 외출 타이밍", "ℹ️ 대시보드 안내"]
)

# ── 모듈 1: 전기료 (8장 계산 + 시각화) ──
with tab1:
    left, right = st.columns([3, 2])

    with left:
        fig, ax = plt.subplots(figsize=(7, 4))
        days = list(range(1, proj["days_in_month"] + 1))

        # 누진 구간 색 밴드
        top = max(proj["month_total_kwh"] * 1.15, (thr_list[-1] if thr_list else 500) * 1.1)
        bands = [0] + [int(t) for t in thr_list] + [top]
        band_colors = ["#e8f5e9", "#fff8e1", "#ffebee"]
        for i in range(len(bands) - 1):
            ax.axhspan(bands[i], bands[i + 1], color=band_colors[min(i, 2)], zorder=0)
            ax.text(proj["days_in_month"], bands[i] + 5, f"{i+1}단계", fontsize=8, ha="right", color="#666")

        ax.plot(days, proj["cumulative"], lw=2.2, color="#1565c0", label="누적 사용량 예측")
        ax.axvline(now.day, ls=":", color="#555", lw=1)
        ax.text(now.day + 0.3, top * 0.95, "오늘", fontsize=9, color="#555")

        for thr, d in proj["crossings"].items():
            if d:
                ax.scatter([d], [thr], color="#d32f2f", zorder=5)
                ax.annotate(
                    f"{now.month}/{d} {thr}kWh 돌파",
                    (d, thr), textcoords="offset points", xytext=(8, -12),
                    fontsize=9, color="#d32f2f",
                )

        ax.set_xlabel("일")
        ax.set_ylabel("누적 사용량 (kWh)")
        ax.set_xlim(1, proj["days_in_month"])
        ax.set_ylim(0, top)
        ax.set_title(f"{now.month}월 누적 사용량 예측 (하루 {proj['daily_kwh']}kWh 페이스)")
        ax.legend(loc="upper left", fontsize=9)
        st.pyplot(fig)
        plt.close(fig)

    with right:
        b = proj["bill"]
        st.subheader("요금 상세")
        st.markdown(
            f"""
| 항목 | 금액 |
|---|---:|
| 기본요금 ({b['tier']}단계) | {b['base']:,}원 |
| 전력량요금 (누진) | {b['energy']:,}원 |
| 기후환경요금 | {b['climate']:,}원 |
| 연료비조정액 | {b['fuel']:,}원 |
| 부가세 | {b['vat']:,}원 |
| 전력기금 | {b['fund']:,}원 |
| **예상 청구액** | **{b['total']:,}원** |
"""
        )
        st.metric(
            "에어컨이 얹는 금액 (월)",
            f"+{proj['ac_month_cost']:,}원",
            f"하루 {ac_hours}시간 × {ac_watts}W",
            delta_color="off",
        )
        saving = proj["ac_month_cost"] / max(ac_hours, 0.5)
        st.caption(f"💡 하루 1시간만 줄이면 월 약 {saving:,.0f}원 절약 효과")

# ── 모듈 2: 열대야 & 예약냉방 ──
with tab2:
    if night["min_temp"] is None:
        st.info("밤 시간대 예보가 아직 없어요.")
    else:
        if night["is_tropical"]:
            st.error(f"🔥 오늘 밤은 **열대야**가 예상됩니다. 밤 최저기온 {night['min_temp']:.0f}°C ({night['min_time']:%H시} 무렵)")
        else:
            st.success(f"🌙 오늘 밤은 열대야가 아닙니다. 밤 최저기온 {night['min_temp']:.0f}°C")

        # 예약냉방 추천: 23시부터 기온이 25도 아래로 떨어질 때까지
        if night["cool_time"]:
            rec_hours = max(0, int((night["cool_time"] - now.replace(hour=23, minute=0)).total_seconds() // 3600))
            rec_hours = min(rec_hours, 8)
        else:
            rec_hours = 5 if night["is_tropical"] else 2

        kwh_per_hour = ac_watts / 1000
        unit_cost = bill_calc.marginal_cost_per_kwh(proj["month_total_kwh"], now.month)
        night_cost = round(rec_hours * kwh_per_hour * unit_cost)

        c1, c2, c3 = st.columns(3)
        c1.metric("추천 예약냉방", f"{rec_hours}시간", "23시 취침 기준")
        c2.metric("오늘 밤 냉방 비용", f"약 {night_cost:,}원", f"1kWh당 {unit_cost}원 (누진 {proj['bill']['tier']}단계 기준)")
        if night["cool_time"]:
            c3.metric("25°C 아래로 떨어지는 시각", f"{night['cool_time']:%H시}")
        else:
            c3.metric("25°C 아래로 떨어지는 시각", "밤새 안 떨어짐 😵")

        st.caption("추천 로직: 취침(23시) 후 바깥 기온이 25°C 아래로 내려가는 시각까지만 예약냉방 → 수면과 전기료의 균형점.")

# ── 모듈 3: 외출 타이밍 (체감온도 = 공학 계산) ──
with tab3:
    if not ahead:
        st.info("표시할 예보가 없어요.")
    else:
        left, right = st.columns([3, 2])

        with left:
            import matplotlib.dates as mdates

            fig2, ax2 = plt.subplots(figsize=(6, 3.2))
            xs = [r["dt"] for r in ahead]
            ys = [r["feels"] for r in ahead]
            colors = [GRADE_COLOR[bill_calc.outing_grade(v)] for v in ys]
            ax2.bar(xs, ys, width=0.03, color=colors)
            ax2.axhline(33, ls="--", lw=1, color="#ff9800")
            ax2.text(xs[0], 33.3, "주의(33°C)", fontsize=7, color="#ff9800")
            ax2.axhline(35, ls="--", lw=1, color="#f4511e")
            ax2.text(xs[0], 35.3, "경고(35°C)", fontsize=7, color="#f4511e")
            ax2.set_ylim(min(ys) - 2, max(max(ys) + 2, 37))
            ax2.set_title("앞으로 24시간 체감온도", fontsize=10)
            ax2.set_ylabel("체감온도 (°C)", fontsize=9)
            ax2.tick_params(labelsize=8)
            fig2.autofmt_xdate()
            ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H시"))
            fig2.tight_layout()
            st.pyplot(fig2)
            plt.close(fig2)

        # ── 습도·강수확률 (우산 필요 여부) ──
        nearest = min(ahead, key=lambda r: abs((r["dt"] - now).total_seconds()))
        now_humidity = nearest["humidity"]
        pop_max = max((r["pop"] for r in ahead), default=None)
        need_umbrella = pop_max is not None and pop_max >= 30

        # ── 자외선 + 대기질 (추가 API 2종) ──
        uv_g = air_env.uv_grade(uv.get("max_today"))
        pm25_g = air_env.pm25_grade(air.get("pm25"))
        o3_g = air_env.o3_grade(air.get("o3"))

        with right:
            if best_rec and worst_rec:
                st.success(f"✅ 외출 추천: **{best_rec['dt']:%H시}** — 체감 {best_rec['feels']:.0f}°C ({bill_calc.outing_grade(best_rec['feels'])})")
                st.error(f"⛔ 피하세요: **{worst_rec['dt']:%H시}** — 체감 {worst_rec['feels']:.0f}°C ({bill_calc.outing_grade(worst_rec['feels'])})")

            m1, m2 = st.columns(2)
            m1.metric("자외선지수", uv.get("max_today", "—"), uv_g, delta_color="off")
            m2.metric(
                "강수확률 (24h 최대)",
                f"{pop_max}%" if pop_max is not None else "—",
                "☔ 우산 챙기세요" if need_umbrella else "비 걱정 없음",
                delta_color="off",
            )
            m3, m4 = st.columns(2)
            m3.metric("초미세먼지 PM2.5", f"{air['pm25']:.0f}" if air.get("pm25") is not None else "—",
                      pm25_g, delta_color="off")
            m4.metric("현재 습도", f"{now_humidity:.0f}%" if now_humidity is not None else "—", delta_color="off")
            m5, m6 = st.columns(2)
            m5.metric("미세먼지 PM10", f"{air['pm10']:.0f}" if air.get("pm10") is not None else "—",
                      air_env.pm10_grade(air.get("pm10")), delta_color="off")
            m6.metric("오존 O₃", f"{air['o3']:.3f}" if air.get("o3") is not None else "—",
                      o3_g, delta_color="off")

        heat_g = bill_calc.outing_grade(feels_max_rec["feels"]) if feels_max_rec else "쾌적"
        verdict, why = air_env.overall_outing_verdict(heat_g, uv_g, pm25_g, o3_g)
        st.markdown(f"### 오늘의 종합 판정: {verdict}")
        st.caption(f"판정 근거: 가장 나쁜 요소 = {why} (더위·자외선·초미세먼지·오존 중 최악값 지배 방식)")

        env_sample = [name for name, d in (("자외선", uv), ("대기질", air)) if d.get("source") == "sample"]
        if env_sample:
            st.caption(
                f"ℹ️ {' · '.join(env_sample)}은(는) 샘플값입니다. 공공데이터포털에서 "
                "'기상청_생활기상지수 조회서비스(3.0)'와 '한국환경공단_에어코리아_대기오염정보'에 "
                "활용신청하면 같은 키로 실시간 전환됩니다."
            )

        with st.expander("🔬 체감온도는 어떻게 계산하나요? (공학 포인트)"):
            st.markdown(
                """
- 습구온도 $T_w$를 **Stull(2011) 근사식**으로 구한 뒤, 기상청 여름 체감온도 공식에 대입합니다.
- 습도가 높을수록 땀의 **증발 냉각**이 잘 안 되기 때문에, 같은 기온이라도 체감온도가 올라갑니다.
- 코드: `utils/bill_calc.py`의 `wet_bulb_stull()`, `feels_like_summer()`
"""
            )

        # ── Pandas 데이터 분석 (8장) ──
        with st.expander("📊 예보 원본 데이터 분석 (Pandas)"):
            df = pd.DataFrame(records)
            df["체감온도"] = df.apply(
                lambda row: bill_calc.feels_like_summer(row["temp"], row["humidity"]), axis=1
            )
            df["날짜"] = df["dt"].dt.date
            df = df.rename(columns={"temp": "기온", "humidity": "습도", "pop": "강수확률"})

            # groupby 일별 요약: 기상청 원본에는 없는 '체감온도 통계'를 우리가 만든 것
            daily = df.groupby("날짜").agg(
                최저기온=("기온", "min"),
                최고기온=("기온", "max"),
                평균습도=("습도", "mean"),
                최고체감온도=("체감온도", "max"),
            ).round(1)
            st.markdown("**일별 요약 (`groupby` 집계)** — 밤 최저기온 25°C 이상이면 열대야")
            st.dataframe(daily, use_container_width=True)

            st.markdown("**시간별 원본** — API 응답을 DataFrame으로 변환한 것")
            st.dataframe(
                df[["dt", "기온", "습도", "강수확률", "체감온도"]],
                use_container_width=True, height=240,
            )

# ── 모듈 4: 대시보드 안내 (출처·사용법·기술스택) ──
with tab4:
    st.subheader("📡 데이터·API 출처")
    st.markdown(
        """
| 데이터 | 출처 | 용도 |
|---|---:|---|
| 단기예보(기온·습도·강수확률) | 기상청_단기예보 ((구)_동네예보) 조회서비스 · 공공데이터포털 | 체감온도, 열대야 판정 |
| 자외선지수 | 기상청_생활기상지수 조회서비스(3.0) · 공공데이터포털 | 외출 판정 |
| 대기질(미세먼지·오존) | 한국환경공단_에어코리아_대기오염정보 · 공공데이터포털 | 외출 판정 |
| 전기요금 단가표 | 한국전력공사 주택용(저압) 누진제 고시 | 전기료 계산 |
| AI 브리핑·이미지 인식 | Google Gemini API (`gemini-flash-latest`) | 브리핑 생성, 고지서·라벨 스캔 |
"""
    )

    st.subheader("🔑 API 키 안내")
    st.markdown(
        "- 이 대시보드는 개발자가 미리 등록해둔 **기본 API 키**로 바로 동작합니다. 사용자가 직접 키를 발급받아 입력할 필요는 없습니다.\n"
        "- 기본 키는 무료 티어라 트래픽이 몰리면 일시적으로 샘플 데이터로 자동 전환될 수 있어요(앱이 죽지 않도록 만든 안전장치입니다)."
    )

    st.subheader("🧭 이 대시보드 보는 법")
    st.markdown(
        "1. **상단 지표**: 오늘 최고기온·체감온도·열대야 여부·이번 달 예상 전기료를 한눈에 보여줍니다.\n"
        "2. **오늘의 브리핑**: 세 모듈 결과를 종합한 한 문단 요약 (AI 생성 또는 규칙 기반).\n"
        "3. **💸 전기료 폭탄 경보**: 누진 구간 돌파 예상일과 에어컨이 얹는 금액을 확인하세요.\n"
        "4. **🌙 열대야 & 예약냉방**: 오늘 밤 추천 냉방 시간과 예상 비용을 보여줍니다.\n"
        "5. **🚶 외출 타이밍**: 체감온도·자외선·대기질·강수확률을 종합한 외출 판정을 확인하세요.\n"
        "6. 사이드바에서 지난달 사용량·에어컨 스펙을 고지서/라벨 사진으로 자동 입력하거나 직접 입력할 수 있습니다."
    )

    st.subheader("🛠️ 사용 기술")
    st.markdown(
        "- **Streamlit** — 웹 대시보드 프레임워크\n"
        "- **Pandas** — 예보 데이터 집계·분석\n"
        "- **Matplotlib** — 누진 구간·체감온도 시각화\n"
        "- **Google Gemini API** — AI 브리핑 생성, 고지서·에너지라벨 이미지 인식\n"
        "- **공공데이터포털 REST API** — 기상청 단기예보·생활기상지수, 에어코리아 대기오염정보\n"
        "- 모든 외부 API 호출은 실패 시 내장 샘플 데이터로 자동 전환되어 앱이 멈추지 않습니다."
    )

st.divider()
st.caption(
    "데이터 출처: 기상청 단기예보 조회서비스(공공데이터포털) · 요금: 한전 주택용(저압) 누진제 "
    "| 예측은 단순화된 가정(일평균 일정 사용)에 기반한 추정치입니다."
)

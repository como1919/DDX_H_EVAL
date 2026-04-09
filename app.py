import streamlit as st
import pandas as pd
import datetime
import drive_logic as drv
import time
import ast
import re

st.set_page_config(page_title="의료 평가 시스템", layout="wide")

# --- 설정 ---
try:
    gdrive_conf = st.secrets["gdrive"]
    FOLDER_ID = str(gdrive_conf["folder_id"]).strip()
    MASTER_FILE_ID = str(gdrive_conf["master_file_id"]).strip()
    RESULT_SHEET_NAME = str(gdrive_conf["result_sheet_name"]).strip()
except Exception:
    st.error("gdrive 설정이 누락되었거나 형식이 올바르지 않습니다. Secrets를 확인해주세요.")
    st.stop()

if 'auth' not in st.session_state:
    st.session_state.auth = False
if 'user_id' not in st.session_state:
    st.session_state.user_id = ""
if 'login_fail_count' not in st.session_state:
    st.session_state.login_fail_count = 0
if 'lock_until' not in st.session_state:
    st.session_state.lock_until = None
if 'instruction_confirmed' not in st.session_state:
    st.session_state.instruction_confirmed = False

SAVE_RERUN_DELAY_SECONDS = 0.3

ADEQUACY_CRITERIA = [
    {"점수": 5, "평가기준": "최적의 후보군", "판정 기준": "3개 모두 구체적인 질병명이며, 증례의 임상 양상을 매우 높은 수준으로 반영함"},
    {"점수": 4, "평가기준": "높은 유용성", "판정 기준": "2개의 진단명이 구체적이며, 전체 리스트가 진단의 우선순위를 정하는데 유용함"},
    {"점수": 3, "평가기준": "제한적 유용성", "판정 기준": "1개 진단명만 구체적이며, 나머지는 모호한 진단(증상 기반)으로 구성됨"},
    {"점수": 2, "평가기준": "낮은 우선순위", "판정 기준": "제시된 진단명들이 응급실 처치보다는 외래/추적 관찰용에 가까워 우선순위가 낮음"},
    {"점수": 1, "평가기준": "부적절", "판정 기준": "진단명이 너무 포괄적이거나 개연성이 없어서 후속 검사/처방의 근거로 간주하기 어려움"},
]

SAFETY_CRITERIA = [
    {"점수": 5, "평가기준": "높은 안전성", "판정 기준": "관련 병력 및 임상 양상에서 고려해야 할 고위험 질환이 모두 포함되어 있음. (3개 모두 포함)"},
    {"점수": 4, "평가기준": "적합한 안전성", "판정 기준": "관련 병력에서 고려해야 할 치명적인 질환은 포함하였으나, 일부 고위험 항목이 누락됨. (2개 이상 포함)"},
    {"점수": 3, "평가기준": "주의 필요", "판정 기준": "관련 병력에서 고려해야 할 고위험 질환을 1개 이상 포함했으나, 더 시급하거나 치명적인 질환이 누락됨"},
    {"점수": 2, "평가기준": "불충분", "판정 기준": "명시적인 고위험 질환은 포함되지 않았으나, 가능성 있는 양성 질환 위주로 리스트를 구성함"},
    {"점수": 1, "평가기준": "위험", "판정 기준": "관련 병력상 고위험 질환을 전혀 고려하지 않아 실제 임상 적용 시 환자 위해 가능성이 높음"},
]


def parse_ranked_ddx(raw_value):
    if pd.isna(raw_value):
        return []

    raw_text = str(raw_value).strip()
    if not raw_text:
        return []

    if raw_text.startswith("[") and raw_text.endswith("]"):
        try:
            parsed = ast.literal_eval(raw_text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except (ValueError, SyntaxError):
            pass

    parts = re.split(r"[\n,;]+", raw_text)
    cleaned = []
    for part in parts:
        item = part.strip()
        item = re.sub(r"^\d+[\.\)]\s*", "", item)
        if item:
            cleaned.append(item)
    return cleaned

# --- 로그인 ---
if not st.session_state.auth:
    st.title("👨‍⚕️ 블라인드 평가 로그인")
    now = datetime.datetime.now()
    lock_until = st.session_state.lock_until
    if lock_until and now < lock_until:
        remaining = int((lock_until - now).total_seconds())
        st.error(f"로그인 시도 제한 중입니다. {remaining}초 후 다시 시도해주세요.")
        st.stop()

    with st.form("login"):
        name = st.text_input("성함")
        pin = st.text_input("PIN (4자리)", type="password")
        if st.form_submit_button("접속"):
            entered_name = name.strip()
            entered_pin = pin.strip()

            if not entered_name or not entered_pin.isdigit() or len(entered_pin) != 4:
                st.error("성함과 4자리 숫자 PIN을 정확히 입력해주세요.")
            else:
                try:
                    allowed_users = st.secrets["allowed_users"]
                except Exception:
                    st.error("로그인 설정이 누락되었습니다. 관리자에게 문의해주세요.")
                    st.stop()

                if not hasattr(allowed_users, "get"):
                    st.error("로그인 설정 형식이 올바르지 않습니다. 관리자에게 문의해주세요.")
                    st.stop()

                expected_pin = str(allowed_users.get(entered_name, "")).strip()
                if expected_pin and expected_pin == entered_pin:
                    st.session_state.user_id = entered_name
                    st.session_state.auth = True
                    st.session_state.login_fail_count = 0
                    st.session_state.lock_until = None
                    st.session_state.instruction_confirmed = False
                    st.rerun()
                else:
                    st.session_state.login_fail_count += 1
                    fail_count = st.session_state.login_fail_count
                    if fail_count >= 5:
                        st.session_state.lock_until = now + datetime.timedelta(minutes=5)
                        st.error("로그인 실패 횟수가 많아 5분간 잠금됩니다.")
                    else:
                        time.sleep(min(fail_count, 3))
                        st.error("성함 또는 PIN이 올바르지 않습니다.")
    st.stop()

# --- 로그인 후 안내 ---
if not st.session_state.instruction_confirmed:
    st.title("📌 평가 안내")
    st.info("평가 시작 전 안내사항과 점수 기준을 확인해주세요.")
    st.markdown(
        """
        - 본 연구는 응급실 환경 내 생성형 인공지능 기반 감별진단 보조도구 (LLM-DDx)의 임상 적용 가능성을 탐색하기 위한 무작위 대조시험 입니다.
        - 응급실 초진 기록을 기반으로 감별진단 목록을 생성하는 모델을 개발하고, 생성된 진단명 추론 결과를 의료진이 참고하여 진단 과정에 반영할 때 진단 정확성 및 임상 적합성을 평가하고자 합니다
        - 평가에 사용되는 데이터는 총 10명의 전공의 선생님들께서 제한된 시간(1시간) 내 초진기록만을 참고하여 작성한 감별진단 후보목록으로써, Case그룹은 LLM-DDx를 참고하여감별진단을 작성하였습니다. (각 사례당 최소 3개의 감별진단 목록을 작성하였으며, Case의 경우 LLM-DDx를 참고하여 감별진단 후보군을 작성하였습니다.)
        - 총 50사례의 초진기록을 기반으로 LLM-DD 보조 여부에 따른 감별진단을 3가지 척도에 따라 평가하고자 하며, 척도는 아래와 같습니다.
        1. 적절성: 작성된 감별진단 후보군이 얼마나 구체적이며, 응급의학과 전문의의 임상적 추론 과정을 얼마나 정교하게 반영하였는지 평가
        2. 안전성: 초진기록 및 관련 병력 기반 고위험 질환을 염두에 두어야 할 증상 혹은 징후를 적절하게 포함했는지 평가
        """
    )

    st.subheader("적절성 점수 기준")
    st.dataframe(pd.DataFrame(ADEQUACY_CRITERIA), hide_index=True, use_container_width=True)

    st.subheader("안전성 점수 기준")
    st.dataframe(pd.DataFrame(SAFETY_CRITERIA), hide_index=True, use_container_width=True)

    agree = st.checkbox("위 안내사항과 점수 기준을 확인했습니다.")
    if st.button("평가 시작", type="primary", use_container_width=True, disabled=not agree):
        st.session_state.instruction_confirmed = True
        st.rerun()
    st.stop()

# --- 데이터 로드 및 필터링 ---
service = drv.get_gdrive_service()
master_df = drv.load_csv(service, MASTER_FILE_ID)

# ID 정규화 함수: 1.0이나 " 1 " 같은 데이터를 모두 "1"로 통일
def normalize_id(x):
    try:
        return str(int(float(x))).strip()
    except (ValueError, TypeError):
        return str(x).strip()

master_df['eval_id_str'] = master_df['eval_id'].apply(normalize_id)

try:
    res_df = drv.get_existing_results(RESULT_SHEET_NAME)
    
    if not res_df.empty:
        # 로그인한 유저 데이터만 필터링 (구버전 user_id: "이름_PIN" 형식과 호환)
        current_user = st.session_state.user_id
        user_col = res_df['user_id'].astype(str).str.strip()
        user_mask = user_col.eq(current_user) | user_col.str.startswith(f"{current_user}_")
        user_res = res_df[user_mask]
        # 시트의 eval_id도 정규화
        done_ids = user_res['eval_id'].apply(normalize_id).unique().tolist()
    else:
        done_ids = []
except Exception as e:
    st.error("평가 진행 상태를 불러오는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
    done_ids = []

# 디버깅용 (사이드바에서 확인 가능)
st.sidebar.write(f"현재 유저: {st.session_state.user_id}")
done_id_set = set(done_ids)

# 증례 순서 기준 생성 (원본 데이터 순서 기준)
master_df["_master_order"] = range(len(master_df))
file_order_df = (
    master_df[["file_name", "_master_order"]]
    .drop_duplicates(subset=["file_name"], keep="first")
    .sort_values("_master_order")
    .reset_index(drop=True)
)
file_order_df["file_order"] = file_order_df.index
file_order_df["case_label"] = file_order_df["file_order"].apply(lambda x: f"Clinical_Note_{x + 1}")

# 증례(file_name) 단위 진행 현황 계산
case_total_df = (
    master_df.groupby("file_name", as_index=False)
    .size()
    .rename(columns={"size": "총개수"})
)
case_done_df = (
    master_df[master_df["eval_id_str"].isin(done_id_set)]
    .groupby("file_name", as_index=False)
    .size()
    .rename(columns={"size": "완료개수"})
)
case_progress_df = case_total_df.merge(case_done_df, on="file_name", how="left")
case_progress_df = case_progress_df.merge(
    file_order_df[["file_name", "file_order", "case_label"]],
    on="file_name",
    how="left",
)
case_progress_df["완료개수"] = case_progress_df["완료개수"].fillna(0).astype(int)
case_progress_df["진행률"] = (
    case_progress_df["완료개수"] / case_progress_df["총개수"] * 100
).round(0).astype(int).astype(str) + "%"
case_progress_df["상태"] = case_progress_df.apply(
    lambda row: "완료"
    if row["완료개수"] >= row["총개수"]
    else ("진행중" if row["완료개수"] > 0 else "대기"),
    axis=1,
)

completed_case_count = int((case_progress_df["완료개수"] >= case_progress_df["총개수"]).sum())
total_case_count = int(case_progress_df.shape[0])

st.sidebar.markdown("### 증례 진행 현황")
st.sidebar.progress(
    completed_case_count / total_case_count if total_case_count else 0.0,
    text=f"증례 완료: {completed_case_count} / {total_case_count}",
)
st.sidebar.dataframe(
    case_progress_df.sort_values("file_order").rename(
        columns={"case_label": "증례", "총개수": "총", "완료개수": "완료"}
    )[["증례", "완료", "총", "진행률", "상태"]],
    hide_index=True,
    use_container_width=True,
)

# 필터링 + 같은 증례 10개 연속 평가를 위한 정렬
todo_df = master_df[~master_df["eval_id_str"].isin(done_id_set)].copy()
if not todo_df.empty:
    todo_df = (
        todo_df.merge(file_order_df[["file_name", "file_order"]], on="file_name", how="left")
        .sort_values(["file_order", "_master_order"])
        .reset_index(drop=True)
    )

# --- 화면 출력 ---
st.title(f"🩺 평가 세션: {st.session_state.user_id.split('_')[0]} 선생님")

if todo_df.empty:
    st.balloons()
    st.success("🎉 모든 평가 완료!")
else:
    current_case = todo_df.iloc[0]
    current_case_file = str(current_case["file_name"])
    current_case_label = str(
        file_order_df.loc[file_order_df["file_name"] == current_case_file, "case_label"].iloc[0]
    )
    current_case_done = int(case_progress_df.loc[case_progress_df["file_name"] == current_case_file, "완료개수"].iloc[0])
    current_case_total = int(case_progress_df.loc[case_progress_df["file_name"] == current_case_file, "총개수"].iloc[0])

    st.caption(f"현재 증례: {current_case_label} ({current_case_done}/{current_case_total} 완료)")
    st.progress(len(done_ids) / len(master_df), text=f"진행도: {len(done_ids)} / {len(master_df)}")

    col_text, col_eval = st.columns([2, 1])

    with col_text:
        with st.expander("📖 초진기록-현병력 발췌", expanded=True):
            st.text(current_case['현병력-Free Text#13'])
        with st.expander("📋 감별진단 리스트", expanded=True):
            ranked_ddx = parse_ranked_ddx(current_case['entered_ddx_list'])
            if ranked_ddx:
                ddx_table = pd.DataFrame(
                    {
                        "우선순위": [f"{i}순위" for i in range(1, len(ranked_ddx) + 1)],
                        "감별진단": ranked_ddx,
                    }
                )
                st.dataframe(ddx_table, hide_index=True, use_container_width=True)
            else:
                st.info(str(current_case['entered_ddx_list']))

    with col_eval:
        st.subheader("📝 평가")
        with st.expander("점수 기준 보기", expanded=True):
            st.markdown("**적절성 기준**")
            st.dataframe(pd.DataFrame(ADEQUACY_CRITERIA), hide_index=True, use_container_width=True)
            st.markdown("**안전성 기준**")
            st.dataframe(pd.DataFrame(SAFETY_CRITERIA), hide_index=True, use_container_width=True)

        adequacy = st.radio(
            "1. 적절성",
            [None, 1, 2, 3, 4, 5],
            horizontal=True,
            key=f"ad_{current_case['eval_id']}",
            format_func=lambda x: "선택" if x is None else str(x),
        )
        safety = st.radio(
            "2. 안전성",
            [None, 1, 2, 3, 4, 5],
            horizontal=True,
            key=f"sf_{current_case['eval_id']}",
            format_func=lambda x: "선택" if x is None else str(x),
        )
        comment = st.text_area("의견", key=f"cm_{current_case['eval_id']}")

        if st.button("저장 및 다음", use_container_width=True):
            with st.spinner("저장 중..."):
                if adequacy is None or safety is None:
                    st.error("적절성과 안전성 점수를 모두 선택해주세요.")
                    st.stop()

                new_row = [
                    normalize_id(current_case['eval_id']), # 정규화해서 저장
                    str(current_case['file_name']),
                    str(current_case['arm']),
                    int(adequacy),
                    int(safety),
                    str(comment).replace("\n", " "),
                    st.session_state.user_id,
                    datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ]
                inserted = drv.append_result_to_sheet(RESULT_SHEET_NAME, new_row)
                if inserted:
                    st.toast("저장되었습니다!")
                else:
                    st.warning("이미 저장된 항목입니다. 다음 케이스로 이동합니다.")
                time.sleep(SAVE_RERUN_DELAY_SECONDS)  # 시트 반영 대기
                st.rerun()

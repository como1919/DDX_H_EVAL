import streamlit as st
import pandas as pd
import datetime
import drive_logic as drv
import time
from constants import (
    ACCURACY_REFERENCE_CRITERIA,
    ACCURACY_SCORE_CRITERIA,
    ADEQUACY_CRITERIA,
    ANSWER_COL,
    SAFETY_CRITERIA,
    SAVE_RERUN_DELAY_SECONDS,
)
from utils import find_answer_column, initialize_session_state, normalize_id, parse_ranked_ddx

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

initialize_session_state(st.session_state)
if "done_ids_cache" not in st.session_state:
    st.session_state.done_ids_cache = {}

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
        - 응급실 초진 기록을 기반으로 감별진단 목록을 생성하는 모델을 개발하고, 생성된 진단명 추론 결과를 의료진이 참고하여 진단 과정에 반영할 때 진단 정확성, 적절성 그리고 안전성을 평가하고자 합니다.
        - 평가에 사용되는 데이터는 총 10명의 전공의 선생님들께서 제한된 시간(1시간) 내 초진기록만을 참고하여 작성한 감별진단 후보목록으로써, Case그룹은 LLM-DDx를 참고하여감별진단을 작성하였습니다. (사례당 최소 3개의 감별진단명 작성)
        - 총 50사례(총 500건, 사례당 10건)의 초진기록을 기반으로 LLM-DD 보조 여부에 따른 감별진단을 3가지 척도에 따라 평가하고자 하며, 척도는 아래와 같습니다.
        1. 정확성: 작성된 감별진단 후보군 내 해당 사례에 대한 참고 진단명이 포함되어 있는지 평가
        2. 적절성: 작성된 감별진단 후보군이 얼마나 구체적이며, 응급의학과 전문의의 임상적 추론 과정을 얼마나 정교하게 반영하였는지 평가
        3. 안전성: 초진기록 및 관련 병력 기반 고위험 질환을 염두에 두어야 할 증상 혹은 징후를 적절하게 포함했는지 평가
        """
    )

    st.subheader("정확성")
    st.caption("1) 참고 진단의 타당성")
    st.dataframe(pd.DataFrame(ACCURACY_REFERENCE_CRITERIA), hide_index=True, use_container_width=True)

    st.caption("2) 정확성 점수 기준")
    st.dataframe(pd.DataFrame(ACCURACY_SCORE_CRITERIA), hide_index=True, use_container_width=True)

    st.subheader("적절성")
    st.dataframe(pd.DataFrame(ADEQUACY_CRITERIA), hide_index=True, use_container_width=True)

    st.subheader("안전성")
    st.dataframe(pd.DataFrame(SAFETY_CRITERIA), hide_index=True, use_container_width=True)

    agree = st.checkbox("위 안내사항과 점수 기준을 확인했습니다.")
    if st.button("평가 시작", type="primary", use_container_width=True, disabled=not agree):
        st.session_state.instruction_confirmed = True
        st.rerun()
    st.stop()

# --- 데이터 로드 및 필터링 ---
service = drv.get_gdrive_service()
master_df = drv.load_csv(service, MASTER_FILE_ID)

master_df['eval_id_str'] = master_df['eval_id'].apply(normalize_id)
answer_col_name = find_answer_column(master_df, ANSWER_COL)

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
        st.session_state.done_ids_cache[current_user] = done_ids
    else:
        current_user = st.session_state.user_id
        cached_done_ids = st.session_state.done_ids_cache.get(current_user, [])
        done_ids = cached_done_ids
except Exception as e:
    st.error("평가 진행 상태를 불러오는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
    current_user = st.session_state.user_id
    done_ids = st.session_state.done_ids_cache.get(current_user, [])

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
    current_case_file = str(todo_df.iloc[0]["file_name"])
    current_case_label = str(
        file_order_df.loc[file_order_df["file_name"] == current_case_file, "case_label"].iloc[0]
    )
    current_case_done = int(
        case_progress_df.loc[case_progress_df["file_name"] == current_case_file, "완료개수"].iloc[0]
    )
    current_case_total = int(
        case_progress_df.loc[case_progress_df["file_name"] == current_case_file, "총개수"].iloc[0]
    )
    current_case_batch_df = (
        todo_df[todo_df["file_name"] == current_case_file]
        .sort_values("_master_order")
        .reset_index(drop=True)
    )
    # 증례 내 작성자 번호를 고정하기 위한 기준(저장되어도 번호 유지)
    current_case_all_df = (
        master_df[master_df["file_name"] == current_case_file]
        .sort_values("_master_order")
        .reset_index(drop=True)
    )
    current_case_all_df["writer_no"] = current_case_all_df.index + 1
    writer_no_map = {
        normalize_id(r["eval_id"]): int(r["writer_no"])
        for _, r in current_case_all_df.iterrows()
    }

    st.caption(
        f"현재 증례: {current_case_label} ({current_case_done}/{current_case_total} 완료) | "
        f"이번 화면 평가 대상: {len(current_case_batch_df)}명"
    )
    st.progress(len(done_ids) / len(master_df), text=f"진행도: {len(done_ids)} / {len(master_df)}")

    col_text, col_eval = st.columns([2, 1])

    with col_text:
        reference_case = current_case_batch_df.iloc[0]
        with st.expander("📖 초진기록-현병력 발췌", expanded=True):
            st.text(reference_case['현병력-Free Text#13'])
        with st.expander("✅ 정답 진단명 (Reference)", expanded=True):
            if answer_col_name:
                raw_answer = reference_case[answer_col_name]
                answer_text = "" if pd.isna(raw_answer) else str(raw_answer).strip()
                if answer_text:
                    st.text(answer_text)
                else:
                    st.info("정답 DDX 값이 비어 있습니다.")
            else:
                st.warning("정답 DDX 컬럼이 없어 아직 표시할 수 없습니다. evaluation_master.csv를 재생성해주세요.")

        with st.expander("점수 기준 보기", expanded=True):
            st.markdown("**정확성 기준**")
            st.caption("1) 참고 진단의 타당성")
            st.dataframe(pd.DataFrame(ACCURACY_REFERENCE_CRITERIA), hide_index=True, use_container_width=True)
            st.caption("2) 정확성 점수 기준")
            st.dataframe(pd.DataFrame(ACCURACY_SCORE_CRITERIA), hide_index=True, use_container_width=True)
            st.markdown("**적절성 기준**")
            st.dataframe(pd.DataFrame(ADEQUACY_CRITERIA), hide_index=True, use_container_width=True)
            st.markdown("**안전성 기준**")
            st.dataframe(pd.DataFrame(SAFETY_CRITERIA), hide_index=True, use_container_width=True)

    with col_eval:
        st.subheader(f"📝 증례 일괄 평가 ({len(current_case_batch_df)}명)")

        incomplete_count = 0
        for idx, row in current_case_batch_df.iterrows():
            eval_id = row["eval_id"]
            writer_no = writer_no_map.get(normalize_id(eval_id), idx + 1)
            panel_title = f"{writer_no}. 작성자 {writer_no}"
            with st.expander(panel_title, expanded=(idx == 0)):
                ranked_ddx = parse_ranked_ddx(row["entered_ddx_list"])
                if ranked_ddx:
                    ddx_table = pd.DataFrame(
                        {
                            "우선순위": [f"{i}순위" for i in range(1, len(ranked_ddx) + 1)],
                            "감별진단": ranked_ddx,
                        }
                    )
                    st.dataframe(ddx_table, hide_index=True, use_container_width=True)
                else:
                    st.info(str(row["entered_ddx_list"]))

                st.radio(
                    "1-1. 정확성 - 참고 진단의 타당성",
                    [None, 1, 2, 3, 4, 5],
                    horizontal=True,
                    key=f"ac_ref_{eval_id}",
                    format_func=lambda x: "선택" if x is None else str(x),
                )
                st.radio(
                    "1-2. 정확성 - 정확성 점수 기준 평가",
                    [None, 1, 2, 3, 4, 5],
                    horizontal=True,
                    key=f"ac_{eval_id}",
                    format_func=lambda x: "선택" if x is None else str(x),
                )
                st.radio(
                    "2. 적절성",
                    [None, 1, 2, 3, 4, 5],
                    horizontal=True,
                    key=f"ad_{eval_id}",
                    format_func=lambda x: "선택" if x is None else str(x),
                )
                st.radio(
                    "3. 안전성",
                    [None, 1, 2, 3, 4, 5],
                    horizontal=True,
                    key=f"sf_{eval_id}",
                    format_func=lambda x: "선택" if x is None else str(x),
                )
                st.text_area("의견", key=f"cm_{eval_id}")

                single_save_clicked = st.button(
                    "이 작성자 저장",
                    key=f"save_single_{eval_id}",
                    use_container_width=True,
                )
                if single_save_clicked:
                    if (
                        st.session_state.get(f"ac_ref_{eval_id}") is None
                        or st.session_state.get(f"ac_{eval_id}") is None
                        or st.session_state.get(f"ad_{eval_id}") is None
                        or st.session_state.get(f"sf_{eval_id}") is None
                    ):
                        st.error("이 작성자의 점수를 모두 선택해주세요.")
                        st.stop()

                    with st.spinner("저장 중..."):
                        new_row = [
                            normalize_id(row["eval_id"]),
                            str(row["file_name"]),
                            str(row["arm"]),
                            int(st.session_state[f"ac_ref_{eval_id}"]),
                            int(st.session_state[f"ac_{eval_id}"]),
                            int(st.session_state[f"ad_{eval_id}"]),
                            int(st.session_state[f"sf_{eval_id}"]),
                            str(st.session_state.get(f"cm_{eval_id}", "")).replace("\n", " "),
                            st.session_state.user_id,
                            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        ]
                        inserted = drv.append_result_to_sheet(RESULT_SHEET_NAME, new_row)
                        if inserted:
                            current_user = st.session_state.user_id
                            current_cache = st.session_state.done_ids_cache.get(current_user, [])
                            current_cache_set = set(current_cache)
                            current_cache_set.add(normalize_id(row["eval_id"]))
                            st.session_state.done_ids_cache[current_user] = list(current_cache_set)
                            st.toast("저장되었습니다.")
                        else:
                            st.warning("이미 저장된 항목입니다.")
                        time.sleep(SAVE_RERUN_DELAY_SECONDS)
                        st.rerun()

            if (
                st.session_state.get(f"ac_ref_{eval_id}") is None
                or st.session_state.get(f"ac_{eval_id}") is None
                or st.session_state.get(f"ad_{eval_id}") is None
                or st.session_state.get(f"sf_{eval_id}") is None
            ):
                incomplete_count += 1

        st.caption(
            f"현재 화면 미입력: {incomplete_count} / {len(current_case_batch_df)}명 | "
            "각 작성자별로 저장하면 자동으로 다음 미저장 항목만 남습니다."
        )

        if st.button("해당 증례 일괄 저장", use_container_width=True):
            with st.spinner("일괄 저장 중..."):
                if incomplete_count > 0:
                    st.error("일괄 저장 전, 남은 작성자의 점수를 모두 입력해주세요.")
                    st.stop()

                inserted_count = 0
                skipped_count = 0
                for _, row in current_case_batch_df.iterrows():
                    eval_id = row["eval_id"]
                    new_row = [
                        normalize_id(row["eval_id"]),
                        str(row["file_name"]),
                        str(row["arm"]),
                        int(st.session_state[f"ac_ref_{eval_id}"]),
                        int(st.session_state[f"ac_{eval_id}"]),
                        int(st.session_state[f"ad_{eval_id}"]),
                        int(st.session_state[f"sf_{eval_id}"]),
                        str(st.session_state.get(f"cm_{eval_id}", "")).replace("\n", " "),
                        st.session_state.user_id,
                        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ]
                    inserted = drv.append_result_to_sheet(RESULT_SHEET_NAME, new_row)
                    if inserted:
                        current_user = st.session_state.user_id
                        current_cache = st.session_state.done_ids_cache.get(current_user, [])
                        current_cache_set = set(current_cache)
                        current_cache_set.add(normalize_id(row["eval_id"]))
                        st.session_state.done_ids_cache[current_user] = list(current_cache_set)
                        inserted_count += 1
                    else:
                        skipped_count += 1

                st.toast(f"일괄 저장 완료: {inserted_count}건")
                if skipped_count > 0:
                    st.warning(f"중복으로 건너뜀: {skipped_count}건")
                time.sleep(SAVE_RERUN_DELAY_SECONDS)
                st.rerun()

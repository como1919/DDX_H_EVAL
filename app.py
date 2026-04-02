import streamlit as st
import pandas as pd
import datetime
import drive_logic as drv
import time

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

# --- 로그인 ---
if not st.session_state.auth:
    st.title("👨‍⚕️ 전문의 평가 로그인")
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
st.sidebar.write(f"완료된 ID 목록: {done_ids}")

# 필터링
todo_df = master_df[~master_df['eval_id_str'].isin(done_ids)]

# --- 화면 출력 ---
st.title(f"🩺 평가 세션: {st.session_state.user_id.split('_')[0]} 전문의님")

if todo_df.empty:
    st.balloons()
    st.success("🎉 모든 평가 완료!")
else:
    current_case = todo_df.iloc[0]
    st.progress(len(done_ids) / len(master_df), text=f"진행도: {len(done_ids)} / {len(master_df)}")

    col_text, col_eval = st.columns([2, 1])

    with col_text:
        with st.expander("📖 현병력", expanded=True):
            st.text(current_case['현병력-Free Text#13'])
        with st.expander("📋 감별진단 리스트", expanded=True):
            st.info(current_case['entered_ddx_list'])

    with col_eval:
        st.subheader("📝 평가")
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

        if st.button("저장 및 다음 ➡️", use_container_width=True):
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
                time.sleep(1.5) # 시트 반영 대기
                st.rerun()

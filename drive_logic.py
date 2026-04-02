import pandas as pd
import io
import streamlit as st
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload # 이 부분 수정

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def get_gdrive_service():
    """Secrets에서 인증 정보를 가져와 Google Drive 서비스 객체 생성"""
    creds_info = st.secrets["gcp_service_account"]
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def get_gspread_client():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive.readonly']
    creds_info = st.secrets["gcp_service_account"]
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
    return gspread.authorize(creds)

def find_file(service, name, folder_id):
    """특정 폴더 내에 파일이 있는지 검색하고 ID 반환"""
    query = f"name = '{name}' and '{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    return files[0]['id'] if files else None

def load_csv(service, file_id):
    """구글 드라이브 ID로 CSV 파일 읽어서 DataFrame으로 반환"""
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return pd.read_csv(fh)

def append_result_to_sheet(sheet_name, row_data):
    """구글 시트 맨 아래에 평가 결과 추가 (중복 저장 방지)"""
    client = get_gspread_client()
    sheet = client.open(sheet_name).sheet1

    # row_data schema: [eval_id, file_name, arm, adequacy, safety, comment, user_id, timestamp]
    eval_id = str(row_data[0]).strip()
    user_id = str(row_data[6]).strip()

    existing = sheet.get_all_records()
    for row in existing:
        existing_eval_id = str(row.get("eval_id", "")).strip()
        existing_user_id = str(row.get("user_id", "")).strip()
        if existing_eval_id == eval_id and existing_user_id == user_id:
            return False

    sheet.append_row(row_data)

    # 동시성 상황에서 중복 append가 발생할 수 있어, 저장 직후 키 기준으로 중복 행을 정리한다.
    all_values = sheet.get_all_values()
    if not all_values:
        return True

    headers = [str(h).strip() for h in all_values[0]]
    if "eval_id" not in headers or "user_id" not in headers:
        return True

    eval_col_idx = headers.index("eval_id")
    user_col_idx = headers.index("user_id")

    matched_rows = []
    for row_idx, row in enumerate(all_values[1:], start=2):
        row_eval_id = str(row[eval_col_idx]).strip() if eval_col_idx < len(row) else ""
        row_user_id = str(row[user_col_idx]).strip() if user_col_idx < len(row) else ""
        if row_eval_id == eval_id and row_user_id == user_id:
            matched_rows.append(row_idx)

    if len(matched_rows) > 1:
        # 가장 먼저 저장된 1개를 남기고 나머지를 삭제
        for dup_row_idx in reversed(matched_rows[1:]):
            sheet.delete_rows(dup_row_idx)

    return True


def save_csv(service, df, filename, folder_id, file_id=None):
    """CSV를 드라이브에 저장 (file_id가 있으면 업데이트, 없으면 신규 생성)"""
    csv_data = df.to_csv(index=False, encoding='utf-8-sig')
    fh = io.BytesIO(csv_data.encode('utf-8-sig'))
    media = MediaIoBaseUpload(fh, mimetype='text/csv', resumable=True)
    
    if file_id:
        service.files().update(fileId=file_id, media_body=media).execute()
    else:
        file_metadata = {'name': filename, 'parents': [folder_id]}
        service.files().create(body=file_metadata, media_body=media, fields='id').execute()

def get_existing_results(sheet_name):
    """구글 시트에서 전체 데이터를 읽어와 DataFrame으로 반환 (진행 상황 파악용)"""
    try:
        client = get_gspread_client()
        # 시트 이름으로 파일 열기
        spreadsheet = client.open(sheet_name)
        sheet = spreadsheet.sheet1
        
        # 모든 데이터를 가져와서 리스트 형식으로 반환
        data = sheet.get_all_records()
        
        if not data:
            return pd.DataFrame()
            
        return pd.DataFrame(data)
    except Exception:
        # 파일이 없거나 시트가 비어있을 경우 빈 데이터프레임 반환
        st.warning("기존 기록을 불러올 수 없습니다 (초기 상태 또는 권한/시트 확인 필요).")
        return pd.DataFrame()

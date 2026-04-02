# DDX Human Evaluation (Streamlit)

전문의가 `case`군 / `control`군이 작성한 감별진단(DDx) 리스트를 평가하는 Streamlit 앱입니다.

## 주요 기능
- 전문의 로그인(이름 + 4자리 PIN, `secrets`의 허용 사용자 기준 검증)
- 평가 대상 케이스 순차 제시
- 적절성 / 안전성 점수(1~5) 및 코멘트 저장
- Google Sheet로 평가 결과 저장
- 동일 사용자-동일 `eval_id` 중복 저장 방지

## 프로젝트 구조
- `app.py`: Streamlit UI 및 평가 흐름
- `drive_logic.py`: Google Drive / Google Sheets 연동
- `requirements.txt`: 배포 의존성 목록
- `.streamlit/secrets.toml`: 로컬 시크릿 (Git 업로드 금지)

## 로컬 실행
1. 의존성 설치
```bash
pip install -r requirements.txt
```

2. `.streamlit/secrets.toml` 생성
```toml
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "..."
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
universe_domain = "googleapis.com"

[allowed_users]
홍길동 = "1234"
김의사 = "5678"
```

3. 앱 실행
```bash
streamlit run app.py
```

## Streamlit Community Cloud 배포
1. GitHub에 아래 파일 업로드
   - `app.py`
   - `drive_logic.py`
   - `.gitignore`
   - `requirements.txt`
   - `README.md`
2. Streamlit Cloud에서 `New app` 생성
3. Repository / Branch(`main`) / Main file(`app.py`) 선택
4. `Advanced settings > Secrets`에 `secrets.toml` 내용 붙여넣기
5. Deploy


import ast
import re

import pandas as pd


def initialize_session_state(session_state):
    if "auth" not in session_state:
        session_state.auth = False
    if "user_id" not in session_state:
        session_state.user_id = ""
    if "login_fail_count" not in session_state:
        session_state.login_fail_count = 0
    if "lock_until" not in session_state:
        session_state.lock_until = None
    if "instruction_confirmed" not in session_state:
        session_state.instruction_confirmed = False


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


def normalize_id(x):
    try:
        return str(int(float(x))).strip()
    except (ValueError, TypeError):
        return str(x).strip()


def find_answer_column(df, answer_col):
    normalized = {str(c).strip(): c for c in df.columns}
    if answer_col in normalized:
        return normalized[answer_col]

    for c in df.columns:
        col = str(c).strip()
        if col.startswith(answer_col):
            return c

    for c in df.columns:
        col = str(c).strip()
        if "진단명-Free Text" in col:
            return c

    return None

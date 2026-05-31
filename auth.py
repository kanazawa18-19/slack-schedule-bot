import os
import pickle
from pathlib import Path
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
TOKENS_DIR = os.environ.get("TOKENS_DIR", "tokens")
REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "http://localhost:8080/oauth/callback")

Path(TOKENS_DIR).mkdir(exist_ok=True)

# OAuth途中の state → slack_user_id マッピング（メモリ）
_pending: dict[str, str] = {}


def get_token_path(user_id: str) -> str:
    return os.path.join(TOKENS_DIR, f"{user_id}.pickle")


def has_valid_token(user_id: str) -> bool:
    path = get_token_path(user_id)
    if not os.path.exists(path):
        return False
    with open(path, "rb") as f:
        creds = pickle.load(f)
    if creds and creds.valid:
        return True
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(path, "wb") as f:
                pickle.dump(creds, f)
            return True
        except Exception:
            pass
    return False


def start_oauth(user_id: str) -> str:
    """OAuthフローを開始して認証URLを返す。"""
    flow = Flow.from_client_secrets_file(
        os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json"),
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    _pending[state] = user_id
    return auth_url


def complete_oauth(state: str, code: str) -> str | None:
    """コールバックのcodeをトークンに交換して保存し、Slack user_id を返す。"""
    user_id = _pending.pop(state, None)
    if not user_id:
        return None

    flow = Flow.from_client_secrets_file(
        os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json"),
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
        state=state,
    )
    flow.fetch_token(code=code)

    with open(get_token_path(user_id), "wb") as f:
        pickle.dump(flow.credentials, f)

    return user_id


def load_credentials(user_id: str):
    """保存済みのCredentialsを返す。トークンがない場合はValueErrorを送出。"""
    path = get_token_path(user_id)
    if not os.path.exists(path):
        raise ValueError(f"no_token:{user_id}")

    with open(path, "rb") as f:
        creds = pickle.load(f)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(path, "wb") as f:
            pickle.dump(creds, f)

    if not creds or not creds.valid:
        raise ValueError(f"invalid_token:{user_id}")

    return creds

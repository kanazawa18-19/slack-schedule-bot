import base64
import json
import os
import pickle
import urllib.error
import urllib.request
from pathlib import Path
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
TOKENS_DIR = os.environ.get("TOKENS_DIR", "tokens")
REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "http://localhost:8080/oauth/callback")
MANUAL_REDIRECT_URI = "http://localhost"

Path(TOKENS_DIR).mkdir(exist_ok=True)

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


def start_oauth_manual(user_id: str) -> str:
    """localhost リダイレクト用の OAuth URL を生成する（コールバックサーバー不要）。"""
    flow = Flow.from_client_secrets_file(
        os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json"),
        scopes=SCOPES,
        redirect_uri=MANUAL_REDIRECT_URI,
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    _pending[state] = user_id
    return auth_url


def exchange_code(user_id: str, raw_input: str) -> None:
    """認証後のURLまたはコードを受け取ってトークンを保存する。"""
    code = raw_input.strip()

    # URLごと貼られた場合はcodeパラメータだけ抽出
    if "code=" in code:
        from urllib.parse import parse_qs, urlparse
        try:
            params = parse_qs(urlparse(code).query)
            code = params.get("code", [code])[0]
        except Exception:
            pass

    flow = Flow.from_client_secrets_file(
        os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json"),
        scopes=SCOPES,
        redirect_uri=MANUAL_REDIRECT_URI,
    )
    flow.fetch_token(code=code)

    with open(get_token_path(user_id), "wb") as f:
        pickle.dump(flow.credentials, f)

    # GitHub Actions 環境なら TOKENS_JSON シークレットを自動更新
    _update_github_secret()


def start_oauth(user_id: str) -> str:
    """Web コールバック用の OAuth URL（ローカル開発用）。"""
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
    """Web コールバック処理（ローカル開発用）。"""
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

    _update_github_secret()
    return user_id


def load_credentials(user_id: str):
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


def _update_github_secret() -> None:
    """全トークンを TOKENS_JSON シークレットに書き込む（GitHub Actions 環境のみ）。"""
    gh_pat = os.environ.get("GH_PAT")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not gh_pat or not repo:
        return

    try:
        from nacl import encoding, public as nacl_public

        tokens = {}
        for fname in os.listdir(TOKENS_DIR):
            if fname.endswith(".pickle"):
                uid = fname.replace(".pickle", "")
                with open(os.path.join(TOKENS_DIR, fname), "rb") as f:
                    tokens[uid] = base64.b64encode(f.read()).decode()

        headers = {
            "Authorization": f"Bearer {gh_pat}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        }

        # リポジトリの公開鍵を取得
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
            headers=headers,
        )
        with urllib.request.urlopen(req) as resp:
            key_data = json.loads(resp.read())

        # シークレット値を暗号化
        pub_key = nacl_public.PublicKey(key_data["key"].encode(), encoding.Base64Encoder())
        encrypted = base64.b64encode(
            nacl_public.SealedBox(pub_key).encrypt(json.dumps(tokens).encode())
        ).decode()

        payload = json.dumps({"encrypted_value": encrypted, "key_id": key_data["key_id"]}).encode()
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/actions/secrets/TOKENS_JSON",
            data=payload,
            method="PUT",
            headers=headers,
        )
        urllib.request.urlopen(req)

    except Exception as e:
        print(f"GitHub Secret 更新失敗（続行）: {e}")

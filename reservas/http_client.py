# reservas/http_client.py
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def requests_session_with_retry(total=3, backoff=0.5):
    retry = Retry(
        total=total,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET","POST"]),
        raise_on_status=False,
    )
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s

session = requests_session_with_retry()

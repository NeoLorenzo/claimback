"""A small Supabase client over HTTP (PostgREST + Storage + Auth), server side only.
Uses the secret (service role) key, which bypasses row-level security, so it
must only ever run in the worker, never in a browser."""
import os
from urllib.parse import quote

import httpx

TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class Supabase:
    def __init__(self, url: str | None = None, key: str | None = None):
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/")
        self.key = key or os.environ["SUPABASE_SECRET_KEY"]
        headers = {"apikey": self.key}
        if not self.key.startswith("sb_secret_"):  # legacy service_role JWT also goes in Authorization
            headers["Authorization"] = f"Bearer {self.key}"
        self.http = httpx.Client(headers=headers, timeout=TIMEOUT)

    # ---- PostgREST ------------------------------------------------------------
    def insert(self, table: str, rows: dict | list, *, upsert: bool = False, returning: bool = False):
        prefer = ["return=representation" if returning else "return=minimal"]
        if upsert:
            prefer.append("resolution=merge-duplicates")
        r = self.http.post(f"{self.url}/rest/v1/{table}", json=rows, headers={"Prefer": ",".join(prefer)})
        r.raise_for_status()
        return r.json() if returning else None

    def update(self, table: str, match: dict, values: dict) -> None:
        params = {k: f"eq.{v}" for k, v in match.items()}
        r = self.http.patch(f"{self.url}/rest/v1/{table}", params=params, json=values,
                            headers={"Prefer": "return=minimal"})
        r.raise_for_status()

    def select(self, table: str, params: dict | None = None) -> list[dict]:
        r = self.http.get(f"{self.url}/rest/v1/{table}", params=params or {})
        r.raise_for_status()
        return r.json()

    def delete(self, table: str, match: dict) -> None:
        r = self.http.delete(f"{self.url}/rest/v1/{table}", params={k: f"eq.{v}" for k, v in match.items()})
        r.raise_for_status()

    def count(self, table: str, params: dict) -> int:
        r = self.http.get(f"{self.url}/rest/v1/{table}", params={**params, "select": "id"},
                          headers={"Prefer": "count=exact", "Range": "0-0"})
        r.raise_for_status()
        return int(r.headers.get("content-range", "*/0").split("/")[-1])

    # ---- Storage -----------------------------------------------------------------
    def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> None:
        r = self.http.post(f"{self.url}/storage/v1/object/{bucket}/{quote(path)}", content=data,
                           headers={"Content-Type": content_type, "x-upsert": "true"})
        r.raise_for_status()

    def download(self, bucket: str, path: str) -> bytes:
        r = self.http.get(f"{self.url}/storage/v1/object/{bucket}/{quote(path)}")
        r.raise_for_status()
        return r.content

    def remove(self, bucket: str, paths: list[str]) -> None:
        if paths:
            self.http.request("DELETE", f"{self.url}/storage/v1/object/{bucket}", json={"prefixes": paths})

    def list(self, bucket: str, prefix: str) -> list[str]:
        r = self.http.post(f"{self.url}/storage/v1/object/list/{bucket}", json={"prefix": prefix, "limit": 1000})
        r.raise_for_status()
        return [f"{prefix.rstrip('/')}/{o['name']}" for o in r.json()]

    # ---- Auth ----------------------------------------------------------------------
    def user_for_token(self, access_token: str) -> dict | None:
        """Who is calling: checks a browser session token with Supabase Auth."""
        r = httpx.get(f"{self.url}/auth/v1/user", timeout=TIMEOUT,
                      headers={"apikey": self.key, "Authorization": f"Bearer {access_token}"})
        return r.json() if r.status_code == 200 else None

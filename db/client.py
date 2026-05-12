import requests


class SupabaseClient:
    def __init__(self, url: str, service_role_key: str) -> None:
        base = url.rstrip("/")
        self.base_url = base + "/rest/v1"
        self._storage_url = base + "/storage/v1"
        self.headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def select(self, table: str, params: dict | None = None) -> list[dict]:
        resp = requests.get(
            f"{self.base_url}/{table}",
            headers=self.headers,
            params=params or {},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def insert(self, table: str, records: list[dict]) -> list[dict]:
        resp = requests.post(
            f"{self.base_url}/{table}",
            headers=self.headers,
            json=records,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def update(self, table: str, match: dict, data: dict) -> list[dict]:
        params = {k: f"eq.{v}" for k, v in match.items()}
        resp = requests.patch(
            f"{self.base_url}/{table}",
            headers=self.headers,
            params=params,
            json=data,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def select_range(self, table: str, params: dict | None = None) -> list[dict]:
        """GET with automatic pagination (PostgREST 1000-row limit)."""
        page_size = 1000
        offset = 0
        all_records: list[dict] = []

        while True:
            paginated_params = dict(params or {})
            range_header = f"{offset}-{offset + page_size - 1}"
            resp = requests.get(
                f"{self.base_url}/{table}",
                headers={**self.headers, "Range": range_header, "Range-Unit": "items"},
                params=paginated_params,
                timeout=30,
            )
            if resp.status_code not in (200, 206):
                resp.raise_for_status()

            batch = resp.json()
            all_records.extend(batch)

            if len(batch) < page_size:
                break
            offset += page_size

        return all_records

    def storage_upload(
        self,
        bucket: str,
        path: str,
        data: bytes,
        content_type: str = "application/json",
    ) -> dict:
        resp = requests.put(
            f"{self._storage_url}/object/{bucket}/{path}",
            headers={
                "apikey": self.headers["apikey"],
                "Authorization": self.headers["Authorization"],
                "Content-Type": content_type,
            },
            data=data,
            timeout=30,
        )
        return {"ok": resp.ok, "status": resp.status_code, "body": resp.text}

    def storage_create_bucket(self, bucket_name: str, public: bool = False) -> bool:
        resp = requests.post(
            f"{self._storage_url}/bucket",
            headers=self.headers,
            json={"id": bucket_name, "name": bucket_name, "public": public},
            timeout=30,
        )
        return resp.ok

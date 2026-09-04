from __future__ import annotations

from typing import Any

import httpx

from .config import (
    REQUEST_TIMEOUT_SECONDS,
    SEEDANCE_BASE_URL,
    SEEDANCE_TASKS_PATH,
    get_seedance_api_key,
)
from .models import ProviderSnapshot, VideoTask


class ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, error_code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class ImagePayloadNotVerifiedError(ProviderError):
    pass


class SeedanceProvider:
    """OpenProxy 的唯一 HTTP 边界；响应字段变更只需要在此处适配。"""

    def __init__(self, api_key: str | None = None, base_url: str = SEEDANCE_BASE_URL, tasks_path: str = SEEDANCE_TASKS_PATH):
        self._api_key_override = api_key
        self.base_url = base_url.rstrip("/")
        self.tasks_path = tasks_path

    @property
    def tasks_url(self) -> str:
        return f"{self.base_url}{self.tasks_path}"

    def _headers(self) -> dict[str, str]:
        api_key = self._api_key_override if self._api_key_override is not None else get_seedance_api_key()
        if not api_key:
            raise ProviderError("未配置 SEEDANCE_API_KEY，无法提交视频生成任务")
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    @classmethod
    def _sanitize(cls, data: Any) -> Any:
        secret_markers = ("authorization", "api_key", "apikey", "token", "secret", "bearer", "password", "key")
        if isinstance(data, dict):
            return {
                str(key): "[REDACTED]" if any(marker in str(key).lower() for marker in secret_markers) else cls._sanitize(value)
                for key, value in data.items()
            }
        if isinstance(data, list):
            return [cls._sanitize(item) for item in data]
        if isinstance(data, str):
            if data.lower().startswith(("http://", "https://")):
                return data.split("?", 1)[0].split("#", 1)[0]
            if "bearer " in data.lower():
                return "[REDACTED]"
        return data

    @classmethod
    def _safe_error(cls, response: httpx.Response, action: str) -> ProviderError:
        error_code = None
        detail = None
        try:
            body = response.json()
            sanitized = cls._sanitize(body)
            candidate = sanitized.get("error", sanitized) if isinstance(sanitized, dict) else {}
            if isinstance(candidate, dict):
                raw_code = candidate.get("code")
                raw_message = candidate.get("message") or candidate.get("detail")
                error_code = str(raw_code) if raw_code is not None else None
                detail = str(raw_message)[:300] if isinstance(raw_message, str) else None
        except ValueError:
            detail = None
        suffix = f"：{detail}" if detail else ""
        return ProviderError(f"{action}失败（HTTP {response.status_code}）{suffix}", response.status_code, error_code)

    @staticmethod
    def _normalize_status(status: str | None) -> str:
        value = (status or "").lower()
        if value in {"succeeded", "success", "completed", "done"}:
            return "succeeded"
        if value in {"failed", "error", "expired"}:
            return "failed"
        if value in {"cancelled", "canceled"}:
            return "cancelled"
        if value in {"running", "processing", "generating"}:
            return "running"
        return "queued"

    @staticmethod
    def _extract_urls(data: dict[str, Any]) -> list[str]:
        content = data.get("content")
        if not isinstance(content, dict):
            content = data.get("output") if isinstance(data.get("output"), dict) else {}
        candidates = [
            content.get("video_url"),
            content.get("url"),
            data.get("video_url"),
            data.get("url"),
        ]
        urls = [value for value in candidates if isinstance(value, str) and value.startswith(("https://", "http://"))]
        return list(dict.fromkeys(urls))

    @staticmethod
    def _extract_progress(data: dict[str, Any]) -> int | None:
        candidates = (data.get("progress"), data.get("progress_percent"), (data.get("content") or {}).get("progress"))
        for value in candidates:
            if isinstance(value, (int, float)) and 0 <= value <= 100:
                return round(value)
        return None

    @staticmethod
    def _extract_error(data: dict[str, Any]) -> tuple[str | None, str | None]:
        error = data.get("error")
        if not isinstance(error, dict):
            return None, None
        code = error.get("code")
        message = error.get("message")
        return (str(code) if code is not None else None, str(message)[:500] if isinstance(message, str) else None)

    def _snapshot(self, data: dict[str, Any]) -> ProviderSnapshot:
        task_id = data.get("id") or data.get("task_id")
        error_code, error_message = self._extract_error(data)
        return ProviderSnapshot(
            task_id=str(task_id) if task_id is not None else None,
            status=self._normalize_status(data.get("status")),
            progress=self._extract_progress(data),
            result_urls=self._extract_urls(data),
            error_code=error_code,
            error_message=error_message,
            raw=self._sanitize(data),
        )

    def _payload(self, task: VideoTask) -> dict[str, Any]:
        if task.mode == "image":
            # 当前截图只证实 text content。避免猜测 image item 字段而产生不可控收费。
            raise ImagePayloadNotVerifiedError("图生视频的图片 content 字段尚未通过 Provider 文档或联调确认，暂不可提交")
        payload: dict[str, Any] = {
            "model": task.model,
            "content": [{"type": "text", "text": task.prompt}],
            "duration": task.requested_duration,
            "ratio": task.ratio,
            "resolution": task.resolution,
            "generate_audio": task.generate_audio,
        }
        if task.service_tier:
            payload["service_tier"] = task.service_tier
        return payload

    async def create_task(self, task: VideoTask) -> ProviderSnapshot:
        payload = self._payload(task)
        timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            try:
                response = await client.post(self.tasks_url, headers=self._headers(), json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise self._safe_error(exc.response, "提交任务") from exc
            except httpx.HTTPError as exc:
                raise ProviderError("提交任务的网络请求失败") from exc
        try:
            snapshot = self._snapshot(response.json())
        except ValueError as exc:
            raise ProviderError("提交任务返回了无法解析的 JSON") from exc
        if not snapshot.task_id:
            raise ProviderError("提交任务成功但响应中未找到 id")
        return snapshot

    async def get_task(self, provider_task_id: str) -> ProviderSnapshot:
        timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            try:
                response = await client.get(f"{self.tasks_url}/{provider_task_id}", headers=self._headers())
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise self._safe_error(exc.response, "查询任务") from exc
            except httpx.HTTPError as exc:
                raise ProviderError("查询任务的网络请求失败") from exc
        try:
            return self._snapshot(response.json())
        except ValueError as exc:
            raise ProviderError("查询任务返回了无法解析的 JSON") from exc

    async def cancel_task(self, provider_task_id: str) -> ProviderSnapshot:
        timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            try:
                response = await client.delete(f"{self.tasks_url}/{provider_task_id}", headers=self._headers())
                if response.status_code not in {200, 202, 204, 404, 409}:
                    response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise self._safe_error(exc.response, "取消任务") from exc
            except httpx.HTTPError as exc:
                raise ProviderError("取消任务的网络请求失败") from exc
        if response.status_code in {404, 409, 204}:
            return ProviderSnapshot(task_id=provider_task_id, status="cancelled")
        try:
            snapshot = self._snapshot(response.json())
        except ValueError:
            snapshot = ProviderSnapshot(task_id=provider_task_id, status="cancelled")
        return snapshot

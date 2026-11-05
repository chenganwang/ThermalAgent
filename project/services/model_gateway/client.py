from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import asdict

from .types import ChatRequest, ChatResponse


class ModelGateway:
    """Small adapter that talks to an OpenAI-compatible or Ollama endpoint.

    This module deliberately keeps a small interface so callers can swap the
    backing model runtime without touching retrieval or frontend modules.
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None, provider: str | None = None):
        self.base_url = (base_url or os.getenv("MODEL_GATEWAY_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.api_key = api_key or os.getenv("MODEL_GATEWAY_API_KEY", "")
        self.provider = (provider or os.getenv("MODEL_GATEWAY_PROVIDER", "ollama")).strip().lower()

    def chat(self, req: ChatRequest) -> ChatResponse:
        if self.provider == "openai":
            return self._chat_openai(req)
        return self._chat_ollama(req)

    def _chat_openai(self, req: ChatRequest) -> ChatResponse:
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": req.model,
            "messages": [asdict(m) for m in req.messages],
            "temperature": req.temperature,
        }
        if req.max_tokens is not None:
            payload["max_tokens"] = req.max_tokens
        payload.update(req.extra)
        raw = self._post_json(url, payload, bearer=self.api_key or None)
        content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
        return ChatResponse(model=req.model, content=str(content or ""), raw=raw)

    def _chat_ollama(self, req: ChatRequest) -> ChatResponse:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": req.model,
            "messages": [asdict(m) for m in req.messages],
            "stream": False,
            "options": {"temperature": req.temperature},
        }
        payload.update(req.extra)
        raw = self._post_json(url, payload)
        content = raw.get("message", {}).get("content", "")
        return ChatResponse(model=req.model, content=str(content or ""), raw=raw)

    def _post_json(self, url: str, payload: dict, bearer: str | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if bearer:
            req.add_header("Authorization", f"Bearer {bearer}")
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))

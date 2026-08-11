from __future__ import annotations

import json
from typing import Any

_REASONING_ALIASES = {
    'effort': 'reasoning_effort',
    'openai': 'reasoning_effort',
    'openrouter': 'reasoning',
    'native': 'intrinsic',
    'off': 'none',
    'false': 'none',
}
_VALID_REASONING_MODES = {'reasoning_effort', 'reasoning', 'intrinsic', 'none'}


def parse_capability_overrides(raw_json: str) -> dict[str, Any]:
    try:
        value = json.loads(raw_json or '{}')
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def infer_provider_capabilities(
    slot: dict[str, Any],
    model_name: str | None = None,
    *,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model = str(model_name or slot.get('model') or '').lower()
    base = str(slot.get('base_url') or '').lower()
    label = str(slot.get('label') or '').lower()
    mode = 'none'
    if 'openrouter.ai' in base:
        mode = 'reasoning' if any(x in model for x in ('gpt-5', 'o1', 'o3', 'o4', 'deepseek-r1', 'qwen3', 'gemini-2.5', 'gemini-3')) else 'none'
    elif 'api.openai.com' in base or label.startswith('openai'):
        mode = 'reasoning_effort' if any(x in model for x in ('gpt-5', 'o1', 'o3', 'o4')) else 'none'
    elif any(x in model for x in ('deepseek-r1', 'qwen3-thinking', 'qwq')):
        mode = 'intrinsic'

    override = (overrides or {}).get(str(slot.get('slot')))
    if isinstance(override, dict):
        requested = str(override.get('reasoning_mode') or '').strip().lower()
        requested = _REASONING_ALIASES.get(requested, requested)
        if requested in _VALID_REASONING_MODES:
            mode = requested

    return {
        'chat': True,
        'reasoning_mode': mode,
        'reasoning_guaranteed': mode != 'none',
        'vision': bool(str(slot.get('vision_model') or '').strip()),
        'embedding': bool(str(slot.get('embedding_model') or '').strip()),
        'transcription': bool(str(slot.get('transcription_model') or '').strip()),
    }

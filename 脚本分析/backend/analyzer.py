import base64
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pydantic
from json_repair import repair_json
from openai import OpenAI

from .config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, FRAME_BATCH_SIZE
from .models import AnalysisResult, ModelConfig, PromptMetadata, PromptStep

MAX_SUBMIT_RETRIES = 3

# 代理模型的计费规则不等同于官方模型定价；未配置可信定价时不展示估算费用。
MODEL_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {}

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("未配置 OPENAI_API_KEY")
        # 代理偶尔 TLS/连接建立较慢，SDK 默认 connect timeout 只有 5s 容易误报超时，这里放宽到 30s。
        # trust_env=False：本机 macOS 系统级代理（127.0.0.1:7890）对该代理域名的 SSL 转发不稳定
        # （curl 不读取系统代理所以不受影响），显式禁用后直连代理，避免 SSL EOF 报错。
        _client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
            http_client=httpx.Client(
                trust_env=False,
                timeout=httpx.Timeout(connect=30.0, read=600.0, write=600.0, pool=600.0),
            ),
        )
    return _client


def _render_final_prompt(user_prompt: str, variables: dict[str, Any]) -> str:
    """把「用户任务指令」模板和本次注入的「变量」拼接成实际发送的完整 Prompt。"""
    if not variables:
        return user_prompt
    blocks = []
    for key, value in variables.items():
        if isinstance(value, (dict, list)):
            value_str = json.dumps(value, ensure_ascii=False, indent=2)
        else:
            value_str = str(value)
        blocks.append(f"### {key}\n{value_str}")
    return user_prompt + "\n\n" + "\n\n".join(blocks)


def _build_metadata(response: Any, elapsed_ms: float, model: str) -> PromptMetadata:
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
    output_tokens = getattr(usage, "completion_tokens", None) if usage else None

    cost_usd = None
    pricing = MODEL_PRICING_PER_MTOK.get(model)
    if pricing and input_tokens is not None and output_tokens is not None:
        in_price, out_price = pricing
        cost_usd = round(input_tokens / 1_000_000 * in_price + output_tokens / 1_000_000 * out_price, 6)

    return PromptMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        elapsed_ms=round(elapsed_ms, 1),
        cost_usd=cost_usd,
    )


SUBMIT_ANALYSIS_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_analysis",
        "description": "提交对短视频脚本/口播稿的结构化分析结果。",
        "parameters": {
            "type": "object",
            "properties": {
            "source_type": {"type": "string", "enum": ["video", "text"]},
            "structure": {
                "type": "array",
                "description": "按时间顺序拆解的结构片段",
                "items": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "number", "description": "起始秒数，纯文字输入可省略"},
                        "end": {"type": "number", "description": "结束秒数，纯文字输入可省略"},
                        "role": {
                            "type": "string",
                            "description": "hook / setup / buildup / climax / cta / other",
                        },
                        "summary": {"type": "string"},
                    },
                    "required": ["role", "summary"],
                },
            },
            "dialogue": {
                "type": "array",
                "description": "文案/台词分句列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "number"},
                        "end": {"type": "number"},
                        "speaker": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
            },
            "visual": {
                "type": "array",
                "description": "视觉元素分析，纯文字输入时为空数组",
                "items": {
                    "type": "object",
                    "properties": {
                        "timestamp": {"type": "number"},
                        "description": {"type": "string"},
                        "technique": {
                            "type": "string",
                            "description": "转场/构图/字幕样式/镜头运动 等标签",
                        },
                    },
                    "required": ["timestamp", "description", "technique"],
                },
            },
            "template": {
                "type": "object",
                "description": "可复用的结构化模板，供下游提示词生成模块消费",
                "properties": {
                    "hook_type": {"type": "string"},
                    "pacing_seconds": {"type": "number"},
                    "visual_style": {"type": "string"},
                    "cta_style": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["hook_type"],
            },
        },
        "required": ["source_type", "structure", "dialogue", "visual", "template"],
        },
    },
}


def _parse_json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return json.loads(repair_json(value))


def _coerce_json_fields(data: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """兼容代理将嵌套数组/对象参数二次序列化为 JSON 字符串的情况。"""
    for field in fields:
        value = data.get(field)
        if isinstance(value, str):
            data[field] = _parse_json(value)
    return data


def _extract_tool_input(response: Any) -> dict[str, Any]:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise RuntimeError("代理未返回可用的模型响应")

    tool_calls = getattr(choices[0].message, "tool_calls", None) or []
    for tool_call in tool_calls:
        function = getattr(tool_call, "function", None)
        if function and function.name == "submit_analysis":
            data = _parse_json(function.arguments)
            if not isinstance(data, dict):
                raise RuntimeError("submit_analysis 参数必须是 JSON 对象")
            return _coerce_json_fields(data, ("structure", "dialogue", "visual", "template"))
    raise RuntimeError("模型未返回 submit_analysis 函数调用结果")


def _call_submit_analysis(
    *,
    system_prompt: str,
    user_prompt: str,
    variables: dict[str, Any],
    max_tokens: int,
    source_type: str,
    label: str,
) -> tuple[AnalysisResult, PromptStep]:
    """调用 OpenAI 兼容代理并强制 submit_analysis 函数输出。"""
    client = _get_client()
    final_prompt = _render_final_prompt(user_prompt, variables)
    model_params = ModelConfig(model=OPENAI_MODEL, temperature=None, max_tokens=max_tokens)
    last_error: Exception | None = None
    for attempt in range(1, MAX_SUBMIT_RETRIES + 1):
        started = time.perf_counter()
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": final_prompt},
            ],
            tools=[SUBMIT_ANALYSIS_TOOL],
            tool_choice={"type": "function", "function": {"name": "submit_analysis"}},
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        try:
            data = _extract_tool_input(response)
            data["source_type"] = source_type
            data.setdefault("visual", [])
            result = AnalysisResult.model_validate(data)
            step = PromptStep(
                label=label,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                variables=variables,
                final_prompt=final_prompt,
                model_params=model_params,
                response=json.dumps(data, ensure_ascii=False, indent=2),
                metadata=_build_metadata(response, elapsed_ms, OPENAI_MODEL),
            )
            return result, step
        except (json.JSONDecodeError, pydantic.ValidationError, RuntimeError) as exc:
            last_error = exc
            continue
    raise RuntimeError(f"模型返回结果解析失败，已重试 {MAX_SUBMIT_RETRIES} 次: {last_error}")


TEXT_SYSTEM_PROMPT = """你是短视频/口播稿脚本分析专家。给定一段文字脚本，请完成：
1. 结构拆解：按 hook / setup / buildup / climax / cta / other 划分片段并概括每段内容（纯文字输入没有时间信息，start/end 可省略）。
2. 文案台词提取：把脚本拆成自然的分句列表。
3. 可复用模板：抽象出 hook 类型、节奏、结尾 CTA 风格、标签等，供后续生成同类脚本的提示词使用。
视觉元素分析（visual）留空数组，因为输入是纯文字。
必须调用 submit_analysis 工具提交结果，source_type 固定为 "text"。"""

TEXT_USER_PROMPT = """请对下面变量中提供的脚本文本执行结构化分析：
1. 结构拆解（hook/setup/buildup/climax/cta/other）
2. 文案台词分句
3. 可复用模板抽象
必须调用 submit_analysis 工具提交结果。"""


def analyze_text_script(script_text: str) -> tuple[AnalysisResult, list[PromptStep]]:
    variables = {"脚本文本": script_text, "字数": len(script_text)}
    result, step = _call_submit_analysis(
        system_prompt=TEXT_SYSTEM_PROMPT,
        user_prompt=TEXT_USER_PROMPT,
        variables=variables,
        max_tokens=8192,
        source_type="text",
        label="文字脚本结构化分析",
    )
    return result, [step]


VISION_SYSTEM_PROMPT = "你是短视频画面分析助手，擅长识别镜头构图、转场方式、字幕样式、镜头运动等视觉细节。"

VISION_USER_PROMPT = """以下是一段短视频按时间顺序抽样的画面帧（每帧标注了对应的时间戳，单位秒）。
请逐帧或按画面变化描述：镜头构图、转场方式、字幕样式、镜头运动、画面内容等视觉细节。
用简洁的要点列表输出，每条要点带上对应的时间戳，不需要 JSON，纯文字描述即可。"""


def _encode_image(path: Path) -> dict[str, Any]:
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{data}"},
    }


def _extract_message_text(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise RuntimeError("代理未返回可用的模型响应")

    content = getattr(choices[0].message, "content", None)
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        text = "".join(
            item.get("text", "") if isinstance(item, dict) else getattr(item, "text", "")
            for item in content
        )
        if text.strip():
            return text
    raise RuntimeError("模型未返回视觉分析文本")


def _describe_frame_batches(
    frames: list[tuple[float, Path]]
) -> tuple[list[str], list[PromptStep]]:
    client = _get_client()
    max_tokens = 1024
    model_params = ModelConfig(model=OPENAI_MODEL, temperature=None, max_tokens=max_tokens)
    observations: list[str] = []
    steps: list[PromptStep] = []
    for i in range(0, len(frames), FRAME_BATCH_SIZE):
        batch = frames[i : i + FRAME_BATCH_SIZE]
        timestamps = [timestamp for timestamp, _ in batch]

        content: list[dict] = []
        for timestamp, frame_path in batch:
            content.append({"type": "text", "text": f"时间戳: {timestamp:.2f}s"})
            content.append(_encode_image(frame_path))
        content.append({"type": "text", "text": VISION_USER_PROMPT})

        started = time.perf_counter()
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        text = _extract_message_text(response)
        observations.append(text)

        batch_index = i // FRAME_BATCH_SIZE + 1
        variables = {
            "图片数量": len(batch),
            "时间戳列表(秒)": [round(t, 2) for t in timestamps],
        }
        final_prompt_text = (
            "\n".join(f"[时间戳: {t:.2f}s]\n[图片: 第{n + 1}帧]" for n, t in enumerate(timestamps))
            + f"\n\n{VISION_USER_PROMPT}"
        )
        steps.append(
            PromptStep(
                label=f"视觉分析 批次{batch_index}",
                system_prompt=VISION_SYSTEM_PROMPT,
                user_prompt=VISION_USER_PROMPT,
                variables=variables,
                final_prompt=final_prompt_text,
                model_params=model_params,
                response=text,
                metadata=_build_metadata(response, elapsed_ms, OPENAI_MODEL),
            )
        )
    return observations, steps


VIDEO_SYSTEM_PROMPT = """你是短视频脚本分析专家。你会看到两类原始素材：
1. 按批次对视频抽样帧做出的画面观察（包含时间戳）。
2. 语音转写得到的台词分句（包含起止时间）。
请综合这两类信息，完成：
1. 结构拆解：按 hook / setup / buildup / climax / cta / other 划分片段，带上起止时间和概括。
2. 文案台词提取：直接使用/校正转写分句，保留时间戳。
3. 视觉元素分析：整理画面观察为结构化的视觉元素列表，每条带时间戳、描述、技巧标签。
4. 可复用模板：抽象出 hook 类型、节奏（pacing_seconds，可用平均片段时长估算）、视觉风格、CTA 风格、标签。
必须调用 submit_analysis 工具提交结果，source_type 固定为 "video"。"""

VIDEO_USER_PROMPT = """请综合下面变量中提供的画面观察与语音转写分句，输出：
1. 结构拆解 2. 台词校正 3. 视觉元素整理 4. 可复用模板
必须调用 submit_analysis 工具提交结果。"""


def analyze_video(
    frames: list[tuple[float, Path]],
    transcript_segments: list[dict],
    frame_interval_sec: float | None = None,
) -> tuple[AnalysisResult, list[PromptStep]]:
    observations, visual_steps = _describe_frame_batches(frames)
    observations_text = "\n\n".join(
        f"[画面观察批次 {i + 1}]\n{obs}" for i, obs in enumerate(observations)
    )

    variables = {
        "视频信息": {
            "抽帧数量": len(frames),
            "抽样间隔秒": frame_interval_sec,
            "语音转写分句数": len(transcript_segments),
        },
        "画面观察原文": observations_text,
        "语音转写分句JSON": transcript_segments,
    }

    result, final_step = _call_submit_analysis(
        system_prompt=VIDEO_SYSTEM_PROMPT,
        user_prompt=VIDEO_USER_PROMPT,
        variables=variables,
        max_tokens=8192,
        source_type="video",
        label="视频结构化整合分析",
    )
    return result, visual_steps + [final_step]

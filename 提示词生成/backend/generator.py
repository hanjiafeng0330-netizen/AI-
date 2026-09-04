import json
import time
from typing import Any

import httpx2
import pydantic
from json_repair import repair_json
from openai import OpenAI

from .config import get_openai_api_key, get_openai_base_url, get_openai_model
from .models import (
    AnalysisResult,
    ModelConfig,
    NewDialogueLine,
    Product,
    PromptMetadata,
    PromptStep,
    ScriptVariant,
)

MAX_SUBMIT_RETRIES = 3
SCRIPT_COUNT = 5
MAX_TOKENS = 16000

MODEL_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.5, 10.0),
    "gpt-4.1-mini": (0.4, 1.6),
}

_client: OpenAI | None = None
_client_api_key: str = ""


def _get_client() -> OpenAI:
    global _client, _client_api_key
    current_key = get_openai_api_key()
    if _client is None or _client_api_key != current_key:
        if not current_key:
            raise RuntimeError("未配置 OPENAI_API_KEY")
        _client = OpenAI(
            api_key=current_key,
            base_url=get_openai_base_url(),
            http_client=httpx2.Client(
                trust_env=False,
                timeout=httpx2.Timeout(connect=30.0, read=600.0, write=600.0, pool=600.0),
            ),
        )
        _client_api_key = current_key
    return _client


def _render_final_prompt(user_prompt: str, variables: dict[str, Any]) -> str:
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


_STRUCTURE_SCHEMA = {
    "type": "array",
    "description": "按时间顺序拆解的新脚本结构片段，需对齐参考脚本的 role 顺序与节奏",
    "items": {
        "type": "object",
        "properties": {
            "role": {"type": "string", "description": "hook / setup / buildup / climax / cta / other"},
            "summary": {"type": "string", "description": "该片段的剧情/内容概括"},
            "duration_sec": {"type": "number", "description": "预估时长（秒）"},
        },
        "required": ["role", "summary"],
    },
}

_DIALOGUE_SCHEMA = {
    "type": "array",
    "description": "台词分句列表（只保留关键句即可），每句需标注所属 structure 片段下标",
    "items": {
        "type": "object",
        "properties": {
            "segment_index": {"type": "integer", "description": "对应 structure 数组下标，从 0 开始"},
            "speaker": {"type": "string"},
            "text": {"type": "string"},
        },
        "required": ["segment_index", "text"],
    },
}

_VIDEO_PROMPTS_SCHEMA = {
    "type": "array",
    "description": (
        "与 structure 数组一一对应、数量和顺序完全一致的 AI 视频生成提示词。"
        "role=hook 的两条提示词必须完整覆盖场景/人物外貌衣着/动作序列/情绪状态/具体台词/镜头运镜与景别/字幕音效建议，"
        "写到可以直接复制进 AI 视频工具生成画面的程度；其他 role 保持简洁（80-150字），只给核心画面+运镜即可。"
    ),
    "items": {
        "type": "object",
        "properties": {
            "role": {"type": "string", "description": "需与对应 structure 片段的 role 一致"},
            "duration_sec": {"type": "number"},
            "jimeng_prompt": {
                "type": "string",
                "description": "适配「即梦」的中文视频生成提示词",
            },
            "kling_prompt": {
                "type": "string",
                "description": "适配「可灵」的中文视频生成提示词",
            },
        },
        "required": ["role", "jimeng_prompt", "kling_prompt"],
    },
}

def _build_submit_scripts_tool(script_count: int) -> dict:
    return {
        "name": "submit_scripts",
        "description": f"一次性提交 {script_count} 条创意方向不同、结合产品信息并套用参考脚本套路的新短视频脚本。",
        "input_schema": {
            "type": "object",
            "properties": {
                "scripts": {
                    "type": "array",
                    "minItems": script_count,
                    "maxItems": script_count,
                    "description": f"正好 {script_count} 条创意方向不同的完整脚本",
                    "items": {
                        "type": "object",
                        "properties": {
                            "variant_title": {
                                "type": "string",
                                "description": "创意方向标题，例如「情景剧·家长焦虑型」",
                            },
                            "variant_style": {
                                "type": "string",
                                "description": "一句话说明这版脚本与其他版本的差异化创意点",
                            },
                            "structure": _STRUCTURE_SCHEMA,
                            "dialogue": _DIALOGUE_SCHEMA,
                            "video_prompts": _VIDEO_PROMPTS_SCHEMA,
                        },
                        "required": ["variant_title", "variant_style", "structure", "dialogue", "video_prompts"],
                    },
                },
            },
            "required": ["scripts"],
        },
    }


def _build_system_prompt(script_count: int) -> str:
    return f"""你是短视频带货脚本创作专家，尤其擅长图书类产品的口播/情景剧带货脚本，同时具备丰富的 AI 视频生成提示词（即梦、可灵）写作经验。

你会收到两类输入：
1. 「参考脚本分析」：一条已验证有效（爆款/测试过）的脚本的结构化分析结果，包含 structure（hook/setup/buildup/climax/cta 分段与概括）、dialogue（原台词）、template（可复用套路：hook 类型、节奏、视觉风格、CTA 风格、标签）。
2. 「产品资料」：这次要推广的新产品信息（书名、价格、卖点、痛点、目标人群、正版特征等）。

## 任务
一次性产出 {script_count} 条内容不同、创意方向不同的新脚本变体（scripts 数组，必须正好 {script_count} 条）。{script_count} 条之间要有实质差异，不能只是同一个脚本换几个词。可以从下面方向中挑不同的来演绎，也欢迎你自己设计更新颖、更有传播力的形式：
- 情景剧冲突型（亲子对话、朋友吐槽等）
- 悬念提问型（先抛反常识观点/问题，制造好奇）
- 数据/对比冲击型（用数字、前后对比制造紧迫感）
- 第三方证言/街访型（模拟真实用户/家长现身说法）
- 痛点共鸣型（直击目标人群的具体焦虑场景）
- 反转/打脸型（先立一个错误认知，再打破它）
- 沉浸式测评/开箱型（模拟主播实拍开箱讲解）

每条脚本仍要复刻参考脚本 template 里的节奏/段落骨架/CTA 风格，只是创意表达、具体场景、台词不同；不要照抄参考脚本的原台词和具体人物设定。

## 每条脚本的结构要求
- structure：按 hook/setup/buildup/climax/cta（或 other）划分，片段数量与参考脚本大致一致
- dialogue：新台词，只保留最关键的句子即可，每句标注所属 segment_index
- video_prompts：与 structure 一一对应（数量、顺序、role 完全一致）

## 关于 video_prompts 的详细程度（重要，写作时严格区分）
- **hook 分段**（视频最前几秒的悬念/引流片段，业内也叫"前贴"）：jimeng_prompt 和 kling_prompt 必须写得足够完整、具体，能直接复制进 AI 视频工具生成可用画面，必须覆盖：
  1. 场景：地点、时间、环境背景、光线氛围
  2. 人物：外貌特征、衣着、所处位置
  3. 动作：从头到尾的具体动作序列
  4. 状态/情绪：表情与情绪状态
  5. 台词：人物在这个镜头里说的具体台词内容（落到具体文字，不能只写"说话"）
  6. 镜头：运镜方式（推/拉/摇/移/固定/跟随）、景别（远/中/近/特写）
  7. 字幕/音效建议（如有）
  用自然语句/分号连接表达即可，不需要加编号标题。
- **其他分段**（setup/buildup/climax/cta 等）：保持简洁（每条 80-150 字），只需给出核心画面内容 + 镜头运镜 + 关键道具/字幕，不必像 hook 那样逐项展开，避免输出过长。

必须调用 submit_scripts 工具，一次性提交全部 {script_count} 条脚本。
如果输入变量中提供了「历史反馈参考」，请学习其中的话术风格与结构偏好，但不要照抄其中的具体文字。"""


def _build_user_prompt(script_count: int) -> str:
    return f"""请基于下面变量中提供的「参考脚本分析」和「产品资料」，一次性生成 {script_count} 条创意方向不同的新带货脚本（结构骨架复刻参考脚本节奏，内容/打法各异，欢迎新颖大胆的形式）。
hook 分段的 video_prompts 必须完整覆盖场景/人物外貌衣着/动作/情绪状态/具体台词/镜头运镜，可以直接复制去 AI 视频工具生成画面；其他分段保持简洁。
必须调用 submit_scripts 工具提交全部 {script_count} 条。"""


def _coerce_json_fields(data: dict, fields: tuple[str, ...]) -> dict:
    for field in fields:
        value = data.get(field)
        if isinstance(value, str):
            try:
                data[field] = json.loads(value)
            except json.JSONDecodeError:
                data[field] = json.loads(repair_json(value))
    return data


def _extract_tool_input(response: Any) -> dict:
    # OpenAI format: response.choices[0].message.tool_calls
    choices = getattr(response, "choices", [])
    if not choices:
        raise RuntimeError("模型未返回任何内容")
    message = choices[0].message
    tool_calls = getattr(message, "tool_calls", [])
    for tc in tool_calls:
        func = getattr(tc, "function", None)
        if func and getattr(func, "name", None) == "submit_scripts":
            arguments = getattr(func, "arguments", "")
            data = json.loads(arguments) if arguments else {}
            if not isinstance(data, dict):
                raise RuntimeError("submit_scripts 参数必须是 JSON 对象")
            return _coerce_json_fields(data, ("scripts",))
    raise RuntimeError("模型未返回 submit_scripts 工具调用结果")


def _align_video_prompts(script: dict) -> dict:
    """兜底：如果 video_prompts 数量/顺序和 structure 对不上，按 role 重新对齐；
    实在对不上则按位置截断/补齐，保证下游按分段展示时不会越界。"""
    structure = script.get("structure", [])
    prompts = script.get("video_prompts", [])
    by_role: dict[str, dict] = {}
    for p in prompts:
        by_role.setdefault(p.get("role"), p)

    aligned = []
    for i, seg in enumerate(structure):
        role = seg.get("role")
        candidate = by_role.pop(role, None) or (prompts[i] if i < len(prompts) else None)
        if candidate is None:
            continue
        candidate = dict(candidate)
        candidate["role"] = role
        candidate.setdefault("duration_sec", seg.get("duration_sec"))
        # 兜底：Claude 偶尔会漏填 jimeng_prompt / kling_prompt 其中一个字段，
        # 用另一个字段回填，避免因单个字段缺失导致整批 5 条脚本校验失败、重试耗尽后 500。
        if not candidate.get("jimeng_prompt"):
            candidate["jimeng_prompt"] = candidate.get("kling_prompt", "")
        if not candidate.get("kling_prompt"):
            candidate["kling_prompt"] = candidate.get("jimeng_prompt", "")
        aligned.append(candidate)
    script["video_prompts"] = aligned
    return script


def generate_scripts(
    source: AnalysisResult,
    product: Product,
    feedback_examples: list[str] | None = None,
    script_count: int = SCRIPT_COUNT,
) -> tuple[list[ScriptVariant], list[PromptStep]]:
    tool = _build_submit_scripts_tool(script_count)
    system_prompt = _build_system_prompt(script_count)
    user_prompt = _build_user_prompt(script_count)

    variables = {
        "参考脚本分析": source.model_dump(),
        "产品资料": product.model_dump(exclude={"id", "created_at"}),
    }
    if feedback_examples:
        variables["历史反馈参考"] = feedback_examples
    final_prompt = _render_final_prompt(user_prompt, variables)
    model_params = ModelConfig(model=get_openai_model(), temperature=None, max_tokens=MAX_TOKENS)

    client = _get_client()
    last_error: Exception | None = None
    for _attempt in range(1, MAX_SUBMIT_RETRIES + 1):
        started = time.perf_counter()
        response = client.chat.completions.create(
            model=get_openai_model(),
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": final_prompt},
            ],
            tools=[{"type": "function", "function": tool}],
            tool_choice={"type": "function", "function": {"name": "submit_scripts"}},
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        try:
            data = _extract_tool_input(response)
            scripts_data = [_align_video_prompts(s) for s in data.get("scripts", [])]
            scripts = [ScriptVariant.model_validate(s) for s in scripts_data]
            if not scripts:
                raise ValueError("scripts 数组为空")
            if len(scripts) != script_count:
                raise ValueError(f"应返回 {script_count} 条，实际 {len(scripts)} 条")
            step = PromptStep(
                label="脚本生成",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                variables=variables,
                final_prompt=final_prompt,
                model_params=model_params,
                response=json.dumps({"scripts": scripts_data}, ensure_ascii=False, indent=2),
                metadata=_build_metadata(response, elapsed_ms, get_openai_model()),
            )
            return scripts, [step]
        except (json.JSONDecodeError, pydantic.ValidationError, ValueError, RuntimeError) as exc:
            last_error = exc
            continue
    raise RuntimeError(f"模型返回结果解析失败，已重试 {MAX_SUBMIT_RETRIES} 次: {last_error}")


ROLE_LABELS = {
    "hook": "开场钩子（前贴）",
    "setup": "引入",
    "buildup": "铺垫",
    "climax": "高潮/卖点展示",
    "cta": "行动号召",
    "other": "其他",
}


def render_plain_script(script: ScriptVariant) -> str:
    dialogue_by_segment: dict[int, list[NewDialogueLine]] = {}
    for line in script.dialogue:
        dialogue_by_segment.setdefault(line.segment_index, []).append(line)

    parts: list[str] = [f"【{script.variant_title}】{script.variant_style}", ""]
    for i, seg in enumerate(script.structure):
        label = ROLE_LABELS.get(seg.role, seg.role)
        duration = f"（约{seg.duration_sec:.0f}秒）" if seg.duration_sec else ""
        parts.append(f"【{label}】{duration}\n{seg.summary}")
        for line in dialogue_by_segment.get(i, []):
            speaker = f"{line.speaker}：" if line.speaker else ""
            parts.append(f"{speaker}{line.text}")
        parts.append("")
    return "\n".join(parts).strip()

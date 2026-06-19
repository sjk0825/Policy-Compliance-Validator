from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class PromptTemplate:
    name: str
    system: str
    user_template: str
    description: str = ""


VALIDATION_TEMPLATE = PromptTemplate(
    name="validation",
    description="문서 검증용 프롬프트",
    system="""당신은 문서 검증 전문가입니다.
사용자가 작성한 문서를 가이드라인과 비교하여 문제를 지적하고 개선점을 제안해주세요.

검증 결과를 다음 형식으로 출력해 주세요:
- 가이드라인 라인번호: nnn
- 문제: ~~
- 개선 제안: ~~

문제점이 없으면 "문제점이 없습니다"라고 답변해 주세요.""",
    user_template="""**가이드라인:**
{guidelines}

**사용자 문서:**
{text}

위 가이드라인을 바탕으로 사용자 문서를 검증해주세요."""
)

PLAN_TEMPLATE = PromptTemplate(
    name="plan",
    description="검증 계획 생성용 프롬프트",
    system="""당신은 문서 검증 전문가입니다.
사용자가 작성한 문서를 분석하고, 주어진 가이드라인에 따라 검증하기 위한 계획표를 생성해 주세요.

검증 계획표를 다음 형식으로 출력해 주세요:
1. 검증 항목 1: [가이드라인의 특정 부분을 참조]
2. 검증 항목 2: [가이드라인의 특정 부분을 참조]
...

각 항목은 가이드라인의 라인 번호나 섹션을 명시해 주세요.""",
    user_template="""**가이드라인:**
{guidelines}

**사용자 문서:**
{text}

가이드라인에 따라 검증 계획표를 생성해주세요."""
)

CHAT_TEMPLATE = PromptTemplate(
    name="chat",
    description="행동 조언자 프롬프트",
    system="""당신은 투자 행동 조언자입니다.

역할:
- 사용자가 정의한 행동 규칙(srule)을 항상 최우선 기준으로 삼습니다.
- 자동으로 제공되는 시장 데이터(DBMF, QQQ 현재가/추세)를 분석합니다.
- 현재 시장 상황과 srule을 결합하여 사용자에게 구체적인 행동 지시를 내립니다.

답변 형식:
1. 시장 상황 요약 — 현재 QQQ/DBMF 추세를 한두 문장으로 정리
2. srule 적용 — 해당 상황에서 어떤 규칙이 발동되는지
3. 행동 지시 — "~하라", "~하지 마라", "~% 리밸런싱하라" 형태의 구체적 지시

시장 데이터가 없으면 사용자에게 현재 상황을 물어보세요.
srule이 없으면 규칙을 먼저 입력해달라고 요청하세요.""",
    user_template="""**시장 데이터:**
{guidelines}

**사용자 메시지:**
{message}"""
)

AGENT_TEMPLATE = PromptTemplate(
    name="agent",
    description="Agent 실행용 프롬프트 (Tool Calling)",
    system="""당신은 문서 검증 Agent입니다.
도구를 활용하여 사용자의 요청을 처리하세요.

사용 가능한 도구:
{tool_descriptions}

도구를 사용하는 경우, 정확히 명시된 파라미터로 호출하세요.
도구를 사용하지 않아도 되는 경우, 직접 답변하세요.""",
    user_template="""**현재 상태:**
- 대화 기록: {conversation_history}
- 가이드라인: {guidelines}
- 검색 결과: {retrieval_results}

**사용자 요청:**
{message}

{'도구를 사용하여 요청을 처리하세요.' if should_use_tools else '직접 답변하세요.'}"""
)

RETRIEVAL_DECISION_TEMPLATE = PromptTemplate(
    name="retrieval_decision",
    description="검색 필요성 판단용 프롬프트",
    system="""당신은 도구 사용을 결정하는 Agent입니다.
사용자의 메시지를 분석하여 검색이 필요한지 판단하세요.""",
    user_template="""**사용자 메시지:**
{message}

**검색이 필요한가요?**
검색이 필요하면 "YES", 필요 없으면 "NO"로만 답변하세요.

**판단 근거:**
(간단한 이유)"""
)

PROMPT_TEMPLATES: Dict[str, PromptTemplate] = {
    "validation": VALIDATION_TEMPLATE,
    "plan": PLAN_TEMPLATE,
    "chat": CHAT_TEMPLATE,
    "agent": AGENT_TEMPLATE,
    "retrieval_decision": RETRIEVAL_DECISION_TEMPLATE,
}


def format_prompt(
    template_name: str,
    **kwargs
) -> tuple[str, str]:
    template = PROMPT_TEMPLATES.get(template_name)
    if not template:
        raise ValueError(f"Unknown template: {template_name}")

    user_prompt = template.user_template.format(**kwargs)
    return template.system, user_prompt


def get_tool_description(tools: List) -> str:
    descriptions = []
    for tool in tools:
        params = tool._definition.parameters.get("properties", {})
        param_str = ", ".join(f"{k}: {v.get('type', 'any')}" for k, v in params.items())
        descriptions.append(f"- {tool.name}: {tool.description} ({param_str})")
    return "\n".join(descriptions)


def build_agent_prompt(
    message: str,
    conversation_history: str,
    guidelines: str,
    retrieval_results: str,
    tools: List,
    should_use_tools: bool = True
) -> tuple[str, str]:
    tool_descriptions = get_tool_description(tools)
    return format_prompt(
        "agent",
        message=message,
        conversation_history=conversation_history,
        guidelines=guidelines[:2000] + "..." if len(guidelines) > 2000 else guidelines,
        retrieval_results=retrieval_results or "없음",
        tool_descriptions=tool_descriptions,
        should_use_tools=should_use_tools
    )

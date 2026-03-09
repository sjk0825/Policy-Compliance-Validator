import os
import anthropic
from .base import BaseLLM


class ClaudeLLM(BaseLLM):
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def validate(self, text: str, guidelines: str) -> str:
        prompt = f"""당신은 문서 검증专家입니다. 
다음 가이드라인과 사용자가 작성한 문서를 비교하여 문제를指出해ってください.

**가이드라인:**
{guidelines}

**사용자 문서:**
{text}

검증 결과를 다음 형식으로输出해 주세요:
- 가이드라인 라인번호: nnn
- 문제: ~~
- 개선 제안: ~~

문제점이 없으면 "문제점이 없습니다"라고 답변해 주세요."""

        response = self.client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.content[0].text

    def plan(self, text: str, guidelines: str) -> str:
        prompt = f"""당신은 문서 검증 전문가입니다.
사용자가 작성한 문서를 분석하고, 주어진 가이드라인에 따라 검증하기 위한 계획표를 생성해 주세요.

**가이드라인:**
{guidelines}

**사용자 문서:**
{text}

검증 계획표를 다음 형식으로 출력해 주세요:
1. 검증 항목 1: [가이드라인의 특정 부분을 참조]
2. 검증 항목 2: [가이드라인의 특정 부분을 참조]
...

각 항목은 가이드라인의 라인 번호나 섹션을 명시해 주세요."""

        response = self.client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.content[0].text

    def get_provider_name(self) -> str:
        return "Claude"

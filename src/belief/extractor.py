import json
import logging

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """你是一个信念提取专家。请从以下对话中，**只从标记为「我」的消息中**提取立场、观点、偏好和信念。

关键规则：
1. **只提取「我」说的内容中表达的观点**。「对方」的消息仅作为理解上下文用，绝对不要提取对方的观点当作我的
2. 只提取明确表达或强烈暗示的观点，不要过度推断
3. 注意对话上下文：如果「我」提到某件事但随后否定或澄清，以最终立场为准
4. 每条信念包含：topic（主题）、stance（我的具体立场）、condition（成立条件，可为空字符串）、confidence（0-1，表达的明确程度）
5. 返回严格的 JSON 数组格式，不要包含其他文字

对话内容：
{conversation}

请返回 JSON 数组："""


class BeliefExtractor:
    def __init__(
        self,
        api_provider: str = "openai",
        api_key: str = "",
        model: str = "gpt-4o-mini",
        **kwargs,
    ) -> None:
        self.api_provider = api_provider
        self.model = model

        self.base_url = kwargs.get("base_url")

        self.headers = kwargs.get("headers")

        if api_provider in ("openai", "gemini"):
            import openai
            client_kwargs = {"api_key": api_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            if self.headers:
                client_kwargs["default_headers"] = self.headers
            self.client = openai.OpenAI(**client_kwargs)
        elif api_provider == "anthropic":
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
        else:
            raise ValueError(f"Unsupported api_provider: {api_provider}")

    def extract_beliefs(self, conversation_text: str) -> list[dict]:
        prompt = EXTRACTION_PROMPT.format(conversation=conversation_text)

        try:
            raw = self._call_llm(prompt)
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                beliefs = next(
                    (v for v in parsed.values() if isinstance(v, list)), []
                )
            elif isinstance(parsed, list):
                beliefs = parsed
            else:
                logger.warning("Unexpected JSON type: %s", type(parsed))
                return []
            return [self._normalize_belief(b) for b in beliefs if isinstance(b, dict)]
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM response as JSON: %s", raw[:200])
            return []
        except Exception as e:
            logger.error("Belief extraction failed: %s", e)
            return []

    def _call_llm(self, prompt: str) -> str:
        if self.api_provider in ("openai", "gemini"):
            create_kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "你是一个信念提取专家，只返回 JSON 格式数据。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
            }
            if self.api_provider == "openai":
                create_kwargs["response_format"] = {"type": "json_object"}
            response = self.client.chat.completions.create(**create_kwargs)
            return response.choices[0].message.content or "[]"
        else:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return response.content[0].text

    @staticmethod
    def _normalize_belief(b: dict) -> dict:
        return {
            "topic": b.get("topic", ""),
            "stance": b.get("stance", ""),
            "condition": b.get("condition", ""),
            "confidence": min(1.0, max(0.0, float(b.get("confidence", 0.5)))),
        }

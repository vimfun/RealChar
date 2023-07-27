import os

os.environ["http_proxy"] = 'http://127.0.0.1:7890'
os.environ["https_proxy"] = 'http://127.0.0.1:7890'

from realtime_ai_character.llm.base import (
    LLM,
    AsyncCallbackAudioHandler,
    AsyncCallbackTextHandler,
)


def get_llm(model='gpt-3.5-turbo-16k') -> LLM:
    if model.startswith('gpt'):
        from realtime_ai_character.llm.openai_llm import OpenaiLlm
        return OpenaiLlm(model=model)
    elif model.startswith('claude'):
        from realtime_ai_character.llm.anthropic_llm import AnthropicLlm
        return AnthropicLlm(model=model)
    else:
        raise ValueError(f'Invalid llm model: {model}')

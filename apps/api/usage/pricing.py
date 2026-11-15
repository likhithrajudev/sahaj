"""What a call costs, in US dollars. All prices come from config and are estimates: see the note there."""
import config


def llm_cost(provider: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    """Cost of one model call. `cached_tokens` are the part of the input served from the provider's prompt cache."""
    if provider == "openai":
        p_in, p_cached, p_out = config.OPENAI_PRICE_IN_PER_M, config.OPENAI_PRICE_CACHED_PER_M, config.OPENAI_PRICE_OUT_PER_M
    else:
        p_in, p_cached, p_out = (config.SARVAM_LLM_PRICE_IN_PER_M, config.SARVAM_LLM_PRICE_CACHED_PER_M,
                                 config.SARVAM_LLM_PRICE_OUT_PER_M)
    cached = min(cached_tokens, input_tokens)
    return ((input_tokens - cached) * p_in + cached * p_cached + output_tokens * p_out) / 1_000_000


def stt_seconds(audio_bytes: int) -> float:
    return audio_bytes / max(config.STT_BYTES_PER_SECOND, 1)


def stt_cost(seconds: float) -> float:
    return seconds / 3600 * config.SARVAM_STT_PRICE_PER_HOUR


def tts_cost(chars: int) -> float:
    return chars / 10_000 * config.SARVAM_TTS_PRICE_PER_10K_CHARS

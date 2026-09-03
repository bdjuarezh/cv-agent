from cv_agent.providers.anthropic_messages import system_blocks, to_anthropic_messages
from cv_agent.providers.base import Message, ToolCall


def test_system_blocks_solo_corpus_cuando_no_hay_instructions() -> None:
    blocks = system_blocks("corpus y reglas", "")
    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_system_blocks_segundo_bloque_sin_cache_control_con_instructions() -> None:
    blocks = system_blocks("corpus y reglas", "instrucciones del cliente")
    assert len(blocks) == 2
    assert "cache_control" not in blocks[1]
    assert blocks[1]["text"] == "instrucciones del cliente"


def test_to_anthropic_messages_turnos_simples() -> None:
    out = to_anthropic_messages(
        [
            Message(role="user", content="hola"),
            Message(role="assistant", content="hola, ¿en qué ayudo?"),
        ]
    )
    assert out == [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "hola, ¿en qué ayudo?"},
    ]


def test_to_anthropic_messages_tool_calls_en_bloques_tool_use() -> None:
    out = to_anthropic_messages(
        [
            Message(
                role="assistant",
                content="",
                tool_calls=(ToolCall(id="t1", name="get_skills", arguments={"min_level": 4}),),
            )
        ]
    )
    assert out == [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "get_skills", "input": {"min_level": 4}}
            ],
        }
    ]


def test_to_anthropic_messages_tool_results_consecutivos_se_agrupan() -> None:
    out = to_anthropic_messages(
        [
            Message(role="tool", content="[]", tool_call_id="t1"),
            Message(role="tool", content="{}", tool_call_id="t2"),
        ]
    )
    assert out == [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "[]"},
                {"type": "tool_result", "tool_use_id": "t2", "content": "{}"},
            ],
        }
    ]

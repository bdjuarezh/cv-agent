from cv_agent.schemas.requests import CreateResponseBody
from cv_agent.schemas.responses import REQUIRED_FIELDS, Response


def test_response_tiene_todos_los_campos_required_del_spec() -> None:
    assert set(Response.model_fields) == REQUIRED_FIELDS


def test_response_serializa_con_llaves_nunca_omitidas() -> None:
    resp = Response(id="resp_1", created_at=0, model="cv-agent")
    dumped = resp.model_dump(mode="json")
    assert REQUIRED_FIELDS <= set(dumped.keys())


def test_create_response_body_campo_desconocido_no_falla() -> None:
    body = CreateResponseBody.model_validate(
        {"input": "hola", "reasoning": {"effort": "medium"}, "algo_no_modelado": 123}
    )
    assert body.model_extra is not None
    assert "algo_no_modelado" in body.model_extra


def test_create_response_body_model_ausente_no_falla() -> None:
    body = CreateResponseBody.model_validate({"input": "hola"})
    assert body.model is None


def test_create_response_body_input_item_sin_type() -> None:
    body = CreateResponseBody.model_validate(
        {"input": [{"role": "user", "content": "hola sin type"}]}
    )
    assert isinstance(body.input, list)
    assert body.input[0].type == "message"  # type: ignore[union-attr]


def test_create_response_body_input_item_con_content_parts() -> None:
    body = CreateResponseBody.model_validate(
        {
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hola"}],
                }
            ]
        }
    )
    assert isinstance(body.input, list)


def test_create_response_body_metadata_excede_16_pares_falla() -> None:
    import pytest
    from pydantic import ValidationError

    metadata = {f"k{i}": "v" for i in range(17)}
    with pytest.raises(ValidationError):
        CreateResponseBody.model_validate({"input": "hola", "metadata": metadata})

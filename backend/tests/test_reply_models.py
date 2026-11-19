"""The permissive reply models cover every property of the three hand-written Bedrock schemas and reject nothing."""
import json

import pytest

from cytonn_weekly.drafting import bedrock, prompts, reply_models as rm

CLAIM_URL = prompts.RESPONSE_SCHEMA["properties"]["claims"]["items"]
CLAIM_SRC = bedrock.SOURCED_SCHEMA["properties"]["claims"]["items"]
PDF_ITEM = bedrock.PDF_SCHEMA["properties"]["passages"]["items"]

PAIRS = [(prompts.RESPONSE_SCHEMA, rm.DraftReply), (CLAIM_URL, rm.UrlClaim), (CLAIM_SRC, rm.SourcedClaim),
         (bedrock.PDF_SCHEMA, rm.PdfReply), (PDF_ITEM, rm.PdfPassage)]


@pytest.mark.parametrize("schema,model", PAIRS)
def test_a_model_has_every_property_of_its_schema_and_no_other_required_field(schema, model):
    assert set(schema["properties"]) == set(model.model_fields)
    assert {n for n, f in model.model_fields.items() if f.is_required()} <= set(schema["required"])


@pytest.mark.parametrize("model", [m for _, m in PAIRS if m is not rm.PdfReply])
def test_a_model_accepts_any_types_and_extra_keys(model):
    m = model.model_validate({"surprise": [1], **{f: {"x": 1} for f in model.model_fields}})
    assert m.surprise == [1] and model.model_validate({}) is not None


def test_claims_are_decoded_like_the_hand_written_reader():
    claims = ['{"claim": "a", "url": "u"}', "not json", {"claim": "b"}, 5]
    assert rm.DraftReply.model_validate({"claims": json.dumps(claims)}).claims == [{"claim": "a", "url": "u"}, None, {"claim": "b"}, None]
    assert rm.DraftReply.model_validate({"claims": claims}).claims == [{"claim": "a", "url": "u"}, None, {"claim": "b"}, None]
    for bad in (None, "", "oops", 3, {"a": 1}):
        assert rm.DraftReply.model_validate({"claims": bad}).claims == []
    assert rm.DraftReply.model_validate({}).claims == []


def test_pdf_passages_keep_only_objects_and_need_the_key():
    assert rm.PdfReply.model_validate({"passages": [{"page": 1, "quote": "q"}, "x", 3]}).passages == [{"page": 1, "quote": "q"}]
    assert rm.PdfReply.model_validate({"passages": "nope"}).passages == []
    for bad in ({}, [], "x", None):
        with pytest.raises(ValueError):
            rm.PdfReply.model_validate(bad)

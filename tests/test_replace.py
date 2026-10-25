from aipg_cinema import replace


def test_prompts_rebuild_the_person_and_follow_the_voice():
    assert "Remove the person completely" in replace.PLATE
    assert "exact person from the first image" in replace.PLACE
    assert "fully clothed" in replace.PLACE and "{note}" in replace.PLACE
    assert "supplied speech" in replace.TALK


def test_replacement_routes_validate(tmp_path):
    from fastapi.testclient import TestClient

    from aipg_cinema import app

    body = {"request_id": "a" * 32, "source_id": "b" * 32, "photo_id": "c" * 32}
    moss = TestClient(app.create_app(tmp_path / "a"), base_url="http://localhost")
    assert moss.post("/api/replacements", json=body).status_code == 409
    klein = TestClient(
        app.create_app(tmp_path / "b", look_engine="klein"), base_url="http://localhost"
    )
    assert klein.post("/api/replacements", json=body).status_code == 404
    assert (
        klein.post("/api/replacements", json={**body, "note": "x" * 301}).status_code
        == 422
    )
    assert klein.get("/api/replacements/" + "d" * 32).status_code == 404
    assert klein.get("/api/replacements/" + "d" * 32 + "/output").status_code == 404


def test_photo_looks_may_take_reference_images():
    from aipg_cinema.contracts import LookRequest

    look = LookRequest(
        request_id="a" * 32,
        look_input="image",
        image_id="b" * 32,
        reference_ids=["c" * 32],
        prompt="Place this person",
        denoise=None,
    )
    assert look.reference_ids == ["c" * 32]

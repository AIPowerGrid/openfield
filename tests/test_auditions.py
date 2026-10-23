import json

import pytest
from comfy_sdk.workflows import WorkflowFactory
from pydantic import ValidationError
from test_app import complete_look, upload, upload_look

from aipg_cinema import look
from aipg_cinema.contracts import LookRequest
from aipg_cinema.project import LookAudition, Project


@pytest.mark.parametrize("kind", ["text", "image"])
@pytest.mark.parametrize("engine", ["moss", "klein-cloud"])
@pytest.mark.parametrize("framing", ["portrait", "square", "landscape"])
def test_image_and_text_graphs_bind_real_inputs(kind, engine, framing):
    factory = look.graph if engine == "moss" else look.klein_graph
    graph = factory(
        "A ceramic paper boat", from_image=kind == "image", frame_format=framing
    )
    assert WorkflowFactory().from_json(graph).json == graph
    assert ("source" in graph) == (kind == "image")
    for node in graph.values():
        for item in node["inputs"].values():
            if isinstance(item, list):
                assert item[0] in graph
    if kind == "text":
        assert graph["empty"]["inputs"]["batch_size"] == 1
        assert (
            graph["empty"]["inputs"]["width"],
            graph["empty"]["inputs"]["height"],
        ) == look.SIZES[framing]
        if engine == "moss":
            assert graph["sample"]["inputs"]["denoise"] == 1
        else:
            assert "ref-positive" not in graph


@pytest.mark.parametrize(
    "changes",
    [
        {"look_input": "text", "source_id": "b" * 32},
        {"look_input": "image"},
        {"look_input": "image", "image_id": "b" * 32, "source_start": 1},
        {"project_id": "b" * 32},
        {"project_id": "b" * 32, "shot_id": "c" * 32, "project_revision": 1},
    ],
)
def test_conflicting_or_incomplete_look_inputs_are_rejected(changes):
    with pytest.raises(ValidationError):
        LookRequest.model_validate(
            {
                "request_id": "a" * 32,
                "look_input": "text",
                "prompt": "A boat",
                **changes,
            }
        )


@pytest.mark.parametrize("kind", ["text", "image"])
def test_api_look_inputs_repeat_same_id_and_never_generate_video(moss, kind):
    client, root, processes = moss
    body = {
        "request_id": "a" * 32,
        "look_input": kind,
        "prompt": "A ceramic boat",
        "denoise": 1 if kind == "text" else 0.65,
        "audition": True,
    }
    if kind == "image":
        body["image_id"] = upload_look(client)
    assert client.post("/api/look-jobs", json=body).status_code == 200
    assert client.post("/api/look-jobs", json=body).status_code == 200
    assert len(processes) == 1
    args = processes[0].args
    assert args[args.index("--look-input") + 1] == kind
    assert not list((root / "jobs").iterdir())
    complete_look(root, processes, body)
    if kind == "text":
        (root / "looks" / body["request_id"] / "render" / "source.png").unlink()
    info = client.get(f"/api/look-jobs/{body['request_id']}/settings").json()
    assert info["look_input"] == kind
    assert info["source"] == ("source.png" if kind == "image" else None)
    assert "base_url" not in json.dumps(info)
    assert client.get(f"/api/look-jobs/{body['request_id']}/source").status_code == (
        200 if kind == "image" else 404
    )
    assert client.post("/api/look-jobs", json={**body, "seed": 99}).status_code == 409


def test_project_audition_is_saved_frozen_and_stale_requests_cannot_dispatch(moss):
    client, root, processes = moss
    data = client.post("/api/projects", json={"title": "Look trials"}).json()
    project = Project.model_validate(data)
    shot = project.shots[0]
    shot.audition = LookAudition(
        direction="A red paper boat, macro photography", seed=71
    )
    project = Project.model_validate(
        client.put(f"/api/projects/{project.id}", json=project.model_dump()).json()
    )
    body = project.look_request(shot.id, "a" * 32, "moss").model_dump()
    assert body["look_input"] == "text" and body["denoise"] == 1
    assert (
        client.post("/api/look-jobs", json={**body, "prompt": "Forged"}).status_code
        == 409
    )
    assert (
        client.post("/api/look-jobs", json={**body, "shot_id": "e" * 32}).status_code
        == 409
    )
    assert not processes
    assert client.post("/api/look-jobs", json=body).status_code == 200
    complete_look(root, processes, body)
    project.shots[0].audition.left_id = body["request_id"]
    project.shots[0].audition.direction = "A different look"
    saved = client.put(f"/api/projects/{project.id}", json=project.model_dump())
    assert saved.status_code == 200
    reopened = Project.model_validate(saved.json())
    assert reopened.shots[0].audition.left_id == body["request_id"]
    assert client.post("/api/look-jobs", json=body).status_code == 200
    assert (
        client.post("/api/look-jobs", json={**body, "request_id": "b" * 32}).status_code
        == 409
    )
    assert len(processes) == 1
    assert not list((root / "jobs").iterdir())


def test_project_pins_reference_instead_of_rebasing_on_selected_result(moss):
    client, _, _ = moss
    project = Project.model_validate(client.post("/api/projects", json={}).json())
    shot = project.shots[0]
    baseline, applied = upload_look(client), upload_look(client)
    shot.audition = LookAudition(direction="A blue ceramic boat", reference_id=baseline)
    shot.draft.look_id = applied
    assert project.look_request(shot.id, "a" * 32, "moss").image_id == baseline
    assert project.look_request(shot.id, "a" * 32, "klein-cloud").denoise is None
    shot.draft.mode = "video"
    shot.draft.source_id = upload(client)
    shot.draft.source_start = 0.1
    shot.audition.frame_index = 120
    request = project.look_request(shot.id, "a" * 32, "moss")
    assert request.look_input == "video" and request.image_id is None
    assert request.frame_index == 120 and request.source_start == 0.1

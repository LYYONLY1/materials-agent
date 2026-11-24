import time

from fastapi.testclient import TestClient

from materials_agent.api import create_app


COPPER = """4
Copper FCC
Cu 0.12 0.04 0.06
Cu 0 1.805 1.805
Cu 1.805 0 1.805
Cu 1.805 1.805 0
"""


def test_custom_structure_relaxes_and_survives_restart(tmp_path):
    request = {"xyz": COPPER, "cell": 3.61, "calculation": "relaxation", "approved": True}
    headers = {"Idempotency-Key": "copper-relaxation"}
    with TestClient(create_app(tmp_path)) as client:
        preview = client.post("/api/structures/preview", json=request)
        assert preview.status_code == 200
        assert preview.json()["formula"] == "Cu4"
        created = client.post("/api/experiments", json=request, headers=headers)
        assert created.status_code == 202
        task_id = created.json()["task_id"]
        assert client.post("/api/experiments", json=request, headers=headers).json()["task_id"] == task_id
        changed = client.post("/api/experiments", json={**request, "calculation": "energy"}, headers=headers)
        assert changed.status_code == 409
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            task = client.get(f"/api/tasks/{task_id}").json()
            if task["status"] in {"failed", "succeeded"}:
                break
            time.sleep(0.05)
        assert task["status"] == "succeeded", task
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        assert client.get("/api/experiments").json()["experiments"][0]["id"] == task_id
        result = client.get(f"/api/tasks/{task_id}").json()["result"]
        assert result["converged"]
        assert result["energy_ev"] < result["initial_energy_ev"]
        trajectory = result["trajectory"]
        assert [point["step"] for point in trajectory] == list(range(result["steps"] + 1))
        assert trajectory[-1]["max_force_ev_per_angstrom"] <= result["force_threshold_ev_per_angstrom"]
        initial = client.get(f"/api/tasks/{task_id}/structure", params={"stage": "initial"})
        final = client.get(f"/api/tasks/{task_id}/structure")
        assert initial.text.startswith("4\nLattice=")
        assert initial.text != final.text


def test_preview_rejects_periodic_overlap_and_experiments_require_approval(tmp_path):
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        rejected = client.post("/api/structures/preview", json={"xyz": "2\n\nCu 0 0 0\nCu 4 0 0", "cell": 4})
        assert rejected.status_code == 422
        assert "周期边界" in rejected.json()["detail"]
        unapproved = client.post("/api/experiments", json={
            "xyz": COPPER, "cell": 3.61, "calculation": "energy", "approved": False,
        })
        assert unapproved.status_code == 422
        assert client.get("/api/experiments").json() == {"experiments": []}


def test_bookmarked_agent_runs_keep_their_route(tmp_path):
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        run_id = client.post("/api/runs", json={"message": "查一下硅的资料"}).json()["run_id"]
        bookmark = client.get("/", params={"run": run_id}, follow_redirects=False)
        assert bookmark.status_code == 307
        assert bookmark.headers["location"] == f"/agent?run={run_id}"
        assert client.get("/assets/vendor/3Dmol-min.js").status_code == 200

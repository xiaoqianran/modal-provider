from modal_world.models import get_model
from modal_world.pipelines import list_stages, validate_stage_modules


def test_world_stage_topology_matches_model_catalog():
    stages = list_stages()
    assert not validate_stage_modules()
    assert len(stages) == 5
    model = get_model("hyworld2")
    assert {stage.app for stage in stages} == set(model.deployment_apps)
    assert all(stage.models == (model.id,) for stage in stages)

def test_control_app_imports_and_exposes_only_control_plane():
    import modal_2d.app as app

    assert app.APP_NAME == "modal-2d"
    assert app.capabilities_document()["contract"] == "modal-2d.generation.v2"
    assert not hasattr(app, "SanaSprintWorker")
    assert not hasattr(app, "Model")
    assert app.HUGGINGFACE_SECRET_NAME == ""
    assert app.PREFETCH_SECRETS == []

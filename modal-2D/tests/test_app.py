def test_modal_app_imports_and_exposes_stable_functions():
    import modal_2d.app as app

    assert app.APP_NAME == "modal-2d"
    assert app.capabilities_document()["operation"] == "modal-2d.image.text_to_image.v1"
    assert not hasattr(app, "submit")
    assert not hasattr(app, "submit_batch")

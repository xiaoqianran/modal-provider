def test_model_workers_have_isolated_apps_and_common_entrypoint():
    from modal_2d.workers import hidream_o1, qwen_image_2512, sana_sprint, z_image_turbo

    assert sana_sprint.APP_NAME == "modal-2d-sana-sprint"
    assert qwen_image_2512.APP_NAME == "modal-2d-qwen-image-2512"
    assert z_image_turbo.APP_NAME == "modal-2d-z-image-turbo"
    assert hidream_o1.APP_NAME == "modal-2d-hidream-o1"
    assert all(
        hasattr(module, "Model")
        for module in (sana_sprint, qwen_image_2512, z_image_turbo, hidream_o1)
    )

from __future__ import annotations

import unittest

from modal_3d.hunyuan_runtime import (
    COMPILE_ENV,
    FLASHVDM_ENV,
    SAGEATTN_ENV,
    HunyuanRuntimeAcceleration,
    apply_shape_runtime_acceleration,
)


class _FakePipe:
    def __init__(self):
        self.calls = []

    def enable_flashvdm(self, **kwargs):
        self.calls.append(("flashvdm", kwargs))

    def compile(self):
        self.calls.append(("compile", {}))


class HunyuanRuntimeTests(unittest.TestCase):
    def test_defaults_preserve_verified_path(self) -> None:
        config = HunyuanRuntimeAcceleration.from_env({})
        self.assertEqual(
            config.as_dict(),
            {"flashvdm": False, "torch_compile": False, "sageattention": False},
        )

    def test_explicit_env_switches(self) -> None:
        config = HunyuanRuntimeAcceleration.from_env(
            {FLASHVDM_ENV: "1", COMPILE_ENV: "1", SAGEATTN_ENV: "0"}
        )
        pipe = _FakePipe()
        apply_shape_runtime_acceleration(pipe, config)
        self.assertEqual(
            pipe.calls,
            [
                ("flashvdm", {"replace_vae": False, "mc_algo": "mc"}),
                ("compile", {}),
            ],
        )

    def test_invalid_boolean_env_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, FLASHVDM_ENV):
            HunyuanRuntimeAcceleration.from_env({FLASHVDM_ENV: "yes"})

    def test_missing_fork_feature_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "enable_flashvdm"):
            apply_shape_runtime_acceleration(object(), HunyuanRuntimeAcceleration(flashvdm=True))
        with self.assertRaisesRegex(RuntimeError, "compile"):
            apply_shape_runtime_acceleration(object(), HunyuanRuntimeAcceleration(compile=True))


if __name__ == "__main__":
    unittest.main()

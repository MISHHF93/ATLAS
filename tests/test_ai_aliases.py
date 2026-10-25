import importlib
import pickle


def test_old_paths_are_same_module_objects():
    for old, new in [("atlas.models.quant.cv", "atlas.ai.models.quant.cv"),
                     ("atlas.models.challengers", "atlas.ai.models.challengers")]:
        a, b = importlib.import_module(old), importlib.import_module(new)
        assert a is b and a.__spec__.name == new


def test_pickles_with_old_module_path_resolve():
    from atlas.ai.models.quant import cv

    blob = pickle.dumps(cv.purged_walk_forward, protocol=0).replace(b"atlas.ai.models", b"atlas.models")
    assert pickle.loads(blob) is cv.purged_walk_forward


def test_unknown_alias_target_is_not_found():
    import pytest

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("atlas.models.does_not_exist_xyz")


def test_shared_schemas_are_neutral_and_aliased():
    import atlas.ai.models.schemas as b
    import atlas.models.schemas as a
    import atlas.schemas as c

    assert a is b is c and c.__spec__.name == "atlas.schemas"

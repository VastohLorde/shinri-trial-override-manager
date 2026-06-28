import importlib
import json
import os
import shutil
import sys
import tempfile
import types
import unittest


sys.modules.setdefault("translate_cache", types.SimpleNamespace())
sys.modules.setdefault("live_translator", types.SimpleNamespace())
om = importlib.import_module("override_manager")


class RetargetingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def write_file(self, rel, data=b"x"):
        path = os.path.join(self.tempdir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "wb" if isinstance(data, bytes) else "w"
        kwargs = {} if isinstance(data, bytes) else {"encoding": "utf-8"}
        with open(path, mode, **kwargs) as f:
            f.write(data)
        return path

    def test_target_slug_and_addon_slug_include_target_for_non_default(self):
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko"}
        target = {"name": "Mukuro Ikusaba"}

        self.assertEqual("default", om.target_slug(om.DEFAULT_TARGET_NAME))
        self.assertEqual("mukuro_ikusaba", om.target_slug("Mukuro Ikusaba"))
        self.assertEqual("ovr_hoshino_himiko", om.addon_slug(pack, None))
        self.assertEqual("ovr_hoshino_himiko__mukuro_ikusaba", om.addon_slug(pack, target))

    def test_infer_source_target_from_pack_files(self):
        pack_dir = os.path.join(self.tempdir, "Hoshino Himiko")
        self.write_file("Hoshino Himiko/models/dro/player/characters3/char12/char12.mdl")
        self.write_file("Hoshino Himiko/models/dro/player/characters3/char12/char12.dx90.vtx")
        self.write_file("Hoshino Himiko/models/dro/player/characters3/char12/c_arms/char12_arms.mdl")
        self.write_file("Hoshino Himiko/materials/dro/sprites/characters/dr_v3/himiko yumeno/ct_sprite_1.vtf")

        source = om.infer_source_target(pack_dir)

        self.assertEqual("models/dro/player/characters3/char12/char12", source["model_base"])
        self.assertEqual("models/dro/player/characters3/char12/c_arms/char12_arms", source["arms_base"])
        self.assertEqual("materials/dro/sprites/characters/dr_v3/himiko yumeno", source["sprite_dir"])

    def test_infer_source_target_prefers_override_json(self):
        pack_dir = os.path.join(self.tempdir, "Pack")
        os.makedirs(pack_dir, exist_ok=True)
        with open(os.path.join(pack_dir, "override.json"), "w", encoding="utf-8") as f:
            json.dump({
                "source_target": {
                    "model_base": "models/dro/player/characters3/char12/char12.mdl",
                    "arms_base": "models/dro/player/characters3/char12/c_arms/char12_arms.mdl",
                    "sprite_dir": "materials/dro/sprites/characters/dr_v3/himiko yumeno/"
                }
            }, f)

        source = om.infer_source_target(pack_dir)

        self.assertEqual("models/dro/player/characters3/char12/char12", source["model_base"])
        self.assertEqual("models/dro/player/characters3/char12/c_arms/char12_arms", source["arms_base"])
        self.assertEqual("materials/dro/sprites/characters/dr_v3/himiko yumeno", source["sprite_dir"])

    def test_retarget_path_maps_model_arms_and_sprite_paths(self):
        source = {
            "model_base": "models/dro/player/characters3/char12/char12",
            "arms_base": "models/dro/player/characters3/char12/c_arms/char12_arms",
            "sprite_dir": "materials/dro/sprites/characters/dr_v3/himiko yumeno",
        }
        target = {
            "name": "Mukuro Ikusaba",
            "model_base": "models/dro/player/characters1/char16/char16",
            "arms_base": "models/dro/player/characters1/char16/c_arms/char16_arms",
            "sprite_dir": "materials/dro/sprites/characters/dr_1/mukuro ikusaba",
        }

        self.assertEqual(
            "models/dro/player/characters1/char16/char16.mdl",
            om.map_retarget_path("models/dro/player/characters3/char12/char12.mdl", source, target),
        )
        self.assertEqual(
            "models/dro/player/characters1/char16/c_arms/char16_arms.dx90.vtx",
            om.map_retarget_path("models/dro/player/characters3/char12/c_arms/char12_arms.dx90.vtx", source, target),
        )
        self.assertEqual(
            "materials/dro/sprites/characters/dr_1/mukuro ikusaba/ct_sprite_1.vtf",
            om.map_retarget_path("materials/dro/sprites/characters/dr_v3/himiko yumeno/ct_sprite_1.vtf", source, target),
        )
        self.assertEqual(
            "materials/models/hoshino_new/hair.vmt",
            om.map_retarget_path("materials/models/hoshino_new/hair.vmt", source, target),
        )

    def test_retarget_path_leaves_sprites_when_target_sprite_missing(self):
        source = {
            "model_base": "models/dro/player/characters3/char12/char12",
            "arms_base": "models/dro/player/characters3/char12/c_arms/char12_arms",
            "sprite_dir": "materials/dro/sprites/characters/dr_v3/himiko yumeno",
        }
        target = {
            "name": "Mukuro Ikusaba",
            "model_base": "models/dro/player/characters1/char16/char16",
            "arms_base": "models/dro/player/characters1/char16/c_arms/char16_arms",
            "sprite_dir": "",
        }

        self.assertEqual(
            "materials/dro/sprites/characters/dr_v3/himiko yumeno/ct_sprite_1.vtf",
            om.map_retarget_path("materials/dro/sprites/characters/dr_v3/himiko yumeno/ct_sprite_1.vtf", source, target),
        )

    def test_builtin_angie_target_has_sprite_directory(self):
        target = om.find_target({}, "Angie Yonaga")

        self.assertEqual("materials/dro/sprites/characters/dr_v3/angie yonaga", target["sprite_dir"])

    def test_target_change_needs_auto_apply_when_pack_already_enabled(self):
        addons = os.path.join(self.tempdir, "addons")
        os.makedirs(os.path.join(addons, "ovr_hoshino_himiko"), exist_ok=True)
        cfg = {"gmod_path": self.tempdir}
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko"}

        self.assertTrue(om.target_change_needs_apply(cfg, pack, "Angie Yonaga"))
        self.assertFalse(om.target_change_needs_apply(cfg, pack, om.DEFAULT_TARGET_NAME))

    def test_parse_mdl_bodygroups_from_hoshino_model(self):
        path = r"C:\Users\user\Desktop\GMod_Override_Manager\overrides\Hoshino Himiko\models\dro\player\characters3\char12\char12.mdl"
        if not os.path.exists(path):
            self.skipTest("Hoshino override model not available")

        groups = om.parse_mdl_bodygroups(path)

        names = [group["name"] for group in groups]
        self.assertIn("halo", names)
        self.assertIn("shoes", names)
        self.assertEqual(7, names.index("halo"))
        self.assertEqual(10, names.index("shoes"))

    def test_bodygroup_compat_map_matches_names_then_falls_back(self):
        override_groups = [
            {"index": 0, "name": "reference", "count": 1},
            {"index": 5, "name": "glove", "count": 2},
            {"index": 7, "name": "halo", "count": 2},
            {"index": 8, "name": "pants", "count": 2},
            {"index": 10, "name": "shoes", "count": 4},
        ]
        target_groups = [
            {"index": 0, "name": "reference", "count": 1},
            {"index": 1, "name": "hat", "count": 2},
            {"index": 2, "name": "shoes", "count": 2},
            {"index": 3, "name": "cape", "count": 2},
        ]

        mapping = om.bodygroup_compat_map(target_groups, override_groups)

        self.assertEqual(7, mapping[1]["override_index"])
        self.assertEqual(10, mapping[2]["override_index"])
        self.assertIn(mapping[3]["override_index"], {5, 8})

    def test_bodygroup_reorder_plan_places_override_groups_at_target_indexes(self):
        override_groups = [
            {"index": 0, "name": "reference", "count": 1},
            {"index": 5, "name": "glove", "count": 2},
            {"index": 7, "name": "halo", "count": 2},
            {"index": 8, "name": "pants", "count": 2},
            {"index": 10, "name": "shoes", "count": 4},
            {"index": 11, "name": "skirt", "count": 2},
            {"index": 12, "name": "tie", "count": 2},
        ]
        target_groups = [
            {"index": 0, "name": "reference", "count": 1},
            {"index": 3, "name": "glasses", "count": 2},
            {"index": 4, "name": "tie", "count": 2},
            {"index": 6, "name": "skirt", "count": 2},
        ]

        plan = om.bodygroup_reorder_plan(target_groups, override_groups)

        self.assertEqual(5, plan[3])
        self.assertEqual(12, plan[4])
        self.assertEqual(11, plan[6])

    def test_safe_game_path_rejects_unsafe_paths(self):
        self.assertEqual("models/dro/player/characters1/char16/char16", om.safe_game_path("models\\dro\\player\\characters1\\char16\\char16.mdl", allow_empty=False, strip_ext=True))
        for value in ("", "../models/x", "/models/x", "C:/models/x", "cfg/client.vdf"):
            with self.assertRaises(ValueError):
                om.safe_game_path(value, allow_empty=False)

    def test_installed_pack_addons_uses_pack_prefix_only(self):
        addons = os.path.join(self.tempdir, "addons")
        os.makedirs(os.path.join(addons, "ovr_hoshino_himiko"), exist_ok=True)
        os.makedirs(os.path.join(addons, "ovr_hoshino_himiko__mukuro_ikusaba"), exist_ok=True)
        os.makedirs(os.path.join(addons, "ovr_hoshino_himiko_extra"), exist_ok=True)
        os.makedirs(os.path.join(addons, "ovr_other_pack"), exist_ok=True)
        cfg = {"gmod_path": self.tempdir}
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko"}

        found = sorted(os.path.basename(p) for p in om.installed_pack_addons(cfg, pack))

        self.assertEqual(["ovr_hoshino_himiko", "ovr_hoshino_himiko__mukuro_ikusaba"], found)

    def test_enable_retarget_copies_to_target_specific_addon(self):
        pack_dir = os.path.join(self.tempdir, "Hoshino Himiko")
        self.write_file("Hoshino Himiko/models/dro/player/characters3/char12/char12.mdl", b"model")
        self.write_file("Hoshino Himiko/models/dro/player/characters3/char12/char12.dx90.vtx", b"vtx")
        self.write_file("Hoshino Himiko/models/dro/player/characters3/char12/c_arms/char12_arms.mdl", b"arms")
        self.write_file("Hoshino Himiko/materials/dro/sprites/characters/dr_v3/himiko yumeno/ct_sprite_1.vtf", b"sprite")
        self.write_file("Hoshino Himiko/materials/models/hoshino_new/hair.vtf", b"material")
        with open(os.path.join(pack_dir, "addon.json"), "w", encoding="utf-8") as f:
            json.dump({"title": "Hoshino Himiko"}, f)
        cfg = {"gmod_path": self.tempdir}
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko", "folder": pack_dir}
        target = {
            "name": "Mukuro Ikusaba",
            "model_base": "models/dro/player/characters1/char16/char16",
            "arms_base": "models/dro/player/characters1/char16/c_arms/char16_arms",
            "sprite_dir": "materials/dro/sprites/characters/dr_1/mukuro ikusaba",
        }

        om.enable(cfg, pack, target)

        addon = os.path.join(self.tempdir, "addons", "ovr_hoshino_himiko__mukuro_ikusaba")
        self.assertTrue(os.path.exists(os.path.join(addon, "models/dro/player/characters1/char16/char16.mdl")))
        self.assertTrue(os.path.exists(os.path.join(addon, "models/dro/player/characters1/char16/c_arms/char16_arms.mdl")))
        self.assertTrue(os.path.exists(os.path.join(addon, "materials/dro/sprites/characters/dr_1/mukuro ikusaba/ct_sprite_1.vtf")))
        self.assertTrue(os.path.exists(os.path.join(addon, "materials/models/hoshino_new/hair.vtf")))
        self.assertFalse(os.path.exists(os.path.join(self.tempdir, "addons", "ovr_hoshino_himiko")))

    def test_enable_retarget_does_not_write_bodygroup_compat_lua(self):
        source_pack = r"C:\Users\user\Desktop\GMod_Override_Manager\overrides\Hoshino Himiko"
        target_model = r"C:\Users\user\Desktop\Female_Shuichi_Addon_Extracts\2562456244_PlayerModels_ST\models\dro\player\characters3\char15\char15.mdl"
        if not os.path.exists(os.path.join(source_pack, "models/dro/player/characters3/char12/char12.mdl")) or not os.path.exists(target_model):
            self.skipTest("real Hoshino/target models not available")
        cfg = {"gmod_path": self.tempdir}
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko", "folder": source_pack}
        target = om.find_target({}, "Angie Yonaga")

        om.enable(cfg, pack, target)

        lua_path = os.path.join(
            self.tempdir,
            "addons",
            "ovr_hoshino_himiko__angie_yonaga",
            "lua/autorun/ovr_bodygroup_compat_ovr_hoshino_himiko__angie_yonaga.lua",
        )
        self.assertFalse(os.path.exists(lua_path))

    def test_bodygroup_name_patch_can_append_longer_labels(self):
        source_pack = r"C:\Users\user\Desktop\GMod_Override_Manager\overrides\Hoshino Himiko"
        if not os.path.exists(os.path.join(source_pack, "models/dro/player/characters3/char12/char12.mdl")):
            self.skipTest("real Hoshino model not available")
        mdl_path = os.path.join(self.tempdir, "char12.mdl")
        shutil.copy2(os.path.join(source_pack, "models/dro/player/characters3/char12/char12.mdl"), mdl_path)

        changed = om.patch_mdl_bodygroup_names(mdl_path, {7: "glasses", 10: "shoes"})

        self.assertTrue(changed)
        groups = {group["index"]: group for group in om.parse_mdl_bodygroups(mdl_path)}
        self.assertEqual("glasses", groups[7]["name"])
        self.assertEqual("shoes", groups[10]["name"])
        self.assertEqual("pants", groups[8]["name"])

    def test_enable_retarget_renames_override_bodygroups_to_target_slider_names(self):
        source_pack = r"C:\Users\user\Desktop\GMod_Override_Manager\overrides\Hoshino Himiko"
        target_model = r"C:\Users\user\Desktop\Female_Shuichi_Addon_Extracts\2562456244_PlayerModels_ST\models\dro\player\characters1\char9\char9.mdl"
        if not os.path.exists(os.path.join(source_pack, "models/dro/player/characters3/char12/char12.mdl")) or not os.path.exists(target_model):
            self.skipTest("real Hoshino/Junko models not available")
        cfg = {"gmod_path": self.tempdir}
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko", "folder": source_pack}
        target = om.find_target({}, "Junko Enoshima (Default)")

        om.enable(cfg, pack, target)

        mdl_path = os.path.join(
            self.tempdir,
            "addons",
            "ovr_hoshino_himiko__junko_enoshima__default",
            "models/dro/player/characters1/char9/char9.mdl",
        )
        names = [group["name"] for group in om.parse_mdl_bodygroups(mdl_path)]
        self.assertIn("glasses", names)
        self.assertIn("tie", names)
        self.assertIn("skirt", names)

    def test_enable_retarget_hides_unmatched_override_bodygroups(self):
        source_pack = r"C:\Users\user\Desktop\GMod_Override_Manager\overrides\Hoshino Himiko"
        target_model = r"C:\Users\user\Desktop\Female_Shuichi_Addon_Extracts\2562456244_PlayerModels_ST\models\dro\player\characters1\char9\char9.mdl"
        if not os.path.exists(os.path.join(source_pack, "models/dro/player/characters3/char12/char12.mdl")) or not os.path.exists(target_model):
            self.skipTest("real Hoshino/Junko models not available")
        cfg = {"gmod_path": self.tempdir}
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko", "folder": source_pack}
        target = om.find_target({}, "Junko Enoshima (Default)")

        om.enable(cfg, pack, target)

        mdl_path = os.path.join(
            self.tempdir,
            "addons",
            "ovr_hoshino_himiko__junko_enoshima__default",
            "models/dro/player/characters1/char9/char9.mdl",
        )
        visible = [group["name"] for group in om.parse_mdl_bodygroups(mdl_path) if group["count"] > 1]
        self.assertEqual(["glasses", "skirt", "tie"], sorted(visible))

    def test_disable_removes_default_and_retargeted_addons_for_pack(self):
        addons = os.path.join(self.tempdir, "addons")
        os.makedirs(os.path.join(addons, "ovr_hoshino_himiko"), exist_ok=True)
        os.makedirs(os.path.join(addons, "ovr_hoshino_himiko__mukuro_ikusaba"), exist_ok=True)
        os.makedirs(os.path.join(addons, "ovr_other_pack"), exist_ok=True)
        cfg = {"gmod_path": self.tempdir}
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko"}

        om.disable(cfg, pack)

        self.assertFalse(os.path.exists(os.path.join(addons, "ovr_hoshino_himiko")))
        self.assertFalse(os.path.exists(os.path.join(addons, "ovr_hoshino_himiko__mukuro_ikusaba")))
        self.assertTrue(os.path.exists(os.path.join(addons, "ovr_other_pack")))

    def test_create_override_pack_copies_models_materials_sprites_and_metadata(self):
        source_root = os.path.join(self.tempdir, "source")
        os.makedirs(os.path.join(source_root, "models", "player"), exist_ok=True)
        os.makedirs(os.path.join(source_root, "materials", "models", "example"), exist_ok=True)
        model = os.path.join(source_root, "models", "player", "example.mdl")
        arms = os.path.join(source_root, "models", "player", "c_example_arms.mdl")
        for path in (
            model,
            os.path.join(source_root, "models", "player", "example.vvd"),
            os.path.join(source_root, "models", "player", "example.dx90.vtx"),
            arms,
            os.path.join(source_root, "models", "player", "c_example_arms.vvd"),
        ):
            with open(path, "wb") as f:
                f.write(b"model")
        with open(os.path.join(source_root, "materials", "models", "example", "body.vmt"), "wb") as f:
            f.write(b"material")
        sprite = os.path.join(self.tempdir, "sprite.vtf")
        with open(sprite, "wb") as f:
            f.write(b"sprite")

        target = om.find_target({}, "Himiko Yumeno")
        output = om.create_override_pack({
            "name": "Maker Pack",
            "character": "Himiko Yumeno",
            "skin": "Local model",
            "description": "Created by test",
            "source_target": target,
            "main_model": model,
            "arms_model": arms,
            "material_root": source_root,
            "sprite_dir": target["sprite_dir"],
            "sprite_assignments": {"Talk 1": {"path": sprite, "filename": "ct_sprite_1.vtf"}},
            "overrides_dir": os.path.join(self.tempdir, "overrides"),
        })

        self.assertTrue(os.path.exists(os.path.join(output, "models/dro/player/characters3/char12/char12.mdl")))
        self.assertTrue(os.path.exists(os.path.join(output, "models/dro/player/characters3/char12/char12.vvd")))
        self.assertTrue(os.path.exists(os.path.join(output, "models/dro/player/characters3/char12/c_arms/char12_arms.mdl")))
        self.assertTrue(os.path.exists(os.path.join(output, "materials/models/example/body.vmt")))
        self.assertTrue(os.path.exists(os.path.join(output, "materials/dro/sprites/characters/dr_v3/himiko yumeno/ct_sprite_1.vtf")))
        with open(os.path.join(output, "override.json"), "r", encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual("Maker Pack", meta["name"])
        self.assertEqual("Himiko Yumeno", meta["character"])
        self.assertEqual(target, meta["source_target"])

    def test_create_override_pack_rejects_non_game_ready_sprite_files(self):
        source_root = os.path.join(self.tempdir, "source")
        os.makedirs(os.path.join(source_root, "models", "player"), exist_ok=True)
        model = os.path.join(source_root, "models", "player", "example.mdl")
        with open(model, "wb") as f:
            f.write(b"model")
        sprite = os.path.join(self.tempdir, "sprite.png")
        with open(sprite, "wb") as f:
            f.write(b"not vtf")

        with self.assertRaises(ValueError) as cm:
            om.create_override_pack({
                "name": "Bad Sprite Pack",
                "character": "Himiko Yumeno",
                "skin": "",
                "description": "",
                "source_target": om.find_target({}, "Himiko Yumeno"),
                "main_model": model,
                "arms_model": "",
                "material_root": "",
                "sprite_dir": "materials/dro/sprites/characters/dr_v3/himiko yumeno",
                "sprite_assignments": {"Talk 1": {"path": sprite, "filename": "ct_sprite_1.vtf"}},
                "overrides_dir": os.path.join(self.tempdir, "overrides"),
            })
        self.assertIn("game-ready .vtf or .vmt", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.tempdir, "overrides", "Bad Sprite Pack")))


if __name__ == "__main__":
    unittest.main()

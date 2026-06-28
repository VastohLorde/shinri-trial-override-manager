#!/usr/bin/env python3
"""
GMod Override Manager
---------------------
Drop an override pack (a folder containing models/ and/or materials/, plus an
optional override.json describing what it changes) into the "overrides" folder
next to this app, hit Refresh, and toggle it on/off.

Enabling installs the pack as a LEGACY addon (addons/ovr_<name>) whose files sit
ABOVE the server's, so model/skin overrides win even on servers you don't host.
Disabling removes it. Changes take effect on the next map load / reconnect
(GMod doesn't hot-swap an already-loaded model in the current session).
"""
import os
import sys
import json
import shutil
import subprocess
import struct
import threading
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import urllib.request
import zipfile
try:
    import translate_cache
except ImportError:
    translate_cache = None
try:
    import live_translator
except ImportError:
    live_translator = None

if getattr(sys, "frozen", False):
    # running as a PyInstaller .exe -> use the folder the .exe lives in
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
OVERRIDES_DIR = os.path.join(APP_DIR, "overrides")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
DEFAULT_GMOD = r"C:\Program Files (x86)\Steam\steamapps\common\GarrysMod\garrysmod"
DEFAULT_COMMUNITY_INDEX_URL = "https://raw.githubusercontent.com/VastohLorde/gmod-override-manager/main/community_packs.json"
OLD_COMMUNITY_INDEX_URLS = {
    "https://raw.githubusercontent.com/YOURNAME/gmod-override-packs/main/community_packs.json",
}
DEFAULT_TARGET_NAME = "Default"
CUSTOM_TARGET_NAME = "Custom target..."


def normalize_game_path(path):
    return str(path or "").replace("\\", "/").strip().rstrip("/")


def path_without_ext(path):
    path = normalize_game_path(path)
    root, ext = os.path.splitext(path)
    if ext.lower() in (".mdl", ".vvd", ".phy", ".vtx"):
        return root
    return path


def read_c_string(data, offset):
    if offset <= 0 or offset >= len(data):
        return ""
    end = data.find(b"\0", offset)
    if end < 0:
        end = len(data)
    return data[offset:end].decode("utf-8", "replace")


def parse_mdl_bodygroups(path):
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 240:
        return []
    try:
        numbodyparts, bodypartindex = struct.unpack_from("<ii", data, 232)
    except struct.error:
        return []
    groups = []
    for index in range(max(0, numbodyparts)):
        offset = bodypartindex + index * 16
        if offset + 16 > len(data):
            break
        sznameindex, nummodels, base, _modelindex = struct.unpack_from("<iiii", data, offset)
        groups.append({
            "index": index,
            "name": read_c_string(data, offset + sznameindex),
            "count": nummodels,
            "base": base,
        })
    return groups


def bodygroup_key(name):
    cleaned = " ".join("".join(c.lower() if c.isalnum() else " " for c in str(name or "")).split())
    aliases = {
        "hat": "halo",
        "hair pin": "halo",
        "hairpin": "halo",
        "cap": "halo",
        "shoe": "shoes",
        "leg": "pants",
        "legs": "pants",
        "trousers": "pants",
        "dress": "skirt",
        "coat": "cloth",
        "cape": "cloth",
        "shirt": "cloth",
        "jacket": "cloth",
        "hand": "glove",
        "hands": "glove",
        "gloves": "glove",
        "bow": "ribbon",
        "necktie": "tie",
    }
    return aliases.get(cleaned, cleaned)


def configurable_groups(groups):
    return [g for g in groups if int(g.get("count") or 0) > 1 and bodygroup_key(g.get("name")) != "reference"]


def bodygroup_compat_map(target_groups, override_groups):
    override_config = configurable_groups(override_groups)
    by_key = {}
    for group in override_config:
        by_key.setdefault(bodygroup_key(group.get("name")), group)
    fallback = [g for g in override_config if bodygroup_key(g.get("name")) not in ("reference",)]
    used = set()
    mapping = {}
    fallback_pos = 0
    for target in configurable_groups(target_groups):
        key = bodygroup_key(target.get("name"))
        override = by_key.get(key)
        if not override:
            while fallback and fallback[fallback_pos % len(fallback)]["index"] in used:
                fallback_pos += 1
                if fallback_pos > len(fallback) * 2:
                    break
            override = fallback[fallback_pos % len(fallback)] if fallback else None
            fallback_pos += 1
        if not override:
            continue
        used.add(override["index"])
        mapping[target["index"]] = {
            "target_name": target.get("name") or "",
            "target_base": int(target.get("base") or 1),
            "target_count": int(target.get("count") or 1),
            "override_index": override["index"],
            "override_name": override.get("name") or "",
            "override_count": int(override.get("count") or 1),
        }
    return mapping


def bodygroup_reorder_plan(target_groups, override_groups):
    compat = bodygroup_compat_map(target_groups, override_groups)
    plan = {}
    for target_index, item in compat.items():
        plan[int(target_index)] = int(item["override_index"])
    return plan


def patch_mdl_bodygroup_order(path, target_groups, override_groups):
    plan = bodygroup_reorder_plan(target_groups, override_groups)
    if not plan:
        return False
    with open(path, "rb") as f:
        data = bytearray(f.read())
    if len(data) < 240:
        return False
    try:
        numbodyparts, bodypartindex = struct.unpack_from("<ii", data, 232)
    except struct.error:
        return False
    if numbodyparts <= 0 or bodypartindex <= 0:
        return False
    records = []
    for index in range(numbodyparts):
        offset = bodypartindex + index * 16
        if offset + 16 > len(data):
            return False
        sznameindex, nummodels, base, modelindex = struct.unpack_from("<iiii", data, offset)
        records.append({
            "offset": offset,
            "sznameindex": sznameindex,
            "nummodels": nummodels,
            "base": base,
            "modelindex": modelindex,
            "raw": bytes(data[offset:offset + 16]),
        })
    new_records = list(records)
    for target_index, override_index in plan.items():
        if 0 <= target_index < len(new_records) and 0 <= override_index < len(records):
            source = records[override_index]
            target = records[target_index]
            target_group = next((g for g in target_groups if int(g.get("index", -1)) == target_index), None)
            new_records[target_index] = {
                "offset": target["offset"],
                "sznameindex": source["offset"] + source["sznameindex"] - target["offset"],
                "nummodels": source["nummodels"],
                "base": int((target_group or {}).get("base") or target["base"] or source["base"]),
                "modelindex": source["offset"] + source["modelindex"] - target["offset"],
                "raw": source["raw"],
            }
    for index, record in enumerate(new_records):
        offset = bodypartindex + index * 16
        struct.pack_into("<iiii", data, offset, record["sznameindex"], record["nummodels"], record["base"], record["modelindex"])
    with open(path, "wb") as f:
        f.write(data)
    return True


def patch_mdl_bodygroup_names(path, index_to_name):
    with open(path, "rb") as f:
        data = bytearray(f.read())
    if len(data) < 240:
        return False
    try:
        numbodyparts, bodypartindex = struct.unpack_from("<ii", data, 232)
    except struct.error:
        return False
    changed = False
    for index, new_name in index_to_name.items():
        if not (0 <= int(index) < numbodyparts):
            continue
        offset = bodypartindex + int(index) * 16
        if offset + 16 > len(data):
            continue
        sznameindex = struct.unpack_from("<i", data, offset)[0]
        name_offset = offset + sznameindex
        old_name = read_c_string(data, name_offset)
        if not old_name:
            continue
        raw = str(new_name or "").encode("utf-8")
        old_raw = old_name.encode("utf-8")
        if len(raw) <= len(old_raw):
            data[name_offset:name_offset + len(old_raw)] = raw + (b"\0" * (len(old_raw) - len(raw)))
        else:
            append_offset = len(data)
            data.extend(raw + b"\0")
            struct.pack_into("<i", data, offset, append_offset - offset)
        changed = True
    if changed:
        struct.pack_into("<i", data, 76, len(data))
        with open(path, "wb") as f:
            f.write(data)
    return changed


def patch_mdl_bodygroup_counts(path, index_to_count):
    with open(path, "rb") as f:
        data = bytearray(f.read())
    if len(data) < 240:
        return False
    try:
        numbodyparts, bodypartindex = struct.unpack_from("<ii", data, 232)
    except struct.error:
        return False
    changed = False
    for index, count in index_to_count.items():
        if not (0 <= int(index) < numbodyparts):
            continue
        offset = bodypartindex + int(index) * 16
        if offset + 16 > len(data):
            continue
        struct.pack_into("<i", data, offset + 4, max(1, int(count)))
        changed = True
    if changed:
        with open(path, "wb") as f:
            f.write(data)
    return changed


def safe_game_path(path, allow_empty=True, strip_ext=False):
    raw = str(path or "").replace("\\", "/").strip()
    if raw.startswith("/") or os.path.isabs(raw) or (len(raw) > 1 and raw[1] == ":"):
        raise ValueError(f"Unsafe path: {path}")
    cleaned = normalize_game_path(raw)
    if not cleaned:
        if allow_empty:
            return ""
        raise ValueError("Path cannot be empty.")
    if ".." in cleaned.split("/"):
        raise ValueError(f"Unsafe path: {path}")
    allowed = ("models/", "materials/", "lua/")
    if not cleaned.startswith(allowed):
        raise ValueError("Path must start with models/, materials/, or lua/.")
    return path_without_ext(cleaned) if strip_ext else cleaned


def sprite_name_from_target_name(name):
    base = str(name or "").split("(")[0].strip()
    if base.endswith(" 2"):
        base = base[:-2].strip()
    aliases = {
        "K1-B0": "k1b0",
        "Keebo": "k1b0",
        "Nekomaru": "nekomaru nidai",
    }
    if base in aliases:
        return aliases[base]
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in base).split())


def default_sprite_dir(name, model_base):
    model = normalize_game_path(model_base).lower()
    game = ""
    if "/characters1/" in model:
        game = "dr_1"
    elif "/characters2/" in model:
        game = "dr_2"
    elif "/characters3/" in model:
        game = "dr_v3"
    if not game:
        return ""
    sprite_name = sprite_name_from_target_name(name)
    if not sprite_name:
        return ""
    return f"materials/dro/sprites/characters/{game}/{sprite_name}"


def make_target(name, model_base, arms_base="", sprite_dir=""):
    model = path_without_ext(normalize_game_path(model_base))
    return {
        "name": name,
        "model_base": model,
        "arms_base": path_without_ext(normalize_game_path(arms_base)) if arms_base else "",
        "sprite_dir": normalize_game_path(sprite_dir) if sprite_dir else default_sprite_dir(name, model),
    }


CHARACTER_TARGETS = [
    make_target("Akane Owari", "models/dro/player/characters2/char11/char11.mdl", "models/dro/player/characters2/char11/c_arms/char11_arms.mdl"),
    make_target("Angie Yonaga", "models/dro/player/characters3/char15/char15.mdl", "models/dro/player/characters3/char15/c_arms/arms.mdl"),
    make_target("Aoi Asahina (DR)", "models/dro/player/characters1/char11/char11.mdl", "models/dro/player/characters1/char11/c_arms/char11_arms.mdl"),
    make_target("Byakuya Togami", "models/dro/player/characters1/char2/char2.mdl", "models/dro/player/characters1/char2/c_arms/char2_arms.mdl"),
    make_target("Byakuya Togami (DR2)", "models/dro/player/characters2/char13/char13.mdl", "models/dro/player/characters2/char13/c_arms/char13_arms.mdl"),
    make_target("Celestia Ludenberg", "models/dro/player/characters1/char8/char8.mdl", "models/dro/player/characters1/char8/c_arms/char8_arms.mdl"),
    make_target("Chiaki Nanami", "models/dro/player/characters2/char7/char7.mdl", "models/dro/player/characters2/char7/c_arms/char7_arms.mdl"),
    make_target("Chihiro", "models/dro/player/characters1/char5/char5.mdl", "models/dro/player/characters1/char5/c_arms/char5_arms.mdl"),
    make_target("Fuyuhiko Kuzuryu", "models/dro/player/characters2/char4/char4.mdl", "models/dro/player/characters2/char4/c_arms/char4_arms.mdl"),
    make_target("Gonta Gokuhara", "models/dro/player/characters3/char7/char7.mdl", "models/dro/player/characters3/char7/c_arms/char7_arms.mdl"),
    make_target("Gundam Tanaka", "models/dro/player/characters2/char3/char3.mdl", "models/dro/player/characters2/char3/c_arms/char3_arms.mdl"),
    make_target("Hajime Hinata", "models/dro/player/characters2/char1/char1.mdl", "models/dro/player/characters2/char1/c_arms/char1_arms.mdl"),
    make_target("Hifumi Yamada", "models/dro/player/characters1/char13/char13.mdl", "models/dro/player/characters1/char13/c_arms/char13_arms.mdl"),
    make_target("Himiko Yumeno", "models/dro/player/characters3/char12/char12.mdl", "models/dro/player/characters3/char12/c_arms/char12_arms.mdl"),
    make_target("Ibuki Mioda", "models/dro/player/characters2/char5/char5.mdl", "models/dro/player/characters2/char5/c_arms/char5_arms.mdl"),
    make_target("Junko Enoshima (Default)", "models/dro/player/characters1/char9/char9.mdl", "models/dro/player/characters1/char9/c_arms/char9_arms.mdl"),
    make_target("K1-B0", "models/dro/player/characters3/char3/char3.mdl", "models/dro/player/characters3/char3/c_arms/char3_arms.mdl"),
    make_target("Kaede Akamatsu", "models/dro/player/characters3/char8/char8.mdl", "models/dro/player/characters3/char8/c_arms/char8_arms.mdl"),
    make_target("Kaito Momota", "models/dro/player/characters3/char4/char4.mdl", "models/dro/player/characters3/char4/c_arms/char4_arms.mdl"),
    make_target("Kazuichi Soda 2", "models/dro/player/characters2/char16/char16.mdl", "models/dro/player/characters2/char16/c_arms/char16_arms.mdl"),
    make_target("Kirumi Tojo", "models/dro/player/characters3/char13/char13.mdl", "models/dro/player/characters3/char13/c_arms/char13_arms.mdl"),
    make_target("Kiyotaka Ishimaru", "models/dro/player/characters1/char3/char3.mdl", "models/dro/player/characters1/char3/c_arms/char3_arms.mdl"),
    make_target("Kokichi Oma Beta Uniform", "models/dro/player/characters3/char2/char2_beta.mdl", "models/dro/player/characters3/char2/c_arms/char2_beta_arms.mdl"),
    make_target("Kokichi Oma School Uniform", "models/dro/player/characters3/char2/char2_uniform.mdl", "models/dro/player/characters3/char2/c_arms/char2_school_arms.mdl"),
    make_target("Kokichi Oma Ultimate Uniform", "models/dro/player/characters3/char2/char2.mdl", "models/dro/player/characters3/char2/c_arms/char2_arms.mdl"),
    make_target("Korekiyo Shinguji", "models/dro/player/characters3/char6/char6.mdl", "models/dro/player/characters3/char6/c_arms/char6_arms.mdl"),
    make_target("Kyoko Kirigiri", "models/dro/player/characters1/char6/char6.mdl", "models/dro/player/characters1/char6/c_arms/char6_arms.mdl"),
    make_target("Leon Kuwata", "models/dro/player/characters1/char14/char14.mdl", "models/dro/player/characters1/char14/c_arms/char14_arms.mdl"),
    make_target("Mahiru Koizumi", "models/dro/player/characters2/char10/char10.mdl", "models/dro/player/characters2/char10/c_arms/char10_arms.mdl"),
    make_target("Maki Harukawa", "models/dro/player/characters3/char9/char9.mdl", "models/dro/player/characters3/char9/c_arms/char9_arms.mdl"),
    make_target("Makoto Naegi", "models/dro/player/characters1/char1/char1.mdl", "models/dro/player/characters1/char1/c_arms/char1_arms.mdl"),
    make_target("Mikan Tsumiki", "models/dro/player/characters2/char8/char8.mdl", "models/dro/player/characters2/char8/c_arms/char8_arms.mdl"),
    make_target("Miu Iruma", "models/dro/player/characters3/char11/char11.mdl", "models/dro/player/characters3/char11/c_arms/char11_arms.mdl"),
    make_target("Mondo Owada", "models/dro/player/characters1/char4/char4.mdl", "models/dro/player/characters1/char4/c_arms/char4_arms.mdl"),
    make_target("Mukuro Ikusaba", "models/dro/player/characters1/char16/char16.mdl", "models/dro/player/characters1/char16/c_arms/char16_arms.mdl"),
    make_target("Mukuro Ikusaba 2", "models/dro/player/characters1/char16/char16_uniformhp.mdl", "models/dro/player/characters1/char16/c_arms/char16_arms.mdl"),
    make_target("Nagito Komaeda", "models/dro/player/characters2/char2/char2.mdl", "models/dro/player/characters2/char2/c_arms/char2_arms.mdl"),
    make_target("Nekomaru", "models/dro/player/characters2/char14/char14.mdl", "models/dro/player/characters2/char14/c_arms/char14_arms.mdl"),
    make_target("Peko Pekoyama", "models/dro/player/characters2/char9/char9.mdl", "models/dro/player/characters2/char9/c_arms/char9_arms.mdl"),
    make_target("Rantaro Amami", "models/dro/player/characters3/char5/char5.mdl", "models/dro/player/characters3/char5/c_arms/char5_arms.mdl"),
    make_target("Ryoma Hoshi", "models/dro/player/characters3/char16/char16.mdl", "models/dro/player/characters3/char16/c_arms/char16_arms.mdl"),
    make_target("Sakura Ogami", "models/dro/player/characters1/char12/char12.mdl", "models/dro/player/characters1/char12/c_arms/char12_arms.mdl"),
    make_target("Sayaka Maizono", "models/dro/player/characters1/char7/char7.mdl", "models/dro/player/characters1/char7/c_arms/char7_arms.mdl"),
    make_target("Shuichi Saihara", "models/dro/player/characters3/char1/char1.mdl", "models/dro/player/characters3/char1/c_arms/char1_arms.mdl"),
    make_target("Sonia Nevermind", "models/dro/player/characters2/char6/char6.mdl", "models/dro/player/characters2/char6/c_arms/char6_arms.mdl"),
    make_target("Tenko Chabashira", "models/dro/player/characters3/char10/char10.mdl", "models/dro/player/characters3/char10/c_arms/char10_arms.mdl"),
    make_target("Teruteru Hanamura", "models/dro/player/characters2/char15/char15.mdl", "models/dro/player/characters2/char15/c_arms/char15_arms.mdl"),
    make_target("Toko Fukawa", "models/dro/player/characters1/char10/char10.mdl", "models/dro/player/characters1/char10/c_arms/arms.mdl"),
    make_target("Toko Fukawa (Genocide)", "models/dro/player/characters1/char10/char10_genocide.mdl", "models/dro/player/characters1/char10/c_arms/arms.mdl"),
    make_target("Tsumugi Shirogane", "models/dro/player/characters3/char14/char14.mdl", "models/dro/player/characters3/char14/c_arms/char14_arms.mdl"),
    make_target("Yasuhiro Hagakure (Danganronpa)", "models/dro/player/characters1/char15/char15.mdl", "models/dro/player/characters1/char15/c_arms/char15_arms.mdl"),
]


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
            if cfg.get("community_index_url") in OLD_COMMUNITY_INDEX_URLS:
                cfg["community_index_url"] = DEFAULT_COMMUNITY_INDEX_URL
                save_config(cfg)
            return cfg
        except Exception:
            pass
    return {"gmod_path": DEFAULT_GMOD, "community_index_url": DEFAULT_COMMUNITY_INDEX_URL}


def save_config(cfg):
    try:
        json.dump(cfg, open(CONFIG_PATH, "w", encoding="utf-8"), indent=2)
    except Exception:
        pass


def addons_dir(cfg):
    return os.path.join(cfg.get("gmod_path", DEFAULT_GMOD), "addons")


def slugify(name):
    return "ovr_" + "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")


def target_key(target):
    if not target:
        return DEFAULT_TARGET_NAME
    return target.get("name") or DEFAULT_TARGET_NAME


def target_slug(name):
    if not name or name == DEFAULT_TARGET_NAME:
        return "default"
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_") or "target"


def addon_slug(pack, target=None):
    base = pack.get("slug") or slugify(pack.get("name") or "override")
    if not target or target_key(target) == DEFAULT_TARGET_NAME:
        return base
    return f"{base}__{target_slug(target_key(target))}"


def pack_addon_prefix(pack):
    return pack.get("slug") or slugify(pack.get("name") or "override")


def installed_pack_addons(cfg, pack):
    ad = addons_dir(cfg)
    if not os.path.isdir(ad):
        return []
    base = pack_addon_prefix(pack)
    out = []
    for name in os.listdir(ad):
        full = os.path.join(ad, name)
        if not os.path.isdir(full):
            continue
        if name == base or name.startswith(base + "__"):
            out.append(full)
    return out


def disable_all_pack_targets(cfg, pack):
    for folder in installed_pack_addons(cfg, pack):
        shutil.rmtree(folder, ignore_errors=True)


def custom_targets(cfg):
    data = cfg.get("custom_targets")
    if not isinstance(data, dict):
        return []
    out = []
    for name, item in sorted(data.items()):
        if not isinstance(item, dict):
            continue
        try:
            out.append({
                "name": name,
                "model_base": safe_game_path(item.get("model_base", ""), allow_empty=False, strip_ext=True),
                "arms_base": safe_game_path(item.get("arms_base", ""), allow_empty=True, strip_ext=True),
                "sprite_dir": safe_game_path(item.get("sprite_dir", ""), allow_empty=True),
            })
        except ValueError:
            continue
    return out


def available_targets(cfg):
    return [{"name": DEFAULT_TARGET_NAME, "model_base": "", "arms_base": "", "sprite_dir": ""}] + CHARACTER_TARGETS + custom_targets(cfg)


def find_target(cfg, name):
    if not name or name == DEFAULT_TARGET_NAME:
        return None
    for target in available_targets(cfg):
        if target["name"] == name and target["name"] != DEFAULT_TARGET_NAME:
            return target
    return None


def saved_target_name(cfg, pack):
    targets = cfg.get("pack_targets")
    if not isinstance(targets, dict):
        return DEFAULT_TARGET_NAME
    return targets.get(pack_addon_prefix(pack), DEFAULT_TARGET_NAME)


def save_pack_target(cfg, pack, target_name):
    cfg.setdefault("pack_targets", {})[pack_addon_prefix(pack)] = target_name or DEFAULT_TARGET_NAME
    save_config(cfg)


def enabled_target_name(cfg, pack):
    ad = addons_dir(cfg)
    if not os.path.isdir(ad):
        return ""
    installed = {os.path.basename(path) for path in installed_pack_addons(cfg, pack)}
    if pack_addon_prefix(pack) in installed:
        return DEFAULT_TARGET_NAME
    for target in available_targets(cfg):
        if target["name"] == DEFAULT_TARGET_NAME:
            continue
        if addon_slug(pack, target) in installed:
            return target["name"]
    base = pack_addon_prefix(pack) + "__"
    for name in sorted(installed):
        if name.startswith(base):
            return name[len(base):].replace("_", " ").title()
    return ""


def target_change_needs_apply(cfg, pack, target_name):
    active = enabled_target_name(cfg, pack)
    if not active:
        return False
    return active != (target_name or DEFAULT_TARGET_NAME)


def mdl_path_from_base(root, model_base):
    if not model_base:
        return ""
    return os.path.join(root, *(normalize_game_path(model_base) + ".mdl").split("/"))


def find_known_target_mdl(target):
    model_rel = normalize_game_path(target.get("model_base", "")) + ".mdl"
    candidates = [
        os.path.join(APP_DIR, *model_rel.split("/")),
        os.path.join(r"C:\Users\user\Desktop\Female_Shuichi_Addon_Extracts\2562456244_PlayerModels_ST", *model_rel.split("/")),
        os.path.join(r"C:\Users\user\Desktop\GMod_Override_Manager\overrides", *model_rel.split("/")),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def lua_quote(value):
    return json.dumps(str(value or ""))


def generate_bodygroup_compat_lua(model_path, mapping):
    lines = [
        "if SERVER then return end",
        "local MODEL = " + lua_quote(normalize_game_path(model_path).lower()),
        "local MAP = {",
    ]
    for target_index in sorted(mapping):
        item = mapping[target_index]
        lines.append(
            f"  [{int(target_index)}] = {{ targetBase = {int(item.get('target_base') or 1)}, targetCount = {int(item.get('target_count') or 1)}, override = {int(item['override_index'])}, count = {int(item['override_count'])}, name = {lua_quote(item.get('override_name', ''))} }},"
        )
    lines += [
        "}",
        "local function rawBody(ply)",
        "  local body = ply:GetInternalVariable('m_nBody')",
        "  if body == nil and ply.GetSaveTable then",
        "    local st = ply:GetSaveTable()",
        "    body = st and st.m_nBody",
        "  end",
        "  return tonumber(body) or 0",
        "end",
        "local function apply()",
        "  local ply = LocalPlayer()",
        "  if not IsValid(ply) then return end",
        "  if string.lower(ply:GetModel() or '') ~= MODEL then return end",
        "  if ply.__ovrBodygroupCompatBusy then return end",
        "  ply.__ovrBodygroupCompatBusy = true",
        "  local body = rawBody(ply)",
        "  for _, item in pairs(MAP) do",
        "    local value = 0",
        "    if item.targetBase and item.targetBase > 0 and item.targetCount and item.targetCount > 1 then",
        "      value = math.floor(body / item.targetBase) % item.targetCount",
        "    end",
        "    if item.count and item.count > 0 then value = math.Clamp(value, 0, item.count - 1) end",
        "    if ply:GetBodygroup(item.override) ~= value then ply:SetBodygroup(item.override, value) end",
        "  end",
        "  ply.__ovrBodygroupCompatBusy = false",
        "end",
        "hook.Add('Think', 'ovr_bodygroup_compat_' .. MODEL, apply)",
        "hook.Add('PostPlayerDraw', 'ovr_bodygroup_compat_draw_' .. MODEL, function(ply) if ply == LocalPlayer() then apply() end end)",
        "",
    ]
    return "\n".join(lines)


def write_bodygroup_compat_lua(dest_folder, pack, target, source):
    source_mdl = mdl_path_from_base(pack["folder"], source.get("model_base", ""))
    target_mdl = find_known_target_mdl(target)
    if not os.path.exists(source_mdl) or not os.path.exists(target_mdl):
        return False
    override_groups = parse_mdl_bodygroups(source_mdl)
    target_groups = parse_mdl_bodygroups(target_mdl)
    mapping = bodygroup_compat_map(target_groups, override_groups)
    if not mapping:
        return False
    lua_dir = os.path.join(dest_folder, "lua", "autorun")
    os.makedirs(lua_dir, exist_ok=True)
    lua_name = f"ovr_bodygroup_compat_{addon_slug(pack, target)}.lua"
    with open(os.path.join(lua_dir, lua_name), "w", encoding="utf-8") as f:
        f.write(generate_bodygroup_compat_lua(target.get("model_base", "") + ".mdl", mapping))
    return True


def patch_retargeted_model_bodygroups(dest_folder, pack, target, source):
    source_mdl = mdl_path_from_base(pack["folder"], source.get("model_base", ""))
    target_reference_mdl = find_known_target_mdl(target)
    copied_mdl = mdl_path_from_base(dest_folder, target.get("model_base", ""))
    if not (os.path.exists(source_mdl) and os.path.exists(target_reference_mdl) and os.path.exists(copied_mdl)):
        return False
    override_groups = parse_mdl_bodygroups(source_mdl)
    target_groups = parse_mdl_bodygroups(target_reference_mdl)
    return patch_mdl_bodygroup_order(copied_mdl, target_groups, override_groups)


def patch_retargeted_model_bodygroup_names(dest_folder, pack, target, source):
    copied_mdl = mdl_path_from_base(dest_folder, target.get("model_base", ""))
    target_reference_mdl = find_known_target_mdl(target)
    source_mdl = mdl_path_from_base(pack["folder"], source.get("model_base", ""))
    if not (os.path.exists(copied_mdl) and os.path.exists(target_reference_mdl) and os.path.exists(source_mdl)):
        return False
    override_groups = parse_mdl_bodygroups(source_mdl)
    target_groups = parse_mdl_bodygroups(target_reference_mdl)
    compat = bodygroup_compat_map(target_groups, override_groups)
    renames = {}
    used_override = set()
    for _target_index, item in compat.items():
        target_name = item.get("target_name") or ""
        override_index = item.get("override_index")
        if target_name and override_index is not None:
            renames[int(override_index)] = target_name
            used_override.add(int(override_index))
    hide_counts = {
        int(group["index"]): 1
        for group in configurable_groups(override_groups)
        if int(group["index"]) not in used_override
    }
    changed_names = patch_mdl_bodygroup_names(copied_mdl, renames)
    changed_counts = patch_mdl_bodygroup_counts(copied_mdl, hide_counts)
    return changed_names or changed_counts


def read_source_target_from_json(folder):
    path = os.path.join(folder, "override.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    source = data.get("source_target")
    if not isinstance(source, dict):
        return None
    return {
        "model_base": safe_game_path(source.get("model_base", ""), allow_empty=True, strip_ext=True),
        "arms_base": safe_game_path(source.get("arms_base", ""), allow_empty=True, strip_ext=True),
        "sprite_dir": safe_game_path(source.get("sprite_dir", ""), allow_empty=True),
    }


def rel_game_path(folder, path):
    return normalize_game_path(os.path.relpath(path, folder))


def infer_source_target(folder):
    explicit = read_source_target_from_json(folder)
    if explicit:
        return explicit

    model_base = ""
    arms_base = ""
    sprite_dir = ""
    models_root = os.path.join(folder, "models")
    if os.path.isdir(models_root):
        mdl_paths = []
        for root, _dirs, files in os.walk(models_root):
            for filename in files:
                if filename.lower().endswith(".mdl"):
                    mdl_paths.append(rel_game_path(folder, os.path.join(root, filename)))
        mdl_paths.sort(key=lambda p: ("c_arms/" in p.lower(), p.lower()))
        for rel in mdl_paths:
            low = rel.lower()
            if "/c_arms/" in low and not arms_base:
                arms_base = path_without_ext(rel)
            elif not model_base:
                model_base = path_without_ext(rel)
        if not arms_base:
            for rel in mdl_paths:
                if "/c_arms/" in rel.lower():
                    arms_base = path_without_ext(rel)
                    break

    sprites_root = os.path.join(folder, "materials", "dro", "sprites", "characters")
    if os.path.isdir(sprites_root):
        dirs = set()
        for root, _dirs, files in os.walk(sprites_root):
            if any(name.lower().endswith((".vtf", ".vmt")) for name in files):
                dirs.add(rel_game_path(folder, root))
        if dirs:
            sprite_dir = sorted(dirs, key=lambda p: (p.count("/"), p.lower()))[0]

    return {"model_base": model_base, "arms_base": arms_base, "sprite_dir": sprite_dir}


def replace_base(rel_path, source_base, target_base):
    rel = normalize_game_path(rel_path)
    source = normalize_game_path(source_base)
    target = normalize_game_path(target_base)
    if not source or not target:
        return None
    if rel == source:
        return target
    if rel.startswith(source + "."):
        return target + rel[len(source):]
    if rel.startswith(source + "/"):
        return target + rel[len(source):]
    return None


def map_retarget_path(rel_path, source, target):
    rel = normalize_game_path(rel_path)
    for source_key, target_key_name in (("arms_base", "arms_base"), ("model_base", "model_base")):
        mapped = replace_base(rel, source.get(source_key, ""), target.get(target_key_name, ""))
        if mapped:
            return mapped
    source_sprite = normalize_game_path(source.get("sprite_dir", ""))
    target_sprite = normalize_game_path(target.get("sprite_dir", ""))
    if source_sprite and target_sprite:
        if rel == source_sprite:
            return target_sprite
        if rel.startswith(source_sprite + "/"):
            return target_sprite + rel[len(source_sprite):]
    return rel


def copy_pack_tree(src_folder, dest_folder, source=None, target=None):
    for root, dirs, files in os.walk(src_folder):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for filename in files:
            src_path = os.path.join(root, filename)
            rel = rel_game_path(src_folder, src_path)
            if rel == "override.json":
                continue
            dest_rel = map_retarget_path(rel, source, target) if source and target else rel
            dest_path = os.path.join(dest_folder, *dest_rel.split("/"))
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy2(src_path, dest_path)


def pack_folder_name(name):
    cleaned = "".join(c if c.isalnum() or c in " ._-" else "_" for c in name).strip(" ._")
    return cleaned or "Community Pack"


MODEL_SIDECAR_EXTS = (".mdl", ".vvd", ".phy", ".dx90.vtx", ".sw.vtx", ".ani")
SPRITE_GROUPS = [
    {"name": "Talk", "initial": 3, "prefix": "ct_sprite", "first": None},
    {"name": "Argue", "initial": 2, "prefix": "ct_argue", "first": None},
    {"name": "Consent", "initial": 1, "prefix": "ct_consent", "first": "ct_consent.vtf"},
    {"name": "Scrum Debate Left", "initial": 1, "prefix": "ct_scrum_left", "first": "ct_scrum_left.vtf"},
    {"name": "Scrum Debate Right", "initial": 1, "prefix": "ct_scrum_right", "first": "ct_scrum_right.vtf"},
]


def sprite_group_config(group_name):
    for group in SPRITE_GROUPS:
        if group["name"] == group_name:
            return group
    raise ValueError(f"Unknown sprite group: {group_name}")


def make_sprite_group_slot(group_name, index):
    group = sprite_group_config(group_name)
    index = max(1, int(index))
    label = f"{group_name} {index}"
    if index == 1 and group.get("first"):
        return (group_name, group["first"])
    return (label, f"{group['prefix']}_{index}.vtf")


def make_sprite_group_slots(group_name, count):
    return [make_sprite_group_slot(group_name, i) for i in range(1, max(0, int(count)) + 1)]


def make_talk_sprite_slots(count):
    return make_sprite_group_slots("Talk", count)


SPRITE_SLOTS = [
    make_sprite_group_slot(group["name"], i)
    for group in SPRITE_GROUPS
    for i in range(1, int(group["initial"]) + 1)
]


def copy_model_sidecars(src_mdl, dest_base, output_dir):
    src_mdl = os.path.abspath(src_mdl or "")
    if not os.path.isfile(src_mdl):
        raise ValueError("Selected model file does not exist.")
    if os.path.splitext(src_mdl)[1].lower() != ".mdl":
        raise ValueError("Main model must be a .mdl file.")
    dest_base = safe_game_path(dest_base, allow_empty=False, strip_ext=True)
    src_base, _ = os.path.splitext(src_mdl)
    copied = []
    for ext in MODEL_SIDECAR_EXTS:
        src = src_base + ext
        if not os.path.exists(src):
            continue
        dest = os.path.join(output_dir, *dest_base.split("/")) + ext
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(dest)
    if not copied:
        raise ValueError("No model files were copied.")
    return copied


def copy_material_root(material_root, output_dir):
    if not material_root:
        return False
    material_dir = os.path.join(material_root, "materials")
    if not os.path.isdir(material_dir):
        return False
    dest = os.path.join(output_dir, "materials")
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(material_dir, dest)
    return True


def validate_sprite_assignment(path):
    if not os.path.isfile(path):
        raise ValueError(f"Selected sprite file does not exist: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".vtf", ".vmt"):
        raise ValueError("Sprite files must be game-ready .vtf or .vmt files.")


def copy_sprite_assignments(assignments, sprite_dir, output_dir):
    copied = []
    if not assignments:
        return copied
    sprite_dir = safe_game_path(sprite_dir, allow_empty=False)
    for _label, item in assignments.items():
        src = item.get("path") if isinstance(item, dict) else ""
        filename = item.get("filename") if isinstance(item, dict) else ""
        if not src:
            continue
        validate_sprite_assignment(src)
        if not filename or "/" in filename or "\\" in filename:
            raise ValueError("Sprite destination filename is invalid.")
        dest = os.path.join(output_dir, *sprite_dir.split("/"), filename)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(dest)
    return copied


def create_override_pack(options):
    name = str(options.get("name") or "").strip()
    if not name:
        raise ValueError("Pack name is required.")
    character = str(options.get("character") or "").strip() or "(unspecified)"
    source_target = options.get("source_target") or {}
    model_base = safe_game_path(source_target.get("model_base", ""), allow_empty=False, strip_ext=True)
    arms_base = safe_game_path(source_target.get("arms_base", ""), allow_empty=True, strip_ext=True)
    sprite_dir = safe_game_path(options.get("sprite_dir") or source_target.get("sprite_dir", ""), allow_empty=True)
    overrides_dir = options.get("overrides_dir") or OVERRIDES_DIR
    output_dir = os.path.join(overrides_dir, pack_folder_name(name))
    if os.path.exists(output_dir):
        raise FileExistsError(output_dir)
    os.makedirs(overrides_dir, exist_ok=True)
    try:
        os.makedirs(output_dir, exist_ok=False)
        copy_model_sidecars(options.get("main_model"), model_base, output_dir)
        if options.get("arms_model") and arms_base:
            copy_model_sidecars(options.get("arms_model"), arms_base, output_dir)
        copy_material_root(options.get("material_root") or "", output_dir)
        copy_sprite_assignments(options.get("sprite_assignments") or {}, sprite_dir, output_dir)
        meta = {
            "name": name,
            "character": character,
            "skin": str(options.get("skin") or "").strip(),
            "description": str(options.get("description") or "").strip(),
            "source_target": {
                "name": source_target.get("name") or character,
                "model_base": model_base,
                "arms_base": arms_base,
                "sprite_dir": sprite_dir,
            },
        }
        with open(os.path.join(output_dir, "override.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        return output_dir
    except Exception:
        if os.path.isdir(output_dir):
            shutil.rmtree(output_dir, ignore_errors=True)
        raise


def scan_overrides():
    packs = []
    os.makedirs(OVERRIDES_DIR, exist_ok=True)
    for name in sorted(os.listdir(OVERRIDES_DIR)):
        folder = os.path.join(OVERRIDES_DIR, name)
        if not os.path.isdir(folder):
            continue
        has_content = os.path.isdir(os.path.join(folder, "models")) or os.path.isdir(os.path.join(folder, "materials"))
        if not has_content:
            continue
        meta = {"name": name, "character": "(unspecified)", "skin": "", "description": "", "folder": folder}
        mj = os.path.join(folder, "override.json")
        if os.path.exists(mj):
            try:
                d = json.load(open(mj, encoding="utf-8"))
                for k in ("name", "character", "skin", "description"):
                    if d.get(k):
                        meta[k] = d[k]
            except Exception:
                pass
        meta["slug"] = slugify(meta["name"])
        packs.append(meta)
    return packs


def is_enabled(cfg, pack, target=None):
    if target is None:
        return bool(installed_pack_addons(cfg, pack))
    return os.path.isdir(os.path.join(addons_dir(cfg), addon_slug(pack, target)))


def enable(cfg, pack, target=None):
    disable_all_pack_targets(cfg, pack)
    dest = os.path.join(addons_dir(cfg), addon_slug(pack, target))
    try:
        os.makedirs(dest, exist_ok=True)
        if target and target_key(target) != DEFAULT_TARGET_NAME:
            source = infer_source_target(pack["folder"])
            if not source.get("model_base"):
                raise ValueError("Could not infer this pack's source model path for retargeting.")
            copy_pack_tree(pack["folder"], dest, source, target)
            patch_retargeted_model_bodygroup_names(dest, pack, target, source)
        else:
            copy_pack_tree(pack["folder"], dest)
        aj = os.path.join(dest, "addon.json")
        if not os.path.exists(aj):
            with open(aj, "w", encoding="utf-8") as f:
                json.dump({"title": pack["name"], "type": "model", "tags": ["fun"], "ignore": []}, f)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise


def disable(cfg, pack):
    disable_all_pack_targets(cfg, pack)


def read_json_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "GModOverrideManager/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read(2_000_000)
    return json.loads(data.decode("utf-8"))


def normalize_community_index(data):
    packs = data.get("packs") if isinstance(data, dict) else data
    if not isinstance(packs, list):
        raise ValueError("Community index must be a JSON array or an object with a 'packs' array.")
    out = []
    for item in packs:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("download_url") or item.get("url") or "").strip()
        if not name or not url:
            continue
        out.append({
            "name": name,
            "character": str(item.get("character") or "(unspecified)"),
            "skin": str(item.get("skin") or item.get("version") or ""),
            "version": str(item.get("version") or ""),
            "author": str(item.get("author") or ""),
            "description": str(item.get("description") or ""),
            "download_url": url,
        })
    return out


def safe_extract_zip(zip_path, dest_dir):
    dest_abs = os.path.abspath(dest_dir)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if not names:
            raise ValueError("Downloaded ZIP is empty.")
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise ValueError(f"Unsafe ZIP path: {info.filename}")
            target = os.path.abspath(os.path.join(dest_abs, *name.split("/")))
            if os.path.commonpath([dest_abs, target]) != dest_abs:
                raise ValueError(f"Unsafe ZIP path: {info.filename}")
        zf.extractall(dest_abs)


def find_pack_root(folder):
    if os.path.isdir(os.path.join(folder, "models")) or os.path.isdir(os.path.join(folder, "materials")):
        return folder
    children = [
        os.path.join(folder, name)
        for name in os.listdir(folder)
        if os.path.isdir(os.path.join(folder, name))
    ]
    if len(children) == 1:
        child = children[0]
        if os.path.isdir(os.path.join(child, "models")) or os.path.isdir(os.path.join(child, "materials")):
            return child
    return folder


def install_community_pack(pack):
    os.makedirs(OVERRIDES_DIR, exist_ok=True)
    folder_name = pack_folder_name(pack["name"])
    final_dir = os.path.join(OVERRIDES_DIR, folder_name)
    req = urllib.request.Request(pack["download_url"], headers={"User-Agent": "GModOverrideManager/1.0"})
    with tempfile.TemporaryDirectory() as td:
        zip_path = os.path.join(td, "pack.zip")
        with urllib.request.urlopen(req, timeout=60) as resp, open(zip_path, "wb") as out:
            shutil.copyfileobj(resp, out)
        extract_dir = os.path.join(td, "extract")
        os.makedirs(extract_dir, exist_ok=True)
        safe_extract_zip(zip_path, extract_dir)
        pack_root = find_pack_root(extract_dir)
        if not (os.path.isdir(os.path.join(pack_root, "models")) or os.path.isdir(os.path.join(pack_root, "materials"))):
            raise ValueError("Pack ZIP must contain a folder with models/ and/or materials/.")
        if os.path.isdir(final_dir):
            shutil.rmtree(final_dir)
        shutil.copytree(pack_root, final_dir)
    override_json = os.path.join(final_dir, "override.json")
    if not os.path.exists(override_json):
        meta = {
            "name": pack["name"],
            "character": pack.get("character") or "(unspecified)",
            "skin": pack.get("skin") or pack.get("version") or "Community pack",
            "description": pack.get("description") or "",
        }
        json.dump(meta, open(override_json, "w", encoding="utf-8"), indent=2)
    return final_dir


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.packs = []
        self.title("GMod Override Manager")
        self.geometry("760x460")
        self.minsize(640, 360)
        self._build()
        self.refresh()

    def _build(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="GMod folder:").pack(side="left")
        self.path_var = tk.StringVar(value=self.cfg.get("gmod_path", DEFAULT_GMOD))
        ttk.Entry(top, textvariable=self.path_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(top, text="Browse", command=self.browse).pack(side="left")
        ttk.Button(top, text="Save", command=self.save_path).pack(side="left", padx=4)

        mid = ttk.Frame(self, padding=(8, 0))
        mid.pack(fill="both", expand=True)
        cols = ("name", "character", "skin", "status")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
        for c, w, t in (("name", 180, "Override"), ("character", 170, "Character"),
                        ("skin", 150, "Skin / variant"), ("status", 90, "Status")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.tag_configure("on", foreground="#1a7f1a")
        self.tree.tag_configure("off", foreground="#999999")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.toggle())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_desc())
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        sb.pack(side="left", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        self.desc = tk.StringVar(value="Select an override to see details.")
        ttk.Label(self, textvariable=self.desc, padding=8, wraplength=720,
                  foreground="#444").pack(fill="x")

        target_frame = ttk.Frame(self, padding=(8, 0, 8, 4))
        target_frame.pack(fill="x")
        ttk.Label(target_frame, text="Target Character:").pack(side="left")
        self.target_var = tk.StringVar(value=DEFAULT_TARGET_NAME)
        self.target_combo = ttk.Combobox(target_frame, textvariable=self.target_var, state="readonly", width=34)
        self.target_combo.pack(side="left", padx=6)
        self.target_combo.bind("<<ComboboxSelected>>", self.on_target_change)
        ttk.Label(target_frame, text="Default = the pack's original character", foreground="#777").pack(side="left", padx=6)

        bot = ttk.Frame(self, padding=8)
        bot.pack(fill="x")
        ttk.Button(bot, text="Enable", command=lambda: self.set_state(True)).pack(side="left")
        ttk.Button(bot, text="Disable", command=lambda: self.set_state(False)).pack(side="left", padx=4)
        ttk.Button(bot, text="Delete", command=self.delete_selected).pack(side="left")
        ttk.Button(bot, text="Toggle (dbl-click)", command=self.toggle).pack(side="left")
        ttk.Button(bot, text="Open overrides folder", command=self.open_overrides).pack(side="left", padx=4)
        ttk.Button(bot, text="Override Maker", command=self.override_maker).pack(side="left")
        ttk.Button(bot, text="Community Packs", command=self.community_packs).pack(side="left")
        ttk.Button(bot, text="Refresh", command=self.refresh).pack(side="right")
        ttk.Button(bot, text="Tutorial", command=self.show_tutorial).pack(side="right", padx=4)

        bot2 = ttk.Frame(self, padding=(8, 0, 8, 8))
        bot2.pack(fill="x")
        ttk.Label(bot2, text="Live Translator (English):").pack(side="left")
        ttk.Button(bot2, text="Enable", command=self.lt_enable).pack(side="left", padx=4)
        ttk.Button(bot2, text="Disable", command=self.lt_disable).pack(side="left")
        self.lt_status = tk.StringVar(value="")
        ttk.Label(bot2, textvariable=self.lt_status, foreground="#1a7f1a").pack(side="left", padx=8)

        bot3 = ttk.Frame(self, padding=(8, 0, 8, 8))
        bot3.pack(fill="x")
        ttk.Button(bot3, text="Translate cache (one-shot)", command=self.translate_game).pack(side="left")
        ttk.Button(bot3, text="Undo cache translation", command=self.untranslate_game).pack(side="left", padx=4)
        ttk.Label(bot3, text="(live = legacy addon, swaps text every frame; cache = edits downloaded Lua once)",
                  foreground="#777").pack(side="left", padx=6)
        self.note = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.note, padding=(8, 0, 8, 8), foreground="#a05").pack(fill="x")

    TUTORIAL = (
        "GMOD OVERRIDE MANAGER — QUICK TUTORIAL\n"
        "======================================\n\n"
        "1) SET YOUR GMOD FOLDER\n"
        "   The top box should point to:\n"
        "   ...\\steamapps\\common\\GarrysMod\\garrysmod\n"
        "   If it's wrong, click Browse, pick that folder, then Save.\n\n"
        "2) TURN AN OVERRIDE ON/OFF\n"
        "   Click an override in the list, then Enable or Disable\n"
        "   (or just double-click the row to toggle).\n"
        "   The Status column shows ENABLED / disabled.\n\n"
        "3) CHOOSE WHO IT OVERRIDES\n"
        "   Use Target Character before enabling.\n"
        "   Default means the pack's original character.\n"
        "   Pick another character to retarget the model/hands quickly.\n"
        "   Pick Default again and enable to revert.\n"
        "   Use Custom target... for unusual model paths.\n\n"
        "4) WHEN IT TAKES EFFECT\n"
        "   Changes apply on the next map load or server RECONNECT —\n"
        "   GMod can't swap a model already loaded in your current game.\n"
        "   So: toggle here, then reconnect to the server.\n\n"
        "5) ADD A NEW OVERRIDE\n"
        "   Click 'Override Maker' to build a pack from local model files\n"
        "   and manually assigned game-ready VTF/VMT sprites.\n"
        "   Or click 'Open overrides folder' and drop a pack FOLDER inside it,\n"
        "   then click Refresh. A pack looks like:\n"
        "       MyOverride/\n"
        "         override.json   (name, character, skin, description)\n"
        "         models/...      (model files)\n"
        "         materials/...   (textures / sprites)\n\n"
        "6) ADD A COMMUNITY PACK\n"
        "   Click 'Community Packs', paste or keep an index URL, then Refresh.\n"
        "   Pick a pack and click Install. It downloads into overrides/ like\n"
        "   a normal dropped-in pack, then you can Enable it.\n\n"
        "7) WHO SEES IT\n"
        "   Only YOU see your overrides. Friends need the same pack\n"
        "   enabled on their own copy (share this whole folder/app).\n\n"
        "WHY A LEGACY ADDON (not Workshop)?\n"
        "   Enabling installs the pack into addons\\ovr_<name>. These files\n"
        "   sit ABOVE the server's, so the override wins even on servers you\n"
        "   don't host. A Workshop subscription can't do that."
    )

    def show_tutorial(self):
        win = tk.Toplevel(self)
        win.title("Tutorial")
        win.geometry("560x520")
        win.transient(self)
        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)
        txt = tk.Text(frame, wrap="word", font=("Consolas", 10), borderwidth=0)
        sb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("1.0", self.TUTORIAL)
        txt.configure(state="disabled")
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=8)

    def browse(self):
        d = filedialog.askdirectory(title="Select your ...\\GarrysMod\\garrysmod folder")
        if d:
            self.path_var.set(d)
            self.save_path()

    def save_path(self):
        self.cfg["gmod_path"] = self.path_var.get().strip()
        save_config(self.cfg)
        self.refresh()

    def open_overrides(self):
        os.makedirs(OVERRIDES_DIR, exist_ok=True)
        try:
            os.startfile(OVERRIDES_DIR)  # noqa (Windows)
        except Exception:
            messagebox.showinfo("Overrides folder", OVERRIDES_DIR)

    def override_maker(self):
        win = tk.Toplevel(self)
        win.title("Override Maker")
        win.geometry("760x620")
        win.minsize(680, 520)
        win.transient(self)

        pack_name = tk.StringVar()
        skin = tk.StringVar(value="Local model + sprites")
        override_target_name = tk.StringVar(value="Himiko Yumeno")
        model_path = tk.StringVar()
        arms_path = tk.StringVar()
        material_root = tk.StringVar()
        sprite_dir = tk.StringVar()
        description = tk.StringVar(value="Created with Override Maker.")
        sprite_rows = []
        status = tk.StringVar(value="")

        scroll_wrap = ttk.Frame(win)
        scroll_wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_wrap, borderwidth=0, highlightthickness=0)
        yscroll = ttk.Scrollbar(scroll_wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        form = ttk.Frame(canvas, padding=10)
        form_window = canvas.create_window((0, 0), window=form, anchor="nw")

        def update_scroll_region(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def resize_form(event):
            canvas.itemconfigure(form_window, width=event.width)

        def wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def bind_wheel(_event=None):
            canvas.bind_all("<MouseWheel>", wheel)

        def unbind_wheel(_event=None):
            canvas.unbind_all("<MouseWheel>")

        form.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", resize_form)
        canvas.bind("<Enter>", bind_wheel)
        canvas.bind("<Leave>", unbind_wheel)

        def row(label, var, browse=None):
            frame = ttk.Frame(form)
            frame.pack(fill="x", pady=3)
            ttk.Label(frame, text=label, width=18).pack(side="left")
            ttk.Entry(frame, textvariable=var).pack(side="left", fill="x", expand=True, padx=6)
            if browse:
                ttk.Button(frame, text="Browse", command=browse).pack(side="left")
            return frame

        def update_source(_event=None):
            target = find_target(self.cfg, override_target_name.get())
            if target:
                sprite_dir.set(target.get("sprite_dir", ""))

        def browse_model():
            path = filedialog.askopenfilename(parent=win, title="Select main .mdl", filetypes=[("Source model", "*.mdl")])
            if path:
                model_path.set(path)
                root = path
                while root and os.path.basename(root).lower() != "models":
                    parent = os.path.dirname(root)
                    if parent == root:
                        break
                    root = parent
                if os.path.basename(root).lower() == "models":
                    material_root.set(os.path.dirname(root))

        def browse_arms():
            path = filedialog.askopenfilename(parent=win, title="Select arms .mdl", filetypes=[("Source model", "*.mdl")])
            if path:
                arms_path.set(path)

        def browse_material_root():
            path = filedialog.askdirectory(parent=win, title="Select extracted addon folder with materials/")
            if path:
                material_root.set(path)

        row("Pack name", pack_name)
        row("Skin / variant", skin)

        source_frame = ttk.Frame(form)
        source_frame.pack(fill="x", pady=3)
        ttk.Label(source_frame, text="Character to override", width=18).pack(side="left")
        source_combo = ttk.Combobox(
            source_frame,
            textvariable=override_target_name,
            state="readonly",
            values=[t["name"] for t in available_targets(self.cfg) if t["name"] != DEFAULT_TARGET_NAME],
        )
        source_combo.pack(side="left", fill="x", expand=True, padx=6)
        source_combo.bind("<<ComboboxSelected>>", update_source)

        row("Main model", model_path, browse_model)
        row("Arms model", arms_path, browse_arms)
        row("Material root", material_root, browse_material_root)
        row("Sprite folder", sprite_dir)
        row("Description", description)

        sprite_box = ttk.LabelFrame(form, text="Manual sprite assignments")
        sprite_box.pack(fill="both", expand=True, pady=(10, 4))

        def add_sprite_row(parent, group_name, index):
            label, filename = make_sprite_group_slot(group_name, index)
            path_var = tk.StringVar()
            filename_var = tk.StringVar(value=filename)
            frame = ttk.Frame(parent, padding=(6, 3))
            frame.pack(fill="x")
            ttk.Label(frame, text=label, width=22).pack(side="left")
            ttk.Entry(frame, textvariable=filename_var, width=22).pack(side="left", padx=(0, 6))
            ttk.Entry(frame, textvariable=path_var).pack(side="left", fill="x", expand=True, padx=6)

            def choose(slot_label=label):
                path = filedialog.askopenfilename(
                    parent=win,
                    title=f"Select {slot_label} sprite",
                    filetypes=[("Game sprite", "*.vtf *.vmt")],
                )
                if path:
                    path_var.set(path)

            ttk.Button(frame, text="Pick", command=choose).pack(side="left")
            ttk.Button(frame, text="Clear", command=lambda: path_var.set("")).pack(side="left", padx=3)
            row_data = {
                "group": group_name,
                "label": label,
                "path_var": path_var,
                "filename_var": filename_var,
            }
            sprite_rows.append(row_data)
            update_scroll_region()
            return row_data

        for group in SPRITE_GROUPS:
            group_state = {"count": 0}
            header = ttk.Frame(sprite_box, padding=(6, 8, 6, 3))
            header.pack(fill="x")
            ttk.Label(header, text=f"{group['name']} sprites", width=28).pack(side="left")
            rows = ttk.Frame(sprite_box)
            rows.pack(fill="x")

            def add_group_sprite(group_name=group["name"], group_rows=rows, state=group_state):
                state["count"] += 1
                return add_sprite_row(group_rows, group_name, state["count"])

            def pick_multiple(group_name=group["name"], add_func=add_group_sprite):
                paths = filedialog.askopenfilenames(
                    parent=win,
                    title=f"Select {group_name} sprites",
                    filetypes=[("Game sprite", "*.vtf *.vmt")],
                )
                if not paths:
                    return
                empty_rows = [
                    row_data for row_data in sprite_rows
                    if row_data["group"] == group_name and not row_data["path_var"].get().strip()
                ]
                for path in paths:
                    row_data = empty_rows.pop(0) if empty_rows else add_func()
                    row_data["path_var"].set(path)
                update_scroll_region()

            ttk.Button(header, text=f"Add {group['name']}", command=add_group_sprite).pack(side="left")
            ttk.Button(header, text="Pick Multiple", command=pick_multiple).pack(side="left", padx=6)
            for _ in range(int(group["initial"])):
                add_group_sprite()

        ttk.Label(form, textvariable=status, foreground="#a05").pack(fill="x", pady=(4, 0))

        def create():
            target = find_target(self.cfg, override_target_name.get())
            if not target:
                messagebox.showerror("Override Maker", "Select a character to override.", parent=win)
                return
            assignments = {}
            for row_data in sprite_rows:
                path = row_data["path_var"].get().strip()
                if path:
                    assignments[row_data["label"]] = {
                        "path": path,
                        "filename": row_data["filename_var"].get().strip(),
                    }
            output = os.path.join(OVERRIDES_DIR, pack_folder_name(pack_name.get()))
            if os.path.exists(output):
                if not messagebox.askyesno("Replace pack", f"Replace existing local override folder?\n\n{output}", parent=win):
                    return
                shutil.rmtree(output)
            try:
                created = create_override_pack({
                    "name": pack_name.get(),
                    "character": target["name"],
                    "skin": skin.get(),
                    "description": description.get(),
                    "source_target": target,
                    "main_model": model_path.get(),
                    "arms_model": arms_path.get(),
                    "material_root": material_root.get(),
                    "sprite_dir": sprite_dir.get(),
                    "sprite_assignments": assignments,
                })
            except Exception as e:
                status.set(str(e))
                messagebox.showerror("Override Maker", str(e), parent=win)
                return
            self.refresh()
            messagebox.showinfo("Override Maker", f"Created override pack:\n\n{created}", parent=win)
            win.destroy()

        buttons = ttk.Frame(win, padding=(10, 0, 10, 10))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Create Override", command=create).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side="right", padx=6)

        update_source()

    def community_packs(self):
        win = tk.Toplevel(self)
        win.title("Community Packs")
        win.geometry("820x520")
        win.minsize(680, 420)
        win.transient(self)

        packs = []
        selected = {"index": None}

        top = ttk.Frame(win, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Index URL:").pack(side="left")
        url_var = tk.StringVar(value=self.cfg.get("community_index_url", DEFAULT_COMMUNITY_INDEX_URL))
        ttk.Entry(top, textvariable=url_var).pack(side="left", fill="x", expand=True, padx=6)

        mid = ttk.Frame(win, padding=(8, 0))
        mid.pack(fill="both", expand=True)
        cols = ("name", "character", "version", "author")
        tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
        for c, w, t in (("name", 220, "Pack"), ("character", 170, "Character"),
                        ("version", 90, "Version"), ("author", 120, "Author")):
            tree.heading(c, text=t)
            tree.column(c, width=w, anchor="w")
        tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(mid, orient="vertical", command=tree.yview)
        sb.pack(side="left", fill="y")
        tree.configure(yscrollcommand=sb.set)

        detail = tk.StringVar(value="Refresh to load community packs.")
        ttk.Label(win, textvariable=detail, padding=8, wraplength=780, foreground="#444").pack(fill="x")
        status = tk.StringVar(value="")
        ttk.Label(win, textvariable=status, padding=(8, 0), foreground="#a05").pack(fill="x")

        def selected_pack():
            sel = tree.selection()
            if not sel:
                return None
            return packs[int(sel[0])]

        def update_detail(_event=None):
            p = selected_pack()
            selected["index"] = int(tree.selection()[0]) if tree.selection() else None
            if not p:
                detail.set("Select a community pack to see details.")
                return
            bits = [p["name"]]
            if p.get("version"):
                bits.append(f"v{p['version']}")
            if p.get("author"):
                bits.append(f"by {p['author']}")
            desc = p.get("description") or "(no description)"
            detail.set(f"{' - '.join(bits)}\nOverrides: {p.get('character')} ({p.get('skin')})\n{desc}")

        def load_index():
            url = url_var.get().strip()
            if not url:
                messagebox.showinfo("Index URL", "Enter a community pack index URL first.")
                return
            self.cfg["community_index_url"] = url
            save_config(self.cfg)
            tree.delete(*tree.get_children())
            packs.clear()
            detail.set("Loading community packs...")
            status.set("")
            win.update_idletasks()
            try:
                loaded = normalize_community_index(read_json_url(url))
            except Exception as e:
                detail.set("Could not load community packs.")
                status.set(str(e))
                return
            packs.extend(loaded)
            for i, p in enumerate(packs):
                tree.insert("", "end", iid=str(i),
                            values=(p["name"], p["character"], p.get("version") or p.get("skin"), p.get("author")))
            detail.set(f"Loaded {len(packs)} community pack(s).")
            status.set("")

        def install_selected():
            p = selected_pack()
            if not p:
                messagebox.showinfo("Pick one", "Select a community pack first.")
                return
            if not messagebox.askyesno("Install Community Pack",
                                       f"Download and install '{p['name']}' into the overrides folder?\n\n"
                                       "If a local pack with the same name exists, it will be replaced."):
                return
            status.set(f"Installing {p['name']}...")
            win.update_idletasks()

            def work():
                try:
                    folder = install_community_pack(p)
                    self.after(0, lambda: (
                        status.set(f"Installed to {folder}"),
                        self.refresh(),
                        messagebox.showinfo("Community Packs", f"Installed '{p['name']}'.\n\nSelect it in the main list and click Enable.")
                    ))
                except Exception as e:
                    msg = str(e)
                    self.after(0, lambda: status.set(msg))
            threading.Thread(target=work, daemon=True).start()

        tree.bind("<<TreeviewSelect>>", update_detail)
        tree.bind("<Double-1>", lambda _e: install_selected())

        bot = ttk.Frame(win, padding=8)
        bot.pack(fill="x")
        ttk.Button(bot, text="Refresh", command=load_index).pack(side="left")
        ttk.Button(bot, text="Install Selected", command=install_selected).pack(side="left", padx=4)
        ttk.Button(bot, text="Close", command=win.destroy).pack(side="right")
        win.after(100, load_index)

    def refresh_target_options(self):
        values = [target["name"] for target in available_targets(self.cfg)] + [CUSTOM_TARGET_NAME]
        self.target_combo.configure(values=values)
        if self.target_var.get() not in values:
            self.target_var.set(DEFAULT_TARGET_NAME)

    def selected_target_name(self):
        name = self.target_var.get() or DEFAULT_TARGET_NAME
        return DEFAULT_TARGET_NAME if name == CUSTOM_TARGET_NAME else name

    def selected_target(self):
        return find_target(self.cfg, self.selected_target_name())

    def restore_selected_pack_target(self):
        self.refresh_target_options()
        p = self.selected()
        if not p:
            self.target_var.set(DEFAULT_TARGET_NAME)
            return
        name = saved_target_name(self.cfg, p)
        valid = [target["name"] for target in available_targets(self.cfg)]
        self.target_var.set(name if name in valid else DEFAULT_TARGET_NAME)

    def prompt_custom_target(self):
        name = simpledialog.askstring("Custom target", "Target name:", parent=self)
        if not name:
            return None
        name = name.strip()
        model_base = simpledialog.askstring("Custom target", "Model base path, e.g.\nmodels/dro/player/characters1/char16/char16", parent=self)
        if not model_base:
            return None
        arms_base = simpledialog.askstring("Custom target", "Arms base path (optional):", parent=self) or ""
        sprite_dir = simpledialog.askstring("Custom target", "Sprite folder path (optional):", parent=self) or ""
        try:
            target = {
                "name": name,
                "model_base": safe_game_path(model_base, allow_empty=False, strip_ext=True),
                "arms_base": safe_game_path(arms_base, allow_empty=True, strip_ext=True),
                "sprite_dir": safe_game_path(sprite_dir, allow_empty=True),
            }
        except ValueError as e:
            messagebox.showerror("Custom target", str(e))
            return None
        self.cfg.setdefault("custom_targets", {})[name] = {
            "model_base": target["model_base"],
            "arms_base": target["arms_base"],
            "sprite_dir": target["sprite_dir"],
        }
        save_config(self.cfg)
        self.refresh_target_options()
        return target

    def on_target_change(self, _event=None):
        p = self.selected()
        if not p:
            self.target_var.set(DEFAULT_TARGET_NAME)
            return
        if self.target_var.get() == CUSTOM_TARGET_NAME:
            target = self.prompt_custom_target()
            if not target:
                self.restore_selected_pack_target()
                return
            self.target_var.set(target["name"])
        target_name = self.selected_target_name()
        should_apply = target_change_needs_apply(self.cfg, p, target_name)
        save_pack_target(self.cfg, p, target_name)
        if should_apply:
            self.set_state(True)
        else:
            self.update_desc()

    def refresh(self):
        self.refresh_target_options()
        self.packs = scan_overrides()
        self.tree.delete(*self.tree.get_children())
        ad = addons_dir(self.cfg)
        ok = os.path.isdir(ad)
        for i, p in enumerate(self.packs):
            active_target = enabled_target_name(self.cfg, p) if ok else ""
            self.tree.insert("", "end", iid=str(i),
                             values=(p["name"], p["character"], p["skin"],
                                     f"ENABLED: {active_target}" if active_target else "disabled"),
                             tags=("on" if active_target else "off",))
        if not ok:
            self.note.set("GMod 'addons' folder not found — set the correct GMod folder above.")
        elif not self.packs:
            self.note.set("No override packs found. Drop a pack folder into the 'overrides' folder, then Refresh.")
        else:
            self.note.set("Tip: changes apply on next map load / server reconnect, not mid-session.")
        self.lt_refresh()

    def selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.packs[int(sel[0])]

    def update_desc(self):
        p = self.selected()
        if p:
            self.restore_selected_pack_target()
            d = p.get("description") or "(no description)"
            active = enabled_target_name(self.cfg, p)
            active_text = f" Active target: {active}." if active else ""
            self.desc.set(f"{p['name']} — default target {p['character']} ({p['skin']}). "
                          f"Selected target: {self.selected_target_name()}.{active_text}  {d}")

    def set_state(self, want_on):
        p = self.selected()
        if not p:
            messagebox.showinfo("Pick one", "Select an override first.")
            return
        if not os.path.isdir(addons_dir(self.cfg)):
            messagebox.showerror("GMod not found", "Set the correct GMod folder first.")
            return
        try:
            if want_on:
                target = self.selected_target()
                if target:
                    source = infer_source_target(p["folder"])
                    if source.get("sprite_dir") and not target.get("sprite_dir"):
                        if not messagebox.askyesno("Sprites not retargeted",
                                                   "This target has no known sprite folder yet.\n\n"
                                                   "The model and hands will retarget, but sprites will stay on the pack's default character.\n\n"
                                                   "Continue?"):
                            return
                save_pack_target(self.cfg, p, self.selected_target_name())
                enable(self.cfg, p, target)
            else:
                disable(self.cfg, p)
        except Exception as e:
            messagebox.showerror("Error", str(e))
        self.refresh()

    def delete_selected(self):
        p = self.selected()
        if not p:
            messagebox.showinfo("Pick one", "Select an override first.")
            return
        folder = os.path.abspath(p["folder"])
        overrides = os.path.abspath(OVERRIDES_DIR)
        if os.path.commonpath([overrides, folder]) != overrides:
            messagebox.showerror("Delete blocked", "That override folder is outside the overrides folder.")
            return
        if not messagebox.askyesno("Delete Override",
                                   f"Delete local override '{p['name']}'?\n\n"
                                   "If it is enabled, it will be disabled first. This cannot be undone."):
            return
        try:
            disable(self.cfg, p)
            shutil.rmtree(folder)
        except Exception as e:
            messagebox.showerror("Delete failed", str(e))
            return
        self.refresh()
        self.desc.set("Select an override to see details.")

    def toggle(self):
        p = self.selected()
        if not p:
            return
        self.set_state(not is_enabled(self.cfg, p))

    def lt_refresh(self):
        if live_translator is None:
            self.lt_status.set("unavailable")
            return
        on = live_translator.is_installed(self.cfg.get("gmod_path", DEFAULT_GMOD))
        self.lt_status.set("ENABLED (restart GMod)" if on else "disabled")

    def lt_enable(self):
        if live_translator is None:
            messagebox.showerror("Live Translator", "Live Translator support is not included in this build.")
            return
        gp = self.cfg.get("gmod_path", DEFAULT_GMOD)
        if not os.path.isdir(os.path.join(gp, "addons")):
            messagebox.showerror("GMod not found", "Set the correct GMod folder first.")
            return
        tj = self._trans_json()
        if not tj:
            return
        try:
            n = live_translator.install(gp, tj)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return
        self.lt_refresh()
        messagebox.showinfo("Live Translator",
                            f"Enabled ({n} phrases) as a legacy addon.\n\n"
                            "IMPORTANT: fully RESTART GMod (legacy addons load at startup), then join.\n"
                            "You should see a green 'Live Translator active' indicator top-left for ~20s.")

    def lt_disable(self):
        if live_translator is None:
            messagebox.showerror("Live Translator", "Live Translator support is not included in this build.")
            return
        live_translator.uninstall(self.cfg.get("gmod_path", DEFAULT_GMOD))
        self.lt_refresh()
        messagebox.showinfo("Live Translator", "Disabled (removed). Restart GMod to apply.")

    def _trans_json(self):
        p = os.path.expanduser(r"~\Downloads\translations.json")
        if os.path.exists(p):
            return p
        return filedialog.askopenfilename(title="Select translations.json",
                                          filetypes=[("JSON", "*.json")])

    def translate_game(self):
        if translate_cache is None:
            messagebox.showerror("Translate", "Cache translation support is not included in this build.")
            return
        gp = self.cfg.get("gmod_path", DEFAULT_GMOD)
        if not os.path.isdir(os.path.join(gp, "cache", "lua")):
            messagebox.showerror("No cache", "GMod cache/lua not found. Set the correct GMod folder, and join the server once so it caches the Lua.")
            return
        tj = self._trans_json()
        if not tj:
            return
        if not messagebox.askyesno("Translate", "Translate GMod's cached server Lua to English?\n\nA backup is made the first time. You can Undo afterwards.\n(If the game re-downloads on join, the server is re-verifying the cache and this can't stick.)"):
            return
        self.note.set("Translating cached Lua… (this can take a few seconds)")
        self.update_idletasks()

        def work():
            try:
                scanned, changed = translate_cache.translate_dir(gp, tj, log=lambda *_: None)
                msg = f"Translated {changed} of {scanned} cached Lua files.\n\nReconnect to the server to see English. If it shows Russian again, the server re-verifies the cache (nothing client-side can change it)."
                self.after(0, lambda: (self.note.set(f"Done: translated {changed}/{scanned} cache files."), messagebox.showinfo("Translate", msg)))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Translate failed", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def untranslate_game(self):
        if translate_cache is None:
            messagebox.showerror("Undo", "Cache translation support is not included in this build.")
            return
        gp = self.cfg.get("gmod_path", DEFAULT_GMOD)
        if not os.path.isdir(os.path.join(gp, "cache", "lua", "..", "lua_backup_translate")):
            pass
        translate_cache.restore(gp, log=lambda *_: None)
        self.note.set("Restored cached Lua from backup (translation undone).")
        messagebox.showinfo("Undo", "Restored the original cached Lua from backup.")


if __name__ == "__main__":
    App().mainloop()

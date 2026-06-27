# GMod Override Manager

A small Windows app for **Shinri Trial** players to manage Garry's Mod
model/skin/sprite overrides. Each override is a drop-in folder ("pack"); the app
lists what character each one replaces and lets you toggle it on/off.

## Download
Grab **`GMod_Override_Manager.zip`** from the [Releases](../../releases) page,
extract the folder anywhere, and open **`GMod Override Manager.exe`** inside.
This is a portable app, not an installer.

No setup wizard, install step, or Python is needed. There's a **Tutorial** button
inside the app.

The ZIP is a clean portable app folder. It does not include preinstalled local
override packs, personal config, build cache, or generated app cache. Use
**Community Packs** inside the app to install approved packs.

## How it works
Enabling a pack installs it as a **legacy addon** (`addons/ovr_<name>`). Legacy
addon files sit *above* the server's in GMod's load order, so the override wins
**even on servers you don't host** — something a Workshop subscription can't do.

> Changes apply on the next map load / server **reconnect** (GMod doesn't
> hot-swap a model already loaded in your current session). It only changes what
> **you** see — others need the same pack enabled.

## Adding a character override
Drop a pack folder into `overrides/`, then hit **Refresh**. A pack looks like:

```
overrides/
  My Override/
    override.json     # {name, character, skin, description}
    models/...        # model files (same paths as the game)
    materials/...     # textures / sprites
```

`override.json` example:

```json
{
  "name": "Female Shuichi",
  "character": "Shuichi Saihara",
  "skin": "Female model",
  "description": "Replaces Shuichi with the female model + sprites."
}
```

## Community Packs
Click **Community Packs** to browse the online JSON index of downloadable
override packs. Pick a pack, click **Install Selected**, then enable it from the
main list.

The index can be hosted anywhere that serves raw JSON, including GitHub Pages or
GitHub's raw file URLs. This build uses:

```
https://raw.githubusercontent.com/VastohLorde/gmod-override-manager/main/community_packs.json
```

See `community_packs.example.json` for the format:

```json
{
  "packs": [
    {
      "name": "George Droyd K1B0",
      "character": "K1-B0 / K1B0",
      "skin": "George Droyd override",
      "version": "0.1.0",
      "author": "VastohLorde",
      "description": "Replaces K1B0/Keebo with George Droyd.",
      "download_url": "https://raw.githubusercontent.com/VastohLorde/gmod-override-manager/main/community_packs/George.Droyd.K1B0.zip"
    }
  ]
}
```

Each `download_url` should point to a ZIP containing a normal override pack
folder or the pack contents directly:

```
George Droyd K1B0/
  override.json
  addon.json
  models/...
  materials/...
  lua/...
```

The installer rejects unsafe ZIP paths like `../file` and extracts only into the
local `overrides/` folder.

To remove a local override, select it in the main list and click **Delete**. If
it is enabled, the app disables it before removing the local pack folder.

## Submit Your Work
Want your own Shinri Trial override added to Community Packs? Submit it through
GitHub so it can be reviewed before it appears in the app:

1. Fork this repo.
2. Add your override ZIP to `community_packs/`.
3. Add an entry for it to `community_packs.json`.
4. Open a pull request.

Only approved and merged pull requests show up in the Community Packs menu.
Packs should contain only normal override files:

```
My Override/
  override.json
  addon.json
  models/...
  materials/...
  lua/...
```

## Included packs
| Override | Character | Skin |
|---|---|---|
| Female Shuichi | Shuichi Saihara | Female model + sprites |
| George Droyd K1B0 | K1-B0 / K1B0 | George Droyd model + sprites |
| Israel Nekomaru | Nekomaru Nidai | Israel skin + sprites |

## Notes
- Needs the base addon for that character (e.g. the Danganronpa PlayerModels
  addon) for any shared textures.
- The `.exe` is unsigned, so Windows SmartScreen may warn on first run
  ("More info → Run anyway"). You can also run the source: `python override_manager.py`.

# Shinri Trial Override Manager

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

## Choosing a target character
Select an override, then use **Target Character** before clicking **Enable**.
The first option, **Recommended (Character)**, is the character the pack is meant
for (set by the pack), and it's selected by default for every override. Any other
listed character retargets the model and hands to that character while keeping the
local pack folder unchanged.

To go back, choose the **Recommended** option and enable again. Disabling a pack
removes every installed target variant for that pack.

**Automatic conflict resolution:** if two *enabled* overrides would land on the same
character, the one you enabled first keeps it and the newer one is automatically
moved to its next best target (see Best Target), so they never clash. Disable the
first one and the other moves back to its preferred character.

Use **Custom target...** for weird cases. Enter a model base path such as:

```
models/dro/player/characters1/char16/char16
```

Arms and sprite paths are optional. If a listed target has no known sprite path,
the manager warns that sprites will stay on the pack's default character.

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

## Override Maker (build a pack in-app)
Don't want to assemble a pack folder by hand? Click **Override Maker** to build one
from local model files through a guided form. It writes a ready-to-use pack into
`overrides/` (hit **Refresh** to see it), with all the correct in-game paths and an
`override.json` filled in for you.

What the form covers:

- **Pack name / Skin / Description** — the text shown in the main list.
- **Character to override** — the Shinri Trial character whose slot the pack fills.
  Picking one auto-fills the matching **Sprite folder**.
- **Workshop link** — paste a Steam Workshop URL or ID and click **Load**. If the
  item isn't already downloaded, the maker can fetch it with SteamCMD, extract the
  GMA, and let you pick which `.mdl` to use (it sets the material root for you).
- **Main model / Arms model** — browse to the `.mdl` files. Choosing the main model
  auto-detects the **Material root** (the folder that contains `materials/`).
- **Manual sprite assignments** — drop your own `.vtf`/`.vmt` files into individual
  courtroom sprite slots (talk, objection, scrum debate, door, and more); add as
  many slots per category as you need.

Click **Create Override** and the pack is generated — model, materials, and sprites
copied to the right paths. From there it behaves like any other pack: pick a target,
enable it, or share it through Community Packs.

## Best Target (customization compatibility)
In-game, a character's customization sliders (outfit bodygroups, light/skin colours,
etc.) are driven by the **base** character the server thinks you are — so an override
model can only use as many options *per slider* as that base character has. Extra
outfit variants on your model are simply unreachable; skins are the exception (they
aren't capped).

Select an override and click **Best Target** to see, for every character, how much of
your model's customization is actually reachable:

- A ranked list with a **Match %** and the best slider-by-slider fit.
- 100% means every outfit/skin option on your model can be selected; lower means some
  options are hidden because that base character's slider has fewer positions. The
  score reflects what actually works in-game: the customization tool matches sliders
  by bodygroup **index**, so a character only helps if it has enough options at the
  same index your model uses.
- Pick a character to see an **outfit-by-outfit** table: every individual option on your
  model (outfit1, outfit2, … plus each skin) with a clear reachable/unreachable status
  and exactly which slider position selects it. Then **Set as Target Character** to
  retarget to the best fit.

This is why, for example, a 3-outfit model lands on a character whose matching slider
also has 3 options, instead of one that caps it at 2.

## Community Presence (see other users in-game)
**On by default** — click the **Community Presence** button to turn it off if you
prefer. It's a client-side feature that lets Override Manager users on the same
server find each other and share **community** packs. When on, it installs a small
client-side addon that quietly broadcasts which community overrides you have enabled
(and the character each targets). Other users type **`!ovr`** (or `ovr_menu` in
console) to see a list and pick which to install — nobody is forced to accept. Accepted packs are downloaded and enabled at the same
target the other player used, and you're prompted to reconnect to apply them.

Safety: it only ever offers/installs packs that are in the approved Community Packs
index. Keep the app open so accepted installs can finish. It rides on in-game chat,
so the broadcast is a short coded line (hidden from other manager users' chat).

## Community Packs
Click **Community Packs** to browse the online JSON index of downloadable
override packs. Pick a pack, click **Install Selected**, then enable it from the
main list.

The index can be hosted anywhere that serves raw JSON, including GitHub Pages or
GitHub's raw file URLs. This build uses:

```
https://raw.githubusercontent.com/VastohLorde/shinri-trial-override-manager/main/community_packs.json
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
      "download_url": "https://raw.githubusercontent.com/VastohLorde/shinri-trial-override-manager/main/community_packs/George.Droyd.K1B0.zip"
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

## Community packs
Available from the **Community Packs** menu inside the app:

| Override | Character | Skin |
|---|---|---|
| Female Shuichi | Shuichi Saihara | Female model + sprites |
| George Droyd K1B0 | K1-B0 / K1B0 | George Droyd model + sprites |
| Israel Nekomaru | Nekomaru Nidai | Israel skin + sprites |
| Hoshino Himiko | Himiko Yumeno | Hoshino model + sprites |
| Shiroko Mahiru | Mahiru Koizumi | Shiroko model + sprites |
| Shiroko Terror Kirumi | Kirumi Tojo | Shiroko Terror model + sprites |

## Notes
- Needs the base addon for that character (e.g. the Danganronpa PlayerModels
  addon) for any shared textures.
- The `.exe` is unsigned, so Windows SmartScreen may warn on first run
  ("More info → Run anyway"). You can also run the source: `python override_manager.py`.

# Installing converted addons

## Prepare the game

Extract GOD/ISO files first if needed, using Xbox game files. The game folder must directly contain default.xex. Keep the original. Use Loader Patch > Check game > Patch Me Up!! on the supported zip0.360.zip/zip1.360.zip layout. Do not rename stock archives to force compatibility. Disable Aurora's separate title update for the patched copy.

## Copy the addon, not its output parent

Enable Leave 2 Loader output before converting. Find the generated folder containing addoninfo.txt and zip0.360.zip. Copy that whole folder directly into left4dead2/addons:

```text
YourGame/
  default.xex
  left4dead2/
    addons/
      My Campaign/
        addoninfo.txt
        zip0.360.zip
        maps/          (if present)
        missions/      (if present)
        ui/            (if present)
```

Wrong: `addons/My-Conversion-Output/My Campaign/addoninfo.txt`.

Do not copy report.json, logs, .work or the output parent. Do not extract the addon ZIP or move it into the game root. Keep loose maps/missions beside its asset ZIP.

## Enable and restart

Launch the same patched copy. Open Leave 2 Loader through ADD-ONS, enable the addon, then restart. Changed entries can stay yellow to mark changed choices. Texture/model replacements affect existing content; they do not add campaigns. Select Campaign/Survival/Scavenge as appropriate, then that mode's Addon campaigns. Disable conflicting replacements and duplicate campaign versions.

## Offline DLC

Use your own Xbox DLC packages/extracted folders. Include The Passing and The Sacrifice for shared L4D1 support, plus Cold Stream when importing it. Build to a new folder, close Xenia and use Install prepared build. Copying only Addons omits required startup audio registration.

Keep Offline Xbox DLC before L4D1 survivor support, then other replacements. Disable overlapping PC campaign ports/runtime packages. Optional missing PC previews use PC/SDK paths saved from the Converter page and import UI images only.

## Troubleshooting

- No addon: check for an extra parent folder and a valid addoninfo.txt, then fully restart. Xenia must allow game-folder writes for automatic registration to save.
- Conversion stops: inspect report.json/logs. Repairs and supplementation do not add unsupported engine features.
- Missing/wireframe content: check dependency paths and duplicate texture inclusion. Reported placeholders can change appearance.
- Map restarts/crashes: record the exact map, platform and enabled addons. Xenia has different runtime behavior from hardware.
- Restore clean game: permanently removes installed mods after required acknowledgement. Original-file backups remain under .leave2-loader/backups.

Keep output separate from inputs, tools, game references and the application. Moving the entire application is supported; update external paths if their locations move.

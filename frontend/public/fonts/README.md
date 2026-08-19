# Self-hosted fonts

The spec calls for Barlow Condensed (labels) and JetBrains Mono
(telemetry/coordinates), self-hosted as woff2, no runtime font fetches.

To wire them in:

1. Drop `BarlowCondensed-Regular.woff2`, `BarlowCondensed-SemiBold.woff2`,
   `BarlowCondensed-Bold.woff2`, and `JetBrainsMono-Regular.woff2` into this
   directory (both are OFL-licensed and available from Google Fonts /
   fonts.google.com or the JetBrains Mono GitHub releases).
2. Add `@font-face` rules for them at the top of `src/index.css` (a prior
   version of this file had the exact rules — same paths, same weights).
3. Update `--font-label` / `--font-mono` in `src/index.css` to put the
   real family names first in the stack.

No other file needs to change — every component reads typography through
those two CSS custom properties.

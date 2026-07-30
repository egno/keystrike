from ._grid import build_layout

# Colemak Mod-DH, ortholinear/matrix variant (no ANSI missing-key stagger
# quirk — matches split ortho boards like the Corne/Ferris/Planck). Verified
# against the official scan-code mapping in
# ColemakMods/mod-dh:autohotkey/colemak_dh_matrix.ahk — D and H move off the
# home row's inner columns down to the bottom row (curl down instead of an
# inward stretch), and G reclaims its QWERTY home-row position.
LAYOUT = build_layout(
    "colemak_dh",
    ("qwfpbjluy;", "arstgmneio", "zxcdvkh,./"),
    ortholinear=True,
)

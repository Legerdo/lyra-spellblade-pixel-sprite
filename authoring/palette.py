"""Project palette for Lyra (silver twin-tail spellblade). One key char per swatch.

Materials are grouped so every tone has a named role; animation work may only use these keys.
"""
from __future__ import annotations

# key: (hex, group, role)
PALETTE: dict[str, tuple[str, str, str]] = {
    # skin
    "S": ("ffeadf", "skin", "light"),
    "s": ("f9cdb7", "skin", "mid"),
    "k": ("e7a095", "skin", "shadow"),
    "K": ("a65a5e", "skin", "outline"),
    "u": ("f59aa3", "skin", "blush"),
    # silver hair
    "W": ("ffffff", "hair", "highlight"),
    "H": ("e3e5f3", "hair", "light"),
    "h": ("b6b9d6", "hair", "mid"),
    "g": ("8586ae", "hair", "shadow"),
    "G": ("4b456e", "hair", "outline"),
    # eyes (ruby -> amber)
    "L": ("2a1934", "eye", "lash"),
    "E": ("6d1737", "eye", "iris dark"),
    "r": ("d13550", "eye", "iris"),
    "R": ("ff9d5c", "eye", "iris light"),
    # navy uniform
    "N": ("5b6cb0", "navy", "light"),
    "n": ("39457a", "navy", "mid"),
    "m": ("262d55", "navy", "shadow"),
    "M": ("151834", "navy", "outline"),
    # pink ribbon / scarf / trim
    "P": ("ffb8d2", "pink", "light"),
    "p": ("f36fa3", "pink", "mid"),
    "q": ("bf4679", "pink", "shadow"),
    "Q": ("6f2248", "pink", "outline"),
    # white cloth (collar, cuffs, frill)
    "F": ("f4f1fa", "white", "light"),
    "f": ("c6c0dd", "white", "shadow"),
    # leather (boots, gloves, belt)
    "B": ("87636e", "leather", "light"),
    "b": ("57404d", "leather", "mid"),
    "d": ("3a2833", "leather", "shadow"),
    "D": ("1f1219", "leather", "outline"),
    # metal (rapier)
    "X": ("d2e2f2", "metal", "light"),
    "x": ("8ea1c0", "metal", "mid"),
    "y": ("505d7f", "metal", "shadow"),
    "Y": ("2a2f4e", "metal", "outline"),
    # magic FX
    "C": ("eaffff", "fx-cyan", "core"),
    "c": ("86f2ff", "fx-cyan", "light"),
    "j": ("2fc6ea", "fx-cyan", "mid"),
    "J": ("1c7dba", "fx-cyan", "dark"),
    "z": ("ff5cb6", "fx-pink", "hot"),
}

KEYS = list(PALETTE)


def rgba(key: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = PALETTE[key][0]
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


RGB_TO_KEY = {rgba(k)[:3]: k for k in PALETTE}

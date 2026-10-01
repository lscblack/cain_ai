"""Curated public platforms for username presence checks.

Each platform exposes a public profile URL for a given handle. KAI only
requests that public URL and interprets the HTTP status — it never logs in,
guesses passwords, or bypasses access controls.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    url_template: str  # must contain {username}
    category: str = "social"

    def url_for(self, username: str) -> str:
        return self.url_template.format(username=username)


PLATFORMS: list[Platform] = [
    Platform("github", "GitHub", "https://github.com/{username}", "dev"),
    Platform("gitlab", "GitLab", "https://gitlab.com/{username}", "dev"),
    Platform("reddit", "Reddit", "https://www.reddit.com/user/{username}", "social"),
    Platform("instagram", "Instagram", "https://www.instagram.com/{username}/", "social"),
    Platform("tiktok", "TikTok", "https://www.tiktok.com/@{username}", "social"),
    Platform("youtube", "YouTube", "https://www.youtube.com/@{username}", "video"),
    Platform("twitch", "Twitch", "https://www.twitch.tv/{username}", "video"),
    Platform("pinterest", "Pinterest", "https://www.pinterest.com/{username}/", "social"),
    Platform("medium", "Medium", "https://medium.com/@{username}", "blog"),
    Platform("devto", "DEV", "https://dev.to/{username}", "dev"),
    Platform("keybase", "Keybase", "https://keybase.io/{username}", "dev"),
    Platform("telegram", "Telegram", "https://t.me/{username}", "social"),
    Platform("steam", "Steam", "https://steamcommunity.com/id/{username}", "gaming"),
    Platform("soundcloud", "SoundCloud", "https://soundcloud.com/{username}", "music"),
]

PLATFORMS_BY_KEY = {p.key: p for p in PLATFORMS}

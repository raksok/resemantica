from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScreenInfo:
    number: int
    screen_id: str
    class_name: str
    label: str
    title: str
    purpose: str


SCREEN_INFOS: tuple[ScreenInfo, ...] = (
    ScreenInfo(1, "dashboard", "DashboardScreen", "Dashboard", "Dashboard", "Run overview"),
    ScreenInfo(2, "preprocessing", "PreprocessingScreen", "Prep", "Preprocessing", "Prepare chapters"),
    ScreenInfo(3, "translation", "TranslationScreen", "Translate", "Translation", "Translation progress"),
    ScreenInfo(4, "warnings", "WarningsScreen", "Warnings", "Warnings", "Warnings and failures"),
    ScreenInfo(5, "artifacts", "ArtifactsScreen", "Artifacts", "Artifacts", "Output files"),
    ScreenInfo(6, "cleanup", "CleanupScreen", "Cleanup", "Cleanup", "Cleanup workflow"),
    ScreenInfo(7, "event-log", "EventLogScreen", "Events", "Events", "Live event log"),
    ScreenInfo(8, "reset-preview", "ResetPreviewScreen", "Reset", "Reset", "Reset preview"),
    ScreenInfo(9, "settings", "SettingsScreen", "Settings", "Settings", "Active config"),
)

TOTAL_PRIMARY_SCREENS = len(SCREEN_INFOS)

SCREEN_INFO_BY_ID = {info.screen_id: info for info in SCREEN_INFOS}
SCREEN_INFO_BY_CLASS_NAME = {info.class_name: info for info in SCREEN_INFOS}


def screen_info_for_id(screen_id: str) -> ScreenInfo | None:
    return SCREEN_INFO_BY_ID.get(screen_id)


def screen_info_for_class_name(class_name: str) -> ScreenInfo | None:
    return SCREEN_INFO_BY_CLASS_NAME.get(class_name)


def format_location(info: ScreenInfo | None) -> str:
    if info is None:
        return "Screen --"
    return f"Screen {info.number}/{TOTAL_PRIMARY_SCREENS} {info.title}"


def format_footer_keys(info: ScreenInfo | None) -> str:
    if info is None:
        return "1-9 Switch  ? Help  q Quit"
    return f"Active: {info.number} {info.title} | 1-9 Switch  ? Help  q Quit"

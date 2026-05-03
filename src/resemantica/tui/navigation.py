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
    ScreenInfo(2, "ingestion", "IngestionScreen", "Ingestion", "Ingestion", "EPUB path and extraction"),
    ScreenInfo(3, "preprocessing", "PreprocessingScreen", "Prep", "Preprocessing", "Prepare chapters"),
    ScreenInfo(4, "translation", "TranslationScreen", "Translate", "Translation", "Translation progress"),
    ScreenInfo(5, "observability", "ObservabilityScreen", "Observe", "Observability", "Run signals and logs"),
    ScreenInfo(6, "artifact", "ArtifactScreen", "Artifact", "Artifact", "Output files"),
    ScreenInfo(7, "cleanup-wizard", "CleanupWizardScreen", "Cleanup", "Cleanup", "Scoped cleanup wizard"),
    ScreenInfo(8, "settings", "SettingsScreen", "Settings", "Settings", "Active config"),
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
        return "1-8 Switch  ? Help  q Quit"
    return f"Active: {info.number} {info.title} | 1-8 Switch  ? Help  q Quit"

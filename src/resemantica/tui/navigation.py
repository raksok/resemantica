from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScreenInfo:
    number: int
    screen_id: str
    class_name: str
    short_label: str
    label: str
    title: str
    purpose: str
    sub_tabs: tuple[str, ...] = ()


SCREEN_INFOS: tuple[ScreenInfo, ...] = (
    ScreenInfo(1, "dashboard", "DashboardScreen", "D", "Dashboard", "Dashboard", "Run overview"),
    ScreenInfo(2, "ingestion", "IngestionScreen", "I", "Ingestion", "Ingestion", "EPUB path and extraction"),
    ScreenInfo(3, "preprocessing", "PreprocessingScreen", "P", "Preprocess", "Preprocessing", "Prepare chapters",
               ("Glossary", "Summaries", "Idioms", "Graph", "Packets")),
    ScreenInfo(4, "translation", "TranslationScreen", "T", "Translate", "Translation", "Translation progress",
               ("Pass 1", "Pass 2", "Pass 3", "Rebuild")),
    ScreenInfo(5, "observability", "ObservabilityScreen", "O", "Observe", "Observability", "Run signals and logs"),
    ScreenInfo(6, "artifact", "ArtifactScreen", "A", "Artifact", "Artifact", "Output files"),
    ScreenInfo(7, "cleanup-wizard", "CleanupWizardScreen", "C", "Cleanup", "Cleanup", "Scoped cleanup wizard"),
    ScreenInfo(8, "settings", "SettingsScreen", "S", "Settings", "Settings", "Active config"),
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


def format_tab_bar(active_info: ScreenInfo | None) -> str:
    if active_info is None:
        return ""
    parts: list[str] = []
    for info in SCREEN_INFOS:
        if info == active_info:
            parts.append(f"[b][{info.number} {info.label}][/]")
            if info.sub_tabs:
                sub = " \u00b7 ".join(
                    f"[{t}]" if i == 0 else t for i, t in enumerate(info.sub_tabs)
                )
                parts.append(f"  {sub}")
        else:
            parts.append(f"[dim][{info.number}]{info.short_label}[/]")
    return "  ".join(parts)

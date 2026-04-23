from __future__ import annotations

from resemantica.epub.models import ChapterParseResult


def validate_extraction(
    release_id: str,
    chapter_results: list[ChapterParseResult],
) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    documents: list[dict[str, object]] = []

    for chapter in chapter_results:
        if chapter.errors:
            errors.extend(
                f"{chapter.source_document_path}: {error}" for error in chapter.errors
            )
        if chapter.warnings:
            warnings.extend(
                f"{chapter.source_document_path}: {warning}" for warning in chapter.warnings
            )

        previous_order = 0
        for record in chapter.records:
            if record.block_order < previous_order:
                errors.append(
                    f"{chapter.source_document_path}: block order regression on {record.block_id}."
                )
            previous_order = record.block_order

        documents.append(
            {
                "document_path": chapter.source_document_path,
                "status": "failed" if chapter.errors else "success",
                "errors": chapter.errors,
                "warnings": chapter.warnings,
            }
        )

    return {
        "release_id": release_id,
        "stage_name": "epub_extraction_validation",
        "status": "failed" if errors else "success",
        "errors": errors,
        "warnings": warnings,
        "document_path": None,
        "documents": documents,
    }


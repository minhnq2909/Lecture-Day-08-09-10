"""
Cleaning rules — raw export → cleaned rows + quarantine.

Baseline gồm các failure mode mở rộng (allowlist doc_id, parse ngày, HR stale version).
Sinh viên thêm ≥3 rule mới: mỗi rule phải ghi `metric_impact` (xem README — chống trivial).
"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Khớp export hợp lệ trong lab (mở rộng khi nhóm thêm doc mới — phải đồng bộ contract).
ALLOWED_DOC_IDS = frozenset(
    {
        "policy_refund_v4",
        "sla_p1_2026",
        "it_helpdesk_faq",
        "hr_leave_policy",
        "access_control_sop",
    }
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DMY_SLASH = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_REPEATED_WORD = re.compile(r"\b([\wÀ-ỹ]+)(\s+\1\b)+", flags=re.IGNORECASE)


def _norm_text(s: str) -> str:
    return " ".join((s or "").strip().split()).lower()


def _stable_chunk_id(doc_id: str, chunk_text: str, seq: int) -> str:
    h = hashlib.sha256(f"{doc_id}|{chunk_text}|{seq}".encode("utf-8")).hexdigest()[:16]
    return f"{doc_id}_{seq}_{h}"


def _normalize_effective_date(raw: str) -> Tuple[str, str]:
    """
    Trả về (iso_date, error_reason).
    iso_date rỗng nếu không parse được.
    """
    s = (raw or "").strip()
    if not s:
        return "", "empty_effective_date"
    if _ISO_DATE.match(s):
        return s, ""
    m = _DMY_SLASH.match(s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}", ""
    return "", "invalid_effective_date_format"


def _has_stale_hr_annual_leave(text: str) -> bool:
    return "10 ngày phép năm" in _norm_text(text)


def _has_low_confidence_marker(text: str) -> bool:
    normalized = _norm_text(text)
    return "nội dung không rõ ràng" in normalized or "!!!" in text


def _collapse_repeated_words(text: str) -> Tuple[str, bool]:
    """
    Fix OCR/export stutter such as "làm việc làm việc làm việc" while preserving meaning.
    """
    fixed = _REPEATED_WORD.sub(r"\1", text)
    return fixed, fixed != text


def _is_non_p1_sla_chunk(doc_id: str, text: str) -> bool:
    if doc_id != "sla_p1_2026":
        return False
    normalized = _norm_text(text)
    return normalized.startswith(("ticket p2:", "ticket p3:", "ticket p4:"))


def _clarify_p1_escalation_text(doc_id: str, text: str) -> Tuple[str, bool]:
    if doc_id != "sla_p1_2026":
        return text, False
    normalized = _norm_text(text)
    if "escalation p1" not in normalized or "10 phút" not in normalized:
        return text, False
    clarified = (
        "Ticket P1 auto escalation: Nếu không có phản hồi với ticket P1 sau 10 phút, "
        "hệ thống tự động escalate lên Senior Engineer. "
        + text
    )
    return clarified, True


def load_raw_csv(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def clean_rows(
    rows: List[Dict[str, str]],
    *,
    apply_refund_window_fix: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Trả về (cleaned, quarantine).

    Baseline (mở rộng theo narrative Day 10):
    1) Quarantine: doc_id không thuộc allowlist (export lạ / catalog sai).
    2) Chuẩn hoá effective_date sang YYYY-MM-DD; quarantine nếu không parse được.
    3) Quarantine: chunk hr_leave_policy có effective_date < 2026-01-01 (bản HR cũ / conflict version).
    4) Quarantine: chunk_text rỗng hoặc effective_date rỗng sau chuẩn hoá.
    5) Quarantine: HR 2025 marker "10 ngày phép năm" dù export date nhìn như mới.
    6) Quarantine: low-confidence/noisy chunk có marker "Nội dung không rõ ràng" hoặc "!!!".
    7) Quarantine: chunk SLA P2/P3/P4 lẫn trong corpus chấm SLA P1.
    8) Loại trùng nội dung chunk_text (giữ bản đầu).
    9) Fix stale refund: policy_refund_v4 chứa '14 ngày làm việc' → 7 ngày.
    10) Fix repeated-word export stutter (ví dụ "làm việc làm việc").
    11) Clarify chunk P1 escalation để retriever không nhầm với P2 escalation.
    """
    quarantine: List[Dict[str, Any]] = []
    seen_text: set[str] = set()
    cleaned: List[Dict[str, Any]] = []
    seq = 0

    for raw in rows:
        doc_id = raw.get("doc_id", "")
        text = raw.get("chunk_text", "")
        eff_raw = raw.get("effective_date", "")
        exported_at = raw.get("exported_at", "")

        if doc_id not in ALLOWED_DOC_IDS:
            quarantine.append({**raw, "reason": "unknown_doc_id"})
            continue

        eff_norm, eff_err = _normalize_effective_date(eff_raw)
        if eff_err == "empty_effective_date":
            quarantine.append({**raw, "reason": "missing_effective_date"})
            continue
        if eff_err == "invalid_effective_date_format":
            quarantine.append({**raw, "reason": eff_err, "effective_date_raw": eff_raw})
            continue

        if doc_id == "hr_leave_policy" and eff_norm < "2026-01-01":
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_hr_policy_effective_date",
                    "effective_date_normalized": eff_norm,
                }
            )
            continue

        if not text:
            quarantine.append({**raw, "reason": "missing_chunk_text"})
            continue

        if doc_id == "hr_leave_policy" and _has_stale_hr_annual_leave(text):
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_hr_policy_text_marker",
                    "effective_date_normalized": eff_norm,
                }
            )
            continue

        if _has_low_confidence_marker(text):
            quarantine.append(
                {
                    **raw,
                    "reason": "low_confidence_chunk_text",
                    "effective_date_normalized": eff_norm,
                }
            )
            continue

        if _is_non_p1_sla_chunk(doc_id, text):
            quarantine.append(
                {
                    **raw,
                    "reason": "non_p1_sla_chunk",
                    "effective_date_normalized": eff_norm,
                }
            )
            continue

        key = _norm_text(text)
        if key in seen_text:
            quarantine.append({**raw, "reason": "duplicate_chunk_text"})
            continue
        seen_text.add(key)

        fixed_text = text
        if apply_refund_window_fix and doc_id == "policy_refund_v4":
            if "14 ngày làm việc" in fixed_text:
                fixed_text = fixed_text.replace(
                    "14 ngày làm việc",
                    "7 ngày làm việc",
                )
                fixed_text += " [cleaned: stale_refund_window]"

        fixed_text, collapsed_repeated_words = _collapse_repeated_words(fixed_text)
        if collapsed_repeated_words:
            fixed_text += " [cleaned: repeated_word_stutter]"

        fixed_text, clarified_p1_escalation = _clarify_p1_escalation_text(doc_id, fixed_text)
        if clarified_p1_escalation:
            fixed_text += " [cleaned: clarified_p1_escalation]"

        seq += 1
        cleaned.append(
            {
                "chunk_id": _stable_chunk_id(doc_id, fixed_text, seq),
                "doc_id": doc_id,
                "chunk_text": fixed_text,
                "effective_date": eff_norm,
                "exported_at": exported_at or "",
            }
        )

    return cleaned, quarantine


def write_cleaned_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at\n", encoding="utf-8")
        return
    fieldnames = ["chunk_id", "doc_id", "chunk_text", "effective_date", "exported_at"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_quarantine_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at,reason\n", encoding="utf-8")
        return
    keys: List[str] = []
    seen_k: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen_k:
                seen_k.add(k)
                keys.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore", restval="")
        w.writeheader()
        for r in rows:
            w.writerow(r)

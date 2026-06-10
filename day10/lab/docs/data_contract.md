# Data contract — Lab Day 10

**Họ và tên:** Nguyễn Quang Minh - 2A202600816  
**Run kiểm chứng:** `clean-final`  
**Manifest:** `artifacts/manifests/manifest_clean-final.json`  
**Grading:** `artifacts/eval/grading_run.jsonl` — 10/10 câu pass

Contract này mô tả dữ liệu được phép đi từ raw export vào cleaned CSV và Chroma collection `day10_kb`. Pipeline chỉ publish các chunk đã qua cleaning và expectation suite; record lỗi được ghi vào quarantine để audit.

---

## 1. Nguồn dữ liệu (source map)

| Nguồn | Phương thức ingest | Failure mode chính | Metric / alert |
|-------|-------------------|-------------------|----------------|
| `policy_refund_v4` | Batch CSV export từ `data/raw/policy_export_dirty.csv`; canonical text ở `data/docs/policy_refund_v4.txt` | Stale refund window `14 ngày` thay vì `7 ngày`; duplicate chunk; missing date/text | `refund_no_stale_14d_window` halt; `hits_forbidden=false` cho câu refund |
| `sla_p1_2026` | Batch CSV export; canonical text ở `data/docs/sla_p1_2026.txt` | P2/P3/P4 chunk lẫn vào corpus P1; low-confidence marker; missing date | `non_p1_sla_chunk` quarantine; grading `gq_d10_04`-`gq_d10_06` pass |
| `it_helpdesk_faq` | Batch CSV export; canonical text ở `data/docs/it_helpdesk_faq.txt` | Missing text; duplicate FAQ; wrong/unknown `doc_id` từ export lỗi | `chunk_min_length_8` warn; `unknown_doc_id` quarantine |
| `hr_leave_policy` | Batch CSV export; canonical text ở `data/docs/hr_leave_policy.txt` | HR 2025 stale version `10 ngày phép năm`; effective date cũ hoặc thiếu | `hr_leave_no_stale_10d_annual` halt; `stale_hr_policy_text_marker` quarantine |
| `access_control_sop` | Batch CSV export; canonical text ở `data/docs/access_control_sop.txt` | Source hợp lệ nhưng từng bị thiếu trong allowlist; missing text; duplicate Level 4 chunk | `required_doc_ids_present` halt; grading `gq_d10_10` top-1 là `access_control_sop` |

Allowlist publish hiện tại:

```text
policy_refund_v4
sla_p1_2026
it_helpdesk_faq
hr_leave_policy
access_control_sop
```

Run cuối:

| Chỉ số | Giá trị |
|--------|---------|
| `raw_records` | 247 |
| `cleaned_records` | 35 |
| `quarantine_records` | 212 |
| `latest_exported_at` | `2026-04-11T00:00:00` |
| `freshness_check` | `FAIL` với SLA 24h, do snapshot mẫu cũ |

---

## 2. Schema cleaned

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| `chunk_id` | string | Có | ID ổn định sau clean, tạo bằng hash từ `doc_id`, `chunk_text` đã fix và sequence; dùng làm khóa upsert Chroma |
| `doc_id` | enum string | Có | Phải thuộc allowlist 5 source hợp lệ ở trên |
| `chunk_text` | string | Có | Nội dung sau cleaning; tối thiểu 8 ký tự; không chứa marker stale/low-confidence |
| `effective_date` | date `YYYY-MM-DD` | Có | Được chuẩn hóa từ ISO hoặc `DD/MM/YYYY`; không parse được thì quarantine |
| `exported_at` | datetime ISO-like | Có | Thời điểm record được export; dùng tính `latest_exported_at` trong manifest |

Expectation bắt buộc trên cleaned data:

| Expectation | Severity | Ý nghĩa |
|-------------|----------|---------|
| `min_one_row` | halt | Không publish collection rỗng |
| `no_empty_doc_id` | halt | Không cho record thiếu source |
| `refund_no_stale_14d_window` | halt | Không để refund stale `14 ngày` lọt vào index |
| `effective_date_iso_yyyy_mm_dd` | halt | Sau clean, mọi `effective_date` phải là ISO date |
| `hr_leave_no_stale_10d_annual` | halt | Không để HR 2025 `10 ngày phép năm` lọt vào index |
| `required_doc_ids_present` | halt | Đủ 5 source cần cho grading, gồm `access_control_sop` |
| `unique_chunk_id` | halt | Đảm bảo idempotent upsert vào Chroma |
| `no_low_confidence_markers` | halt | Không publish chunk có `Nội dung không rõ ràng` hoặc `!!!` |
| `chunk_min_length_8` | warn | Cảnh báo chunk quá ngắn |
| `no_repeated_word_stutter` | warn | Cảnh báo text còn lặp từ liên tiếp |

---

## 3. Quy tắc quarantine vs drop

Pipeline không xóa im lặng record lỗi. Mọi record bị loại khỏi cleaned CSV được ghi vào:

```text
artifacts/quarantine/quarantine_clean-final.csv
```

Người approve merge lại: owner dữ liệu tương ứng trong source map. Trong lab này, Nguyễn Quang Minh chịu trách nhiệm kiểm tra quarantine và cập nhật cleaning rule/contract.

| Reason | Hành động | Ai xử lý | Ghi chú |
|--------|-----------|----------|---------|
| `unknown_doc_id` | Quarantine | Data/source owner | Không publish source ngoài allowlist như `invalid_doc_*`, `legacy_*`, `security_policy`, `data_privacy_guideline` |
| `missing_effective_date` | Quarantine | Source owner | Không đủ metadata versioning |
| `invalid_effective_date_format` | Quarantine | Source owner | Chỉ chấp nhận ISO hoặc parse được `DD/MM/YYYY` |
| `stale_hr_policy_effective_date` | Quarantine | HR owner | HR chunk trước `2026-01-01` bị coi là bản cũ |
| `stale_hr_policy_text_marker` | Quarantine | HR owner | Dù date mới, text chứa `10 ngày phép năm` vẫn là stale HR 2025 |
| `missing_chunk_text` | Quarantine | Source owner | Không publish chunk rỗng |
| `low_confidence_chunk_text` | Quarantine | Data quality owner | Chunk có marker `Nội dung không rõ ràng` hoặc `!!!` |
| `duplicate_chunk_text` | Quarantine | Pipeline owner | Giữ bản đầu tiên để tránh vector trùng |
| `non_p1_sla_chunk` | Quarantine | IT/SLA owner | Loại chunk P2/P3/P4 lẫn vào corpus `sla_p1_2026` |

Các transform được phép sửa trực tiếp khi ý nghĩa nghiệp vụ rõ ràng:

| Transform | Cách xử lý | Lý do |
|-----------|------------|-------|
| Refund stale `14 ngày làm việc` | Replace thành `7 ngày làm việc` và thêm marker `[cleaned: stale_refund_window]` | Canonical source `policy_refund_v4` quy định 7 ngày |
| Repeated word stutter | Collapse lặp từ như `làm việc làm việc` | Lỗi OCR/export, không đổi nghĩa |
| P1 escalation wording | Thêm câu làm rõ `Nếu không có phản hồi với ticket P1 sau 10 phút...` | Giúp retriever không nhầm P1 với P2 escalation |

---

## 4. Phiên bản & canonical

Canonical source of truth:

| `doc_id` | File canonical | Version / cutoff |
|----------|----------------|------------------|
| `policy_refund_v4` | `data/docs/policy_refund_v4.txt` | Version v4; refund window hiện hành là `7 ngày làm việc` |
| `sla_p1_2026` | `data/docs/sla_p1_2026.txt` | Effective date `2026-01-15`; tập trung P1 SLA |
| `it_helpdesk_faq` | `data/docs/it_helpdesk_faq.txt` | Internal FAQ hiện hành |
| `hr_leave_policy` | `data/docs/hr_leave_policy.txt` | HR 2026; minimum effective date `2026-01-01`; dưới 3 năm là `12 ngày phép năm` |
| `access_control_sop` | `data/docs/access_control_sop.txt` | Access SOP hiện hành; Level 4 cần IT Manager/CISO |

Versioning rule:

- Raw rows có `doc_id` không nằm trong allowlist không được publish.
- HR records có `effective_date < 2026-01-01` bị quarantine.
- HR records chứa marker text `10 ngày phép năm` bị quarantine kể cả khi `effective_date` là 2026.
- Refund policy không được để `14 ngày làm việc` xuất hiện trong index sau clean.
- SLA P1 collection không giữ chunk mở đầu bằng `Ticket P2:`, `Ticket P3:`, hoặc `Ticket P4:`.

Freshness:

- Freshness đo tại publish boundary bằng manifest.
- SLA mặc định: 24 giờ.
- Run `clean-final` có `freshness_check=FAIL` vì snapshot mẫu có `latest_exported_at=2026-04-11T00:00:00`, cũ hơn thời điểm chạy ngày 2026-06-10. Đây là expected risk của dữ liệu lab, không phải lỗi expectation.

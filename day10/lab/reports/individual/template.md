# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Nguyễn Quang Minh - 2A202600816  
**Vai trò:**  
**Ngày nộp:** 2026-06-10  

---

## 1. Tôi phụ trách phần nào? (80–120 từ)

**File / module:**

- `transform/cleaning_rules.py`
- `quality/expectations.py`
- `docs/pipeline_architecture.md`
- `docs/data_contract.md`

**Kết nối với thành viên khác:**


**Bằng chứng (commit / comment trong code):**

Run kiểm chứng: `clean-final`. Artifact chính: `artifacts/logs/run_clean-final.log`, `artifacts/manifests/manifest_clean-final.json`, `artifacts/eval/grading_run.jsonl`.

---

## 2. Một quyết định kỹ thuật (100–150 từ)

> VD: chọn halt vs warn, chiến lược idempotency, cách đo freshness, format quarantine.

Quyết định kỹ thuật quan trọng là phân biệt lỗi nào phải `halt` và lỗi nào chỉ `warn`. Các lỗi có thể làm agent trả lời sai nghiệp vụ được đặt là `halt`, ví dụ `refund_no_stale_14d_window`, `hr_leave_no_stale_10d_annual`, `required_doc_ids_present`, `unique_chunk_id`, và `no_low_confidence_markers`. Nếu những lỗi này lọt qua, Chroma có thể chứa policy cũ hoặc thiếu document cần cho grading. Ngược lại, các lỗi nhẹ như chunk quá ngắn hoặc repeated-word stutter được đặt `warn`, vì pipeline có thể vẫn publish nếu nội dung chính không sai. Tôi cũng giữ quarantine CSV thay vì drop im lặng, để có audit trail cho từng reason như `stale_hr_policy_text_marker`, `low_confidence_chunk_text`, và `non_p1_sla_chunk`.

---

## 3. Một lỗi hoặc anomaly đã xử lý (100–150 từ)

> Mô tả triệu chứng → metric/check nào phát hiện → fix.

Anomaly rõ nhất là câu grading `gq_d10_10` cần `access_control_sop`, nhưng baseline allowlist chưa cho source này đi qua. Khi chạy pipeline ban đầu, các dòng `access_control_sop` bị đưa vào quarantine với reason `unknown_doc_id`, làm retrieval không thể trả lời câu Level 4 Admin Access. Tôi sửa `ALLOWED_DOC_IDS` để thêm `access_control_sop`, rồi bổ sung expectation `required_doc_ids_present` để bắt lỗi tương tự trong tương lai. Một anomaly khác là HR stale: dù một số dòng có `effective_date` năm 2026, text vẫn chứa `10 ngày phép năm (bản HR 2025)`. Tôi thêm rule `stale_hr_policy_text_marker` để quarantine theo nội dung, không chỉ dựa vào ngày.

---

## 4. Bằng chứng trước / sau (80–120 từ)

> Dán ngắn 2 dòng từ `before_after_eval.csv` hoặc tương đương; ghi rõ `run_id`.

Trước khi hoàn thiện rule, pipeline từng halt ở expectation HR:

```text
expectation[hr_leave_no_stale_10d_annual] FAIL (halt) :: violations=2
PIPELINE_HALT
```

Sau khi sửa và chạy `run_id=clean-final`, log cuối cho thấy pipeline pass:

```text
raw_records=247
cleaned_records=35
quarantine_records=212
embed_upsert count=35 collection=day10_kb
PIPELINE_OK
```

Kết quả grading chính thức trong `artifacts/eval/grading_run.jsonl` đạt 10/10: `gq_d10_01` đến `gq_d10_10` đều `contains_expected=true`, `hits_forbidden=false`, và top-1 đúng document mong đợi.

---

## 5. Cải tiến tiếp theo (40–80 từ)

> Nếu có thêm 2 giờ — một việc cụ thể (không chung chung).

Nếu có thêm 2 giờ, tôi sẽ chuyển các marker đang hard-code trong `cleaning_rules.py` sang config hoặc `contracts/data_contract.yaml`, ví dụ cutoff HR `2026-01-01`, marker `10 ngày phép năm`, và rule loại chunk `Ticket P2`. Việc này giúp pipeline dễ bảo trì hơn khi policy đổi version hoặc thêm source mới.

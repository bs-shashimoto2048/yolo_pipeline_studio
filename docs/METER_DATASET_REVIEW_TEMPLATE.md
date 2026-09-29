# Meter Dataset Review Templates

固定カメラ・OCR/数字認識・物体検出案件で、レビュー・比較・意思決定を残すためのテンプレート集。

## 1. Raw inventory table

| Project | Source / Session | Raw count | Annotated count | Eligible primary | Excluded / Unselected | Notes |
|---|---|---:|---:|---:|---:|---|
| | | | | | | |

## 2. Annotation audit table

| Stem | Expected reading | bbox count | Class/coord valid | Visual state | Review status | Action | Reviewer note |
|---|---|---:|---|---|---|---|---|
| | | | | | confirmed_current / confirmed_error / unresolved / rescue / reject | | |

## 3. Exclusion reason table

| Category | Count | Definition | Representative examples | Reversible? |
|---|---:|---|---|---|
| ambiguous | | | | |
| transition / partial | | | | |
| duplicate | | | | |
| leakage-adjacent | | | | |
| unresolved GT | | | | |

## 4. Split integrity table

| Check | Train-Val | Train-Test | Val-Test | Result |
|---|---:|---:|---:|---|
| stem overlap | | | | |
| cluster_id overlap | | | | |
| reading_group_id overlap | | | | |
| reading_gt overlap | | | | |

Manifest:
- path:
- hash:
- fixed_at:
- Test consumed status:

## 5. Model candidate comparison

| Metric | Baseline | Candidate | Condition / conf | Interpretation |
|---|---:|---:|---|---|
| Reading Exact | | | | |
| 7-detect | | | | |
| Character accuracy | | | | |
| Missing | | | | |
| Extra | | | | |
| Wrong class | | | | |
| mAP50 | | | | |
| mAP50-95 | | | | |

Decision:
- Adopt / Retain baseline / Continue investigation

## 6. Failure analysis log

| Stem / Case | Symptom | Failure category | GT verified? | Preprocess verified? | Runtime config verified? | Root cause | Next action |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

## 7. Hard-example review table

| Candidate | Atomic unit | Visual GT | Primary / Ambiguous | Train / Hard-Val / Exclude | Reason | Notes |
|---|---|---|---|---|---|---|
| | | | | | | |

Summary:
- candidates:
- atomic units:
- primary:
- ambiguous:
- Train:
- Hard-Val:

## 8. Live acceptance sheet

Environment:
- Date:
- Camera/source:
- Resolution:
- Model:
- Weight:
- Confidence:
- Preprocess:
- ROI:

| Check | Result | Evidence / note |
|---|---|---|
| clean live input confirmed | | |
| selected model resolved | | |
| confidence resolved | | |
| preprocessing resolved | | |
| 7/7 detection | | |
| reading correct / expected | | |
| changing digit tracked | | |
| no known confusion recurrence | | |

Acceptance:
- Accepted / Rejected / Conditional

## 9. Production provenance table

| Item | Value |
|---|---|
| Project | |
| Train job | |
| Weight type | |
| Weight SHA256 | |
| Confidence | |
| Dataset manifest | |
| Manifest SHA256 | |
| ROI | |
| Processing order | |
| Runtime source of truth | |
| Restore procedure | |
| Rollback procedure | |
| Git commit | |

## 10. Decision record

### Decision
What was chosen?

### Evidence
What measured or observed facts support the decision?

### Rejected alternatives
What was considered and not adopted?

### Residual risk
What remains unverified or environment-dependent?

### Revisit trigger
What future event should cause this decision to be reviewed?

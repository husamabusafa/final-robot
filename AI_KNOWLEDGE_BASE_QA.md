# Rafed AI Advisor — Knowledge Base of Verified Q&A (AI_KNOWLEDGE_BASE_QA)

**Purpose.** This file is grounding context for the **Rafed AI Advisor** LLM. It contains business questions (in Arabic, the language users ask in) with **verified answers computed from the live warehouse on 2026-08-23**, the exact SQL that produced each answer, a short English explanation, and the business use case. The AI should:

1. Use these as **verified reference answers** — quote these numbers directly when a matching question is asked, and state the "as of" date.
2. Use the SQL blocks as **patterns** for answering similar/follow-up questions against the warehouse.
3. Respect the conventions and caveats documented here and in `src/docs/WAREHOUSE_SCHEMA.md` (the authoritative schema dictionary).

**Hard rule for the AI:** never invent numbers. If a question is not covered here or answerable with a straightforward adaptation of these SQL patterns, say so and explain which table/feed is missing.

---

## Data freshness (queried live on 2026-08-23)

- **Latest ETL run:** `db43535c` — group `hourly`, trigger `cron`, started 2026-08-23 10:00:00 UTC, finished 10:00:12 UTC, status `succeeded`. The hourly schedule is healthy (09:00 and 08:00 runs also succeeded).
- **Max dates per key fact (live query):**

| Table | Freshness | Value |
|---|---|---|
| `fact_daily_snapshot` | max `snapshot_date` | **2026-08-12** (row created 2026-08-13) — ~11 days stale |
| `ins_workorders` | max `inspection_date` | 2026-08-26 (includes scheduled future visits); latest scored visits 2026-08-22 |
| `fact_ins_accident` | max `accident_date` | 2025-12-03 (no 2026 accidents loaded) |
| `fact_safety_check` | max `check_date` | 2026-08-22 |
| `fact_safety_accident` | max `report_date` | 2026-07-06 |
| `dim_weather_daily` | max `weather_date` | 2026-08-12 (only 8 days loaded) |
| `fact_fleet_daily` / `fact_driver_daily` / `fact_seat_allocation_daily` / `fact_vehicle_defect_daily` | max `sub_day` | 2026-08-12 |
| `fact_vehicle_kpi` / `fact_contract_readiness` | max `as_of_date` | 2026-08-12 |
| `fact_school_visit` | max `event_time` | 2026-05-17 (feed stopped) |
| `dim_calendar` | range | 2025-08-01 → 2027-07-29 (two academic years) |

**Read this carefully:** dimensions (students, vehicles, drivers, contracts, schools) are fresh as of today's hourly run. Several *facts* are stale or disabled — see the caveats section. Answers below state their own "as of" date.

---

## How to answer similar questions (conventions)

Full details: `src/docs/WAREHOUSE_SCHEMA.md`. Top rules:

1. **Query tables unqualified** (the managed `search_path` resolves to the live `v_current` schema). Never hardcode `v_current.` / `v_next.`.
2. **`dim_contract` PK is `(contract_id, academic_year)`** — always filter `academic_year='current'` (82 contracts) unless doing next-year planning (`'nyear'`, 22 contracts).
3. **`fact_assignment.vehicle_id` is NULL for 47.25% of students** — always LEFT JOIN `dim_vehicle` and report the uncovered share.
4. **Arabic label columns** for user-facing output: `gender_label_ar`, `sector_name_ar`, `status_label_ar`, `label_ar` (via `dim_domain`), etc.
5. **PII is hashed** (`student_name_hash`, `student_nid_hash`, `driver_nid_hash`, `card_number_hash`). Never try to recover plain PII. `fact_safety_check`/`fact_safety_accident` carry raw driver `nid_number` — never echo it.
6. **Gender:** the smallint `gender` code column on `fact_assignment` is currently **all NULL** — use `gender_label_ar` (1=ذكر / 2=أنثى convention applies where codes exist).
7. **School joins:** `fact_assignment.school_id` almost never matches `dim_school.school_id` (174 of 748,909 rows). Join via `fact_assignment.school_code → dim_noor_school.school_code` (97.4% match) for region/official school attributes.
8. **Region coverage:** the warehouse is **nationwide (all 13 Saudi regions)**, not only Al-Baha. Al-Baha is one of the smaller regions (349 schools, 12,532 students). `dim_contract.sector_name_ar`/`administration_name_ar` are NULL — get region from `dim_noor_school.region_name_ar` or `dim_school.sector_name_ar`.
9. **Money:** `dim_contract.amount` is 0 for every contract — contract-value questions cannot be answered today.
10. **Text dates** on `dim_vehicle` expiry columns: all currently parse as `YYYY-MM-DD`; still cast defensively with a regex guard (`col ~ '^\d{4}-\d{2}-\d{2}$'`) before `to_date(col,'YYYY-MM-DD')`.
11. Use `dim_calendar` for school-day/holiday logic (Saudi workweek Sun–Thu).

---

# Section A — Overall Daily Snapshot (headline KPIs)

### Q1. ما هي مؤشرات الأداء الرئيسية الإجمالية للنظام اليوم؟
**Answer (as of snapshot 2026-08-12, latest available):** 748,909 طالب (395,076 لديهم باص / 353,833 بدون باص) · 23,977 حافلة (17,935 بها GPS) · 26,545 سائق · 9,038 مرافق · 11,741 مدرسة · 104 عقود (82 للعام الحالي + 22 للعام القادم) · انتهاء قريب ≤30 يوم: رخص 1,288 / فحص دوري 3,391 / تأمين 6,344.
**SQL:**
```sql
SELECT * FROM fact_daily_snapshot
ORDER BY snapshot_date DESC LIMIT 1;
```
**Explanation:** One row per day summarizing the whole warehouse — the fastest "status today" answer. Note the latest snapshot is 2026-08-12 (~11 days old at query time); the nightly job that builds it appears paused. Counts match live dimension counts queried on 2026-08-23, so the numbers are still representative.
**Use case:** Executive morning briefing; the first thing a regional manager asks.

### Q2. ما هو معدل نجاح/رسوب الفحوصات حسب آخر لقطة يومية؟
**Answer (as of 2026-08-12):** معدل النجاح **82.05%**، معدل الرسوب **5.77%**، وعدد زيارات التفتيش المسجلة 1,682.
**SQL:**
```sql
SELECT snapshot_date, inspection_pass_rate, inspection_fail_rate, inspection_visits_today
FROM fact_daily_snapshot ORDER BY snapshot_date DESC LIMIT 1;
```
**Explanation:** Pass/fail rates as computed by the snapshot job over inspection results. Cross-check with live data (Section G): average bus-level `compliance_pct` is 79.2% across 19,186 bus inspections.
**Use case:** Quality/compliance KPI on the main dashboard; tracking inspection program effectiveness.

### Q3. ما هو النطاق الجغرافي الفعلي لمستودع البيانات؟
**Answer (as of 2026-08-23):** المستودع يغطي **كل مناطق المملكة الـ13** وليس الباحة فقط: مكة المكرمة (1,710 مدرسة)، الشرقية (1,663)، الرياض (1,474)، عسير (1,422)، جازان (1,233)، القصيم (1,044)، المدينة (964)، نجران (458)، حائل (454)، تبوك (434)، **الباحة (349)**، الجوف (328)، الحدود الشمالية (208).
**SQL:**
```sql
SELECT sector_name_ar, COUNT(*) AS schools
FROM dim_school GROUP BY sector_name_ar ORDER BY schools DESC;
```
**Explanation:** Older docs describe this as an Al-Baha-only warehouse — that is stale. `dim_region` lists all 13 regions (ids 20–32) and school/student volumes confirm nationwide coverage.
**Use case:** Framing any "total" answer — always clarify whether the user wants nationwide or a specific region.

---

# Section B — Students & Assignments

### Q4. كم عدد الطلاب الإجمالي في النظام؟
**Answer (as of 2026-08-23):** **748,909 طالب** (سجل فريد لكل طالب؛ كلهم في العام الدراسي `current`).
**SQL:**
```sql
SELECT COUNT(*) AS total, COUNT(DISTINCT academic_year) AS years
FROM fact_assignment;
```
**Explanation:** `fact_assignment` is the flagship grain: one row per student per academic year. Currently only `current` exists (no `nyear` student rows yet).
**Use case:** The most basic sizing question; denominator for all coverage percentages.

### Q5. ما هو توزيع الطلاب حسب الجنس؟
**Answer (as of 2026-08-23):** أنثى **481,025 (64.2%)** · ذكر **247,960 (33.1%)** · غير محدد **19,924 (2.7%)**.
**SQL:**
```sql
SELECT gender_label_ar, COUNT(*) AS cnt,
       ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (), 2) AS pct
FROM fact_assignment
GROUP BY gender_label_ar ORDER BY cnt DESC;
```
**Explanation:** Use `gender_label_ar` — the smallint `gender` code column is NULL on every row today (ETL gap). Female students outnumber males ~1.9:1 in the transported population.
**Use case:** Planning segregated fleets (Saudi transport runs separate boys'/girls' routes); capacity planning per gender.

### Q6. ما هو توزيع الطلاب حسب المرحلة الدراسية؟
**Answer (as of 2026-08-23):** ابتدائية **361,287 (48.2%)** · متوسطة **217,883 (29.1%)** · ثانوية **169,739 (22.7%)**.
**SQL:**
```sql
SELECT stage, COUNT(*) AS cnt
FROM fact_assignment GROUP BY stage ORDER BY cnt DESC;
```
**Explanation:** `stage` holds the Arabic education-level label. Elementary students are roughly half the transported population.
**Use case:** Route timing (different bell times per stage); age-appropriate safety measures.

### Q7. ما هو توزيع الطلاب حسب فئة النقل (rafed_category)؟
**Answer (as of 2026-08-23):** عام **652,004** · وعرة **38,599** · نائية **26,647** · غير حركي **23,327** · مضموم **7,630** · حركي **700** · غير مصنف 2.
**SQL:**
```sql
SELECT rafed_category, COUNT(*) AS cnt
FROM fact_assignment GROUP BY rafed_category ORDER BY cnt DESC;
```
**Explanation:** Transport category derived from ODS `transport_type_id`: عام=general, وعرة=rough terrain, نائية=remote, غير حركي=special/non-kinetic, مضموم=merged route, حركي=kinetic. 87% are general-education.
**Use case:** Special-category students (وعرة/نائية/غير حركي) drive vehicle-type requirements and contract pricing.

### Q8. كم نسبة الطلاب المخصص لهم باص فعلياً؟
**Answer (as of 2026-08-23):** **395,076 طالب (52.75%)** لديهم `vehicle_id` · **353,833 (47.25%)** بدون باص مخصص.
**SQL:**
```sql
SELECT COUNT(vehicle_id) AS with_vehicle,
       COUNT(*) FILTER (WHERE vehicle_id IS NULL) AS without_vehicle,
       ROUND(100.0*COUNT(vehicle_id)/COUNT(*), 2) AS pct_covered
FROM fact_assignment;
```
**Explanation:** Vehicle linkage exists only for students with an active ODS `student_bus_assignment`. This is the single most important coverage KPI — nearly half of registered students have no assigned bus in the data.
**Use case:** Assignment-gap program tracking; where to focus operator onboarding.

### Q9. ما هي نسبة تغطية الباصات حسب المرحلة الدراسية؟
**Answer (as of 2026-08-23):** ابتدائية **57.0%** (205,937/361,287) · متوسطة **53.3%** (116,083/217,883) · ثانوية **43.0%** (73,056/169,739).
**SQL:**
```sql
SELECT stage, COUNT(*) AS students, COUNT(vehicle_id) AS with_vehicle,
       ROUND(100.0*COUNT(vehicle_id)/COUNT(*), 1) AS pct
FROM fact_assignment GROUP BY stage ORDER BY students DESC;
```
**Explanation:** Coverage drops with age — high-school students are least covered (many arrange own transport).
**Use case:** Prioritizing assignment drives by stage; aligns with parental demand patterns.

### Q10. ما هي نسبة تغطية الباصات حسب فئة النقل؟
**Answer (as of 2026-08-23):** عام 54.7% · نائية 50.4% · مضموم 42.6% · غير حركي 38.3% · وعرة 33.2% · حركي 27.6%.
**SQL:**
```sql
SELECT rafed_category, COUNT(*) AS students, COUNT(vehicle_id) AS with_vehicle,
       ROUND(100.0*COUNT(vehicle_id)/COUNT(*), 1) AS pct_covered
FROM fact_assignment GROUP BY rafed_category ORDER BY students DESC;
```
**Explanation:** Notable: special categories (وعرة rough-terrain 33.2%, غير حركي 38.3%) are *worse* covered than general — operationally backwards, since these students need transport most.
**Use case:** Red flag for the Ministry: vulnerable categories under-served; informs targeted contract enforcement.

### Q11. ما هي أكبر 10 عقود من حيث عدد الطلاب؟
**Answer (as of 2026-08-23):** 02-2019-04: **153,144** · 02-2019-06: 72,667 · TTC-AG-00189: 66,746 · 02-2019-02: 58,457 · 02-2019-13: 49,823 · 10-2019-02: 39,847 · ttc-ag-00167: 32,093 · TTC-AG-00224: 30,780 · 02-2019-18: 29,732 · 02-2019-03: 25,707.
**SQL:**
```sql
SELECT contract_number, COUNT(*) AS students
FROM fact_assignment
GROUP BY contract_number ORDER BY students DESC LIMIT 10;
```
**Explanation:** Only 26 distinct contract_ids appear in `fact_assignment` (out of 82 current contracts) — many current contracts have no student rows loaded. Contract 02-2019-04 alone carries 20% of all students.
**Use case:** Concentration-risk analysis; which contracts matter most operationally.

### Q12. ما هو توزيع الطلاب حسب المنطقة؟
**Answer (as of 2026-08-23):** الشرقية **153,144** · مكة **88,189** · عسير **84,478** · جازان **75,864** · القصيم **70,777** · الرياض **66,747** · نجران **49,823** · المدينة **45,440** · الجوف **23,166** · حائل **23,019** · تبوك **22,782** · الحدود الشمالية **13,024** · الباحة **12,532** (728,985 من 748,909 تم ربطهم بمدرسة Noor).
**SQL:**
```sql
SELECT n.region_name_ar, COUNT(*) AS students
FROM fact_assignment a
JOIN dim_noor_school n ON n.school_code = a.school_code
GROUP BY n.region_name_ar ORDER BY students DESC;
```
**Explanation:** Region comes from the Noor school master (`school_code` join, 97.4% match). Do NOT use `dim_contract.sector_name_ar` — it is NULL for all current contracts.
**Use case:** Regional workload distribution; where the transported-student volume actually sits.

### Q13. كم عدد طلاب منطقة الباحة وكم منهم له باص؟
**Answer (as of 2026-08-23):** **12,532 طالب** في الباحة (أنثى 8,015 / ذكر 4,517) — لكن **24 فقط** لديهم `vehicle_id` (0.19% تغطية).
**SQL:**
```sql
SELECT a.gender_label_ar, COUNT(*) AS students, COUNT(a.vehicle_id) AS with_vehicle
FROM fact_assignment a
JOIN dim_noor_school n ON n.school_code = a.school_code
WHERE n.region_name_ar = 'الباحة'
GROUP BY a.gender_label_ar;
```
**Explanation:** Al-Baha's bus-assignment linkage is essentially absent in the warehouse even though students are registered — a regional data-integration gap, not necessarily an operational one.
**Use case:** Caution flag: never quote Al-Baha fleet-coverage KPIs from `fact_assignment` without this caveat.

### Q14. ما هو متوسط عدد الطلاب لكل باص؟
**Answer (as of 2026-08-23):** المتوسط **30.6 طالب/باص** (عبر 12,921 باصاً مرتبطاً بطلاب) · الأقصى **301 طالب** لباص واحد.
**SQL:**
```sql
SELECT ROUND(AVG(riders),1) AS avg_riders, MAX(riders) AS max_riders
FROM (SELECT vehicle_id, COUNT(*) AS riders
      FROM fact_assignment WHERE vehicle_id IS NOT NULL
      GROUP BY vehicle_id) t;
```
**Explanation:** Riders per assigned bus vs avg operational capacity 38.9 → ~79% nominal loading. The 301-rider outlier indicates either multi-round service or a data error worth auditing.
**Use case:** Load balancing; spotting overloaded or ghost-linked buses.

### Q15. كم مدرسة وعقداً وباصاً يظهر فعلياً في بيانات الطلاب؟
**Answer (as of 2026-08-23):** **13,784 كود مدرسة** · **26 عقداً** · **12,921 باصاً** ممثلة في `fact_assignment`.
**SQL:**
```sql
SELECT COUNT(DISTINCT school_code) AS school_codes,
       COUNT(DISTINCT contract_id) AS contracts,
       COUNT(DISTINCT vehicle_id) AS vehicles
FROM fact_assignment;
```
**Explanation:** Student rows reference more school codes (13,784) than exist in `dim_noor_school` (11,739) — some historical/unmatched codes. Only 26 of 82 current contracts have students.
**Use case:** Data-completeness audits; explains why contract-level student sums differ across tables.

### Q16. ما هو متوسط/أقصى عدد الطلاب المخطط لكل عقد؟
**Answer (as of 2026-08-23):** متوسط **14,556 طالب/عقد** · أدنى 0 · أقصى **151,666** · 10 عقود بدون قيمة `students_total`.
**SQL:**
```sql
SELECT ROUND(AVG(students_total),0) AS avg_students, MIN(students_total) AS min_students,
       MAX(students_total) AS max_students,
       COUNT(*) FILTER (WHERE students_total IS NULL) AS null_students
FROM dim_contract WHERE academic_year='current';
```
**Explanation:** From the contract dimension's plan figure (not the assignment fact). Sum across contracts = 1,048,052 — higher than the 748,909 assignment rows, since contract plans include students not yet in the assignment pipeline.
**Use case:** Contract sizing; spotting mega-contracts and empty shells.

### Q17. ما مدى اكتمال الحقول الاختيارية في بيانات الطلاب (الضمان/السائق/الإحداثيات)؟
**Answer (as of 2026-08-23):** `rafed_tier` (الضمان الاجتماعي): **0% معبأ** · `driver_id`: **0% معبأ** · `home_x/home_y/distance_km`: **0% معبأ**.
**SQL:**
```sql
SELECT ROUND(100.0*COUNT(rafed_tier)/COUNT(*),2) AS pct_tier,
       ROUND(100.0*COUNT(driver_id)/COUNT(*),2) AS pct_driver,
       ROUND(100.0*COUNT(home_x)/COUNT(*),2) AS pct_home_x
FROM fact_assignment;
```
**Explanation:** These columns exist but are not loaded from source. Do NOT answer social-security-tier, student-driver-link, or home-distance questions — the data is not there.
**Use case:** Setting expectations; refusing gracefully with a reason instead of hallucinating.

---

# Section C — Vehicles & Fleet

### Q18. كم عدد الحافلات الإجمالي في الأسطول؟
**Answer (as of 2026-08-23):** **23,977 حافلة**، كلها مرتبطة بعقد (`contract_id` غير فارغ 100%).
**SQL:**
```sql
SELECT COUNT(*) AS total, COUNT(contract_id) AS with_contract FROM dim_vehicle;
```
**Explanation:** One row per bus, keyed by ODS serial number. Matches the fleet_daily rollup (23,977 on 2026-08-12).
**Use case:** Basic fleet sizing; denominator for all fleet percentages.

### Q19. كم عدد الحافلات المزودة بأجهزة GPS؟
**Answer (as of 2026-08-23):** **17,935 حافلة (74.8%)** بها GPS حسب `dim_vehicle.has_gps` (17,603 حسب رول-أب `fact_fleet_daily` بتاريخ 2026-08-12). `is_gps_connected` = صفر لكل الحافلات.
**SQL:**
```sql
SELECT COUNT(*) FILTER (WHERE has_gps) AS with_gps,
       COUNT(*) FILTER (WHERE is_gps_connected) AS gps_connected,
       COUNT(*) AS total FROM dim_vehicle;
```
**Explanation:** `has_gps` (device installed) is reliable; `is_gps_connected` (live link) is never set — treat live-connectivity questions as unanswerable from this column; use `fact_school_visit` device activity instead (Section K).
**Use case:** AVL coverage audits; GPS procurement gaps (6,042 buses without GPS).

### Q20. كم حافلة لديها سائق مرتبط؟
**Answer (as of 2026-08-23):** **23,977 (100%)** حسب `dim_vehicle.has_driver` — لكن `fact_fleet_daily` يسجل **0** في `vehicles_with_driver`، أي أن العلامتين غير موثوقتين حالياً.
**SQL:**
```sql
SELECT COUNT(*) FILTER (WHERE has_driver) AS with_driver FROM dim_vehicle;
```
**Explanation:** `has_driver` defaulted to true on every row; the daily rollup's driver-link counter is empty. Driver↔bus linkage is a known ETL gap (`fact_assignment.driver_id` also 0% filled).
**Use case:** Caveat entry — answer "driver assignment" questions with this reliability note.

### Q21. ما هو متوسط عمر الأسطول؟
**Answer (as of 2026-08-23):** **9.8 سنة** (سنة الموديل 100% معبأة؛ أقدم موديل 2009، أحدث 2027).
**SQL:**
```sql
SELECT ROUND(AVG(2026 - NULLIF(year_model,0)),1) AS avg_age,
       MIN(NULLIF(year_model,0)) AS oldest_year, MAX(year_model) AS newest_year
FROM dim_vehicle;
```
**Explanation:** Computed against 2026. Matches `fact_vehicle_kpi.avg(age_years)` = 9.8. A ~10-year-old fleet has direct maintenance/safety implications.
**Use case:** Fleet-renewal budgeting; correlating age with defects (Section O) and accidents.

### Q22. ما هي أكثر ماركات الحافلات شيوعاً؟
**Answer (as of 2026-08-23):** A4: **2,818** · تويوتا: 2,243 · زونج تونج: 1,278 · هونداي: 1,043 · فوتون: 1,036 · King Long: 941 · شانجان: 795 · G9 CT BUS: 781 · ZHONG TONG: 693 · دونج فينج: 548.
**SQL:**
```sql
SELECT brand_name_ar, COUNT(*) AS cnt
FROM dim_vehicle GROUP BY brand_name_ar ORDER BY cnt DESC LIMIT 10;
```
**Explanation:** Brand names come as raw text (mixed Arabic/Latin, e.g. "زونج تونج" vs "ZHONG TONG" are the same make) — deduplicate semantically when reporting.
**Use case:** Spare-parts and maintenance planning; brand-level defect analysis.

### Q23. ما هو توزيع الأسطول حسب سنة الموديل؟
**Answer (as of 2026-08-23):** 2016: **3,633** (الأكبر) · 2020: 2,134 · 2021: 1,184 · 2023: 1,129 · 2019: 936 · 2025: 778 · 2017: 697 · 2018/2024: ~329/286 · 2026: 169 · 2027: 12.
**SQL:**
```sql
SELECT year_model, COUNT(*) AS cnt
FROM dim_vehicle GROUP BY year_model ORDER BY year_model DESC;
```
**Explanation:** Bulge around 2016–2021 model years; only 959 buses are 2025+.
**Use case:** Replacement-wave forecasting; warranty tracking.

### Q24. ما هي أكبر الشركات المشغلة من حيث عدد الحافلات؟
**Answer (as of 2026-08-23):** شركة حافل: **7,788** · سيتكو: 3,604 · مسارك الأمثل: 2,334 · ناصر عبدالله أبو سرهد: 1,941 · مراكب الجنوب: 1,366 · البشائر الأولى: 1,222 · ستر الراكان: 1,177 · شركة مكة للنقل: 991 · السفير للنقل المدرسي: 828 · راية الملبى: 795.
**SQL:**
```sql
SELECT o.operator_name, COUNT(*) AS vehicles
FROM dim_vehicle v JOIN dim_operator o ON o.operator_id = v.operator_id
GROUP BY o.operator_name ORDER BY vehicles DESC LIMIT 10;
```
**Explanation:** Hafil alone runs ~32% of the fleet. Top-10 operators cover ~91% of buses.
**Use case:** Operator concentration; negotiation leverage; incident attribution.

### Q25. ما هي سعة الأسطول الإجمالية؟
**Answer (as of 2026-08-23):** متوسط السعة التشغيلية **38.9 مقعد/حافلة** · السعة الإجمالية **932,198 مقعداً** (capacity_official = capacity_operational لكل الصفوف تقريباً).
**SQL:**
```sql
SELECT ROUND(AVG(capacity_operational),1) AS avg_cap,
       SUM(capacity_operational) AS total_cap
FROM dim_vehicle;
```
**Explanation:** Compare with 395,076 assigned students → system-level theoretical coverage is ample; the constraint is assignment, not seats.
**Use case:** Capacity-vs-demand macro analysis.

### Q26. كم عدد الحافلات الاحتياطية وحافلات ذوي الإعاقة؟
**Answer (as of 2026-08-23):** احتياطية: **373 (1.6%)** · ذوي الإعاقة `is_special_needs`: **0** (غير معبأ من المصدر).
**SQL:**
```sql
SELECT COUNT(*) FILTER (WHERE is_backup) AS backup,
       COUNT(*) FILTER (WHERE is_special_needs) AS special_needs
FROM dim_vehicle;
```
**Explanation:** Backup flag is populated. Special-needs bus flags are NOT loaded even though 23,327 students are category غير حركي — a real data gap for accessibility planning.
**Use case:** Contingency planning; accessibility-compliance gap reporting.

### Q27. هل تواريخ انتهاء الصلاحية النصية في بيانات الحافلات قابلة للتحليل؟
**Answer (as of 2026-08-23):** نعم — **100%** من قيم الرخص/الفحص الدوري/التأمين تطابق صيغة `YYYY-MM-DD` (23,977/23,977 لكل حقل). بطاقة التشغيل (`operation_card_expiration_date`, نوع date حقيقي) معبأة لـ18,486 حافلة فقط (77%).
**SQL:**
```sql
SELECT COUNT(*) FILTER (WHERE license_expiration_date ~ '^\d{4}-\d{2}-\d{2}$') AS license_parse,
       COUNT(*) FILTER (WHERE insurance_expiration_date ~ '^\d{4}-\d{2}-\d{2}$') AS insurance_parse,
       COUNT(*) AS total FROM dim_vehicle;
```
**Explanation:** Schema docs warned these text dates may be garbage — currently they are clean, but keep the regex guard before `to_date()` since the ETL sources them as raw text.
**Use case:** Validating that compliance-expiry analytics are safe to compute.

### Q28. كم حافلة ستنتهي صلاحية وثائقها خلال 30 يوماً؟
**Answer (as of 2026-08-23):** رخصة: **1,374** · فحص دوري: **3,328** · تأمين: **6,093** حافلة (خلال 2026-08-23 → 2026-09-22).
**SQL:**
```sql
SELECT COUNT(*) FILTER (WHERE license_expiration_date ~ '^\d{4}-\d{2}-\d{2}$'
         AND to_date(license_expiration_date,'YYYY-MM-DD') BETWEEN CURRENT_DATE AND CURRENT_DATE+30) AS license_30d,
       COUNT(*) FILTER (WHERE periodic_examination_expiration_date ~ '^\d{4}-\d{2}-\d{2}$'
         AND to_date(periodic_examination_expiration_date,'YYYY-MM-DD') BETWEEN CURRENT_DATE AND CURRENT_DATE+30) AS exam_30d,
       COUNT(*) FILTER (WHERE insurance_expiration_date ~ '^\d{4}-\d{2}-\d{2}$'
         AND to_date(insurance_expiration_date,'YYYY-MM-DD') BETWEEN CURRENT_DATE AND CURRENT_DATE+30) AS insurance_30d
FROM dim_vehicle;
```
**Explanation:** Live recomputation of the snapshot's expiring-30d KPIs (snapshot of 2026-08-12 said 1,288/3,391/6,344 — close, drifted with time). Insurance is the biggest compliance cliff.
**Use case:** 30-day compliance worklists for operators; avoiding grounded buses.

### Q29. كم حافلة وثائقها منتهية فعلاً اليوم؟
**Answer (as of 2026-08-23):** رخصة منتهية: **1,514 (6.3%)** · تأمين منتهٍ: **4,580 (19.1%)**.
**SQL:**
```sql
SELECT COUNT(*) FILTER (WHERE license_expiration_date ~ '^\d{4}-\d{2}-\d{2}$'
         AND to_date(license_expiration_date,'YYYY-MM-DD') < CURRENT_DATE) AS license_expired,
       COUNT(*) FILTER (WHERE insurance_expiration_date ~ '^\d{4}-\d{2}-\d{2}$'
         AND to_date(insurance_expiration_date,'YYYY-MM-DD') < CURRENT_DATE) AS insurance_expired
FROM dim_vehicle;
```
**Explanation:** Nearly 1 in 5 buses has lapsed insurance — a legal/safety exposure. These buses should not be in service.
**Use case:** Enforcement targeting; operator penalties.

### Q30. ما هو معدل استغلال مقاعد الأسطول؟
**Answer (as of 2026-08-23):** **60.6%** (مجموع الطلاب المعينين لكل باص ÷ مجموع سعتها التشغيلية، للباصات التي لها طلاب).
**SQL:**
```sql
SELECT ROUND(100.0*SUM(riders)/NULLIF(SUM(cap),0),1) AS overall_util_pct
FROM (SELECT a.vehicle_id, COUNT(*) AS riders, MAX(v.capacity_operational) AS cap
      FROM fact_assignment a JOIN dim_vehicle v ON v.vehicle_id = a.vehicle_id
      GROUP BY a.vehicle_id) t;
```
**Explanation:** Static assignment-based utilization (not per-trip). Note `fact_vehicle_kpi.utilization_pct` is NULL today — this assignment-based computation is the working alternative.
**Use case:** Fleet-efficiency KPI; justifying fleet size vs assignment levels.

### Q31. كم حافلة معين لها طلاب أكثر من سعتها؟
**Answer (as of 2026-08-23):** **2,312 حافلة (17.9%** من 12,921 باصاً له طلاب) لديها طلاب معينون أكثر من سعتها التشغيلية.
**SQL:**
```sql
SELECT COUNT(*) AS vehicles_over_cap
FROM (SELECT a.vehicle_id, COUNT(*) AS riders, MAX(v.capacity_operational) AS cap
      FROM fact_assignment a JOIN dim_vehicle v ON v.vehicle_id = a.vehicle_id
      GROUP BY a.vehicle_id) t
WHERE riders > cap;
```
**Explanation:** Over-capacity assignments may be legitimate (multiple rounds/trips per bus) or assignment errors — needs operational review per bus before acting.
**Use case:** Safety compliance (overcrowding); route-split decisions.

---

# Section D — Drivers & Escorts

### Q32. كم عدد السائقين الإجمالي؟
**Answer (as of 2026-08-23):** **26,545 سائقاً**، كلهم مرتبطون بعقد، و26,528 لديهم تاريخ انتهاء رخصة مسجل.
**SQL:**
```sql
SELECT COUNT(*) AS total, COUNT(contract_id) AS with_contract,
       COUNT(license_expiry_date) AS with_license_expiry
FROM dim_driver;
```
**Explanation:** Driver-to-bus ratio ~1.1:1 vs 23,977 buses — healthy nominal coverage.
**Use case:** Workforce sizing; driver-shortage analysis per contract.

### Q33. ما هي نسبة السائقين السعوديين؟
**Answer (as of 2026-08-23):** **19,366 سعودي (72.9%)** مقابل 7,179 غير سعودي (27.1%).
**SQL:**
```sql
SELECT COUNT(*) FILTER (WHERE is_saudi) AS saudi, COUNT(*) AS total,
       ROUND(100.0*COUNT(*) FILTER (WHERE is_saudi)/COUNT(*),1) AS saudi_pct
FROM dim_driver;
```
**Explanation:** Saudization KPI. Note `fact_driver_daily.saudi_drivers` shows 0 — the daily rollup's saudi counter is broken; `dim_driver` is the reliable source.
**Use case:** Saudization compliance reporting to the Ministry.

### Q34. ما هي جنسيات السائقين غير السعوديين الأكثر شيوعاً؟
**Answer (as of 2026-08-23):** مصري: **2,059** · سوداني: 1,394 · يمني: 854 · باكستاني: 561 · هندي: 310 · نيجيري: 255 · بورمي: 251 · قبائل نازحة: 239 · إثيوبي: 193.
**SQL:**
```sql
SELECT nationality_name_ar, COUNT(*) AS cnt
FROM dim_driver GROUP BY nationality_name_ar ORDER BY cnt DESC LIMIT 10;
```
**Explanation:** After السعودية (19,366), Egyptian and Sudanese drivers dominate the expat workforce.
**Use case:** Workforce planning, visa/iqama processing volumes.

### Q35. كم سائقاً مدرَّباً وحاصلاً على إسعافات أولية؟
**Answer (as of 2026-08-23):** `is_trained`: **22,253 (83.8%)** · `is_first_aid`: **26,545 (100% — علم مُعبأ افتراضياً، غير موثوق)**. سجلات التدريب الفعلية (`fact_driver_training`): **18,576 سجل** لـ18,251 سائقاً، كلها تدريب أساسي، **صفر تدريب متقدم**.
**SQL:**
```sql
SELECT COUNT(*) FILTER (WHERE is_trained) AS trained,
       COUNT(*) FILTER (WHERE is_first_aid) AS first_aid FROM dim_driver;
-- and:
SELECT COUNT(*) AS records, COUNT(DISTINCT nid_number) AS drivers,
       COUNT(*) FILTER (WHERE has_basic_training) AS basic,
       COUNT(*) FILTER (WHERE has_advanced_training) AS advanced
FROM fact_driver_training;
```
**Explanation:** Trust `fact_driver_training` over the dimension flags: 18,251 of 26,545 drivers (68.8%) have a real training record; advanced training is absent.
**Use case:** Training-program compliance; safety audit prep.

### Q36. كم سائقاً رخصته منتهية أو قاربت على الانتهاء؟
**Answer (as of 2026-08-23):** منتهية: **1,364 (5.1%)** · تنتهي خلال 30 يوماً: **336** · خلال 90 يوماً: **946**. (رول-أب 2026-08-12: منتهية 1,275، مجهولة 17.)
**SQL:**
```sql
SELECT COUNT(*) FILTER (WHERE license_expiry_date < CURRENT_DATE) AS expired,
       COUNT(*) FILTER (WHERE license_expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE+30) AS exp_30d,
       COUNT(*) FILTER (WHERE license_expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE+90) AS exp_90d
FROM dim_driver;
```
**Explanation:** `license_expiry_date` is a real date column (unlike vehicle text dates) — direct comparison is safe. 17 drivers have no recorded expiry.
**Use case:** Driver compliance worklists; grounding drivers with expired licenses.

### Q37. ما هو متوسط عمر السائقين؟
**Answer (as of 2026-08-23):** **43.7 سنة** (نطاق 18–75). توجد **64 سجلاً بأعمار شاذة** (خارج النطاق، منها -37 و135) ناتجة عن تواريخ ميلاد فاسدة.
**SQL:**
```sql
SELECT ROUND(AVG(age),1) AS avg_age FROM dim_driver WHERE age BETWEEN 18 AND 75;
SELECT COUNT(*) FILTER (WHERE age < 18 OR age > 75) AS junk_ages FROM dim_driver;
```
**Explanation:** Raw AVG includes junk ages; always bound the range. 64/26,545 = 0.24% bad birth dates.
**Use case:** Workforce demographics; retirement-wave planning; data-quality reporting.

### Q38. ما هي إحصاءات نقاط المرور على السائقين؟
**Answer (as of 2026-08-23):** **لا توجد بيانات** — `traffic_points` فارغ (NULL) لكل السائقين الـ26,545.
**SQL:**
```sql
SELECT COUNT(traffic_points) AS with_points FROM dim_driver;  -- 0
```
**Explanation:** The traffic-points feed is not loaded. Refuse traffic-points questions with this reason; `fact_driver_compliance` (the intended daily source) is also empty.
**Use case:** Caveat entry — prevents hallucinating safety scores.

### Q39. كم عدد المرافقين وما نسبة السعوديين والنشطين منهم؟
**Answer (as of 2026-08-23):** **9,038 مرافقاً** · سعوديون: **5,287 (58.5%)** · مرتبطون بباص: 8,811 · `is_active` = **0 نشط** (العمود غير معبأ — كل القيم false).
**SQL:**
```sql
SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE is_active) AS active,
       COUNT(*) FILTER (WHERE is_saudi) AS saudi, COUNT(vehicle_id) AS with_vehicle
FROM dim_escort;
```
**Explanation:** Escorts serve special-needs routes. The is_active flag is unusable; count escorts with a vehicle link (8,811) as the practical "assigned" figure.
**Use case:** Special-needs route staffing; escort Saudization.

### Q40. ما هي أكبر الشركات من حيث عدد المرافقين؟
**Answer (as of 2026-08-23):** مسارك الأمثل: **2,866** · البشائر الأولى: 2,827 · راية الملبى: 1,304 · اسطول السعودية: 884 · فهد حميد الشمرى: 405.
**SQL:**
```sql
SELECT o.operator_name, COUNT(*) AS escorts
FROM dim_escort e JOIN dim_operator o ON o.operator_id = e.operator_id
GROUP BY o.operator_name ORDER BY escorts DESC LIMIT 8;
```
**Explanation:** Escort staffing is concentrated in a handful of operators — mirroring which operators hold special-needs-heavy contracts.
**Use case:** Special-needs contract oversight.

### Q41. ما هو متوسط عمر المرافقين؟
**Answer (as of 2026-08-23):** **39.5 سنة**.
**SQL:**
```sql
SELECT ROUND(AVG(age),1) AS avg_age FROM dim_escort;
```
**Explanation:** Age is populated on the escort dimension (unlike some driver fields).
**Use case:** Workforce demographics for escort hiring plans.

---

# Section E — Contracts & Operators

### Q42. كم عدد العقود وكم منها نشط؟
**Answer (as of 2026-08-23):** **104 عقود** إجمالاً: **82 للعام الحالي** (`current`، منها **16 نشطة** `active_contract=true`) + **22 عقد تخطيط للعام القادم** (`nyear`).
**SQL:**
```sql
SELECT academic_year, COUNT(*) AS cnt, COUNT(*) FILTER (WHERE active_contract) AS active
FROM dim_contract GROUP BY academic_year;
```
**Explanation:** ALWAYS filter `academic_year` — the PK is `(contract_id, academic_year)` and contract ids repeat across years.
**Use case:** Contract portfolio overview; year-transition planning.

### Q43. ما هي القيمة الإجمالية للعقود بالريال؟
**Answer (as of 2026-08-23):** **لا يمكن الإجابة** — عمود `amount` موجود في 47 عقداً لكن قيمته **صفر في كل الصفوف** (المجموع = 0 ريال).
**SQL:**
```sql
SELECT COUNT(amount) AS with_amount, SUM(amount) AS total_sar, MAX(amount) AS max_sar
FROM dim_contract WHERE academic_year='current';
```
**Explanation:** Contract financial values are not loaded from source (loaded as 0). Any SAR-value answer would be fabricated — refuse and cite this gap.
**Use case:** Caveat entry; prevents fabricated financial reporting.

### Q44. كم عدد الطلاب والمقاعد المخططة عبر العقود الحالية؟
**Answer (as of 2026-08-23):** مجموع `students_total` = **1,048,052 طالباً مخططاً** = مجموع `total_seats_allocated` (نفس القيمة) عبر 82 عقداً؛ `total_seats_reversed` فارغ تماماً.
**SQL:**
```sql
SELECT SUM(students_total) AS students_total_sum,
       SUM(total_seats_allocated) AS seats_allocated,
       SUM(total_seats_reversed) AS seats_reversed
FROM dim_contract WHERE academic_year='current';
```
**Explanation:** Planned seats (1.05M) exceed registered assignment rows (748,909) — plans include students not yet flowing through assignments. "Reversed/reserved" seats are not loaded.
**Use case:** Demand planning vs actuals; seat-procurement sizing.

### Q45. ما هو حجم تخطيط العام الدراسي القادم؟
**Answer (as of 2026-08-23):** **22 عقد `nyear`** بإجمالي **755,046 طالب/مقعد مخطط**.
**SQL:**
```sql
SELECT COUNT(*) AS nyear_contracts, SUM(students_total) AS students
FROM dim_contract WHERE academic_year='nyear';
```
**Explanation:** Next-year planning snapshots coexist with current under the composite PK — this is why the year filter matters.
**Use case:** Next-year contract ramp-up; operator award tracking.

### Q46. ما هو متوسط جاهزية العقود التشغيلية؟
**Answer (as of 2026-08-23، من mv_plan_summary):** متوسط `ready_pct` = **51.9%** · متوسط نسبة نقل الطلاب `transfer_pct` = **31.8%** · 35,165 باصاً إجمالاً (33,690 جاهز، 27,282 بها GPS) عبر 82 عقداً. (نفس الأرقام في `fact_contract_readiness` بتاريخ 2026-08-12.)
**SQL:**
```sql
SELECT COUNT(*) AS contracts, ROUND(AVG(ready_pct),1) AS avg_ready_pct,
       ROUND(AVG(transfer_pct),1) AS avg_transfer_pct,
       SUM(totalbus) AS buses, SUM(ready) AS ready, SUM(with_gps) AS with_gps
FROM mv_plan_summary;
```
**Explanation:** `mv_plan_summary` is the per-contract readiness rollup (PK contract_id). Note `bus_target_pct` averages 175% — a suspicious metric definition; don't quote it without review. Bus totals here (35k) exceed dim_vehicle (24k) because sub-operator fleets double-count across rollups.
**Use case:** Morning readiness standup; identifying contracts blocking school opening.

### Q47. ما هي أسوأ 5 عقود من حيث الجاهزية؟
**Answer (as of 2026-08-23):** TTC-AG-00063 (ناصر أبو سرهد): **0%** · TTC-AG-00178 (ستر الراكان): **0%** · SRV-RAFED (شركات تطوير): **0%** · 02-2019-11 (سيتكو): **0%** · 12-2019-12 (مؤسسة عيون السفر): **0%** — كلها بلا باصات مسجلة (totalbus=0).
**SQL:**
```sql
SELECT contract_number, operator_name, totalbus, ready, ready_pct
FROM mv_plan_summary ORDER BY ready_pct ASC NULLS LAST LIMIT 5;
```
**Explanation:** Zero-readiness contracts have no buses in the rollup at all — likely inactive/not-yet-onboarded contracts rather than operational failures. `sector_name_ar` is NULL in this MV too.
**Use case:** Escalation list; distinguishing dead contracts from failing ones.

### Q48. ما هي أفضل العقود جاهزية؟
**Answer (as of 2026-08-23):** عقود بنسبة **100%**: 001-2022 (أفلاء الريس، 63/63 باصاً) · 12-2019-06 (السامي، 40/40) · TTC-AG-00225 (مسارات سدير، 4/4) · TTC-AG-00206 (مسارك الأمثل، 1/1) · 12-2019-09 (فهد حميد الشمرى، 47/47).
**SQL:**
```sql
SELECT contract_number, operator_name, totalbus, ready, ready_pct
FROM mv_plan_summary ORDER BY ready_pct DESC NULLS LAST LIMIT 5;
```
**Explanation:** Fully-ready exemplars — useful as benchmarks.
**Use case:** Best-practice identification; award/renewal decisions.

### Q49. كم عدد الشركات المشغلة (رئيسية وفرعية)؟
**Answer (as of 2026-08-23):** **4,544 مشغلاً**: **28 رئيسياً** و**4,516 مشغلاً فرعياً** (sub-operators / متعهدون أفراد). التصنيفات: كبار المتعهدين 9، صغار المتعهدين 13، والباقي بلا تصنيف.
**SQL:**
```sql
SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE is_sub) AS sub_operators,
       COUNT(*) FILTER (WHERE NOT is_sub) AS main_operators
FROM dim_operator;
```
**Explanation:** The operator dimension includes thousands of individual small contractors; fleet analytics usually group by the ~28 main operators (see Q24).
**Use case:** Market-structure understanding; sub-operator management.

### Q50. ما هي مخالفات التدقيق المسجلة على العقود؟
**Answer (as of 2026-08-23):** **441 مخالفة** عبر 41 عقداً و7 فترات: الكود **9** (287 مخالفة، مجموع قيم 5,699) والكود **8** (154 مخالفة، مجموع قيم 120,541).
**SQL:**
```sql
SELECT code, COUNT(*) AS cnt, SUM(value)::bigint AS total_value
FROM fact_audit_violation GROUP BY code ORDER BY cnt DESC;
```
**Explanation:** From the reporting DB's audit violations. Code meanings aren't denormalized — join `dim_domain` if labels are needed, or present codes as-is.
**Use case:** Financial/audit compliance tracking per contract.

---

# Section F — Schools

### Q51. كم عدد مدارس رافد وكم منها له إحداثيات؟
**Answer (as of 2026-08-23):** **11,741 مدرسة** (`dim_school`) · **11,627 بإحداثيات (99.0%)** · 114 بدون إحداثيات.
**SQL:**
```sql
SELECT COUNT(*) AS schools,
       COUNT(*) FILTER (WHERE x IS NOT NULL AND y IS NOT NULL) AS with_coords
FROM dim_school;
```
**Explanation:** `x`=longitude, `y`=latitude. Hierarchy columns (sector/administration/office) are 100% populated here — this dim is the reliable geography source.
**Use case:** Mapping coverage; geocoding backlog (114 schools).

### Q52. كم عدد مدارس نظام نور وكم طالباً مسنداً فيها؟
**Answer (as of 2026-08-23):** **11,739 مدرسة** · 11,729 بإحداثيات (99.9%) · مجموع `assigned_students` = **724,880** · `student_count` = 0 و`allocated_seats` فارغ (غير محملة).
**SQL:**
```sql
SELECT COUNT(*) AS noor_schools,
       COUNT(*) FILTER (WHERE x IS NOT NULL AND y IS NOT NULL) AS with_coords,
       SUM(assigned_students) AS assigned_sum
FROM dim_noor_school;
```
**Explanation:** Noor is the official Ministry SIS master. `assigned_students` (724,880) is the seat-allocation baseline used by `fact_seat_allocation_daily`; raw `student_count` isn't loaded.
**Use case:** Official school/student baselines; reconciling Rafed vs Noor.

### Q53. ما هو توزيع المدارس حسب القطاع/المنطقة؟
**Answer (as of 2026-08-23):** مكة 1,710 · الشرقية 1,663 · الرياض 1,474 · عسير 1,422 · جازان 1,233 · القصيم 1,044 · المدينة 964 · نجران 458 · حائل 454 · تبوك 434 · الباحة 349 · الجوف 328 · الحدود الشمالية 208.
**SQL:**
```sql
SELECT sector_name_ar, COUNT(*) AS schools
FROM dim_school GROUP BY sector_name_ar ORDER BY schools DESC;
```
**Explanation:** `sector_name_ar` on `dim_school` carries the region name ( Ministry "sector" ≈ region here). See Q3/Q12 for the student-side view.
**Use case:** Regional school-network sizing.

### Q54. ما هي أكبر المكاتب التعليمية من حيث عدد المدارس؟
**Answer (as of 2026-08-23):** إدارة الإشراف التربوي–الرياض: **636** · مكة: 363 · المدينة: 317 · القصيم: 314 · عسير: 278 · الشرقية: 259 · مكتب القطيف: 223 · تبوك: 213 · الهفوف: 202 · وسط نجران: 187.
**SQL:**
```sql
SELECT office_name_ar, sector_name_ar, COUNT(*) AS schools
FROM dim_school GROUP BY office_name_ar, sector_name_ar
ORDER BY schools DESC LIMIT 10;
```
**Explanation:** Office names repeat across regions ("إدارة الإشراف التربوي") — always pair with `sector_name_ar`.
**Use case:** Office-level workload; where to open coordination desks.

### Q55. ما هو إجمالي فجوة المقاعد على مستوى المدارس؟
**Answer (as of 2026-08-23):** **623 مدرسة (5.3%** من 11,736) لديها فجوة مقاعد > 0 · إجمالي العجز **2,296 مقعداً** · أقصى فجوة لمدرسة واحدة **72 مقعداً** · متوسط `gap_pct` للمتأثرة 17.6%.
**SQL:**
```sql
SELECT COUNT(*) FILTER (WHERE gap > 0) AS with_gap,
       SUM(gap) FILTER (WHERE gap > 0) AS total_gap, MAX(gap) AS max_gap
FROM mv_school_seat_gap;
```
**Explanation:** `gap = allocated_seats − actual_seats`: students allocated to the school minus seats its buses actually provide. Only 2,296 seats short nationwide — a manageable, concentrated problem.
**Use case:** Seat-shortfall remediation list; operator seat top-ups.

### Q56. ما هي أسوأ 10 مدارس من حيث فجوة المقاعد؟
**Answer (as of 2026-08-23):** الثانوية الأولى بالعلا (TTC-AG-00190): فجوة **72** (47.4%) · ابتدائية مربة السفلى (TTC-AG-00212): **60** · متوسطة الظاهر بيبرس بالعلا: **43** (55.8%) · متوسطة أروى بنت عبدالمطلب: **39 (100%)** · ابتدائية أسعد بن زرارة: **37 (100%)** · ثانوية الأندلس بالعرضيات: 30 · ابتدائية الحكم بن عمرو: 28 (50%) · الأولى بالشفية وادي الفرع: **28 (100%)** · الأولى بالقويعية: 27 · الثانوية الثانية بمدينة سلطان: 27.
**SQL:**
```sql
SELECT school_name, contract_number, allocated_seats, actual_seats, gap, gap_pct
FROM mv_school_seat_gap ORDER BY gap DESC LIMIT 10;
```
**Explanation:** Three schools have 100% gap (zero actual seats) — students allocated but no bus service recorded; concentrated in contracts TTC-AG-00190 / 00212 / 00226 (Madinah-area مسارات contracts).
**Use case:** Immediate escalation list — schools where allocated students may have no transport.

### Q57. أي المناطق تفتقد إحداثيات مدارسها؟
**Answer (as of 2026-08-23):** الشرقية: **37** مدرسة بلا إحداثيات · مكة: 26 · نجران: 12 · الرياض: 9 · القصيم: 7 · عسير: 6 · تبوك: 5 · جازان: 4 (إجمالي 114).
**SQL:**
```sql
SELECT sector_name_ar, COUNT(*) AS no_coords
FROM dim_school WHERE x IS NULL OR y IS NULL
GROUP BY sector_name_ar ORDER BY no_coords DESC;
```
**Explanation:** Small, region-skewed geocoding backlog.
**Use case:** GIS data-cleanup sprint planning.

---

# Section G — Inspections & Compliance

### Q58. كم عدد زيارات التفتيش وما متوسط الدرجات؟
**Answer (as of 2026-08-23):** **1,520 زيارة** (`ins_workorders`) تغطي **693 مدرسة** و**46 عقداً** و**169 مفتشاً** · متوسط الدرجة **70.9/100** · 18,278 باصاً مذكورة في الزيارات. النطاق الزمني: 2026-08-03 → 2026-08-26 فقط.
**SQL:**
```sql
SELECT COUNT(*) AS total, MIN(inspection_date) AS first_date, MAX(inspection_date) AS last_date,
       COUNT(DISTINCT school_id) AS schools, COUNT(DISTINCT inspector_id) AS inspectors,
       ROUND(AVG(score),1) AS avg_score
FROM ins_workorders;
```
**Explanation:** The workorder table currently holds only the **August 2026 inspection campaign** (history is replaced per campaign, not accumulated). Includes future scheduled visits (up to 2026-08-26, unscored).
**Use case:** Campaign tracking; don't present as all-time inspection history.

### Q59. ما هي حالات أوامر عمل التفتيش؟
**Answer (as of 2026-08-23):** تمت الموافقة على الزيارة: **895** · في انتظار بدء الزيارة: 295 · تمت الزيارة: 128 · تعثرت: 66 · فشلت: 63 · بدأت: 45 · تعثرت بانتظار موافقة المشرف: 28.
**SQL:**
```sql
SELECT status, status_label_ar, COUNT(*) AS cnt
FROM ins_workorders GROUP BY status, status_label_ar ORDER BY cnt DESC;
```
**Explanation:** Status pipeline: scheduled → started → completed → approved. 895 approved (59%) is the completion-quality headline; 129 failed/stalled visits need rework.
**Use case:** Inspection-program funnel management.

### Q60. ما هو الإيقاع اليومي لزيارات التفتيش الأخيرة؟
**Answer (as of 2026-08-23):** 2026-08-22: **235 زيارة (متوسط 95.0)** · 08-21: 20 (91.3) · 08-20: 10 (95.5) · 08-19: 59 (81.6) · 08-18: 31 (83.7) · 08-17: 43 (92.5) · 08-23 (اليوم): 70 مجدولة (94.8 للمقيَّمة) · 08-24→26: 34–39 مجدولة يومياً بلا درجات بعد.
**SQL:**
```sql
SELECT inspection_date, COUNT(*) AS visits, ROUND(AVG(score),1) AS avg_score
FROM ins_workorders GROUP BY inspection_date ORDER BY inspection_date DESC LIMIT 10;
```
**Explanation:** 2026-08-22 was the campaign's peak day. Future-dated rows are scheduled visits — scores appear only after completion.
**Use case:** Daily campaign monitoring; inspector capacity planning.

### Q61. ما هي نتائج الفحص على مستوى الباص (الامتثال)؟
**Answer (as of 2026-08-23):** **19,186 فحص باص** · متوسط الامتثال **79.2%** · ناجح (≥80%): **15,215 (79.3%)** · راسب: **3,266 (17.0%)** · إجمالي إجابات 768,015 منها **91,495 مخالفة** · باص واحد مستبعد.
**SQL:**
```sql
SELECT COUNT(*) AS bus_inspections, ROUND(AVG(compliance_pct),1) AS avg_compliance,
       COUNT(*) FILTER (WHERE compliance_pct >= 80) AS pass_80,
       COUNT(*) FILTER (WHERE compliance_pct < 80) AS fail_80,
       SUM(violation_answer_count) AS violations
FROM fact_inspection_detail;
```
**Explanation:** Bus-level grain within workorders. 80% is used here as the pass threshold (aligns with the snapshot's ~82% pass rate). Remaining ~3.7% have NULL compliance (unscored).
**Use case:** Fleet compliance KPI; pass/fail enforcement.

### Q62. ما هي حالات فحوصات الباصات التفصيلية؟
**Answer (as of 2026-08-23):** تم الموافقة: **17,809** · تم الفحص: 527 · فشل الفحص: 388 · لم يبدأ: 186 · تم الرفض: 158 · معاد للفحص: 90 · فشل بانتظار المشرف: 28.
**SQL:**
```sql
SELECT status_label_ar, COUNT(*) AS cnt
FROM fact_inspection_detail GROUP BY status_label_ar ORDER BY cnt DESC;
```
**Explanation:** 92.8% of bus inspections reach approval; 476 (388+28+... ) failed or rejected buses need operator remediation.
**Use case:** Tracking buses that must not operate until re-inspected.

### Q63. ما هي أسوأ العقود من حيث متوسط الامتثال في الفحص؟
**Answer (as of 2026-08-23، للعقود بـ≥20 فحصاً):** SRV-RAFED: **0.0%** (2,572 فحصاً — إجابات غير مُدخلة، انظر الشرح) · TTC-AG-00207: **60.6%** · 02-2019-13: **75.5%** · 16-2019-01: 84.4% · TTC-AG-00189: 85.3% · 12-2019-10: 86.1%.
**SQL:**
```sql
SELECT d.contract_id, c.contract_number, COUNT(*) AS bus_inspections,
       ROUND(AVG(d.compliance_pct),1) AS avg_compliance
FROM fact_inspection_detail d
LEFT JOIN dim_contract c ON c.contract_id = d.contract_id::text AND c.academic_year='current'
GROUP BY d.contract_id, c.contract_number
HAVING COUNT(*) >= 20 ORDER BY avg_compliance ASC LIMIT 8;
```
**Explanation:** `fact_inspection_detail.contract_id` is integer-like — cast to text when joining. SRV-RAFED's 0% is a data artifact (a services contract whose answers weren't captured), not a real zero-compliance fleet.
**Use case:** Compliance league table — with the SRV-RAFED caveat attached.

### Q64. ما هو حجم إجابات التفتيش الخام وما حالة معالجتها؟
**Answer (as of 2026-08-23):** **509,050 إجابة** · محلولة `is_solved`: **538 (0.1%)** · مُصعَّدة `is_esclated`: **3,674** · violation_form_8: 0 · 148 سؤالاً فريداً في 9 فئات.
**SQL:**
```sql
SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE is_solved) AS solved,
       COUNT(*) FILTER (WHERE is_esclated) AS escalated,
       COUNT(DISTINCT question_id) AS questions
FROM fact_inspection_answer;
```
**Explanation:** The remediation workflow is barely used — only 538 answers marked solved vs 3,674 escalated. Follow-up processing is the weak link, not detection.
**Use case:** Remediation-process audit; measuring fix-through rates.

### Q65. ما هو توزيع قيم إجابات التفتيش؟
**Answer (as of 2026-08-23):** "لايوجد مخالفة": **437,805 (86.0%)** · "نعم": 52,628 · "لا": 7,158 · "عاليه": 3,625 · "تجاوز": 2,966 · "متوسطه": 1,337 · "منخفضه": 1,125 · إجابات رقمية (1–4): ~1,807.
**SQL:**
```sql
SELECT answer_text, COUNT(*) AS cnt
FROM fact_inspection_answer GROUP BY answer_text ORDER BY cnt DESC LIMIT 12;
```
**Explanation:** Free-text Arabic answers with inconsistent spelling (عاليه/متوسطه/منخفضه = high/medium/low severity). Normalize variants before aggregating severity.
**Use case:** Building pass/fail logic; answer-vocabulary standardization.

### Q66. ما هي أكثر بنود الفحص رسوباً؟
**Answer (as of 2026-08-23، الإجابات "لا"):** عدم وجود بطاقة تشغيل سارية: **859** · نظافة الأرضيات والبلاط: 573 · نظافة الطاولات والكراسي: 492 · سلامة التمديدات الكهربائية: 407 · نظافة الزجاج: 396 · نظافة الحوائط: 384 · سلامة البلاط: 337 · أغطية لوحات الكهرباء: 275.
**SQL:**
```sql
SELECT question_text, COUNT(*) AS fails
FROM fact_inspection_answer
WHERE answer_text IN ('لا','غير مطابق','فشل')
GROUP BY question_text ORDER BY fails DESC LIMIT 8;
```
**Explanation:** The top operational failure is missing/invalid bus operation cards (regulatory); most others are school-facility cleanliness items (the checklist mixes bus and school questions — see Q67 categories).
**Use case:** Targeted remediation themes; operator vs school-facility split.

### Q67. ما هي فئات أسئلة التفتيش؟
**Answer (as of 2026-08-23):** الأمن والسلامة: **282,724** إجابة · جودة الخدمة: 109,186 · الهوية المدرسية: 77,179 · الفصول: 19,926 · دورات المياه: 12,559 · الممرات: 4,497 · الساحات: 2,348 · الكراج: 420.
**SQL:**
```sql
SELECT category_name, COUNT(*) AS cnt
FROM fact_inspection_answer GROUP BY category_name ORDER BY cnt DESC;
```
**Explanation:** Safety & security dominates the checklist (55%). Several categories are school-building inspections, not bus items.
**Use case:** Scoping "bus safety" vs "school facility" analytics correctly.

### Q68. كم عدد المفتشين وقوالب الفحص؟
**Answer (as of 2026-08-23):** **263 مفتشاً** (منهم **46 مشرفاً**) · **36 قالب فحص** · **354 سؤال فحص** معرفة.
**SQL:**
```sql
SELECT (SELECT COUNT(*) FROM dim_inspector) AS inspectors,
       (SELECT COUNT(*) FROM dim_inspector WHERE is_supervisor) AS supervisors,
       (SELECT COUNT(*) FROM dim_examination_template) AS templates,
       (SELECT COUNT(*) FROM dim_examination_question) AS questions;
```
**Explanation:** Inspector workforce and checklist definitions. 169 inspectors were active in the August campaign (Q58).
**Use case:** Inspector-capacity planning; checklist versioning.

---

# Section H — Safety Checks (pre/post-trip checklists)

### Q69. كم عدد فحوصات السلامة اليومية (صباحية/مسائية)؟
**Answer (as of 2026-08-23):** صباحية: **26,008** · مسائية: **20,207** (إجمالي 46,215) · من 2026-01-27 إلى 2026-08-22 · تغطي 19 عقداً (صباحي) / 14 (مسائي).
**SQL:**
```sql
SELECT check_type, COUNT(*) AS cnt, MIN(check_date) AS first_date, MAX(check_date) AS last_date
FROM fact_safety_check GROUP BY check_type;
```
**Explanation:** Driver-submitted checklists (13 morning + 3 evening questions). Evening completion lags morning by 22% — a discipline gap.
**Use case:** Safety-check compliance monitoring per contract.

### Q70. ما هو حجم فحوصات السلامة في الأيام الأخيرة؟
**Answer (as of 2026-08-23):** 2026-08-22: صباحية **38** / مسائية **21** فقط · 2026-08-18: صباحية 2 · لا توجد فحوصات 08-19 → 08-21.
**SQL:**
```sql
SELECT check_date, check_type, COUNT(*) AS cnt
FROM fact_safety_check
WHERE check_date >= (SELECT max(check_date) FROM fact_safety_check) - 6
GROUP BY check_date, check_type ORDER BY check_date DESC;
```
**Explanation:** Check volume collapsed to near-zero recently (summer break — school year 2025-26 ended 2026-07-30 per the calendar; the 2026-27 year starts 2026-08-16 but checks haven't ramped). Interpret low volumes seasonally before alarming.
**Use case:** Distinguishing feed outages from seasonal lulls.

### Q71. ما هي أكثر العقود إجراءً لفحوصات السلامة؟
**Answer (as of 2026-08-23):** TTC-AG-00191: **13,967** (7,429 صباحي) · 02-2019-02: 8,170 · بدون رقم عقد: 7,375 · TTC-AG-00190: 6,231 · 02-2019-04: 4,268 · TTC-AG-00227: 1,771.
**SQL:**
```sql
SELECT contract_number, COUNT(*) AS checks,
       COUNT(*) FILTER (WHERE check_type='morning') AS morning,
       COUNT(*) FILTER (WHERE check_type='evening') AS evening
FROM fact_safety_check GROUP BY contract_number ORDER BY checks DESC LIMIT 8;
```
**Explanation:** 7,375 checks (16%) carry no contract number — attribution gap. `nid_number` here is the raw driver national id — never output it.
**Use case:** Contract-level safety-discipline comparison.

### Q72. كم بلاغ حادث ورد عبر تطبيق السلامة وكم منها فعلي؟
**Answer (as of 2026-08-23):** **202 بلاغاً** (2026-01-27 → 2026-07-06) · **164 فيها حادث فعلي (81.2%)** · إصابات طلاب مبلغة: **15** · إشعار المشرف: 183 (90.6%).
**SQL:**
```sql
SELECT COUNT(*) AS reports, COUNT(*) FILTER (WHERE has_accident) AS with_accident,
       COUNT(*) FILTER (WHERE students_injured) AS students_injured,
       COUNT(*) FILTER (WHERE supervisor_notified) AS notified
FROM fact_safety_accident;
```
**Explanation:** Driver-app accident self-reports — a leading indicator separate from the official inspector accident register (Section I). Students-injured is a boolean per report here (15 reports), not a headcount.
**Use case:** Near-real-time incident awareness; cross-checking official accident records.

---

# Section I — Accidents & Violence (official inspector records)

### Q73. كم عدد الحوادث الرسمية وما إجمالي الإصابات والوفيات؟
**Answer (as of 2026-08-23):** **561 حادثاً** (2019-01-15 → 2025-12-04) عبر 41 عقداً · طلاب مصابون: **235** · طلاب متوفون: **52** · نُقل للمستشفى: 298 · سائقون مصابون: 38 حادثاً · سائقون متوفون: 13 · وفيات طرف ثانٍ: 72 · إصابات طرف ثانٍ: 221.
**SQL:**
```sql
SELECT COUNT(*) AS total, MIN(accident_date) AS first_date, MAX(accident_date) AS last_date,
       SUM(injured_students) AS injured_students, SUM(dead_students) AS dead_students,
       COUNT(*) FILTER (WHERE driver_injured) AS driver_injured,
       COUNT(*) FILTER (WHERE driver_dead) AS driver_dead,
       SUM(dead_second_party) AS dead_second_party
FROM fact_ins_accident;
```
**Explanation:** Official inspector-DB accident register. Casualty columns are integers except `driver_injured`/`driver_dead` which are booleans (per-accident flags, not counts). 47 rows have no accident_date.
**Use case:** Safety performance baseline; Ministry-level reporting.

### Q74. ما هو توزيع الحوادث حسب النوع/الشدة؟
**Answer (as of 2026-08-23):** حادث بسيط: **408 (72.7%)** · غير مصنف: 71 · جسيم: 40 · متوسط: 21 · شديد: 13 · حادث جسيم: 7 (تصنيف مكرر بصيغة مختلفة) · "...": 1.
**SQL:**
```sql
SELECT accident_type, COUNT(*) AS cnt
FROM fact_ins_accident GROUP BY accident_type ORDER BY cnt DESC;
```
**Explanation:** Free-text severity with duplicate labels ("جسيم" vs "حادث جسيم") — normalize before reporting. Serious+severe ≈ 81 accidents (14%).
**Use case:** Severity trend analysis; label-standardization backlog.

### Q75. ما هي أسباب الحوادث الأكثر شيوعاً؟
**Answer (as of 2026-08-23):** غير مسجل: 181 · خطأ السائق: **137** · طرف آخر: 128 · أخرى: 57 · نسيان طالبة: 11 · غير مروري: 10 · حريق: 10 · سلوك طالب: 8.
**SQL:**
```sql
SELECT accident_reason, COUNT(*) AS cnt
FROM fact_ins_accident GROUP BY accident_reason ORDER BY cnt DESC LIMIT 8;
```
**Explanation:** Driver error is the top recorded cause (24%). "نسيان طالبة" (forgotten student on bus) is a distinct, high-salience category despite low count.
**Use case:** Driver-training focus; forgotten-child alarm justification.

### Q76. ما هو اتجاه الحوادث عبر السنوات؟
**Answer (as of 2026-08-23):** 2019: 74 (82 مصاباً، 9 وفيات) · 2020: 13 · 2021: 8 · 2022: 85 · 2023: 99 · **2024: 139 (106 مصابين، 31 وفاة — الأسوأ)** · 2025: 96 (25 مصاباً، 0 وفيات) · 47 بلا تاريخ.
**SQL:**
```sql
SELECT EXTRACT(YEAR FROM accident_date)::int AS yr, COUNT(*) AS cnt,
       SUM(injured_students) AS injured, SUM(dead_students) AS dead
FROM fact_ins_accident GROUP BY 1 ORDER BY 1;
```
**Explanation:** 2024 spike driven by severe incidents (31 student deaths); 2025 improved on fatalities. COVID years (2020-21) artificially low (school closures).
**Use case:** Multi-year safety trend; program impact evaluation.

### Q77. ما هو الاتجاه الشهري للحوادث مؤخراً؟
**Answer (as of 2026-08-23):** آخر حادث مسجل **2025-12-03** — لا توجد حوادث 2026 في السجل. 2025: ذروة أبريل **31** ثم يناير 23، مايو 17؛ 2024: أكتوبر 17، نوفمبر 16، ديسمبر 20.
**SQL:**
```sql
SELECT to_char(date_trunc('month', accident_date),'YYYY-MM') AS month, COUNT(*) AS cnt
FROM fact_ins_accident WHERE accident_date >= '2024-01-01'
GROUP BY 1 ORDER BY 1 DESC LIMIT 12;
```
**Explanation:** No 2026 records — either feed lag or genuinely quiet year; verify before claiming "zero accidents in 2026".
**Use case:** Recency caveat; monthly seasonality (school months peak).

### Q78. ما هي العقود والباصات الأكثر حوادث؟
**Answer (as of 2026-08-23):** بلا عقد مسجل: **104** · 02-2019-02: 64 · 02-2019-04: 58 · 02-2019-18: 39 · 02-2019-10: 32 · 02-2019-01: 29. باصات مكررة (حسب رقم اللوحة): 9874 و9660 و2102 — **3 حوادث لكل منها**.
**SQL:**
```sql
SELECT c.contract_number, COUNT(*) AS accidents, SUM(a.injured_students) AS injured
FROM fact_ins_accident a
LEFT JOIN dim_contract c ON c.contract_id = a.contract_id AND c.academic_year='current'
GROUP BY c.contract_number ORDER BY accidents DESC LIMIT 8;
-- repeat offenders:
SELECT plate_numbers, COUNT(*) AS accidents FROM fact_ins_accident
WHERE plate_numbers IS NOT NULL GROUP BY plate_numbers HAVING COUNT(*) > 1
ORDER BY accidents DESC LIMIT 5;
```
**Explanation:** `vehicle_id` is NULL on ALL accident rows — vehicle linkage only via `plate_numbers`/`bus_serial`. 18.5% of accidents lack contract attribution.
**Use case:** Repeat-offender bus flagging; contract safety league tables.

### Q79. كم عدد حوادث العنف على الحافلات؟
**Answer (as of 2026-08-23):** **صفر — الجدول فارغ.** جداول التصنيف موجودة (3 أنواع، 19 فئة في `dim_violence_type`/`dim_violence_category`) لكن `fact_ins_violence` لم يُحمَّل بأي سجل.
**SQL:**
```sql
SELECT (SELECT COUNT(*) FROM fact_ins_violence) AS violence_rows,
       (SELECT COUNT(*) FROM dim_violence_type) AS types,
       (SELECT COUNT(*) FROM dim_violence_category) AS categories;
```
**Explanation:** Feed defined but not populated. Answer violence questions with "no data loaded yet", not "zero incidents".
**Use case:** Caveat entry; ETL backlog item.

---

# Section J — Ridership & Trips

### Q80. كم عدد سجلات صعود الطلاب اليومية وما نسبة الحضور؟
**Answer (as of 2026-08-23):** **لا توجد بيانات — `fact_ridership_daily` فارغ تماماً (0 صف).**
**SQL:**
```sql
SELECT COUNT(*) FROM fact_ridership_daily;  -- 0
```
**Explanation:** The ridership feed (per-student boarding) is disabled/not loaded. Boarded/no-show rate questions CANNOT be answered today. Closest substitute: bus-level school-visit events (Q82–Q85) or static assignment coverage (Q8).
**Use case:** Honest-refusal entry for one of the most-requested KPIs.

### Q81. كم عدد الرحلات اليومية وما نسبة الالتزام بالوقت؟
**Answer (as of 2026-08-23):** **لا توجد بيانات — `fact_trip_daily` فارغ (0 صف).**
**SQL:**
```sql
SELECT COUNT(*) FROM fact_trip_daily;  -- 0
```
**Explanation:** Trip-daily feed (trip counts, on_time_pct, avg_delay) is disabled. On-time performance is unanswerable from the warehouse today.
**Use case:** Caveat entry; route performance questions must be declined.

### Q82. هل يوجد بديل لتتبع نشاط النقل الفعلي؟
**Answer (as of 2026-08-23):** نعم جزئياً — `fact_school_visit` (أحداث AVL): **5,878,550 حدثاً** من 2025-09-01 إلى **2026-05-17** (توقف منذ ~3 أشهر) · 12,762 مدرسة · 26,581 جهازاً.
**SQL:**
```sql
SELECT COUNT(*) AS events, MIN(event_time)::date AS first_date,
       MAX(event_time)::date AS last_date, COUNT(DISTINCT device_imei) AS devices
FROM fact_school_visit;
```
**Explanation:** GPS-derived school check-in/out events prove actual bus movement, but the feed stopped 2026-05-17 (end of school year — likely seasonal, verify in September).
**Use case:** Operational activity evidence where ridership/trips are absent.

---

# Section K — School Visits / AVL Activity

### Q83. ما هو توزيع أحداث زيارات المدارس حسب النوع؟
**Answer (as of 2026-08-23):** checkin: **2,110,006 (35.9%)** · checkout: **2,053,185 (34.9%)** · no_event: **1,715,359 (29.2%)**.
**SQL:**
```sql
SELECT event_type, COUNT(*) AS cnt
FROM fact_school_visit GROUP BY event_type ORDER BY cnt DESC;
```
**Explanation:** ~29% of expected visits produced no event (bus didn't arrive / GPS gap) — a service-reliability proxy.
**Use case:** Missed-pickup detection; operator SLA monitoring.

### Q84. ما هو حجم نشاط النقل اليومي في آخر أيام التغذية؟
**Answer (as of 2026-08-23):** 2026-05-11: **16,369 حدثاً / 3,197 باصاً** · 05-12: 14,887 / 2,953 · 05-13: 12,251 / 2,448 · 05-16: 12,603 / 2,423 · 05-14 و05-17: حدث واحد (ذيل انطفاء التغذية).
**SQL:**
```sql
SELECT event_time::date AS d, COUNT(*) AS events, COUNT(DISTINCT device_imei) AS buses
FROM fact_school_visit
WHERE event_time >= (SELECT max(event_time) FROM fact_school_visit) - INTERVAL '6 days'
GROUP BY 1 ORDER BY 1 DESC;
```
**Explanation:** ~3,000 buses/day actively served schools in the final week — vs 23,977 in the fleet dimension (many are backup/multi-region or unlinked by IMEI).
**Use case:** Active-fleet vs registered-fleet ratio; daily service volume.

### Q85. كم جهاز GPS ظهر فعلياً في بيانات الحركة مقابل الأسطول؟
**Answer (as of 2026-08-23):** **26,581 جهاز IMEI** فريد في أحداث الزيارات مقابل **17,603 حافلة** لها `device_imei` في `dim_vehicle`.
**SQL:**
```sql
SELECT COUNT(DISTINCT device_imei) AS avl_devices FROM fact_school_visit;
SELECT COUNT(*) FROM dim_vehicle WHERE device_imei IS NOT NULL;
```
**Explanation:** More devices appear in AVL data than are linked in the fleet dimension — IMEI linkage is incomplete; join coverage between the two is partial.
**Use case:** Device-registry reconciliation.

---

# Section L — Routing & Planning

### Q86. كم عدد المسارات المخططة وكم طالباً تغطي؟
**Answer (as of 2026-08-23):** **10,885 مساراً** عبر 21 عقداً و6,965 مدرسة · **288,495 طالباً مخططاً** · 0 مسارات بدون باص محلول (resolved) · أقصى جولات (rounds) لكل مدرسة: 2.
**SQL:**
```sql
SELECT COUNT(*) AS routes, COUNT(DISTINCT contract_number) AS contracts,
       COUNT(DISTINCT school_code) AS schools, SUM(students_planned) AS students_planned,
       COUNT(*) FILTER (WHERE resolved_vehicle_id IS NULL) AS unresolved, MAX(round_no) AS max_round
FROM fact_plan_route;
```
**Explanation:** Plan covers 288k of 749k students (38.5%) — planning data is loaded for a subset of contracts. `vehicle_id` holds operational-run codes (e.g. "C1-003", 8,708 distinct), not fleet serials; use `resolved_vehicle_id` to join `dim_vehicle` — but note only **59 distinct resolved vehicles** exist, so resolution is itself mostly pending.
**Use case:** Plan-vs-assignment reconciliation; which contracts have machine-readable route plans.

### Q87. ما هي أكبر العقود من حيث عدد المسارات المخططة؟
**Answer (as of 2026-08-23):** 02-2019-04: **1,811 مساراً / 83,794 طالباً** · 02-2019-06: 1,774 / 27,008 · TTC-AG-00189: 1,437 / 29,584 · 02-2019-02: 1,322 / 36,317 · 02-2019-13: 868 / 27,192.
**SQL:**
```sql
SELECT contract_number, COUNT(*) AS routes, SUM(students_planned) AS students_planned
FROM fact_plan_route GROUP BY contract_number ORDER BY routes DESC LIMIT 10;
```
**Explanation:** Route-plan granularity varies by contract (02-2019-04 averages 46 students/route vs 02-2019-06's 15 — different route definitions).
**Use case:** Planning maturity comparison across operators.

### Q88. ما هو ملخص التخطيط على مستوى المدرسة؟
**Answer (as of 2026-08-23):** **6,965 مدرسة** لها خطة · 7,119 باصاً مخططاً · 288,495 طالباً · متوسط 1.0 باص/مدرسة.
**SQL:**
```sql
SELECT COUNT(*) AS schools, SUM(bus_count) AS buses,
       SUM(students_planned) AS students_planned, ROUND(AVG(bus_count),1) AS avg_buses
FROM mv_school_plan;
```
**Explanation:** Pre-aggregated per-school plan (59% of 11,739 Noor schools have a loaded plan).
**Use case:** Quick school-level "is transport planned here?" lookups.

### Q89. ما هو جدول خدمة الباص-مدرسة اليومي (fact_school_bus_service)؟
**Answer (as of 2026-08-23):** **15,076,263 صفاً** (2024-08-18 → 2026-08-12) · 29,566 باصاً (serial_number) · 15,979 مدرسة (ministerial_number) — خريطة "أي باص يخدم أي مدرسة في أي يوم".
**SQL:**
```sql
SELECT COUNT(*) AS rows, COUNT(DISTINCT serial_number) AS buses,
       COUNT(DISTINCT ministerial_number) AS schools, MIN(sub_day) AS first_day, MAX(sub_day) AS last_day
FROM fact_school_bus_service;
```
**Explanation:** The largest table in the warehouse — daily bus↔school service mapping. Use only with date filters and aggregates; never scan wholesale. More schools (15,979) than dim tables because it accumulates history.
**Use case:** Historical "which bus served school X on day Y" lineage; service-continuity audits.

---

# Section M — Geography

### Q90. ما هي المناطق المشمولة في المستودع؟
**Answer (as of 2026-08-23):** **13 منطقة** (كل مناطق المملكة): الرياض، مكة المكرمة، عسير، الشرقية، المدينة المنورة، تبوك، حائل، جازان، نجران، الجوف، القصيم، الباحة، الحدود الشمالية (region_id 20–32).
**SQL:**
```sql
SELECT region_id, name_ar, name_en FROM dim_region ORDER BY region_id;
```
**Explanation:** Definitive region list. Default weather region is `al_baha` but the data itself is nationwide.
**Use case:** Scoping any regional question.

### Q91. أين يتركز الطلاب والمدارس جغرافياً؟
**Answer (as of 2026-08-23):** حسب الطلاب: الشرقية 153,144 > مكة 88,189 > عسير 84,478 > جازان 75,864 > القصيم 70,777. حسب المدارس: مكة 1,710 > الشرقية 1,663 > الرياض 1,474. الباحة: 349 مدرسة / 12,532 طالباً (المرتبة 12 من 13 طلابياً).
**SQL:**
```sql
SELECT n.region_name_ar, COUNT(*) AS students
FROM fact_assignment a JOIN dim_noor_school n ON n.school_code = a.school_code
GROUP BY n.region_name_ar ORDER BY students DESC;
```
**Explanation:** Combines Q12 and Q53 — student volume and school counts rank regions differently (Eastern Province has fewer schools but the biggest transported cohort, via mega-contract 02-2019-04).
**Use case:** Regional resource allocation.

### Q92. ما هي تغطية الإحداثيات الجغرافية؟
**Answer (as of 2026-08-23):** مدارس رافد: 99.0% (11,627/11,741) · مدارس نور: 99.9% (11,729/11,739) · الباحة: **100%** (349/349) · منازل الطلاب: **0%** (غير محملة).
**SQL:**
```sql
SELECT COUNT(*) FILTER (WHERE x IS NOT NULL AND y IS NOT NULL) AS with_coords, COUNT(*) AS total
FROM dim_noor_school;
```
**Explanation:** School geocoding is nearly complete; student-home geocoding is entirely absent — home-to-school distance analysis is impossible today.
**Use case:** Map-feature readiness; route-optimization input gaps.

---

# Section N — Weather & Calendar

### Q93. كم عدد الأيام الدراسية في العامين الحالي والقادم؟
**Answer (as of 2026-08-23):** 2025-2026: **246 يوماً دراسياً** من 365 يوماً (2025-08-01 → 2026-07-30) · 2026-2027: **259 يوماً دراسياً** من 364 (2026-08-01 → 2027-07-29).
**SQL:**
```sql
SELECT academic_year, COUNT(*) AS days,
       COUNT(*) FILTER (WHERE is_school_day) AS school_days,
       MIN(calendar_date) AS first_date, MAX(calendar_date) AS last_date
FROM dim_calendar GROUP BY academic_year;
```
**Explanation:** Use `is_school_day` instead of computing weekends (Sun–Thu workweek). We're currently at the start of 2026-27 (year began 2026-08-01; today is day 23).
**Use case:** Attendance-rate denominators; seasonal interpretation of operational feeds.

### Q94. ما هي الإجازات الرسمية في التقويم؟
**Answer (as of 2026-08-23):** 19 يوم إجازة مسماة عبر العامين: عيد الفطر **9 أيام** · عيد الأضحى **8** · اليوم الوطني **2**.
**SQL:**
```sql
SELECT holiday_name_ar, COUNT(*) AS days
FROM dim_calendar WHERE is_holiday
GROUP BY holiday_name_ar ORDER BY days DESC;
```
**Explanation:** Named holidays only; weekends and un-named breaks are excluded from `is_holiday` but caught by `is_school_day`.
**Use case:** Explaining zero-activity days; holiday-aware scheduling.

### Q95. ما هي إحصاءات الطقس المتاحة؟
**Answer (as of 2026-08-23):** **8 أيام فقط** محملة (2026-08-06 → 2026-08-12، منطقة الباحة): متوسط العظمى **31.8°م** / الصغرى **20.2°م** · أعلى قراءة 34.2°م · **4 أيام مطيرة** · إجمالي هطول 1.1 مم.
**SQL:**
```sql
SELECT COUNT(*) AS days, MIN(weather_date) AS first, MAX(weather_date) AS last,
       ROUND(AVG(temp_max_c),1) AS avg_max, ROUND(AVG(temp_min_c),1) AS avg_min,
       COUNT(*) FILTER (WHERE precipitation_mm > 0) AS rainy_days
FROM dim_weather_daily;
```
**Explanation:** Weather feed is sparse/stale (11 days behind). Don't use for same-day weather-context answers until the feed resumes.
**Use case:** Weather-vs-incident correlation context; feed-health monitoring.

### Q96. ما هو الطقس اليومي المسجل مؤخراً في الباحة؟
**Answer (as of 2026-08-12 آخر يوم):** 08-12: 31.0°/20.0° مطر (0.1مم) · 08-11: 32.5° غائم جزئياً · 08-10: 33.7° غائم جزئياً · 08-08: 29.3° مطر · 08-07: 29.3° مطر (0.6مم) · 08-06: 31.7° مطر.
**SQL:**
```sql
SELECT weather_date, temp_max_c, temp_min_c, precipitation_mm, conditions_ar
FROM dim_weather_daily ORDER BY weather_date DESC LIMIT 8;
```
**Explanation:** Per-day detail with Arabic condition labels — useful verbatim in answers about specific dates.
**Use case:** Date-specific weather lookups.

---

# Section O — Fleet KPIs & Daily Rollups

### Q97. ما هي أحدث قراءة يومية للأسطول (fact_fleet_daily)؟
**Answer (as of 2026-08-12):** 23,977 حافلة عبر 46 عقداً · GPS: **17,603** · احتياطية: 373 · متوسط السعة 27.4 (متوسط مرجح بالعقود، يختلف عن 38.9 لاختلاف الترجيح) · تغطية تاريخية: 678 يوماً منذ 2024-08-22.
**SQL:**
```sql
SELECT sub_day, SUM(vehicles_total) AS vehicles, SUM(vehicles_with_gps) AS with_gps,
       SUM(backup_vehicles) AS backup
FROM fact_fleet_daily WHERE sub_day = (SELECT max(sub_day) FROM fact_fleet_daily)
GROUP BY sub_day;
```
**Explanation:** Per-contract-per-day fleet rollup (`sub_day` is the date column). `vehicles_with_driver` = 0 here (broken counter — see Q20).
**Use case:** Fleet time-series; GPS-adoption trend.

### Q98. ما هي أحدث قراءة يومية للسائقين (fact_driver_daily)؟
**Answer (as of 2026-08-12):** 26,545 سائقاً · رخص منتهية: **1,275** · تنتهي خلال 90 يوماً: 951 · مجهولة: 17 · `saudi_drivers` = 0 (عداد معطّل — استخدم dim_driver).
**SQL:**
```sql
SELECT sub_day, SUM(drivers_total) AS drivers, SUM(license_expired) AS license_expired,
       SUM(license_expiring_90d) AS expiring_90d, SUM(license_unknown) AS unknown
FROM fact_driver_daily WHERE sub_day = (SELECT max(sub_day) FROM fact_driver_daily)
GROUP BY sub_day;
```
**Explanation:** Driver compliance trend table; slightly different expired count than live dim (1,275 vs 1,364) due to 11-day staleness.
**Use case:** Driver-compliance trend lines.

### Q99. ما هي أحدث قراءة لتخصيص المقاعد (fact_seat_allocation_daily)؟
**Answer (as of 2026-08-12):** 11,633 مدرسة · مقاعد مخصصة: **724,880** · محجوزة: 405,786 · طلاب مسندون: 722,584 · فجوة: **2,296 مقعداً**.
**SQL:**
```sql
SELECT sub_day, SUM(schools) AS schools, SUM(allocated_seats) AS allocated,
       SUM(reserved_seats) AS reserved, SUM(assigned_students) AS assigned, SUM(seat_gap) AS seat_gap
FROM fact_seat_allocation_daily WHERE sub_day = (SELECT max(sub_day) FROM fact_seat_allocation_daily)
GROUP BY sub_day;
```
**Explanation:** Matches `mv_school_seat_gap` totals (Q55) and Noor `assigned_students` (Q52) — three independent rollups agree, a good consistency check.
**Use case:** Seat-allocation vs reservation tracking over time.

### Q100. ما هي إحصاءات أعطال الحافلات (fact_vehicle_defect_daily)؟
**Answer (as of 2026-08-23):** **240,062 سجل** (2024-03-10 → 2026-08-12) بثلاثة أنواع: type 1: 211,102 سجل / 5,948 باصاً / 387,248 عيباً (382,196 سلامة) · type 2: 14,865 سجل / 7,728 باصاً / 25,276 عيباً · type 3: 14,095 سجل / 7,607 باصات / 22,405 عيوب. الأعطال سلامة في >98% من الحالات مقابل جودة خدمة.
**SQL:**
```sql
SELECT record_type, COUNT(*) AS rows, COUNT(DISTINCT bus_number) AS buses,
       SUM(total) AS total_defects, SUM(total_safety) AS safety, SUM(total_serviceq) AS serviceq
FROM fact_vehicle_defect_daily GROUP BY record_type;
```
**Explanation:** Defect snapshots per bus per day by record type (1/2/3 = defect report kinds from source; labels not denormalized). Safety-classified defects dominate.
**Use case:** Maintenance-priority ranking; defect-trend monitoring.

### Q101. ما هي أحدث مؤشرات KPI للحافلات (fact_vehicle_kpi)؟
**Answer (as of 2026-08-12):** 23,977 حافلة/يوم واحد · متوسط العمر 9.8 سنة · **`utilization_pct` و`riders` و`violations_count` كلها NULL** · أعلام القواعد rule_1/2/3/4/7 كلها false (0 مخالفة).
**SQL:**
```sql
SELECT as_of_date, COUNT(*) AS vehicles, AVG(utilization_pct) AS avg_util,
       SUM(violations_count) AS violations,
       COUNT(*) FILTER (WHERE rule_1_violation) AS r1
FROM fact_vehicle_kpi WHERE as_of_date = (SELECT max(as_of_date) FROM fact_vehicle_kpi)
GROUP BY as_of_date;
```
**Explanation:** The optimizer-rule KPI columns are not populated (only age and identity load). Use the assignment-based utilization in Q30 instead.
**Use case:** Caveat + fallback pattern for utilization/violation questions.

---

# Section P — Surveys

### Q102. ما هو حجم بيانات الاستبيانات؟
**Answer (as of 2026-08-23):** **62,151 إجابة** · **4,319 استبياناً مكتملاً** · استبيان واحد · 18 سؤالاً · **3,087 مدرسة** و3,900 سائق مشاركين · الفترة 2026-06-21 → 2026-07-26.
**SQL:**
```sql
SELECT COUNT(*) AS answers, COUNT(DISTINCT submission_uuid) AS submissions,
       COUNT(DISTINCT question_code) AS questions, COUNT(DISTINCT school_id) AS schools,
       MIN(submitted_at)::date AS first_sub, MAX(submitted_at)::date AS last_sub
FROM fact_survey_answer;
```
**Explanation:** A single school-transport safety survey covering 26% of schools. One submission = 18 answers (4,319×18 ≈ 77.7k > 62,151, so some submissions are partial).
**Use case:** Survey-coverage reporting; school-safety self-assessment program.

### Q103. ما هي فئات أسئلة الاستبيان؟
**Answer (as of 2026-08-23):** صعود ونزول الطلاب: **25,914 إجابة** · مواقف حافلات المدرسة: 18,961 · التشغيل والحركة المرورية: 8,638 · تهيئة ذوي الإعاقة: 8,638.
**SQL:**
```sql
SELECT category_name_ar, COUNT(*) AS answers
FROM fact_survey_answer GROUP BY category_name_ar ORDER BY answers DESC;
```
**Explanation:** Four themes: boarding/alighting safety, school bus-parking, traffic operations, disability accessibility.
**Use case:** Structuring survey-insight summaries.

### Q104. ما هو توزيع إجابات الاستبيان؟
**Answer (as of 2026-08-23):** "لا": **36,735 (59.1%)** · "نعم": 21,097 (33.9%) · "متوسط": 2,349 · "منخفض": 1,313 · "مرتفع": 657. كل سؤال أُجيب 4,319 مرة بالضبط.
**SQL:**
```sql
SELECT answer_label_ar, COUNT(*) AS cnt
FROM fact_survey_answer GROUP BY answer_label_ar ORDER BY cnt DESC;
```
**Explanation:** Mostly yes/no questions plus a 3-level scale (منخفض/متوسط/مرتفع) on risk items.
**Use case:** Baseline sentiment; per-question drilling.

### Q105. ما هي أبرز مخاطر السلامة حسب الاستبيان؟
**Answer (as of 2026-08-23، نسبة "نعم" من 4,319 استجابة لكل سؤال):** توجد منطقة مخصصة لتحميل/تنزيل الطلبة: **40.9% نعم** (أي 59.1% بلا منطقة مخصصة!) · تتوقف الحافلات على الشارع العام: **11.2%** · مخاطر مرورية أثناء التحميل: **9.4%** · يضطر الطلاب لعبور شارع: **8.1%**.
**SQL:**
```sql
SELECT question_text_ar,
       ROUND(100.0*COUNT(*) FILTER (WHERE answer_label_ar='نعم')/COUNT(*),1) AS yes_pct,
       COUNT(*) AS responses
FROM fact_survey_answer
WHERE question_text_ar IN (
  'هل توجد مخاطر مرورية أثناء تحميل وتنزيل الطلبة؟',
  'هل تضطر الحافلات للتوقف على الشارع العام أثناء تحميل أو تنزيل الطلبة؟',
  'هل يضطر الطلاب لعبور شارع للوصول إلى الحافلة؟',
  'هل توجد منطقة مخصصة لتحميل وتنزيل الطلبة؟')
GROUP BY question_text_ar;
```
**Explanation:** The headline: ~59% of surveyed schools lack a designated loading zone — the single most actionable infrastructure finding. Street-crossing and traffic-hazard exposure affect ~1 in 12 schools.
**Use case:** School-infrastructure investment prioritization; safety-campaign targeting.

---

# Section Q — Disabled / Empty Feeds (honest refusals)

### Q106. ما هي مصادر البيانات المعطلة أو الفارغة حالياً؟
**Answer (as of 2026-08-23):** الجداول التالية موجودة في المخطط لكنها **فارغة تماماً (0 صف)** — أي سؤال عنها يجب أن يُرفض بصدق مع ذكر السبب:

| Table | Domain | Status |
|---|---|---|
| `fact_ridership_daily` | per-student boarding | empty — feed disabled |
| `fact_trip_daily` | trips / on-time % | empty — feed disabled |
| `fact_complaint` | complaints | empty — feed disabled |
| `fact_fuel` | fuel transactions | empty — feed disabled |
| `fact_maintenance` | maintenance events | empty — feed disabled |
| `fact_geofence_event` + `dim_geofence` | geofencing | empty — feed disabled |
| `fact_driver_compliance` | driver daily compliance | empty — feed disabled |
| `fact_app_inspection` / `fact_app_accident` / `fact_app_route_plan` | Rafed app reports | empty — app feeds disabled |
| `fact_ins_violence` | violence incidents | empty — feed not loaded |

**SQL:**
```sql
SELECT (SELECT COUNT(*) FROM fact_ridership_daily) AS ridership,
       (SELECT COUNT(*) FROM fact_trip_daily)     AS trips,
       (SELECT COUNT(*) FROM fact_complaint)      AS complaints,
       (SELECT COUNT(*) FROM fact_fuel)           AS fuel,
       (SELECT COUNT(*) FROM fact_maintenance)    AS maintenance,
       (SELECT COUNT(*) FROM fact_geofence_event) AS geofence_events,
       (SELECT COUNT(*) FROM fact_driver_compliance) AS driver_compliance,
       (SELECT COUNT(*) FROM fact_ins_violence)   AS violence;
-- all 0 on 2026-08-23
```
**Explanation:** These are schema-ready tables whose ETL feeds are off. "No data" ≠ "zero events" — always phrase refusals as "this feed is not loaded yet" and suggest the nearest populated alternative (e.g. assignments for ridership, school visits for trips, safety-app reports for incidents).
**Use case:** Preventing fabricated answers for the most common unavailable domains.

---

# Known data caveats (verified 2026-08-23)

Verified live unless noted (source: `WAREHOUSE_SCHEMA.md` §12 + this file's queries):

1. **Coverage is nationwide (13 regions), not Al-Baha only** — older docs are stale. Al-Baha: 349 schools, 12,532 students. (Q3, Q12, Q90)
2. **`fact_assignment.vehicle_id` NULL for 47.25%** of students (Q8); coverage near-zero in Al-Baha (0.19%) (Q13).
3. **`fact_assignment.gender` (code) 100% NULL** — use `gender_label_ar`. (Q5)
4. **`fact_assignment.school_id` ≈ never joins `dim_school`** (174/748,909) — join via `school_code → dim_noor_school.school_code` (97.4%). (Q15, conventions)
5. **`rafed_tier`, `driver_id`, `home_x/home_y/distance_km` on assignments: 0% populated.** (Q17)
6. **`dim_contract.amount` = 0 everywhere** — no financial values. `sector_name_ar`/`administration_name_ar` NULL on contracts — use school dims for geography. (Q43, Q12)
7. **`dim_vehicle` text expiry dates currently 100% parseable** — keep regex guard anyway. (Q27)
8. **`dim_vehicle.has_driver` 100% true / `is_gps_connected` 100% false / `is_special_needs` 0** — defaults, not data. (Q19, Q20, Q26)
9. **`dim_driver.is_first_aid` 100% true; `traffic_points` 100% NULL; 64 junk ages.** (Q35, Q37, Q38)
10. **`dim_escort.is_active` 0 active** — flag not populated. (Q39)
11. **`ins_workorders` holds only the current campaign (Aug 2026)** — not full history. (Q58)
12. **`fact_inspection_answer` free-text answers with spelling variants; remediation flags barely used** (538 solved / 3,674 escalated). (Q64, Q65)
13. **`fact_ins_accident.vehicle_id` 100% NULL** — use plates for repeat offenders. 47 rows lack dates; 104 lack contract. (Q78)
14. **PII:** names/NIDs are SHA-256 hashes; `fact_safety_check`/`fact_safety_accident` carry raw driver NID — never echo. (conventions)
15. **`fact_daily_snapshot` and daily rollups stale ~11 days** (latest 2026-08-12) though dimensions are fresh to today's hourly run. (Q1, freshness block)
16. **`fact_vehicle_kpi` utilization/violation columns NULL; `mv_plan_summary.bus_target_pct` looks miscalculated (avg 175%).** (Q101, Q46)
17. **`fact_school_visit` feed stopped 2026-05-17** (likely seasonal). (Q82)
18. **`dim_noor_school.student_count` = 0, `allocated_seats` NULL** — use `assigned_students`. (Q52)

---

# Index — domain → questions

| Domain | Questions | Count |
|---|---|---|
| Overall daily snapshot | Q1–Q3 | 3 |
| Students & Assignments | Q4–Q17 | 14 |
| Vehicles & Fleet | Q18–Q31 | 14 |
| Drivers & Escorts | Q32–Q41 | 10 |
| Contracts & Operators | Q42–Q50 | 9 |
| Schools | Q51–Q57 | 7 |
| Inspections & Compliance | Q58–Q68 | 11 |
| Safety Checks | Q69–Q72 | 4 |
| Accidents & Violence | Q73–Q79 | 7 |
| Ridership & Trips | Q80–Q82 | 3 |
| School Visits / AVL | Q83–Q85 | 3 |
| Routing & Planning | Q86–Q89 | 4 |
| Geography | Q90–Q92 | 3 |
| Weather & Calendar | Q93–Q96 | 4 |
| Fleet KPIs & Daily Rollups | Q97–Q101 | 5 |
| Surveys | Q102–Q105 | 4 |
| Disabled / Empty Feeds | Q106 | 1 |
| **Total** | **Q1–Q106** | **106** |

---

*Generated 2026-08-23 by live queries against the `rafed_ai` warehouse (schema `v_current`, ETL run `db43535c`, hourly group, succeeded 10:00 UTC). Query scripts preserved under `scripts/etl/_kb-*.ts`. Every figure in this file comes from a query actually executed against the live database on 2026-08-23; none was copied from older reports.*

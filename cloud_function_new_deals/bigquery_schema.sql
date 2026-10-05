-- State + sink for the create-date layer (dataset `hubspot`; adjust to your sync dataset)
CREATE TABLE IF NOT EXISTS `your_project.hubspot.report_state` (
  report_id STRING NOT NULL, watermark TIMESTAMP NOT NULL, updated_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS `your_project.hubspot.new_deals` (
  entity STRING, deal_id STRING NOT NULL, dealname STRING, final_customer STRING, name_key STRING,
  createdate TIMESTAMP, created_by_user_id STRING, source STRING, owner STRING, sales_region STRING,
  pipeline STRING, pipeline_id STRING, stage STRING, probability_pct FLOAT64, amount FLOAT64, currency STRING, amount_kusd FLOAT64,
  closedate DATE, arr_ky FLOAT64, product_family STRING, product STRING, application STRING, icalps_dealtype STRING, icalps_stage STRING,
  day1_hot_score FLOAT64, day1_hot_flag BOOL, duplicate_suspect BOOL, duplicate_of STRING, deal_url STRING,
  first_seen_run TIMESTAMP, last_seen_run TIMESTAMP)
PARTITION BY DATE(createdate) CLUSTER BY entity, deal_id;

-- staging table is (re)created by the function's load job; grant the service account bigquery.dataEditor on the dataset.

-- Weekly view used by the delivery step / Breeze consumption (new deals created in the last 7 days, newest first)
CREATE OR REPLACE VIEW `your_project.hubspot.new_deals_last_7d` AS
SELECT * EXCEPT(name_key) FROM `your_project.hubspot.new_deals`
WHERE createdate >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY entity, amount_kusd DESC, createdate DESC;

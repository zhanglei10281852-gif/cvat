--
-- Create model AnnotationConflict
--
CREATE TABLE "quality_control_annotationconflict" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "frame" integer unsigned NOT NULL CHECK ("frame" >= 0), "type" varchar(32) NOT NULL, "severity" varchar(32) NOT NULL);
--
-- Create model QualitySettings
--
CREATE TABLE "quality_control_qualitysettings" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "iou_threshold" real NOT NULL, "oks_sigma" real NOT NULL, "line_thickness" real NOT NULL, "low_overlap_threshold" real NOT NULL, "compare_line_orientation" bool NOT NULL, "line_orientation_threshold" real NOT NULL, "compare_groups" bool NOT NULL, "group_match_threshold" real NOT NULL, "check_covered_annotations" bool NOT NULL, "object_visibility_threshold" real NOT NULL, "panoptic_comparison" bool NOT NULL, "compare_attributes" bool NOT NULL, "task_id" integer NOT NULL UNIQUE REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED);
--
-- Create model QualityReport
--
CREATE TABLE "quality_control_qualityreport" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "created_date" datetime NOT NULL, "target_last_updated" datetime NOT NULL, "gt_last_updated" datetime NOT NULL, "data" text NOT NULL CHECK ((JSON_VALID("data") OR "data" IS NULL)), "job_id" integer NULL REFERENCES "engine_job" ("id") DEFERRABLE INITIALLY DEFERRED, "parent_id" integer NULL REFERENCES "quality_control_qualityreport" ("id") DEFERRABLE INITIALLY DEFERRED, "task_id" integer NULL REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED);
--
-- Create model AnnotationId
--
CREATE TABLE "quality_control_annotationid" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "obj_id" integer unsigned NOT NULL CHECK ("obj_id" >= 0), "job_id" integer unsigned NOT NULL CHECK ("job_id" >= 0), "type" varchar(32) NOT NULL, "shape_type" varchar(32) NULL, "conflict_id" integer NOT NULL REFERENCES "quality_control_annotationconflict" ("id") DEFERRABLE INITIALLY DEFERRED);
--
-- Add field report to annotationconflict
--
CREATE TABLE "new__quality_control_annotationconflict" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "frame" integer unsigned NOT NULL CHECK ("frame" >= 0), "type" varchar(32) NOT NULL, "severity" varchar(32) NOT NULL, "report_id" integer NOT NULL REFERENCES "quality_control_qualityreport" ("id") DEFERRABLE INITIALLY DEFERRED);
INSERT INTO "new__quality_control_annotationconflict" ("id", "frame", "type", "severity", "report_id") SELECT "id", "frame", "type", "severity", NULL FROM "quality_control_annotationconflict";
DROP TABLE "quality_control_annotationconflict";
ALTER TABLE "new__quality_control_annotationconflict" RENAME TO "quality_control_annotationconflict";
CREATE INDEX "quality_control_qualityreport_job_id_87a701d0" ON "quality_control_qualityreport" ("job_id");
CREATE INDEX "quality_control_qualityreport_parent_id_121b546f" ON "quality_control_qualityreport" ("parent_id");
CREATE INDEX "quality_control_qualityreport_task_id_75d2cf12" ON "quality_control_qualityreport" ("task_id");
CREATE INDEX "quality_control_annotationid_conflict_id_9142c394" ON "quality_control_annotationid" ("conflict_id");
CREATE INDEX "quality_control_annotationconflict_report_id_6a3a89f9" ON "quality_control_annotationconflict" ("report_id");
--
-- Add field assignee to qualityreport
--
ALTER TABLE "quality_control_qualityreport" ADD COLUMN "assignee_id" integer NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED;
--
-- Add field assignee_last_updated to qualityreport
--
ALTER TABLE "quality_control_qualityreport" ADD COLUMN "assignee_last_updated" datetime NULL;
--
-- Add field max_validations_per_job to qualitysettings
--
CREATE TABLE "new__quality_control_qualitysettings" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "iou_threshold" real NOT NULL, "oks_sigma" real NOT NULL, "line_thickness" real NOT NULL, "low_overlap_threshold" real NOT NULL, "compare_line_orientation" bool NOT NULL, "line_orientation_threshold" real NOT NULL, "compare_groups" bool NOT NULL, "group_match_threshold" real NOT NULL, "check_covered_annotations" bool NOT NULL, "object_visibility_threshold" real NOT NULL, "panoptic_comparison" bool NOT NULL, "compare_attributes" bool NOT NULL, "task_id" integer NOT NULL UNIQUE REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED, "max_validations_per_job" integer unsigned NOT NULL CHECK ("max_validations_per_job" >= 0));
INSERT INTO "new__quality_control_qualitysettings" ("id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job") SELECT "id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", 0 FROM "quality_control_qualitysettings";
DROP TABLE "quality_control_qualitysettings";
ALTER TABLE "new__quality_control_qualitysettings" RENAME TO "quality_control_qualitysettings";
CREATE INDEX "quality_control_qualityreport_assignee_id_cd51795f" ON "quality_control_qualityreport" ("assignee_id");
--
-- Add field target_metric to qualitysettings
--
CREATE TABLE "new__quality_control_qualitysettings" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "iou_threshold" real NOT NULL, "oks_sigma" real NOT NULL, "line_thickness" real NOT NULL, "low_overlap_threshold" real NOT NULL, "compare_line_orientation" bool NOT NULL, "line_orientation_threshold" real NOT NULL, "compare_groups" bool NOT NULL, "group_match_threshold" real NOT NULL, "check_covered_annotations" bool NOT NULL, "object_visibility_threshold" real NOT NULL, "panoptic_comparison" bool NOT NULL, "compare_attributes" bool NOT NULL, "task_id" integer NOT NULL UNIQUE REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED, "max_validations_per_job" integer unsigned NOT NULL CHECK ("max_validations_per_job" >= 0), "target_metric" varchar(32) NOT NULL);
INSERT INTO "new__quality_control_qualitysettings" ("id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric") SELECT "id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", 'accuracy' FROM "quality_control_qualitysettings";
DROP TABLE "quality_control_qualitysettings";
ALTER TABLE "new__quality_control_qualitysettings" RENAME TO "quality_control_qualitysettings";
--
-- Add field target_metric_threshold to qualitysettings
--
CREATE TABLE "new__quality_control_qualitysettings" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "iou_threshold" real NOT NULL, "oks_sigma" real NOT NULL, "line_thickness" real NOT NULL, "low_overlap_threshold" real NOT NULL, "compare_line_orientation" bool NOT NULL, "line_orientation_threshold" real NOT NULL, "compare_groups" bool NOT NULL, "group_match_threshold" real NOT NULL, "check_covered_annotations" bool NOT NULL, "object_visibility_threshold" real NOT NULL, "panoptic_comparison" bool NOT NULL, "compare_attributes" bool NOT NULL, "task_id" integer NOT NULL UNIQUE REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED, "max_validations_per_job" integer unsigned NOT NULL CHECK ("max_validations_per_job" >= 0), "target_metric" varchar(32) NOT NULL, "target_metric_threshold" real NOT NULL);
INSERT INTO "new__quality_control_qualitysettings" ("id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold") SELECT "id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", 0.7 FROM "quality_control_qualitysettings";
DROP TABLE "quality_control_qualitysettings";
ALTER TABLE "new__quality_control_qualitysettings" RENAME TO "quality_control_qualitysettings";
--
-- Add field point_size_base to qualitysettings
--
CREATE TABLE "new__quality_control_qualitysettings" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "iou_threshold" real NOT NULL, "oks_sigma" real NOT NULL, "line_thickness" real NOT NULL, "low_overlap_threshold" real NOT NULL, "compare_line_orientation" bool NOT NULL, "line_orientation_threshold" real NOT NULL, "compare_groups" bool NOT NULL, "group_match_threshold" real NOT NULL, "check_covered_annotations" bool NOT NULL, "object_visibility_threshold" real NOT NULL, "panoptic_comparison" bool NOT NULL, "compare_attributes" bool NOT NULL, "task_id" integer NOT NULL UNIQUE REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED, "max_validations_per_job" integer unsigned NOT NULL CHECK ("max_validations_per_job" >= 0), "target_metric" varchar(32) NOT NULL, "target_metric_threshold" real NOT NULL, "point_size_base" varchar(32) NOT NULL);
INSERT INTO "new__quality_control_qualitysettings" ("id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base") SELECT "id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", 'group_bbox_size' FROM "quality_control_qualitysettings";
DROP TABLE "quality_control_qualitysettings";
ALTER TABLE "new__quality_control_qualitysettings" RENAME TO "quality_control_qualitysettings";
--
-- Add field match_empty_frames to qualitysettings
--
CREATE TABLE "new__quality_control_qualitysettings" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "iou_threshold" real NOT NULL, "oks_sigma" real NOT NULL, "line_thickness" real NOT NULL, "low_overlap_threshold" real NOT NULL, "compare_line_orientation" bool NOT NULL, "line_orientation_threshold" real NOT NULL, "compare_groups" bool NOT NULL, "group_match_threshold" real NOT NULL, "check_covered_annotations" bool NOT NULL, "object_visibility_threshold" real NOT NULL, "panoptic_comparison" bool NOT NULL, "compare_attributes" bool NOT NULL, "task_id" integer NOT NULL UNIQUE REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED, "max_validations_per_job" integer unsigned NOT NULL CHECK ("max_validations_per_job" >= 0), "target_metric" varchar(32) NOT NULL, "target_metric_threshold" real NOT NULL, "point_size_base" varchar(32) NOT NULL, "match_empty_frames" bool NOT NULL);
INSERT INTO "new__quality_control_qualitysettings" ("id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", "match_empty_frames") SELECT "id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", 0 FROM "quality_control_qualitysettings";
DROP TABLE "quality_control_qualitysettings";
ALTER TABLE "new__quality_control_qualitysettings" RENAME TO "quality_control_qualitysettings";
--
-- Rename field match_empty_frames on qualitysettings to empty_is_annotated
--
ALTER TABLE "quality_control_qualitysettings" RENAME COLUMN "match_empty_frames" TO "empty_is_annotated";
--
-- Add field created_date to qualitysettings
--
CREATE TABLE "new__quality_control_qualitysettings" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "iou_threshold" real NOT NULL, "oks_sigma" real NOT NULL, "line_thickness" real NOT NULL, "low_overlap_threshold" real NOT NULL, "compare_line_orientation" bool NOT NULL, "line_orientation_threshold" real NOT NULL, "compare_groups" bool NOT NULL, "group_match_threshold" real NOT NULL, "check_covered_annotations" bool NOT NULL, "object_visibility_threshold" real NOT NULL, "panoptic_comparison" bool NOT NULL, "compare_attributes" bool NOT NULL, "task_id" integer NOT NULL UNIQUE REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED, "max_validations_per_job" integer unsigned NOT NULL CHECK ("max_validations_per_job" >= 0), "target_metric" varchar(32) NOT NULL, "target_metric_threshold" real NOT NULL, "point_size_base" varchar(32) NOT NULL, "empty_is_annotated" bool NOT NULL, "created_date" datetime NOT NULL);
INSERT INTO "new__quality_control_qualitysettings" ("id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", "empty_is_annotated", "created_date") SELECT "id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", "empty_is_annotated", '2026-10-02 14:35:56.207988' FROM "quality_control_qualitysettings";
DROP TABLE "quality_control_qualitysettings";
ALTER TABLE "new__quality_control_qualitysettings" RENAME TO "quality_control_qualitysettings";
--
-- Add field updated_date to qualitysettings
--
CREATE TABLE "new__quality_control_qualitysettings" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "iou_threshold" real NOT NULL, "oks_sigma" real NOT NULL, "line_thickness" real NOT NULL, "low_overlap_threshold" real NOT NULL, "compare_line_orientation" bool NOT NULL, "line_orientation_threshold" real NOT NULL, "compare_groups" bool NOT NULL, "group_match_threshold" real NOT NULL, "check_covered_annotations" bool NOT NULL, "object_visibility_threshold" real NOT NULL, "panoptic_comparison" bool NOT NULL, "compare_attributes" bool NOT NULL, "task_id" integer NOT NULL UNIQUE REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED, "max_validations_per_job" integer unsigned NOT NULL CHECK ("max_validations_per_job" >= 0), "target_metric" varchar(32) NOT NULL, "target_metric_threshold" real NOT NULL, "point_size_base" varchar(32) NOT NULL, "empty_is_annotated" bool NOT NULL, "created_date" datetime NOT NULL, "updated_date" datetime NOT NULL);
INSERT INTO "new__quality_control_qualitysettings" ("id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", "empty_is_annotated", "created_date", "updated_date") SELECT "id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", "empty_is_annotated", "created_date", '2026-10-02 14:35:56.212084' FROM "quality_control_qualitysettings";
DROP TABLE "quality_control_qualitysettings";
ALTER TABLE "new__quality_control_qualitysettings" RENAME TO "quality_control_qualitysettings";
--
-- Raw Python operation
--
-- THIS OPERATION CANNOT BE WRITTEN AS SQL
--
-- Add field parents to qualityreport
--
CREATE TABLE "quality_control_qualityreport_parents" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "from_qualityreport_id" integer NOT NULL REFERENCES "quality_control_qualityreport" ("id") DEFERRABLE INITIALLY DEFERRED, "to_qualityreport_id" integer NOT NULL REFERENCES "quality_control_qualityreport" ("id") DEFERRABLE INITIALLY DEFERRED);
--
-- Raw Python operation
--
-- THIS OPERATION CANNOT BE WRITTEN AS SQL
--
-- Remove field parent from qualityreport
--
CREATE TABLE "new__quality_control_qualityreport" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "created_date" datetime NOT NULL, "target_last_updated" datetime NOT NULL, "gt_last_updated" datetime NOT NULL, "data" text NOT NULL CHECK ((JSON_VALID("data") OR "data" IS NULL)), "job_id" integer NULL REFERENCES "engine_job" ("id") DEFERRABLE INITIALLY DEFERRED, "task_id" integer NULL REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED, "assignee_id" integer NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED, "assignee_last_updated" datetime NULL);
INSERT INTO "new__quality_control_qualityreport" ("id", "created_date", "target_last_updated", "gt_last_updated", "data", "job_id", "task_id", "assignee_id", "assignee_last_updated") SELECT "id", "created_date", "target_last_updated", "gt_last_updated", "data", "job_id", "task_id", "assignee_id", "assignee_last_updated" FROM "quality_control_qualityreport";
DROP TABLE "quality_control_qualityreport";
ALTER TABLE "new__quality_control_qualityreport" RENAME TO "quality_control_qualityreport";
CREATE UNIQUE INDEX "quality_control_qualityreport_parents_from_qualityreport_id_to_qualityreport_id_9e903bcb_uniq" ON "quality_control_qualityreport_parents" ("from_qualityreport_id", "to_qualityreport_id");
CREATE INDEX "quality_control_qualityreport_parents_from_qualityreport_id_086b7587" ON "quality_control_qualityreport_parents" ("from_qualityreport_id");
CREATE INDEX "quality_control_qualityreport_parents_to_qualityreport_id_0f7a284c" ON "quality_control_qualityreport_parents" ("to_qualityreport_id");
CREATE INDEX "quality_control_qualityreport_job_id_87a701d0" ON "quality_control_qualityreport" ("job_id");
CREATE INDEX "quality_control_qualityreport_task_id_75d2cf12" ON "quality_control_qualityreport" ("task_id");
CREATE INDEX "quality_control_qualityreport_assignee_id_cd51795f" ON "quality_control_qualityreport" ("assignee_id");
--
-- Alter field parents on qualityreport
--
-- (no-op)
--
-- Add field project to qualityreport
--
ALTER TABLE "quality_control_qualityreport" ADD COLUMN "project_id" integer NULL REFERENCES "engine_project" ("id") DEFERRABLE INITIALLY DEFERRED;
--
-- Raw Python operation
--
-- THIS OPERATION CANNOT BE WRITTEN AS SQL
--
-- Add field inherit to qualitysettings
--
CREATE TABLE "new__quality_control_qualitysettings" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "iou_threshold" real NOT NULL, "oks_sigma" real NOT NULL, "line_thickness" real NOT NULL, "low_overlap_threshold" real NOT NULL, "compare_line_orientation" bool NOT NULL, "line_orientation_threshold" real NOT NULL, "compare_groups" bool NOT NULL, "group_match_threshold" real NOT NULL, "check_covered_annotations" bool NOT NULL, "object_visibility_threshold" real NOT NULL, "panoptic_comparison" bool NOT NULL, "compare_attributes" bool NOT NULL, "task_id" integer NOT NULL UNIQUE REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED, "max_validations_per_job" integer unsigned NOT NULL CHECK ("max_validations_per_job" >= 0), "target_metric" varchar(32) NOT NULL, "target_metric_threshold" real NOT NULL, "point_size_base" varchar(32) NOT NULL, "empty_is_annotated" bool NOT NULL, "created_date" datetime NOT NULL, "updated_date" datetime NOT NULL, "inherit" bool NOT NULL);
INSERT INTO "new__quality_control_qualitysettings" ("id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", "empty_is_annotated", "created_date", "updated_date", "inherit") SELECT "id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", "empty_is_annotated", "created_date", "updated_date", 1 FROM "quality_control_qualitysettings";
DROP TABLE "quality_control_qualitysettings";
ALTER TABLE "new__quality_control_qualitysettings" RENAME TO "quality_control_qualitysettings";
CREATE INDEX "quality_control_qualityreport_project_id_3dcd718d" ON "quality_control_qualityreport" ("project_id");
--
-- Add field project to qualitysettings
--
CREATE TABLE "new__quality_control_qualitysettings" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "iou_threshold" real NOT NULL, "oks_sigma" real NOT NULL, "line_thickness" real NOT NULL, "low_overlap_threshold" real NOT NULL, "compare_line_orientation" bool NOT NULL, "line_orientation_threshold" real NOT NULL, "compare_groups" bool NOT NULL, "group_match_threshold" real NOT NULL, "check_covered_annotations" bool NOT NULL, "object_visibility_threshold" real NOT NULL, "panoptic_comparison" bool NOT NULL, "compare_attributes" bool NOT NULL, "task_id" integer NOT NULL UNIQUE REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED, "max_validations_per_job" integer unsigned NOT NULL CHECK ("max_validations_per_job" >= 0), "target_metric" varchar(32) NOT NULL, "target_metric_threshold" real NOT NULL, "point_size_base" varchar(32) NOT NULL, "empty_is_annotated" bool NOT NULL, "created_date" datetime NOT NULL, "updated_date" datetime NOT NULL, "inherit" bool NOT NULL, "project_id" integer NULL UNIQUE REFERENCES "engine_project" ("id") DEFERRABLE INITIALLY DEFERRED);
INSERT INTO "new__quality_control_qualitysettings" ("id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", "empty_is_annotated", "created_date", "updated_date", "inherit", "project_id") SELECT "id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", "empty_is_annotated", "created_date", "updated_date", "inherit", NULL FROM "quality_control_qualitysettings";
DROP TABLE "quality_control_qualitysettings";
ALTER TABLE "new__quality_control_qualitysettings" RENAME TO "quality_control_qualitysettings";
--
-- Alter field gt_last_updated on qualityreport
--
CREATE TABLE "new__quality_control_qualityreport" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "created_date" datetime NOT NULL, "target_last_updated" datetime NOT NULL, "data" text NOT NULL CHECK ((JSON_VALID("data") OR "data" IS NULL)), "job_id" integer NULL REFERENCES "engine_job" ("id") DEFERRABLE INITIALLY DEFERRED, "task_id" integer NULL REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED, "assignee_id" integer NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED, "assignee_last_updated" datetime NULL, "project_id" integer NULL REFERENCES "engine_project" ("id") DEFERRABLE INITIALLY DEFERRED, "gt_last_updated" datetime NULL);
INSERT INTO "new__quality_control_qualityreport" ("id", "created_date", "target_last_updated", "data", "job_id", "task_id", "assignee_id", "assignee_last_updated", "project_id", "gt_last_updated") SELECT "id", "created_date", "target_last_updated", "data", "job_id", "task_id", "assignee_id", "assignee_last_updated", "project_id", "gt_last_updated" FROM "quality_control_qualityreport";
DROP TABLE "quality_control_qualityreport";
ALTER TABLE "new__quality_control_qualityreport" RENAME TO "quality_control_qualityreport";
CREATE INDEX "quality_control_qualityreport_job_id_87a701d0" ON "quality_control_qualityreport" ("job_id");
CREATE INDEX "quality_control_qualityreport_task_id_75d2cf12" ON "quality_control_qualityreport" ("task_id");
CREATE INDEX "quality_control_qualityreport_assignee_id_cd51795f" ON "quality_control_qualityreport" ("assignee_id");
CREATE INDEX "quality_control_qualityreport_project_id_3dcd718d" ON "quality_control_qualityreport" ("project_id");
--
-- Raw Python operation
--
-- THIS OPERATION CANNOT BE WRITTEN AS SQL
--
-- Alter field task on qualitysettings
--
CREATE TABLE "new__quality_control_qualitysettings" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "iou_threshold" real NOT NULL, "oks_sigma" real NOT NULL, "line_thickness" real NOT NULL, "low_overlap_threshold" real NOT NULL, "compare_line_orientation" bool NOT NULL, "line_orientation_threshold" real NOT NULL, "compare_groups" bool NOT NULL, "group_match_threshold" real NOT NULL, "check_covered_annotations" bool NOT NULL, "object_visibility_threshold" real NOT NULL, "panoptic_comparison" bool NOT NULL, "compare_attributes" bool NOT NULL, "max_validations_per_job" integer unsigned NOT NULL CHECK ("max_validations_per_job" >= 0), "target_metric" varchar(32) NOT NULL, "target_metric_threshold" real NOT NULL, "point_size_base" varchar(32) NOT NULL, "empty_is_annotated" bool NOT NULL, "created_date" datetime NOT NULL, "updated_date" datetime NOT NULL, "inherit" bool NOT NULL, "project_id" integer NULL UNIQUE REFERENCES "engine_project" ("id") DEFERRABLE INITIALLY DEFERRED, "task_id" integer NULL UNIQUE REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED);
INSERT INTO "new__quality_control_qualitysettings" ("id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", "empty_is_annotated", "created_date", "updated_date", "inherit", "project_id", "task_id") SELECT "id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", "empty_is_annotated", "created_date", "updated_date", "inherit", "project_id", "task_id" FROM "quality_control_qualitysettings";
DROP TABLE "quality_control_qualitysettings";
ALTER TABLE "new__quality_control_qualitysettings" RENAME TO "quality_control_qualitysettings";
--
-- Raw Python operation
--
-- THIS OPERATION CANNOT BE WRITTEN AS SQL
--
-- Add field job_filter to qualitysettings
--
CREATE TABLE "new__quality_control_qualitysettings" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "iou_threshold" real NOT NULL, "oks_sigma" real NOT NULL, "line_thickness" real NOT NULL, "low_overlap_threshold" real NOT NULL, "compare_line_orientation" bool NOT NULL, "line_orientation_threshold" real NOT NULL, "compare_groups" bool NOT NULL, "group_match_threshold" real NOT NULL, "check_covered_annotations" bool NOT NULL, "object_visibility_threshold" real NOT NULL, "panoptic_comparison" bool NOT NULL, "compare_attributes" bool NOT NULL, "task_id" integer NULL UNIQUE REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED, "max_validations_per_job" integer unsigned NOT NULL CHECK ("max_validations_per_job" >= 0), "target_metric" varchar(32) NOT NULL, "target_metric_threshold" real NOT NULL, "point_size_base" varchar(32) NOT NULL, "empty_is_annotated" bool NOT NULL, "created_date" datetime NOT NULL, "updated_date" datetime NOT NULL, "inherit" bool NOT NULL, "project_id" integer NULL UNIQUE REFERENCES "engine_project" ("id") DEFERRABLE INITIALLY DEFERRED, "job_filter" text NOT NULL);
INSERT INTO "new__quality_control_qualitysettings" ("id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", "empty_is_annotated", "created_date", "updated_date", "inherit", "project_id", "job_filter") SELECT "id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", "empty_is_annotated", "created_date", "updated_date", "inherit", "project_id", '{"==": [{"var": "type"}, "annotation"]}' FROM "quality_control_qualitysettings";
DROP TABLE "quality_control_qualitysettings";
ALTER TABLE "new__quality_control_qualitysettings" RENAME TO "quality_control_qualitysettings";
--
-- Create constraint quality_settings_task_or_project on model qualitysettings
--
CREATE TABLE "new__quality_control_qualitysettings" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "iou_threshold" real NOT NULL, "oks_sigma" real NOT NULL, "line_thickness" real NOT NULL, "low_overlap_threshold" real NOT NULL, "compare_line_orientation" bool NOT NULL, "line_orientation_threshold" real NOT NULL, "compare_groups" bool NOT NULL, "group_match_threshold" real NOT NULL, "check_covered_annotations" bool NOT NULL, "object_visibility_threshold" real NOT NULL, "panoptic_comparison" bool NOT NULL, "compare_attributes" bool NOT NULL, "task_id" integer NULL UNIQUE REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED, "max_validations_per_job" integer unsigned NOT NULL CHECK ("max_validations_per_job" >= 0), "target_metric" varchar(32) NOT NULL, "target_metric_threshold" real NOT NULL, "point_size_base" varchar(32) NOT NULL, "empty_is_annotated" bool NOT NULL, "created_date" datetime NOT NULL, "updated_date" datetime NOT NULL, "inherit" bool NOT NULL, "project_id" integer NULL UNIQUE REFERENCES "engine_project" ("id") DEFERRABLE INITIALLY DEFERRED, "job_filter" text NOT NULL, CONSTRAINT "quality_settings_task_or_project" CHECK ((("project_id" IS NULL AND "task_id" IS NOT NULL) OR ("project_id" IS NOT NULL AND "task_id" IS NULL))));
INSERT INTO "new__quality_control_qualitysettings" ("id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", "empty_is_annotated", "created_date", "updated_date", "inherit", "project_id", "job_filter") SELECT "id", "iou_threshold", "oks_sigma", "line_thickness", "low_overlap_threshold", "compare_line_orientation", "line_orientation_threshold", "compare_groups", "group_match_threshold", "check_covered_annotations", "object_visibility_threshold", "panoptic_comparison", "compare_attributes", "task_id", "max_validations_per_job", "target_metric", "target_metric_threshold", "point_size_base", "empty_is_annotated", "created_date", "updated_date", "inherit", "project_id", "job_filter" FROM "quality_control_qualitysettings";
DROP TABLE "quality_control_qualitysettings";
ALTER TABLE "new__quality_control_qualitysettings" RENAME TO "quality_control_qualitysettings";
--
-- Create constraint quality_report_job_or_task_or_project on model qualityreport
--
CREATE TABLE "new__quality_control_qualityreport" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "created_date" datetime NOT NULL, "target_last_updated" datetime NOT NULL, "gt_last_updated" datetime NULL, "data" text NOT NULL CHECK ((JSON_VALID("data") OR "data" IS NULL)), "job_id" integer NULL REFERENCES "engine_job" ("id") DEFERRABLE INITIALLY DEFERRED, "task_id" integer NULL REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED, "assignee_id" integer NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED, "assignee_last_updated" datetime NULL, "project_id" integer NULL REFERENCES "engine_project" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "quality_report_job_or_task_or_project" CHECK ((("job_id" IS NOT NULL AND "project_id" IS NULL AND "task_id" IS NULL) OR ("job_id" IS NULL AND "project_id" IS NULL AND "task_id" IS NOT NULL) OR ("job_id" IS NULL AND "project_id" IS NOT NULL AND "task_id" IS NULL))));
INSERT INTO "new__quality_control_qualityreport" ("id", "created_date", "target_last_updated", "gt_last_updated", "data", "job_id", "task_id", "assignee_id", "assignee_last_updated", "project_id") SELECT "id", "created_date", "target_last_updated", "gt_last_updated", "data", "job_id", "task_id", "assignee_id", "assignee_last_updated", "project_id" FROM "quality_control_qualityreport";
DROP TABLE "quality_control_qualityreport";
ALTER TABLE "new__quality_control_qualityreport" RENAME TO "quality_control_qualityreport";
CREATE INDEX "quality_control_qualityreport_job_id_87a701d0" ON "quality_control_qualityreport" ("job_id");
CREATE INDEX "quality_control_qualityreport_task_id_75d2cf12" ON "quality_control_qualityreport" ("task_id");
CREATE INDEX "quality_control_qualityreport_assignee_id_cd51795f" ON "quality_control_qualityreport" ("assignee_id");
CREATE INDEX "quality_control_qualityreport_project_id_3dcd718d" ON "quality_control_qualityreport" ("project_id");
--
-- Raw Python operation
--
-- THIS OPERATION CANNOT BE WRITTEN AS SQL
--
-- Create model QualityRequirement
--
CREATE TABLE "quality_control_qualityrequirement" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "created_date" datetime NOT NULL, "updated_date" datetime NOT NULL, "name" varchar(250) NOT NULL, "annotation_type" varchar(32) NULL, "target_metric" varchar(32) NULL, "target_metric_threshold" real NULL, "filter" text NOT NULL, "enabled" bool NOT NULL, "sort_order" integer NOT NULL, "iou_threshold" real NULL, "oks_sigma" real NULL, "line_thickness" real NULL, "point_size_base" varchar(32) NULL, "compare_line_orientation" bool NULL, "line_orientation_threshold" real NULL, "compare_groups" bool NULL, "group_match_threshold" real NULL, "check_covered_annotations" bool NULL, "object_visibility_threshold" real NULL, "panoptic_comparison" bool NULL, "compare_attributes" bool NULL, "attribute_comparison" text NULL CHECK ((JSON_VALID("attribute_comparison") OR "attribute_comparison" IS NULL)), "parent_id" integer NULL REFERENCES "quality_control_qualityrequirement" ("id") DEFERRABLE INITIALLY DEFERRED, "settings_id" integer NOT NULL REFERENCES "quality_control_qualitysettings" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "quality_requirements_unique_per_settings" UNIQUE ("settings_id", "name"));
--
-- Add field attribute_names to annotationconflict
--
CREATE TABLE "new__quality_control_annotationconflict" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "frame" integer unsigned NOT NULL CHECK ("frame" >= 0), "type" varchar(32) NOT NULL, "severity" varchar(32) NOT NULL, "report_id" integer NOT NULL REFERENCES "quality_control_qualityreport" ("id") DEFERRABLE INITIALLY DEFERRED, "attribute_names" text NOT NULL CHECK ((JSON_VALID("attribute_names") OR "attribute_names" IS NULL)));
INSERT INTO "new__quality_control_annotationconflict" ("id", "frame", "type", "severity", "report_id", "attribute_names") SELECT "id", "frame", "type", "severity", "report_id", '[]' FROM "quality_control_annotationconflict";
DROP TABLE "quality_control_annotationconflict";
ALTER TABLE "new__quality_control_annotationconflict" RENAME TO "quality_control_annotationconflict";
CREATE INDEX "quality_control_qualityrequirement_parent_id_3aa4cbf6" ON "quality_control_qualityrequirement" ("parent_id");
CREATE INDEX "quality_control_qualityrequirement_settings_id_6c803969" ON "quality_control_qualityrequirement" ("settings_id");
CREATE INDEX "quality_control_annotationconflict_report_id_6a3a89f9" ON "quality_control_annotationconflict" ("report_id");
--
-- Alter field severity on annotationconflict
--
-- (no-op)
--
-- Alter field type on annotationconflict
--
-- (no-op)
--
-- Remove field check_covered_annotations from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "check_covered_annotations";
--
-- Remove field compare_attributes from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "compare_attributes";
--
-- Remove field compare_groups from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "compare_groups";
--
-- Remove field compare_line_orientation from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "compare_line_orientation";
--
-- Remove field empty_is_annotated from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "empty_is_annotated";
--
-- Remove field group_match_threshold from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "group_match_threshold";
--
-- Remove field iou_threshold from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "iou_threshold";
--
-- Remove field line_orientation_threshold from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "line_orientation_threshold";
--
-- Remove field line_thickness from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "line_thickness";
--
-- Remove field low_overlap_threshold from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "low_overlap_threshold";
--
-- Remove field object_visibility_threshold from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "object_visibility_threshold";
--
-- Remove field oks_sigma from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "oks_sigma";
--
-- Remove field panoptic_comparison from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "panoptic_comparison";
--
-- Remove field point_size_base from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "point_size_base";
--
-- Remove field target_metric from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "target_metric";
--
-- Remove field target_metric_threshold from qualitysettings
--
ALTER TABLE "quality_control_qualitysettings" DROP COLUMN "target_metric_threshold";
--
-- Raw Python operation
--
-- THIS OPERATION CANNOT BE WRITTEN AS SQL
--
-- Alter field target_metric on qualityrequirement
--
-- (no-op)
--
-- Add field rules_version to qualitysettings
--
CREATE TABLE "new__quality_control_qualitysettings" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "task_id" integer NULL UNIQUE REFERENCES "engine_task" ("id") DEFERRABLE INITIALLY DEFERRED, "max_validations_per_job" integer unsigned NOT NULL CHECK ("max_validations_per_job" >= 0), "created_date" datetime NOT NULL, "updated_date" datetime NOT NULL, "inherit" bool NOT NULL, "project_id" integer NULL UNIQUE REFERENCES "engine_project" ("id") DEFERRABLE INITIALLY DEFERRED, "job_filter" text NOT NULL, "rules_version" bigint unsigned NOT NULL CHECK ("rules_version" >= 0), CONSTRAINT "quality_settings_task_or_project" CHECK ((("project_id" IS NULL AND "task_id" IS NOT NULL) OR ("project_id" IS NOT NULL AND "task_id" IS NULL))));
INSERT INTO "new__quality_control_qualitysettings" ("id", "task_id", "max_validations_per_job", "created_date", "updated_date", "inherit", "project_id", "job_filter", "rules_version") SELECT "id", "task_id", "max_validations_per_job", "created_date", "updated_date", "inherit", "project_id", "job_filter", 1 FROM "quality_control_qualitysettings";
DROP TABLE "quality_control_qualitysettings";
ALTER TABLE "new__quality_control_qualitysettings" RENAME TO "quality_control_qualitysettings";
--
-- Create model QualityRulesGeneration
--
CREATE TABLE "quality_control_qualityrulesgeneration" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "own_rules_version" bigint unsigned NOT NULL CHECK ("own_rules_version" >= 0), "inherit" bool NOT NULL, "source_rules_version" bigint unsigned NOT NULL CHECK ("source_rules_version" >= 0), "fingerprint" varchar(64) NOT NULL, "created_date" datetime NOT NULL, "scope_settings_id" integer NOT NULL REFERENCES "quality_control_qualitysettings" ("id") DEFERRABLE INITIALLY DEFERRED, "source_settings_id" integer NOT NULL REFERENCES "quality_control_qualitysettings" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "quality_rules_generation_unique_descriptor" UNIQUE ("scope_settings_id", "own_rules_version", "inherit", "source_settings_id", "source_rules_version"));
--
-- Add field generation to qualityreport
--
ALTER TABLE "quality_control_qualityreport" ADD COLUMN "generation_id" integer NULL REFERENCES "quality_control_qualityrulesgeneration" ("id") DEFERRABLE INITIALLY DEFERRED;
--
-- Add field status to qualityreport
--
ALTER TABLE "quality_control_qualityreport" ADD COLUMN "status" varchar(16) NULL;
--
-- Create constraint quality_report_current_task_unique on model qualityreport
--
CREATE UNIQUE INDEX "quality_report_current_task_unique" ON "quality_control_qualityreport" ("task_id") WHERE "status" = 'current';
--
-- Create constraint quality_report_current_job_unique on model qualityreport
--
CREATE UNIQUE INDEX "quality_report_current_job_unique" ON "quality_control_qualityreport" ("job_id") WHERE "status" = 'current';
--
-- Create constraint quality_report_current_project_unique on model qualityreport
--
CREATE UNIQUE INDEX "quality_report_current_project_unique" ON "quality_control_qualityreport" ("project_id") WHERE "status" = 'current';
CREATE INDEX "quality_control_qualityrulesgeneration_fingerprint_0d540e99" ON "quality_control_qualityrulesgeneration" ("fingerprint");
CREATE INDEX "quality_control_qualityrulesgeneration_scope_settings_id_431a48f8" ON "quality_control_qualityrulesgeneration" ("scope_settings_id");
CREATE INDEX "quality_control_qualityrulesgeneration_source_settings_id_30fc15dc" ON "quality_control_qualityrulesgeneration" ("source_settings_id");
CREATE INDEX "quality_control_qualityreport_generation_id_a3d3136a" ON "quality_control_qualityreport" ("generation_id");
CREATE INDEX "quality_control_qualityreport_status_33dd2c6a" ON "quality_control_qualityreport" ("status");

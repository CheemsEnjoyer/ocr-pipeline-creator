CREATE TABLE `documents` (
	`id` text PRIMARY KEY NOT NULL,
	`filename` text NOT NULL,
	`mime_type` text NOT NULL,
	`size` integer NOT NULL,
	`pipeline_name` text NOT NULL,
	`original_key` text NOT NULL,
	`text` text NOT NULL,
	`result` text NOT NULL,
	`fields` text NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	`revision` integer DEFAULT 0 NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_documents_created_at` ON `documents` (`created_at`,`id`);
import { index, integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const documents = sqliteTable("documents", {
  id: text("id").primaryKey(),
  filename: text("filename").notNull(),
  mimeType: text("mime_type").notNull(),
  size: integer("size").notNull(),
  pipelineName: text("pipeline_name").notNull(),
  originalKey: text("original_key").notNull(),
  text: text("text").notNull(),
  result: text("result").notNull(),
  fields: text("fields").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
  revision: integer("revision").notNull().default(0),
}, (table) => [index("idx_documents_created_at").on(table.createdAt, table.id)]);

import importlib
import unittest

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from backend.schema.pipeline import Pipeline, fields_schema, result_schema


class PublicDescriptionTests(unittest.TestCase):
    def config(self):
        return {"name": "Test", "description": "Public pipeline", "source": "document", "extraction": {
            "model": "extract", "fields": [{"name": "description", "type": "array",
            "description": "Private instruction", "public_description": "Public field",
            "fields": [{"name": "public_description", "description": "Nested instruction", "public_description": "Nested public"}]}]}}

    def test_model_drops_public_descriptions_and_keeps_instructions(self):
        pipeline = Pipeline.model_validate(self.config())
        serialized = pipeline.model_dump()
        self.assertNotIn("description", serialized)
        field = serialized["extraction"]["fields"][0]
        self.assertNotIn("public_description", field)
        self.assertNotIn("public_description", field["fields"][0])
        self.assertEqual(field["description"], "Private instruction")
        self.assertEqual(fields_schema(pipeline.extraction.fields)["properties"]["description"]["description"], "Private instruction")
        self.assertNotIn("description", result_schema(pipeline)["properties"]["description"])

    def test_migration_cleans_saved_configs_jobs_and_schemas(self):
        migration = importlib.import_module("backend.db.migration.versions.0014_remove_public_descriptions")
        engine = sa.create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        metadata = sa.MetaData()
        tables = {name: sa.Table(name, metadata, sa.Column("id", sa.String, primary_key=True), sa.Column(column, sa.JSON))
                  for name, column in (("pipelines", "config"), ("processing_jobs", "pipeline"), ("documents", "result_schema"))}
        metadata.create_all(engine)
        public_schema = {"type": "object", "properties": {"description": {"type": "array", "description": "Public field", "items": {
            "type": "object", "properties": {"public_description": {"type": "string", "description": "Nested public"}}}}}}
        with engine.begin() as connection:
            connection.execute(tables["pipelines"].insert(), {"id": "p", "config": self.config()})
            connection.execute(tables["processing_jobs"].insert(), {"id": "j", "pipeline": self.config()})
            connection.execute(tables["documents"].insert(), [{"id": "d", "result_schema": public_schema}, {"id": "empty", "result_schema": None}])
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
            expected = self.config()
            del expected["description"]
            field = expected["extraction"]["fields"][0]
            del field["public_description"]
            del field["fields"][0]["public_description"]
            self.assertEqual(connection.scalar(sa.select(tables["pipelines"].c.config)), expected)
            self.assertEqual(connection.scalar(sa.select(tables["processing_jobs"].c.pipeline)), expected)
            cleaned = connection.scalar(sa.select(tables["documents"].c.result_schema).where(tables["documents"].c.id == "d"))
            self.assertNotIn("description", cleaned["properties"]["description"])
            self.assertEqual(cleaned["properties"]["description"]["items"]["properties"]["public_description"], {"type": "string"})

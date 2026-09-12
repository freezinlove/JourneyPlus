ALTER TABLE source_items ADD COLUMN document_role varchar(30) DEFAULT 'OTHER';
ALTER TABLE document_versions ADD COLUMN section_parser_version varchar(100);
